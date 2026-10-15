from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, AuthIdentity, LoginSession, Template, User
from ..schemas import AdminUserCreate, AdminUserUpdate
from ..security import hash_password
from .deps import current_user, require_csrf

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    return user


def user_payload(user: User, identities: list[AuthIdentity]) -> dict:
    local = next((item for item in identities if item.provider == "local"), None)
    feishu = next((item for item in identities if item.provider == "feishu"), None)
    return {
        "id": user.id,
        "username": local.provider_user_id if local else None,
        "feishu_open_id": feishu.provider_user_id if feishu else None,
        "providers": sorted({item.provider for item in identities}),
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[dict]:
    del admin
    users = db.scalars(select(User).order_by(User.created_at)).all()
    identities: dict[str, list[AuthIdentity]] = {}
    for identity in db.scalars(select(AuthIdentity)).all():
        identities.setdefault(identity.user_id, []).append(identity)
    return [user_payload(user, identities.get(user.id, [])) for user in users]


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_csrf),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可执行此操作")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == admin.id and (payload.role == "user" or payload.is_active is False):
        raise HTTPException(status.HTTP_409_CONFLICT, "不能降级或停用当前登录的管理员账号")
    changes: dict = {}
    if payload.role is not None and payload.role != user.role:
        changes["role"] = payload.role
        user.role = payload.role
    if payload.is_active is not None and payload.is_active != user.is_active:
        changes["is_active"] = payload.is_active
        user.is_active = payload.is_active
        if not payload.is_active:
            now = datetime.now(UTC)
            for login_session in db.scalars(
                select(LoginSession).where(
                    LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None)
                )
            ):
                login_session.revoked_at = now
    if changes:
        db.add(
            AuditEvent(
                actor_user_id=admin.id,
                action="admin.user.update",
                resource_type="user",
                resource_id=user.id,
                details=changes,
            )
        )
    db.commit()
    identities = list(db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)))
    return user_payload(user, identities)


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
    identities = list(db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)))
    return user_payload(user, identities)


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
