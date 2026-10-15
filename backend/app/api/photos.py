from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..domain.catalog import LEAF_IDS
from ..models import AuditEvent, Photo, PhotoGroup, ProjectTestItem, User
from ..schemas import (
    PhotoGroupCreate,
    PhotoGroupOrderUpdate,
    PhotoGroupUpdate,
    PhotoOrderUpdate,
    PhotoUpdate,
)
from ..services.image_pipeline import ImagePipelineError, process_image
from ..services.photo_groups import ensure_project_photo_groups, group_photo_counts
from ..storage import LocalBlobStore
from .deps import current_user, require_csrf
from .projects import get_project_or_404, owns_project

router = APIRouter(tags=["photos"])


def photo_payload(photo: Photo, test_item_id: str | None = None) -> dict:
    return {
        "id": photo.id,
        "photo_group_id": photo.photo_group_id,
        "test_item_id": test_item_id,
        "original_filename": photo.original_filename,
        "mime_type": photo.mime_type,
        "width": photo.processed_width,
        "height": photo.processed_height,
        "caption": photo.caption,
        "sort_order": photo.sort_order,
        "status": photo.status,
        "error_code": photo.error_code,
        "error_detail": photo.error_detail,
        "preview_url": f"/api/photos/{photo.id}/content",
    }


def group_payload(group: PhotoGroup, photo_count: int = 0) -> dict:
    return {
        "id": group.id,
        "project_id": group.project_id,
        "test_item_id": group.test_item_id,
        "scope": group.scope,
        "template_group_id": group.template_group_id,
        "key": group.key,
        "title": group.title,
        "sort_order": group.sort_order,
        "source": group.source,
        "requiredness": group.requiredness,
        "min_photos": group.min_photos,
        "layout_profile": group.layout_profile,
        "preferred_columns": group.preferred_columns,
        "hint": group.hint,
        "photo_count": photo_count,
    }


def get_group_or_404(db: Session, group_id: str, user: User) -> PhotoGroup:
    group = db.get(PhotoGroup, group_id)
    if group is None or not owns_project(db, group.project_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片分组不存在")
    return group


def get_photo_or_404(db: Session, photo_id: str, user: User) -> Photo:
    photo = db.get(Photo, photo_id)
    group = db.get(PhotoGroup, photo.photo_group_id) if photo is not None else None
    if photo is None or group is None or not owns_project(db, group.project_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    return photo


def selected_leaf(db: Session, project_id: str, test_item_id: str) -> bool:
    return bool(
        db.scalar(
            select(ProjectTestItem.selected).where(
                ProjectTestItem.project_id == project_id,
                ProjectTestItem.test_item_id == test_item_id,
            )
        )
    )


@router.get("/projects/{project_id}/photo-groups")
def list_photo_groups(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    get_project_or_404(db, project_id, user)
    groups = ensure_project_photo_groups(db, project_id)
    db.commit()
    counts = group_photo_counts(db, project_id)
    return [group_payload(group, counts.get(group.id, 0)) for group in groups]


@router.post("/projects/{project_id}/photo-groups", status_code=201)
def create_photo_group(
    project_id: str,
    payload: PhotoGroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    get_project_or_404(db, project_id, user)
    if payload.test_item_id not in LEAF_IDS or not selected_leaf(
        db, project_id, payload.test_item_id
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "只能为已选择的叶子测试项新增分组")
    max_order = db.scalar(
        select(func.max(PhotoGroup.sort_order)).where(
            PhotoGroup.project_id == project_id,
            PhotoGroup.test_item_id == payload.test_item_id,
            PhotoGroup.source == "custom",
        )
    )
    group = PhotoGroup(
        project_id=project_id,
        test_item_id=payload.test_item_id,
        key=f"custom_{uuid4().hex[:12]}",
        title=payload.title.strip(),
        sort_order=max(1000, (max_order or 990) + 10),
        source="custom",
        requiredness="optional",
        layout_profile="adaptive_grid",
        hint="项目自定义照片分组。",
    )
    db.add(group)
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo_group.create",
            resource_type="project",
            resource_id=project_id,
            details={"test_item_id": payload.test_item_id, "title": group.title},
        )
    )
    db.commit()
    return group_payload(group)


@router.patch("/photo-groups/{group_id}")
def update_photo_group(
    group_id: str,
    payload: PhotoGroupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    group = get_group_or_404(db, group_id, user)
    if group.source != "custom":
        raise HTTPException(status.HTTP_409_CONFLICT, "模板分组不能重命名")
    group.title = payload.title.strip()
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo_group.update",
            resource_type="photo_group",
            resource_id=group.id,
        )
    )
    db.commit()
    return group_payload(group)


@router.delete("/photo-groups/{group_id}", status_code=204)
def delete_photo_group(
    group_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> None:
    group = get_group_or_404(db, group_id, user)
    if group.source != "custom":
        raise HTTPException(status.HTTP_409_CONFLICT, "模板分组不能删除")
    count = db.scalar(select(func.count(Photo.id)).where(Photo.photo_group_id == group.id)) or 0
    if count:
        raise HTTPException(status.HTTP_409_CONFLICT, "请先移动或删除分组内照片")
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo_group.delete",
            resource_type="photo_group",
            resource_id=group.id,
        )
    )
    db.delete(group)
    db.commit()


@router.put("/projects/{project_id}/photo-groups/order")
def reorder_photo_groups(
    project_id: str,
    payload: PhotoGroupOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> list[dict]:
    get_project_or_404(db, project_id, user)
    if not payload.photo_group_ids:
        return []
    requested = db.scalars(
        select(PhotoGroup).where(PhotoGroup.id.in_(payload.photo_group_ids))
    ).all()
    if len(requested) != len(payload.photo_group_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "排序包含不存在的照片分组")
    test_item_ids = {group.test_item_id for group in requested}
    if len(test_item_ids) != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "只能排序同一测试项的自定义分组")
    test_item_id = next(iter(test_item_ids))
    groups = db.scalars(
        select(PhotoGroup).where(
            PhotoGroup.project_id == project_id,
            PhotoGroup.test_item_id == test_item_id,
            PhotoGroup.source == "custom",
        )
    ).all()
    by_id = {group.id: group for group in groups}
    if set(payload.photo_group_ids) != set(by_id) or len(payload.photo_group_ids) != len(by_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "排序必须包含项目内全部自定义分组")
    for index, group_id in enumerate(payload.photo_group_ids):
        by_id[group_id].sort_order = 1000 + index * 10
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo_group.reorder",
            resource_type="project",
            resource_id=project_id,
        )
    )
    db.commit()
    counts = group_photo_counts(db, project_id)
    return [group_payload(by_id[group_id], counts.get(group_id, 0)) for group_id in payload.photo_group_ids]


@router.get("/projects/{project_id}/photos")
def list_photos(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    get_project_or_404(db, project_id, user)
    rows = db.execute(
        select(Photo, PhotoGroup.test_item_id)
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(PhotoGroup.project_id == project_id)
        .order_by(PhotoGroup.test_item_id, PhotoGroup.sort_order, Photo.sort_order)
    ).all()
    return [photo_payload(photo, test_item_id) for photo, test_item_id in rows]


def legacy_group(db: Session, project_id: str, test_item_id: str) -> PhotoGroup:
    groups = [g for g in ensure_project_photo_groups(db, project_id, [test_item_id]) if g.scope == "test_item"]
    generic = next((group for group in groups if group.key == "test_photos"), None)
    if generic:
        return generic
    existing = next((group for group in groups if group.key == "legacy_unclassified"), None)
    if existing:
        return existing
    group = PhotoGroup(
        project_id=project_id,
        test_item_id=test_item_id,
        key="legacy_unclassified",
        title="未分类测试照片",
        sort_order=990,
        source="custom",
        requiredness="optional",
        layout_profile="adaptive_grid",
        hint="通过旧接口上传，请移动到合适的模板分组。",
    )
    db.add(group)
    db.flush()
    return group


@router.post("/projects/{project_id}/photos", status_code=201)
async def upload_photos(
    project_id: str,
    files: list[UploadFile] = File(...),
    photo_group_id: str | None = Form(default=None),
    test_item_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    get_project_or_404(db, project_id, user)
    if photo_group_id:
        group = db.get(PhotoGroup, photo_group_id)
        if group is None or group.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片分组不存在")
    elif test_item_id:
        if test_item_id not in LEAF_IDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "照片只能关联叶子测试项目")
        group = legacy_group(db, project_id, test_item_id)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "必须指定 photo_group_id")

    current_count = db.scalar(
        select(func.count(Photo.id))
        .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
        .where(PhotoGroup.project_id == project_id)
    ) or 0
    if current_count + len(files) > settings.max_project_photos:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "项目图片总数超过 200 张")

    next_order = db.scalar(select(func.max(Photo.sort_order)).where(Photo.photo_group_id == group.id))
    next_order = (next_order if next_order is not None else -1) + 1
    original_store = LocalBlobStore(settings.originals_dir)
    processed_store = LocalBlobStore(settings.processed_dir)
    result: list[Photo] = []
    for upload in files:
        source = await upload.read(settings.max_photo_bytes + 1)
        photo_id = str(uuid4())
        original_path = original_store.atomic_write(f"{project_id}/{photo_id}.bin", source)
        photo = Photo(
            id=photo_id,
            photo_group_id=group.id,
            original_filename=Path(upload.filename or "photo").name[:255],
            original_path=str(original_path),
            mime_type=upload.content_type or "application/octet-stream",
            sha256=hashlib.sha256(source).hexdigest(),
            sort_order=next_order,
        )
        next_order += 1
        try:
            processed = process_image(
                source,
                max_bytes=settings.max_photo_bytes,
                max_pixels=settings.max_image_pixels,
            )
            processed_path = processed_store.atomic_write(
                f"{project_id}/{photo_id}{processed.output_extension}", processed.data
            )
            photo.processed_path = str(processed_path)
            photo.mime_type = processed.mime_type
            photo.original_width = processed.original_width
            photo.original_height = processed.original_height
            photo.processed_width = processed.processed_width
            photo.processed_height = processed.processed_height
            photo.processed_bytes = len(processed.data)
            photo.status = "processed"
        except ImagePipelineError as exc:
            photo.status = "failed"
            photo.error_code = exc.code
            photo.error_detail = str(exc)
        db.add(photo)
        result.append(photo)
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo.upload",
            resource_type="photo_group",
            resource_id=group.id,
            details={"count": len(result), "test_item_id": group.test_item_id},
        )
    )
    db.commit()
    return [photo_payload(photo, group.test_item_id) for photo in result]


@router.patch("/photos/{photo_id}")
def update_photo(
    photo_id: str,
    payload: PhotoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    photo = get_photo_or_404(db, photo_id, user)
    source_group = db.get(PhotoGroup, photo.photo_group_id)
    if source_group is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "原照片分组不存在")
    if payload.caption is not None:
        photo.caption = payload.caption
    if payload.photo_group_id and payload.photo_group_id != photo.photo_group_id:
        target = db.get(PhotoGroup, payload.photo_group_id)
        if (
            target is None
            or target.project_id != source_group.project_id
            or target.scope != source_group.scope
            or target.test_item_id != source_group.test_item_id
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "照片只能移动到同一测试项的分组")
        max_order = db.scalar(
            select(func.max(Photo.sort_order)).where(Photo.photo_group_id == target.id)
        )
        photo.photo_group_id = target.id
        photo.sort_order = (max_order if max_order is not None else -1) + 1
        db.flush()
        source_rows = db.scalars(
            select(Photo)
            .where(Photo.photo_group_id == source_group.id)
            .order_by(Photo.sort_order)
        ).all()
        for index, row in enumerate(source_rows):
            row.sort_order = index
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo.update",
            resource_type="photo",
            resource_id=photo_id,
            details={"moved": bool(payload.photo_group_id)},
        )
    )
    db.commit()
    target_group = db.get(PhotoGroup, photo.photo_group_id)
    return photo_payload(photo, target_group.test_item_id if target_group else None)


@router.put("/photo-groups/{group_id}/order")
def reorder_photos(
    group_id: str,
    payload: PhotoOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> list[dict]:
    group = get_group_or_404(db, group_id, user)
    rows = db.scalars(select(Photo).where(Photo.photo_group_id == group_id)).all()
    if {row.id for row in rows} != set(payload.photo_ids) or len(rows) != len(payload.photo_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "排序列表必须包含组内全部照片且不得重复")
    by_id = {row.id: row for row in rows}
    for index, photo_id in enumerate(payload.photo_ids):
        by_id[photo_id].sort_order = index
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo.reorder",
            resource_type="photo_group",
            resource_id=group_id,
        )
    )
    db.commit()
    return [photo_payload(by_id[photo_id], group.test_item_id) for photo_id in payload.photo_ids]


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(
    photo_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> None:
    photo = get_photo_or_404(db, photo_id, user)
    for value in (photo.original_path, photo.processed_path):
        if value:
            Path(value).unlink(missing_ok=True)
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="photo.delete",
            resource_type="photo",
            resource_id=photo_id,
        )
    )
    db.delete(photo)
    db.commit()


@router.get("/photos/{photo_id}/content")
def photo_content(
    photo_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    photo = get_photo_or_404(db, photo_id, user)
    if not photo.processed_path or not Path(photo.processed_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在")
    return FileResponse(photo.processed_path, media_type=photo.mime_type)
