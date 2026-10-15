"""HTTP API for 升压一体机 projects, mounted under /api/boost."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.deps import current_user, require_csrf
from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, Template, User
from ..storage import LocalBlobStore
from ..time_utils import as_utc, utc_iso
from . import service
from .input import parse_workbook
from .input.model import BoostDocument
from .models import BoostGeneratedDocument, BoostGenerationTask, BoostProject, BoostSourceFile
from .settings import BoostSettings, get_boost_settings

router = APIRouter(prefix="/boost", tags=["boost"])
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class BoostProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class BoostProjectUpdate(BaseModel):
    revision: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    document_number: str | None = Field(default=None, max_length=100)
    document_version: str | None = Field(default=None, max_length=30)
    fields: dict[str, str] | None = None


class BoostGenerationRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    allow_warnings: bool = False


def _project_or_404(db: Session, project_id: str, user: User) -> BoostProject:
    project = db.get(BoostProject, project_id)
    if project is None or project.created_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


def _owned(db: Session, project_id: str, user: User) -> bool:
    project = db.get(BoostProject, project_id)
    return project is not None and project.created_by == user.id


def _source_or_404(db: Session, file_id: str, user: User) -> BoostSourceFile:
    row = db.get(BoostSourceFile, file_id)
    if row is None or not _owned(db, row.project_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "测试项分类表不存在")
    return row


def _task_payload(task: BoostGenerationTask) -> dict:
    now = datetime.now(UTC)
    started = as_utc(task.started_at) or as_utc(task.created_at)
    completed = as_utc(task.completed_at)
    heartbeat = as_utc(task.heartbeat_at)
    active = task.status not in {"succeeded", "failed"}
    return {
        "id": task.id,
        "status": task.status,
        "phase": task.phase,
        "progress_percent": task.progress_percent,
        "progress_message": task.progress_message,
        "heartbeat_at": utc_iso(task.heartbeat_at),
        "started_at": utc_iso(task.started_at),
        "completed_at": utc_iso(task.completed_at),
        "created_at": utc_iso(task.created_at),
        "elapsed_seconds": round(((completed or now) - started).total_seconds()) if started else 0,
        "stalled": bool(active and heartbeat and (now - heartbeat).total_seconds() > 120),
        "attempts": task.attempts,
        "diagnostics": task.diagnostics or {},
        "error_code": task.error_code,
        "error_detail": task.error_detail,
        "events": task.events or [],
    }


@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: BoostSettings = Depends(get_boost_settings),
) -> dict:
    del user
    template = service.current_template(db, settings)
    return {
        "available": template is not None,
        "template_id": template.id if template else None,
        "template_version": template.version if template else None,
        "template_status": template.status if template else None,
        "fields": service.manifest(settings).get("fields", []) if template else [],
        "input_template_available": (settings.template_dir / "input-template.xlsx").is_file(),
    }


@router.get("/input-template")
def download_input_template(
    user: User = Depends(current_user),
    settings: BoostSettings = Depends(get_boost_settings),
) -> FileResponse:
    del user
    path = settings.template_dir / "input-template.xlsx"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "标准填写模板不存在")
    return FileResponse(path, media_type=XLSX_MEDIA_TYPE, filename="升压一体机测试项分类表-标准模板.xlsx")


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    rows = db.scalars(
        select(BoostProject).where(BoostProject.created_by == user.id).order_by(BoostProject.updated_at.desc())
    ).all()
    return [service.project_payload(db, row) for row in rows]


@router.post("/projects", status_code=201)
def create_project(
    payload: BoostProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: BoostSettings = Depends(get_boost_settings),
) -> dict:
    template = service.current_template(db, settings)
    if template is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "升压一体机模板尚未初始化")
    project = BoostProject(template_id=template.id, name=payload.name, description=payload.description, created_by=user.id)
    db.add(project)
    db.flush()
    db.add(AuditEvent(actor_user_id=user.id, action="boost_project.create", resource_type="boost_project", resource_id=project.id))
    db.commit()
    db.refresh(project)
    return service.project_payload(db, project)


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    return service.project_payload(db, _project_or_404(db, project_id, user))


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    payload: BoostProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: BoostSettings = Depends(get_boost_settings),
) -> dict:
    project = _project_or_404(db, project_id, user)
    if project.revision != payload.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "项目已被其他操作更新，请刷新后重试")
    values = payload.model_dump(exclude={"revision"}, exclude_none=True)
    if "fields" in values:
        problems = service.validate_fields(service.manifest(settings), values["fields"])
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "；".join(problems))
    for key, value in values.items():
        setattr(project, key, value)
    project.revision += 1
    db.add(AuditEvent(actor_user_id=user.id, action="boost_project.update", resource_type="boost_project",
                      resource_id=project.id, details={"fields": sorted(values)}))
    db.commit()
    db.refresh(project)
    return service.project_payload(db, project)


@router.post("/projects/{project_id}/source-file", status_code=201)
async def upload_source_file(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
    boost: BoostSettings = Depends(get_boost_settings),
) -> dict:
    _project_or_404(db, project_id, user)
    filename = Path(file.filename or "workbook.xlsx").name[:255]
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请上传 .xlsx 格式的测试项分类表")
    data = await file.read(boost.max_source_file_bytes + 1)
    if len(data) > boost.max_source_file_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "测试项分类表超过大小限制")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件为空")

    file_id = str(uuid4())
    store = LocalBlobStore(boost.sources_dir)
    original = store.atomic_write(f"{project_id}/{file_id}/original.xlsx", data)
    input_config = service.manifest(boost).get("input", {})
    result = await run_in_threadpool(
        parse_workbook,
        original,
        store.resolve(project_id, file_id, "images"),
        max_image_bytes=settings.max_photo_bytes,
        max_image_pixels=settings.max_image_pixels,
        max_images=boost.max_images,
        revision_sheet=input_config.get("revision_sheet", "版本修改记录"),
        ignored_sheets=tuple(input_config.get("ignored_sheets", ["填写说明"])),
    )
    row = BoostSourceFile(
        id=file_id,
        project_id=project_id,
        original_filename=filename,
        original_path=str(original),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        status="parsed" if result.valid else "invalid",
        parser_version=result.document.parser_version if result.document else "",
        document=result.document.to_dict() if result.document else None,
        issues=[issue.to_dict() for issue in result.issues],
        summary=result.summary(),
        uploaded_by=user.id,
    )
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, action="boost_source_file.upload", resource_type="boost_project",
                      resource_id=project_id, details={"source_file_id": file_id, "status": row.status, **row.summary}))
    db.commit()
    db.refresh(row)
    return service.source_file_payload(row)


@router.get("/projects/{project_id}/source-file")
def get_source_file(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict | None:
    _project_or_404(db, project_id, user)
    row = service.latest_source_file(db, project_id)
    return service.source_file_payload(row) if row is not None else None


@router.get("/source-files/{file_id}/images/{image_id}")
def source_file_image(file_id: str, image_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    row = _source_or_404(db, file_id, user)
    refs = BoostDocument.from_dict(row.document).image_refs() if row.document else []
    ref = next((item for item in refs if item.id == image_id), None)
    if ref is None or not Path(ref.path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在")
    return FileResponse(ref.path, media_type="image/png" if ref.path.lower().endswith(".png") else "image/jpeg")


@router.get("/source-files/{file_id}/original")
def source_file_original(file_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    row = _source_or_404(db, file_id, user)
    if not Path(row.original_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "原始文件不存在")
    return FileResponse(row.original_path, media_type=XLSX_MEDIA_TYPE, filename=row.original_filename)


@router.get("/projects/{project_id}/preflight")
def preflight(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: BoostSettings = Depends(get_boost_settings),
) -> dict:
    return service.preflight(db, _project_or_404(db, project_id, user), settings)


@router.post("/projects/{project_id}/generations", status_code=202)
def create_generation(
    project_id: str,
    payload: BoostGenerationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
    boost: BoostSettings = Depends(get_boost_settings),
) -> dict:
    project = _project_or_404(db, project_id, user)
    template = db.get(Template, project.template_id)
    if settings.env == "production" and (template is None or template.status != "approved"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "生产生成前必须完成升压一体机母版人工复核并标记为 approved")
    if template is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "升压一体机模板尚未初始化")
    check = service.preflight(db, project, boost)
    if check["blockers"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "；".join(item["message"] for item in check["blockers"]))
    if check["warnings"] and not payload.allow_warnings:
        raise HTTPException(status.HTTP_409_CONFLICT, "测试项分类表存在提醒，请确认后继续")
    existing = db.scalar(select(BoostGenerationTask).where(BoostGenerationTask.idempotency_key == payload.idempotency_key))
    if existing:
        return _task_payload(existing)
    source = service.latest_source_file(db, project.id)
    task = BoostGenerationTask(
        project_id=project.id,
        requested_by=user.id,
        idempotency_key=payload.idempotency_key,
        input_snapshot=service.snapshot(project, template, source, service.manifest(boost)),
        diagnostics={"source_file_id": source.id, **check["stats"]},
        events=[],
    )
    db.add(task)
    db.add(AuditEvent(actor_user_id=user.id, action="boost_generation.enqueue", resource_type="boost_project", resource_id=project.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(BoostGenerationTask).where(BoostGenerationTask.idempotency_key == payload.idempotency_key))
        return _task_payload(existing)
    db.refresh(task)
    return _task_payload(task)


@router.get("/generations/{task_id}")
def get_generation(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    task = db.get(BoostGenerationTask, task_id)
    if task is None or not _owned(db, task.project_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "生成任务不存在")
    return _task_payload(task)


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    _project_or_404(db, project_id, user)
    documents = db.scalars(
        select(BoostGeneratedDocument).where(BoostGeneratedDocument.project_id == project_id)
        .order_by(BoostGeneratedDocument.created_at.desc())
    ).all()
    return [
        {"id": doc.id, "task_id": doc.task_id, "file_sha256": doc.file_sha256, "created_at": utc_iso(doc.created_at),
         "download_url": f"/api/boost/documents/{doc.id}/download"}
        for doc in documents
    ]


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    document = db.get(BoostGeneratedDocument, document_id)
    if document is None or not _owned(db, document.project_id, user) or not Path(document.file_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "生成文档不存在")
    project = db.get(BoostProject, document.project_id)
    local = as_utc(document.created_at).astimezone(ZoneInfo(get_settings().display_timezone))
    return FileResponse(
        document.file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{project.name if project else '升压一体机'}-{local:%Y%m%d-%H%M%S}.docx",
    )


@router.post("/admin/template/approve")
def approve_template(
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: BoostSettings = Depends(get_boost_settings),
) -> dict:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    template = service.current_template(db, settings)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "升压一体机模板不存在")
    actual = hashlib.sha256(settings.master.read_bytes()).hexdigest()
    if actual != template.master_sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "母版哈希与已登记版本不一致")
    template.status = "approved"
    db.add(AuditEvent(actor_user_id=user.id, action="boost_template.approve", resource_type="template",
                      resource_id=template.id, details={"master_sha256": actual}))
    db.commit()
    return {"id": template.id, "status": template.status, "master_sha256": actual}
