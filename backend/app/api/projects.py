from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain.catalog import BY_ID, LEAF_IDS, display_numbers, tree_payload
from ..models import (
    AuditEvent,
    Photo,
    PhotoGroup,
    Project,
    ProjectTestItem,
    Template,
    User,
)
from ..schemas import ProjectCreate, ProjectUpdate, SelectionUpdate
from ..services.photo_groups import ensure_project_photo_groups, group_photo_counts
from ..time_utils import utc_iso
from .deps import current_user, require_csrf

router = APIRouter(tags=["projects"])


def selected_ids(db: Session, project_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ProjectTestItem.test_item_id).where(
                ProjectTestItem.project_id == project_id, ProjectTestItem.selected.is_(True)
            )
        )
    )


def project_payload(db: Session, project: Project) -> dict:
    selected = selected_ids(db, project.id)
    photo_count = db.scalar(
        select(func.count(Photo.id))
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(PhotoGroup.project_id == project.id)
    ) or 0
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "document_number": project.document_number,
        "document_title": project.document_title,
        "document_version": project.document_version,
        "product_phase": project.product_phase,
        "test_period": project.test_period,
        "test_location": project.test_location,
        "testers": project.testers,
        "product_model": project.product_model,
        "product_serial_no": project.product_serial_no,
        "product_info": project.product_info,
        "project_differences": project.project_differences,
        "status": project.status,
        "revision": project.revision,
        "selected_test_item_ids": selected,
        "display_numbers": display_numbers(selected) if selected else {},
        "photo_count": photo_count,
        "created_at": utc_iso(project.created_at),
        "updated_at": utc_iso(project.updated_at),
    }


def get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


@router.get("/templates/{version}/test-items")
def get_test_items(version: str, user: User = Depends(current_user)) -> dict:
    del user
    if version != "1":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板版本不存在")
    return {"version": version, "items": tree_payload()}


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[dict]:
    del user
    projects = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return [project_payload(db, project) for project in projects]


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    template = db.scalar(select(Template).where(Template.key == "liquid-cooled-cabinet", Template.version == "1"))
    if template is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "模板尚未初始化")
    project = Project(
        template_id=template.id,
        name=payload.name,
        description=payload.description,
        document_title=payload.name,
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    for leaf_id in sorted(LEAF_IDS):
        db.add(ProjectTestItem(project_id=project.id, test_item_id=leaf_id, selected=False))
    db.add(AuditEvent(actor_user_id=user.id, action="project.create", resource_type="project", resource_id=project.id))
    db.commit()
    db.refresh(project)
    return project_payload(db, project)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    del user
    return project_payload(db, get_project_or_404(db, project_id))


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    project = get_project_or_404(db, project_id)
    if project.revision != payload.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "项目已被其他操作更新，请刷新后重试")
    values = payload.model_dump(exclude={"revision"}, exclude_none=True)
    for key, value in values.items():
        setattr(project, key, value)
    project.revision += 1
    db.add(AuditEvent(actor_user_id=user.id, action="project.update", resource_type="project", resource_id=project.id, details={"fields": sorted(values)}))
    db.commit()
    db.refresh(project)
    return project_payload(db, project)


@router.put("/projects/{project_id}/selection")
def update_selection(
    project_id: str,
    payload: SelectionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    project = get_project_or_404(db, project_id)
    if project.revision != payload.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "项目已被其他操作更新，请刷新后重试")
    requested = set(payload.test_item_ids)
    invalid = requested - LEAF_IDS
    if invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"包含无效叶子节点：{sorted(invalid)}")
    rows = db.scalars(select(ProjectTestItem).where(ProjectTestItem.project_id == project_id)).all()
    for row in rows:
        row.selected = row.test_item_id in requested
        row.selection_source = payload.source if row.selected else "manual"
    ensure_project_photo_groups(db, project_id, list(requested))
    project.revision += 1
    db.add(AuditEvent(actor_user_id=user.id, action="project.selection.update", resource_type="project", resource_id=project.id, details={"selected_count": len(requested)}))
    db.commit()
    return {
        "revision": project.revision,
        "selected_test_item_ids": sorted(requested, key=lambda item_id: BY_ID[item_id].order),
        "display_numbers": display_numbers(requested) if requested else {},
        "tree": tree_payload(requested),
    }


@router.get("/projects/{project_id}/preflight")
def preflight(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    del user
    project = get_project_or_404(db, project_id)
    selected = selected_ids(db, project_id)
    blockers: list[dict] = []
    warnings: list[dict] = []
    if not selected:
        blockers.append({"code": "INVALID_SELECTION", "message": "至少选择一个测试项目"})
    if not project.name or not project.document_title:
        blockers.append({"code": "MISSING_REQUIRED_FIELD", "message": "项目名称和文档名称不能为空"})
    failed = db.scalar(
        select(func.count(Photo.id))
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(PhotoGroup.project_id == project_id, Photo.status == "failed")
    ) or 0
    if failed:
        blockers.append({"code": "IMAGE_PROCESSING_FAILED", "message": f"有 {failed} 张图片处理失败"})
    groups = ensure_project_photo_groups(db, project_id, selected)
    db.commit()
    counts = group_photo_counts(db, project_id)
    completeness = []
    required_missing = []
    recommended_missing = []
    for group in groups:
        count = counts.get(group.id, 0)
        complete = count >= max(1, group.min_photos)
        entry = {
            "photo_group_id": group.id,
            "test_item_id": group.test_item_id,
            "scope": group.scope,
            "key": group.key,
            "title": group.title,
            "requiredness": group.requiredness,
            "min_photos": group.min_photos,
            "photo_count": count,
            "complete": complete,
        }
        completeness.append(entry)
        if group.requiredness == "required" and count < group.min_photos:
            required_missing.append(entry)
        elif group.requiredness == "recommended" and not complete:
            recommended_missing.append(entry)
    if required_missing:
        blockers.append(
            {
                "code": "MISSING_REQUIRED_PHOTO_GROUP",
                "message": f"有 {len(required_missing)} 个必填照片分组尚未达到最少数量",
                "photo_groups": required_missing,
            }
        )
    if recommended_missing:
        warnings.append(
            {
                "code": "MISSING_RECOMMENDED_PHOTO_GROUP",
                "message": f"有 {len(recommended_missing)} 个推荐照片分组未达到建议数量",
                "photo_groups": recommended_missing,
            }
        )
    item_counts: dict[str, int] = {}
    for group in groups:
        item_counts[group.test_item_id] = item_counts.get(group.test_item_id, 0) + counts.get(group.id, 0)
    missing = [item_id for item_id in selected if not item_counts.get(item_id)]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "selected_count": len(selected),
        "photo_count": sum(counts.values()),
        "without_photos": missing,
        "group_completeness": completeness,
        "sample_group_completeness": [entry for entry in completeness if entry["scope"] == "sample"],
        "warning_confirmation_required": bool(warnings),
    }
