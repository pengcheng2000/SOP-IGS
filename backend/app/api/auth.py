from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, AuthIdentity, LoginSession
from ..schemas import LoginRequest, UserResponse
from ..security import new_session, verify_password
from .deps import SESSION_COOKIE, current_session, require_csrf

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "local", AuthIdentity.provider_user_id == payload.username
        )
    )
    if (
        identity is None
        or not identity.password_hash
        or not identity.user.is_active
        or not verify_password(identity.password_hash, payload.password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token, token_hash, csrf, expires_at = new_session(settings.session_ttl_hours)
    login_session = LoginSession(
        user_id=identity.user_id,
        token_hash=token_hash,
        csrf_token=csrf,
        expires_at=expires_at,
    )
    db.add(login_session)
    db.add(
        AuditEvent(
            actor_user_id=identity.user_id,
            action="auth.login",
            resource_type="user",
            resource_id=identity.user_id,
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return UserResponse(
        id=identity.user.id,
        display_name=identity.user.display_name,
        role=identity.user.role,
        csrf_token=csrf,
    )


@router.get("/me", response_model=UserResponse)
def me(login_session: LoginSession = Depends(current_session)) -> UserResponse:
    return UserResponse(
        id=login_session.user.id,
        display_name=login_session.user.display_name,
        role=login_session.user.role,
        csrf_token=login_session.csrf_token,
    )


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    login_session: LoginSession = Depends(current_session),
    user=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    del user
    login_session.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
