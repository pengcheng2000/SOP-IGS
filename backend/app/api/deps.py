from __future__ import annotations

import secrets
from datetime import UTC

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LoginSession, User, utcnow
from ..security import token_digest

SESSION_COOKIE = "sop_session"


def current_session(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> LoginSession:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    login_session = db.scalar(
        select(LoginSession).where(LoginSession.token_hash == token_digest(session_token))
    )
    expires_at = login_session.expires_at if login_session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        login_session is None
        or login_session.revoked_at is not None
        or expires_at is None
        or expires_at <= utcnow()
        or not login_session.user.is_active
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期")
    return login_session


def current_user(login_session: LoginSession = Depends(current_session)) -> User:
    return login_session.user


def require_csrf(
    request: Request,
    login_session: LoginSession = Depends(current_session),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> User:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and (
        not csrf_token or not secrets.compare_digest(csrf_token, login_session.csrf_token)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF 校验失败")
    return login_session.user
