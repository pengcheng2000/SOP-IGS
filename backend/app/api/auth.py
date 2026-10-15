from __future__ import annotations

import hmac
import logging
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, AuthIdentity, LoginSession, User
from ..schemas import LoginRequest, PasswordChange, UserResponse
from ..security import hash_password, new_session, verify_password
from ..services import feishu
from .deps import SESSION_COOKIE, current_session, require_csrf

router = APIRouter(prefix="/auth", tags=["auth"])
LOGGER = logging.getLogger("sop.auth")
FEISHU_STATE_COOKIE = "sop_feishu_state"
FEISHU_COOKIE_PATH = "/api/auth/feishu"
FEISHU_STATE_TTL_SECONDS = 900


def has_local_password(db: Session, user_id: str) -> bool:
    return (
        db.scalar(
            select(AuthIdentity.id).where(
                AuthIdentity.provider == "local",
                AuthIdentity.user_id == user_id,
                AuthIdentity.password_hash.is_not(None),
            )
        )
        is not None
    )


def user_response(db: Session, user: User, csrf_token: str) -> UserResponse:
    return UserResponse(
        id=user.id,
        display_name=user.display_name,
        role=user.role,
        csrf_token=csrf_token,
        can_change_password=has_local_password(db, user.id),
    )


def start_session(
    db: Session, response: Response, user: User, settings: Settings, provider: str
) -> str:
    token, token_hash, csrf, expires_at = new_session(settings.session_ttl_hours)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=token_hash,
            csrf_token=csrf,
            expires_at=expires_at,
        )
    )
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            details={"provider": provider},
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
    return csrf


@router.get("/providers")
def providers(settings: Settings = Depends(get_settings)) -> dict:
    return {"local": True, "feishu": settings.feishu_enabled}


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
    csrf = start_session(db, response, identity.user, settings, "local")
    return user_response(db, identity.user, csrf)


def feishu_redirect_uri(request: Request, settings: Settings) -> str:
    if settings.public_base_url:
        base = settings.public_base_url.rstrip("/")
    else:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc
        )
        base = f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"
    return f"{base}/api/auth/feishu/callback"


def login_error(message: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={quote(message)}", status_code=302)
    response.delete_cookie(FEISHU_STATE_COOKIE, path=FEISHU_COOKIE_PATH)
    return response


def _state_signature(settings: Settings, nonce: str, issued: str) -> str:
    message = f"{nonce}.{issued}".encode()
    return hmac.new(settings.secret_key.encode(), message, "sha256").hexdigest()[:32]


def issue_feishu_state(request: Request, response: Response, settings: Settings) -> str:
    """Bind an OAuth state to this browser; every QR code it renders stays valid until expiry."""
    nonce = request.cookies.get(FEISHU_STATE_COOKIE) or secrets.token_urlsafe(24)
    response.set_cookie(
        FEISHU_STATE_COOKIE,
        nonce,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=FEISHU_STATE_TTL_SECONDS,
        path=FEISHU_COOKIE_PATH,
    )
    issued = str(int(time.time()))
    return f"{issued}.{_state_signature(settings, nonce, issued)}"


def valid_feishu_state(request: Request, state: str | None, settings: Settings) -> bool:
    nonce = request.cookies.get(FEISHU_STATE_COOKIE)
    issued, _, signature = (state or "").partition(".")
    if not nonce or not issued.isdigit() or not signature:
        return False
    if time.time() - int(issued) > FEISHU_STATE_TTL_SECONDS:
        return False
    return hmac.compare_digest(signature, _state_signature(settings, nonce, issued))


@router.get("/feishu/login")
def feishu_login(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    if not settings.feishu_enabled:
        return login_error("正泰飞讯登录未配置")
    response = RedirectResponse("/", status_code=302)
    state = issue_feishu_state(request, response, settings)
    response.headers["location"] = feishu.authorize_url(
        settings, feishu_redirect_uri(request, settings), state
    )
    return response


@router.get("/feishu/qr")
def feishu_qr(
    request: Request, response: Response, settings: Settings = Depends(get_settings)
) -> dict:
    if not settings.feishu_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "正泰飞讯登录未配置")
    state = issue_feishu_state(request, response, settings)
    return {
        "goto": feishu.qr_goto_url(settings, feishu_redirect_uri(request, settings), state),
        "refresh_seconds": FEISHU_STATE_TTL_SECONDS - 120,
    }


def upsert_feishu_user(db: Session, profile: feishu.FeishuUser, settings: Settings) -> User:
    is_admin = profile.open_id in settings.feishu_admin_open_id_set
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "feishu", AuthIdentity.provider_user_id == profile.open_id
        )
    )
    if identity is None:
        user = User(
            display_name=(profile.name or "正泰飞讯用户")[:100],
            role="admin" if is_admin else "user",
        )
        db.add(user)
        db.flush()
        db.add(AuthIdentity(user_id=user.id, provider="feishu", provider_user_id=profile.open_id))
        db.add(
            AuditEvent(
                actor_user_id=user.id,
                action="auth.feishu.register",
                resource_type="user",
                resource_id=user.id,
                details={"open_id": profile.open_id, "email": profile.email},
            )
        )
        db.commit()
        return user
    user = identity.user
    if profile.name:
        user.display_name = profile.name[:100]
    if is_admin:
        user.role = "admin"
    db.commit()
    return user


@router.get("/feishu/callback")
def feishu_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not settings.feishu_enabled:
        return login_error("正泰飞讯登录未配置")
    if not valid_feishu_state(request, state, settings):
        return login_error("正泰飞讯登录已过期，请重新发起登录")
    if not code:
        return login_error("正泰飞讯回调缺少授权码")
    try:
        profile = feishu.fetch_user(settings, code)
    except feishu.FeishuAuthError as exc:
        LOGGER.warning("feishu login failed: %s", exc)
        return login_error(str(exc))
    user = upsert_feishu_user(db, profile, settings)
    if not user.is_active:
        return login_error("账号已被管理员停用")
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(FEISHU_STATE_COOKIE, path=FEISHU_COOKIE_PATH)
    start_session(db, response, user, settings, "feishu")
    return response


@router.get("/me", response_model=UserResponse)
def me(
    login_session: LoginSession = Depends(current_session), db: Session = Depends(get_db)
) -> UserResponse:
    return user_response(db, login_session.user, login_session.csrf_token)


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


@router.post("/password", status_code=204)
def change_password(
    payload: PasswordChange,
    login_session: LoginSession = Depends(current_session),
    user=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "local", AuthIdentity.user_id == user.id
        )
    )
    if (
        identity is None
        or not identity.password_hash
        or not verify_password(identity.password_hash, payload.current_password)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    if payload.new_password == payload.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码不能与当前密码相同")
    identity.password_hash = hash_password(payload.new_password)
    now = datetime.now(UTC)
    other_sessions = db.scalars(
        select(LoginSession).where(
            LoginSession.user_id == user.id,
            LoginSession.id != login_session.id,
            LoginSession.revoked_at.is_(None),
        )
    ).all()
    for other in other_sessions:
        other.revoked_at = now
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="auth.password.change",
            resource_type="user",
            resource_id=user.id,
            details={"revoked_sessions": len(other_sessions)},
        )
    )
    db.commit()
