from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select

from ..boost.bootstrap import bootstrap_boost
from ..boost.worker import claim_boost_task, run_boost_task
from ..bootstrap import bootstrap
from ..config import get_settings
from ..db import SessionLocal
from ..domain.catalog import BY_ID
from ..models import DocumentGenerationTask, DocumentTaskEvent, GeneratedDocument, utcnow
from ..services.docx import (
    DocPhoto,
    DocPhotoGroup,
    GenerationInput,
    generate_docx,
    validate_docx,
)
from ..services.docx.com_finalizer import WordComError
from ..services.layout import LAYOUT_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("sop.word-worker")


def finalize_with_word_subprocess(
    path: Path,
    timeout_seconds: int,
    heartbeat_callback=None,
) -> dict:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "app.services.docx.com_runner", str(path.resolve())],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creation_flags,
    )
    started = time.monotonic()
    while process.poll() is None and time.monotonic() - started < timeout_seconds:
        if heartbeat_callback:
            heartbeat_callback(round(time.monotonic() - started))
        time.sleep(1)
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        else:
            process.kill()
        raise WordComError(f"Word COM 超过 {timeout_seconds} 秒未完成")
    stdout, stderr = process.communicate()
    if process.returncode:
        raise WordComError(stderr.strip() or stdout.strip() or "Word COM 子进程失败")
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise WordComError("Word COM 未返回有效验证结果") from exc


def claim_task(worker_id: str) -> str | None:
    with SessionLocal.begin() as db:
        query = (
            select(DocumentGenerationTask)
            .where(
                or_(
                    DocumentGenerationTask.status == "queued",
                    and_(
                        DocumentGenerationTask.status.in_(
                            ["assembling", "word_finalizing", "validating"]
                        ),
                        DocumentGenerationTask.lease_expires_at < utcnow(),
                        DocumentGenerationTask.attempts < 2,
                    ),
                )
            )
            .order_by(DocumentGenerationTask.created_at)
            .limit(1)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        task = db.scalar(query)
        if task is None:
            return None
        task.status = "assembling"
        task.phase = "validating_inputs"
        task.attempts += 1
        task.lease_owner = worker_id
        task.lease_expires_at = utcnow() + timedelta(minutes=15)
        task.heartbeat_at = utcnow()
        task.started_at = task.started_at or utcnow()
        task.phase_started_at = utcnow()
        task.progress_percent = 5
        task.progress_message = "正在校验项目、模板和照片"
        db.add(
            DocumentTaskEvent(
                task_id=task.id,
                phase=task.phase,
                progress_percent=task.progress_percent,
                message=task.progress_message,
                details={"attempt": task.attempts},
            )
        )
        return task.id


def update_progress(
    db,
    task: DocumentGenerationTask,
    phase: str,
    percent: int,
    message: str,
    details: dict | None = None,
) -> None:
    if task.phase != phase:
        task.phase_started_at = utcnow()
    task.phase = phase
    task.progress_percent = max(task.progress_percent, min(100, percent))
    task.progress_message = message
    task.heartbeat_at = utcnow()
    task.lease_expires_at = utcnow() + timedelta(minutes=15)
    if details:
        task.diagnostics = {**(task.diagnostics or {}), **details}
    db.add(
        DocumentTaskEvent(
            task_id=task.id,
            phase=phase,
            progress_percent=task.progress_percent,
            message=message,
            details=details or {},
        )
    )
    db.commit()


def refresh_heartbeat(
    db,
    task: DocumentGenerationTask,
    message: str,
    percent: int | None = None,
) -> None:
    task.heartbeat_at = utcnow()
    task.lease_expires_at = utcnow() + timedelta(minutes=15)
    task.progress_message = message
    if percent is not None:
        task.progress_percent = max(task.progress_percent, min(100, percent))
    db.commit()


def run_task(task_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        task = db.get(DocumentGenerationTask, task_id)
        if task is None:
            return
        snapshot = task.input_snapshot
        grouped: dict[str, list[DocPhoto]] = {}
        for photo in snapshot.get("photos", []):
            grouped.setdefault(photo["test_item_id"], []).append(
                DocPhoto(photo["id"], Path(photo["processed_path"]), photo.get("caption", ""))
            )
        photo_groups_by_item: dict[str, list[DocPhotoGroup]] = {}
        for group in snapshot.get("photo_groups", []):
            photos = tuple(
                DocPhoto(
                    photo["id"],
                    Path(photo["processed_path"]),
                    photo.get("caption", ""),
                )
                for photo in group.get("photos", [])
            )
            photo_groups_by_item.setdefault(group["test_item_id"], []).append(
                DocPhotoGroup(
                    id=group["id"],
                    key=group["key"],
                    title=group["title"],
                    photos=photos,
                    layout_profile=group.get("layout_profile", "adaptive_grid"),
                    preferred_columns=group.get("preferred_columns"),
                    source=group.get("source", "template"),
                    sort_order=group.get("sort_order", 0),
                )
            )
        request = GenerationInput(
            project=snapshot["project"],
            selected_test_item_ids=tuple(snapshot["selected_test_item_ids"]),
            photos_by_test_item={key: tuple(value) for key, value in grouped.items()},
            result_notes=dict(snapshot.get("result_notes", {})),
            photo_groups_by_test_item={
                key: tuple(value) for key, value in photo_groups_by_item.items()
            },
            sample_photo_groups=tuple(
                DocPhotoGroup(id=group["id"], key=group["key"], title=group["title"],
                              photos=tuple(DocPhoto(p["id"], Path(p["processed_path"]), p.get("caption", "")) for p in group["photos"]),
                              layout_profile=group["layout_profile"], preferred_columns=group.get("preferred_columns"),
                              sort_order=group["sort_order"])
                for group in snapshot.get("sample_photo_groups", [])
            ),
        )
        temp_dir = settings.temp_dir / task.id
        temp_dir.mkdir(parents=True, exist_ok=True)
        intermediate = temp_dir / "assembled.docx"
        output_dir = settings.outputs_dir / task.project_id
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / f"{task.id}.docx"
        try:
            update_progress(
                db,
                task,
                "assembling_sections",
                15,
                "正在删除未选章节并重建测试项目汇总表",
            )

            def layout_progress(current: int, total: int, title: str) -> None:
                percent = 25 + round(35 * current / max(total, 1))
                update_progress(
                    db,
                    task,
                    "laying_out_photos",
                    percent,
                    f"正在排版第 {current}/{total} 个照片组：{title}",
                    {"current_group": title, "photo_groups_completed": current, "photo_groups_total": total},
                )

            generation_report = generate_docx(
                settings.template_dir / "master.docx",
                intermediate,
                request,
                layout_progress,
            )
            update_progress(
                db,
                task,
                "validating_ooxml",
                65,
                "正在检查 DOCX XML、媒体关系和图片边界",
            )
            validation = validate_docx(intermediate)
            os.replace(intermediate, final_path)
            com_report = None
            if settings.word_com_enabled:
                task.status = "word_finalizing"
                update_progress(
                    db,
                    task,
                    "word_finalizing",
                    72,
                    "Microsoft Word 正在更新目录、域和分页",
                )

                def word_heartbeat(elapsed_seconds: int) -> None:
                    refresh_heartbeat(
                        db,
                        task,
                        f"Microsoft Word 正在重新分页，已等待 {elapsed_seconds} 秒",
                        min(88, 72 + elapsed_seconds // 8),
                    )

                com_report = finalize_with_word_subprocess(
                    final_path,
                    settings.word_com_timeout_seconds,
                    word_heartbeat,
                )
                expected_numbers = generation_report["display_numbers"]
                actual_numbers = {
                    entry["text"]: entry["number"].rstrip(".")
                    for entry in com_report.get("headings", [])
                }
                mismatches = {
                    item_id: {
                        "expected": expected,
                        "actual": actual_numbers.get(BY_ID[item_id].title),
                    }
                    for item_id, expected in expected_numbers.items()
                    if actual_numbers.get(BY_ID[item_id].title) != expected
                }
                if mismatches:
                    raise WordComError(f"Word 标题编号与生成快照不一致：{mismatches}")
            task.status = "validating"
            update_progress(
                db,
                task,
                "final_validation",
                94,
                "正在重新打开文档并核对标题编号",
            )
            post_validation = validate_docx(final_path)
            digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
            db.add(
                GeneratedDocument(
                    project_id=task.project_id,
                    task_id=task.id,
                    file_path=str(final_path),
                    file_sha256=digest,
                    template_version=snapshot["template_version"],
                    layout_version=LAYOUT_VERSION,
                    snapshot=snapshot,
                    validation_report={
                        "generation": generation_report,
                        "pre_word": validation,
                        "word": com_report,
                        "post_word": post_validation,
                    },
                )
            )
            task.status = "succeeded"
            task.completed_at = utcnow()
            update_progress(db, task, "succeeded", 100, "DOCX 已生成并通过验证")
            LOGGER.info("generation succeeded task=%s", task.id)
        except WordComError as exc:
            task.status = "failed"
            task.error_code = "WORD_COM_TIMEOUT"
            task.error_detail = str(exc)[:2000]
            task.completed_at = utcnow()
            update_progress(db, task, "failed", 100, "Word 更新目录或分页失败")
            LOGGER.exception("Word finalization failed task=%s", task.id)
        except Exception as exc:
            task.status = "failed"
            task.error_code = getattr(exc, "code", "DOCX_ASSEMBLY_FAILED")
            task.error_detail = str(exc)[:2000]
            task.completed_at = utcnow()
            update_progress(db, task, "failed", 100, "DOCX 生成失败")
            LOGGER.exception("generation failed task=%s", task.id)


def main() -> None:
    bootstrap()
    bootstrap_boost()
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    LOGGER.info("Word worker started id=%s com=%s", worker_id, settings.word_com_enabled)
    while True:
        task_id = claim_task(worker_id)
        if task_id:
            run_task(task_id)
            continue
        boost_task_id = claim_boost_task(worker_id)
        if boost_task_id:
            run_boost_task(boost_task_id)
        else:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
