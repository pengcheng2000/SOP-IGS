"""Generation tasks for 工商业柜测试方案, executed by the shared Word worker process."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import timedelta

from sqlalchemy import and_, or_, select

from ..config import get_settings
from ..db import SessionLocal
from ..document_common.model import DocumentModel as CabinetPlanDocument
from ..document_common.ooxml import DocxGenerationError
from ..document_common.runner import WordProcessError as CabinetPlanWordError
from ..document_common.runner import finalize_with_word
from ..models import utcnow
from ..time_utils import utc_iso
from .docx.builder import generate_cabinet_plan_docx
from .docx.content import validate_docx_body
from .docx.validator import validate_cabinet_plan_docx, validate_pagination
from .models import CabinetPlanGeneratedDocument, CabinetPlanGenerationTask
from .settings import get_cabinet_plan_settings

LOGGER = logging.getLogger("sop.cabinet-plan-worker")
LEASE = timedelta(minutes=15)


def _fail_abandoned_tasks(db) -> None:
    """Tasks whose worker vanished and that used up their attempts would otherwise spin forever."""
    abandoned = db.scalars(
        select(CabinetPlanGenerationTask).where(
            CabinetPlanGenerationTask.status.in_(["assembling", "word_finalizing", "validating"]),
            CabinetPlanGenerationTask.lease_expires_at < utcnow(),
            CabinetPlanGenerationTask.attempts >= 2,
        )
    ).all()
    for task in abandoned:
        task.status = "failed"
        task.error_code = "WORKER_LOST"
        task.error_detail = "Worker 中断且已用完重试次数，请重新点击生成"
        task.completed_at = utcnow()
        _progress(task, "failed", 100, "生成任务中断")


def claim_cabinet_plan_task(worker_id: str) -> str | None:
    with SessionLocal.begin() as db:
        _fail_abandoned_tasks(db)
        query = (
            select(CabinetPlanGenerationTask)
            .where(
                or_(
                    CabinetPlanGenerationTask.status == "queued",
                    and_(
                        CabinetPlanGenerationTask.status.in_(
                            ["assembling", "word_finalizing", "validating"]
                        ),
                        CabinetPlanGenerationTask.lease_expires_at < utcnow(),
                        CabinetPlanGenerationTask.attempts < 2,
                    ),
                )
            )
            .order_by(CabinetPlanGenerationTask.created_at)
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
        _progress(
            task,
            "validating_inputs",
            5,
            "正在校验项目、模板和测试需求表",
            {"attempt": task.attempts},
        )
        return task.id


def _progress(
    task: CabinetPlanGenerationTask,
    phase: str,
    percent: int,
    message: str,
    details: dict | None = None,
) -> None:
    task.phase = phase
    task.progress_percent = max(task.progress_percent or 0, min(100, percent))
    task.progress_message = message
    task.heartbeat_at = utcnow()
    task.lease_expires_at = utcnow() + LEASE
    if details:
        task.diagnostics = {**(task.diagnostics or {}), **details}
    task.events = [
        *(task.events or []),
        {
            "phase": phase,
            "progress_percent": task.progress_percent,
            "message": message,
            "details": details or {},
            "created_at": utc_iso(utcnow()),
        },
    ]


def heading_mismatches(expected_headings: list, com_report: dict) -> dict:
    expected = [list(entry) for entry in expected_headings]
    actual = [
        [entry["number"].rstrip("."), entry["text"]]
        for entry in com_report.get("headings", [])
        if entry["number"].startswith("5.") and "." in entry["number"].rstrip(".")
    ]
    if actual == expected:
        return {}
    first = next(
        (i for i, pair in enumerate(zip(expected, actual)) if pair[0] != pair[1]),
        min(len(expected), len(actual)),
    )
    return {
        "first_difference": first,
        "expected": expected[first : first + 3],
        "actual": actual[first : first + 3],
        "expected_count": len(expected),
        "actual_count": len(actual),
    }


def run_cabinet_plan_task(task_id: str) -> None:
    settings = get_settings()
    plan = get_cabinet_plan_settings()
    with SessionLocal() as db:
        task = db.get(CabinetPlanGenerationTask, task_id)
        if task is None:
            return
        snapshot = task.input_snapshot
        intermediate = plan.temp_dir / task.id / "assembled.docx"
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        final_path = plan.outputs_dir / task.project_id / f"{task.id}.docx"
        final_path.parent.mkdir(parents=True, exist_ok=True)

        def update(phase: str, percent: int, message: str, details: dict | None = None) -> None:
            _progress(task, phase, percent, message, details)
            db.commit()

        try:
            if (
                not plan.master.is_file()
                or hashlib.sha256(plan.master.read_bytes()).hexdigest() != snapshot["master_sha256"]
            ):
                raise DocxGenerationError(
                    "TEMPLATE_CHANGED", "母版已变化或不存在，请重新提交生成任务"
                )
            update("assembling_sections", 15, "正在填写母版字段并重建调试项目汇总表")

            def chapter_progress(current: int, total: int, title: str) -> None:
                update(
                    "building_chapters",
                    20 + round(40 * current / max(total, 1)),
                    f"正在生成第 {current}/{total} 章：{title}",
                    {
                        "current_chapter": title,
                        "chapters_completed": current,
                        "chapters_total": total,
                    },
                )

            report = generate_cabinet_plan_docx(
                plan.master,
                intermediate,
                snapshot["fields"],
                CabinetPlanDocument.from_dict(snapshot["document"]),
                chapter_progress,
                generation_date=snapshot["generation_date"],
            )
            floating = report["floating_drawings_expected"]
            update("validating_ooxml", 65, "正在检查 DOCX XML、媒体关系和图片")
            validation = validate_cabinet_plan_docx(intermediate, floating)
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

                com_report = finalize_with_word(
                    final_path,
                    settings.word_com_timeout_seconds,
                    heartbeat,
                    module="app.cabinet_plan.docx.word",
                )
                validate_pagination(com_report)
                mismatches = heading_mismatches(report["expected_headings"], com_report)
                if mismatches:
                    raise CabinetPlanWordError(f"Word 标题编号与生成快照不一致：{mismatches}")
            task.status = "validating"
            update("final_validation", 94, "正在重新打开文档并核对标题编号")
            post_validation = validate_cabinet_plan_docx(final_path, floating)
            post_validation["content"] = validate_docx_body(
                final_path,
                CabinetPlanDocument.from_dict(snapshot["document"]),
                snapshot["fields"],
                snapshot["generation_date"],
            )
            db.add(
                CabinetPlanGeneratedDocument(
                    project_id=task.project_id,
                    task_id=task.id,
                    file_path=str(final_path),
                    file_sha256=hashlib.sha256(final_path.read_bytes()).hexdigest(),
                    template_version=snapshot.get("template_version", ""),
                    snapshot=snapshot,
                    validation_report={
                        "generation": report,
                        "pre_word": validation,
                        "word": com_report,
                        "post_word": post_validation,
                    },
                )
            )
            task.status = "succeeded"
            task.completed_at = utcnow()
            update("succeeded", 100, "DOCX 已生成并通过验证")
            LOGGER.info("plan generation succeeded task=%s", task.id)
        except Exception as exc:
            db.rollback()
            task = db.get(CabinetPlanGenerationTask, task_id)
            task.status = "failed"
            task.error_code = getattr(exc, "code", "DOCX_ASSEMBLY_FAILED")
            task.error_detail = str(exc)[:2000]
            task.completed_at = utcnow()
            _progress(
                task,
                "failed",
                100,
                "Word 更新域或分页失败"
                if isinstance(exc, CabinetPlanWordError)
                else "DOCX 生成失败",
            )
            db.commit()
            LOGGER.exception("plan generation failed task=%s", task.id)
