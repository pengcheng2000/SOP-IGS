"""Generation tasks for 升压一体机, executed by the shared Word worker process."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select

from ..config import get_settings
from ..db import SessionLocal
from ..models import utcnow
from ..time_utils import utc_iso
from .docx.builder import generate_boost_docx
from .docx.validator import validate_boost_docx
from .input.model import BoostDocument
from .models import BoostGeneratedDocument, BoostGenerationTask
from .settings import get_boost_settings

LOGGER = logging.getLogger("sop.boost-worker")
LEASE = timedelta(minutes=15)


class BoostWordError(RuntimeError):
    code = "WORD_COM_FAILED"


def _fail_abandoned_tasks(db) -> None:
    """Tasks whose worker vanished and that used up their attempts would otherwise spin forever."""
    abandoned = db.scalars(
        select(BoostGenerationTask).where(
            BoostGenerationTask.status.in_(["assembling", "word_finalizing", "validating"]),
            BoostGenerationTask.lease_expires_at < utcnow(),
            BoostGenerationTask.attempts >= 2,
        )
    ).all()
    for task in abandoned:
        task.status = "failed"
        task.error_code = "WORKER_LOST"
        task.error_detail = "Worker 中断且已用完重试次数，请重新点击生成"
        task.completed_at = utcnow()
        _progress(task, "failed", 100, "生成任务中断")


def claim_boost_task(worker_id: str) -> str | None:
    with SessionLocal.begin() as db:
        _fail_abandoned_tasks(db)
        query = (
            select(BoostGenerationTask)
            .where(
                or_(
                    BoostGenerationTask.status == "queued",
                    and_(
                        BoostGenerationTask.status.in_(["assembling", "word_finalizing", "validating"]),
                        BoostGenerationTask.lease_expires_at < utcnow(),
                        BoostGenerationTask.attempts < 2,
                    ),
                )
            )
            .order_by(BoostGenerationTask.created_at)
            .limit(1)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        task = db.scalar(query)
        if task is None:
            return None
        task.status = "assembling"
        task.attempts += 1
        task.lease_owner = worker_id
        task.started_at = task.started_at or utcnow()
        _progress(task, "validating_inputs", 5, "正在校验项目、模板和测试项分类表", {"attempt": task.attempts})
        return task.id


def _progress(task: BoostGenerationTask, phase: str, percent: int, message: str, details: dict | None = None) -> None:
    task.phase = phase
    task.progress_percent = max(task.progress_percent or 0, min(100, percent))
    task.progress_message = message
    task.heartbeat_at = utcnow()
    task.lease_expires_at = utcnow() + LEASE
    if details:
        task.diagnostics = {**(task.diagnostics or {}), **details}
    task.events = [*(task.events or []), {
        "phase": phase, "progress_percent": task.progress_percent, "message": message,
        "details": details or {}, "created_at": utc_iso(utcnow()),
    }]


def _finalize_with_word(path: Path, timeout_seconds: int, heartbeat) -> dict:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # The child's output goes to temporary files, not pipes: a Windows pipe holds only 4 KB and the child
    # blocks on exit when the heading report is larger, while this loop only polls. Output is UTF-8 because
    # heading text may contain any Unicode character.
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.boost.docx.word", str(path.resolve())],
            stdout=out_file,
            stderr=err_file,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            cwd=str(Path(__file__).resolve().parents[2]),
            creationflags=creation_flags,
        )
        started = time.monotonic()
        while process.poll() is None and time.monotonic() - started < timeout_seconds:
            heartbeat(round(time.monotonic() - started))
            time.sleep(1)
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True)
            else:
                process.kill()
            raise BoostWordError(f"Word COM 超过 {timeout_seconds} 秒未完成")
        out_file.seek(0)
        err_file.seek(0)
        stdout = out_file.read().decode("utf-8", errors="replace")
        stderr = err_file.read().decode("utf-8", errors="replace")
    if process.returncode:
        raise BoostWordError((stderr or stdout or "Word COM 子进程失败").strip())
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise BoostWordError("Word COM 未返回有效验证结果") from exc


def heading_mismatches(expected_headings: list, com_report: dict) -> dict:
    expected = [list(entry) for entry in expected_headings]
    actual = [
        [entry["number"].rstrip("."), entry["text"]]
        for entry in com_report.get("headings", [])
        if entry["number"].startswith("5.") and "." in entry["number"].rstrip(".")
    ]
    if actual == expected:
        return {}
    first = next((i for i, pair in enumerate(zip(expected, actual)) if pair[0] != pair[1]), min(len(expected), len(actual)))
    return {"first_difference": first, "expected": expected[first:first + 3], "actual": actual[first:first + 3],
            "expected_count": len(expected), "actual_count": len(actual)}


def run_boost_task(task_id: str) -> None:
    settings = get_settings()
    boost = get_boost_settings()
    with SessionLocal() as db:
        task = db.get(BoostGenerationTask, task_id)
        if task is None:
            return
        snapshot = task.input_snapshot
        intermediate = boost.temp_dir / task.id / "assembled.docx"
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        final_path = boost.outputs_dir / task.project_id / f"{task.id}.docx"
        final_path.parent.mkdir(parents=True, exist_ok=True)

        def update(phase: str, percent: int, message: str, details: dict | None = None) -> None:
            _progress(task, phase, percent, message, details)
            db.commit()

        try:
            update("assembling_sections", 15, "正在填写母版字段并重建调试项目汇总表")

            def chapter_progress(current: int, total: int, title: str) -> None:
                update("building_chapters", 20 + round(40 * current / max(total, 1)), f"正在生成第 {current}/{total} 章：{title}",
                       {"current_chapter": title, "chapters_completed": current, "chapters_total": total})

            report = generate_boost_docx(boost.master, intermediate, snapshot["fields"],
                                         BoostDocument.from_dict(snapshot["document"]), chapter_progress)
            floating = report["floating_drawings_expected"]
            update("validating_ooxml", 65, "正在检查 DOCX XML、媒体关系和图片")
            validation = validate_boost_docx(intermediate, floating)
            os.replace(intermediate, final_path)
            com_report = None
            if settings.word_com_enabled:
                task.status = "word_finalizing"
                update("word_finalizing", 72, "Microsoft Word 正在更新域和分页")

                def heartbeat(elapsed: int) -> None:
                    task.heartbeat_at = utcnow()
                    task.lease_expires_at = utcnow() + LEASE
                    task.progress_message = f"Microsoft Word 正在重新分页，已等待 {elapsed} 秒"
                    task.progress_percent = max(task.progress_percent, min(88, 72 + elapsed // 8))
                    db.commit()

                com_report = _finalize_with_word(final_path, settings.word_com_timeout_seconds, heartbeat)
                mismatches = heading_mismatches(report["expected_headings"], com_report)
                if mismatches:
                    raise BoostWordError(f"Word 标题编号与生成快照不一致：{mismatches}")
            task.status = "validating"
            update("final_validation", 94, "正在重新打开文档并核对标题编号")
            post_validation = validate_boost_docx(final_path, floating)
            db.add(BoostGeneratedDocument(
                project_id=task.project_id,
                task_id=task.id,
                file_path=str(final_path),
                file_sha256=hashlib.sha256(final_path.read_bytes()).hexdigest(),
                template_version=snapshot.get("template_version", ""),
                snapshot=snapshot,
                validation_report={"generation": report, "pre_word": validation, "word": com_report, "post_word": post_validation},
            ))
            task.status = "succeeded"
            task.completed_at = utcnow()
            update("succeeded", 100, "DOCX 已生成并通过验证")
            LOGGER.info("boost generation succeeded task=%s", task.id)
        except Exception as exc:
            db.rollback()
            task = db.get(BoostGenerationTask, task_id)
            task.status = "failed"
            task.error_code = getattr(exc, "code", "DOCX_ASSEMBLY_FAILED")
            task.error_detail = str(exc)[:2000]
            task.completed_at = utcnow()
            _progress(task, "failed", 100, "Word 更新域或分页失败" if isinstance(exc, BoostWordError) else "DOCX 生成失败")
            db.commit()
            LOGGER.exception("boost generation failed task=%s", task.id)
