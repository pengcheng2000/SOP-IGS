from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..domain.catalog import BY_ID
from ..models import (
    AuditEvent,
    DocumentGenerationTask,
    DocumentTaskEvent,
    GeneratedDocument,
    Photo,
    PhotoGroup,
    Project,
    Template,
    User,
)
from ..schemas import GenerationRequest
from ..services.photo_groups import ensure_project_photo_groups, group_photo_counts
from ..time_utils import as_utc, utc_iso
from .deps import current_user, require_csrf
from .projects import get_project_or_404, owns_project, selected_ids

router = APIRouter(tags=["generation"])


def _snapshot(db: Session, project: Project, selected: list[str]) -> dict:
    project_fields = {
        key: getattr(project, key)
        for key in (
            "id", "name", "description", "document_number", "document_title",
            "document_version", "product_phase", "test_period", "test_location",
            "testers", "product_model", "product_serial_no", "product_info",
            "project_differences", "revision",
        )
    }
    rows = db.execute(
        select(Photo, PhotoGroup.test_item_id)
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(
            PhotoGroup.project_id == project.id,
            or_(PhotoGroup.scope == "sample", PhotoGroup.test_item_id.in_(selected)),
            Photo.status == "processed",
        )
        .order_by(PhotoGroup.test_item_id, Photo.sort_order)
    ).all()
    photos = [
        {
            "id": photo.id,
            "photo_group_id": photo.photo_group_id,
            "test_item_id": test_item_id,
            "processed_path": photo.processed_path,
            "caption": photo.caption,
            "sha256": photo.sha256,
            "sort_order": photo.sort_order,
        }
        for photo, test_item_id in rows
    ]
    groups = ensure_project_photo_groups(db, project.id, selected)
    photos_by_group: dict[str, list[dict]] = {}
    for photo in photos:
        photos_by_group.setdefault(photo["photo_group_id"], []).append(photo)
    photo_groups = [
        {
            "id": group.id,
            "test_item_id": group.test_item_id,
            "scope": group.scope,
            "key": group.key,
            "title": group.title,
            "sort_order": group.sort_order,
            "source": group.source,
            "requiredness": group.requiredness,
            "min_photos": group.min_photos,
            "layout_profile": group.layout_profile,
            "preferred_columns": group.preferred_columns,
            "photos": photos_by_group.get(group.id, []),
        }
        for group in groups
    ]
    return {
        "project": project_fields,
        "selected_test_item_ids": sorted(selected, key=lambda item_id: BY_ID[item_id].order),
        "photos": [photo for photo in photos if photo["test_item_id"] is not None],
        "photo_groups": [group for group in photo_groups if group["scope"] == "test_item"],
        "sample_photo_groups": [group for group in photo_groups if group["scope"] == "sample"],
        "template_version": "1",
    }


def task_payload(db: Session, task: DocumentGenerationTask) -> dict:
    now = datetime.now(UTC)
    heartbeat = as_utc(task.heartbeat_at)
    started = as_utc(task.started_at) or as_utc(task.created_at)
    completed = as_utc(task.completed_at)
    phase_started = as_utc(task.phase_started_at) or started
    active = task.status not in {"succeeded", "failed"}
    events = db.scalars(
        select(DocumentTaskEvent)
        .where(DocumentTaskEvent.task_id == task.id)
        .order_by(DocumentTaskEvent.created_at)
    ).all()
    return {
        "id": task.id,
        "status": task.status,
        "phase": task.phase,
        "progress_percent": task.progress_percent,
        "progress_message": task.progress_message,
        "heartbeat_at": utc_iso(task.heartbeat_at),
        "phase_started_at": utc_iso(task.phase_started_at),
        "started_at": utc_iso(task.started_at),
        "completed_at": utc_iso(task.completed_at),
        "created_at": utc_iso(task.created_at),
        "updated_at": utc_iso(task.updated_at),
        "elapsed_seconds": round(((completed or now) - started).total_seconds()) if started else 0,
        "phase_elapsed_seconds": round((now - phase_started).total_seconds()) if active and phase_started else 0,
        "stalled": bool(active and heartbeat and (now - heartbeat).total_seconds() > 120),
        "diagnostics": task.diagnostics or {},
        "attempts": task.attempts,
        "error_code": task.error_code,
        "error_detail": task.error_detail,
        "events": [
            {
                "phase": event.phase,
                "progress_percent": event.progress_percent,
                "message": event.message,
                "details": event.details,
                "created_at": utc_iso(event.created_at),
            }
            for event in events
        ],
    }


@router.post("/projects/{project_id}/generations", status_code=202)
def create_generation(
    project_id: str,
    payload: GenerationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = get_project_or_404(db, project_id, user)
    template = db.get(Template, project.template_id)
    if settings.env == "production" and (template is None or template.status != "approved"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "生产生成前必须完成母版人工复核并标记为 approved",
        )
    selected = selected_ids(db, project_id)
    if not selected:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "至少选择一个测试项目")
    failed = db.scalar(
        select(func.count(Photo.id))
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(PhotoGroup.project_id == project_id, Photo.status == "failed")
    ) or 0
    if failed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "存在处理失败的图片")
    groups = ensure_project_photo_groups(db, project_id, selected)
    counts = group_photo_counts(db, project_id)
    required_missing = [
        group
        for group in groups
        if group.requiredness == "required" and counts.get(group.id, 0) < group.min_photos
    ]
    if required_missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "必填照片分组不完整：" + "、".join(group.title for group in required_missing),
        )
    settings.data_root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(settings.data_root).free / (1024**3)
    if free_gb < settings.minimum_free_disk_gb:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, "服务器磁盘空间不足")
    recommended_missing = [
        group
        for group in groups
        if group.requiredness == "recommended" and counts.get(group.id, 0) < max(1, group.min_photos)
    ]
    if recommended_missing and not payload.allow_warnings:
        raise HTTPException(status.HTTP_409_CONFLICT, "部分推荐照片分组为空，请确认后继续")
    existing = db.scalar(
        select(DocumentGenerationTask).where(
            DocumentGenerationTask.idempotency_key == payload.idempotency_key
        )
    )
    if existing:
        return task_payload(db, existing)
    task = DocumentGenerationTask(
        project_id=project_id,
        requested_by=user.id,
        idempotency_key=payload.idempotency_key,
        input_snapshot=_snapshot(db, project, selected),
        progress_percent=0,
        progress_message="等待 Word Worker",
        diagnostics={"photo_count": sum(counts.values()), "photo_group_count": len(groups)},
    )
    db.add(task)
    db.add(AuditEvent(actor_user_id=user.id, action="generation.enqueue", resource_type="project", resource_id=project_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(DocumentGenerationTask).where(
                DocumentGenerationTask.idempotency_key == payload.idempotency_key
            )
        )
        return task_payload(db, existing)
    db.refresh(task)
    return task_payload(db, task)


@router.get("/generations/{task_id}")
def get_generation(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    task = db.get(DocumentGenerationTask, task_id)
    if task is None or not owns_project(db, task.project_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "生成任务不存在")
    return task_payload(db, task)


@router.get("/projects/{project_id}/generated-documents")
def list_generated_documents(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    get_project_or_404(db, project_id, user)
    documents = db.scalars(
        select(GeneratedDocument)
        .where(GeneratedDocument.project_id == project_id)
        .order_by(GeneratedDocument.created_at.desc())
    ).all()
    return [
        {
            "id": document.id,
            "task_id": document.task_id,
            "file_sha256": document.file_sha256,
            "created_at": utc_iso(document.created_at),
            "download_url": f"/api/generated-documents/{document.id}/download",
        }
        for document in documents
    ]


@router.get("/generated-documents/{document_id}/download")
def download_document(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    document = db.get(GeneratedDocument, document_id)
    if (
        document is None
        or not owns_project(db, document.project_id, user)
        or not Path(document.file_path).is_file()
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "生成文档不存在")
    project = db.get(Project, document.project_id)
    local_created = as_utc(document.created_at).astimezone(ZoneInfo(get_settings().display_timezone))
    filename = f"{(project.name if project else 'SOP')}-{local_created:%Y%m%d-%H%M%S}.docx"
    return FileResponse(
        document.file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
