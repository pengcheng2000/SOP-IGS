from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, AuthIdentity, Template, User
from ..schemas import AdminUserCreate
from ..security import hash_password
from .deps import current_user, require_csrf

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    return user


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[dict]:
    del admin
    rows = db.execute(
        select(User, AuthIdentity.provider_user_id)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(AuthIdentity.provider == "local")
        .order_by(User.created_at)
    ).all()
    return [
        {
            "id": user.id,
            "username": username,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
        }
        for user, username in rows
    ]


@router.post("/users", status_code=201)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_csrf),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    existing = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "local",
            AuthIdentity.provider_user_id == payload.username,
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(display_name=payload.display_name, role=payload.role)
    db.add(user)
    db.flush()
    db.add(
        AuthIdentity(
            user_id=user.id,
            provider="local",
            provider_user_id=payload.username,
            password_hash=hash_password(payload.password),
        )
    )
    db.add(
        AuditEvent(
            actor_user_id=admin.id,
            action="admin.user.create",
            resource_type="user",
            resource_id=user.id,
            details={"role": payload.role},
        )
    )
    db.commit()
    return {
        "id": user.id,
        "username": payload.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.post("/templates/{template_id}/approve")
def approve_template(
    template_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_csrf),
    settings: Settings = Depends(get_settings),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    master = settings.template_dir / "master.docx"
    actual_hash = hashlib.sha256(master.read_bytes()).hexdigest()
    if actual_hash != template.master_sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "母版哈希与已登记版本不一致")
    template.status = "approved"
    db.add(
        AuditEvent(
            actor_user_id=admin.id,
            action="template.approve",
            resource_type="template",
            resource_id=template.id,
            details={"master_sha256": actual_hash},
        )
    )
    db.commit()
    return {"id": template.id, "status": template.status, "master_sha256": actual_hash}
