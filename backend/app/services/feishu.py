from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import Settings

FEISHU_BASE = "https://open.feishu.cn/open-apis"
PASSPORT_AUTHORIZE = "https://passport.feishu.cn/suite/passport/oauth/authorize"


class FeishuAuthError(Exception):
    pass


@dataclass(frozen=True)
class FeishuUser:
    open_id: str
    name: str
    email: str


def authorize_url(settings: Settings, redirect_uri: str, state: str) -> str:
    query = urlencode({"app_id": settings.feishu_app_id, "redirect_uri": redirect_uri, "state": state})
    return f"{FEISHU_BASE}/authen/v1/authorize?{query}"


def qr_goto_url(settings: Settings, redirect_uri: str, state: str) -> str:
    """Authorization URL used by the embedded QR-code SDK (LarkSSOSDKWebQRCode)."""
    query = urlencode(
        {
            "client_id": settings.feishu_app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return f"{PASSPORT_AUTHORIZE}?{query}"


def _json(response: httpx.Response, failure: str) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuAuthError(f"{failure}（HTTP {response.status_code}）") from exc
    if body.get("code") != 0:
        raise FeishuAuthError(f"{failure}：{body.get('msg') or body.get('code')}")
    return body


def fetch_user(settings: Settings, code: str) -> FeishuUser:
    """Exchange an OAuth code for the Feishu user's identity."""
    try:
        with httpx.Client(timeout=settings.feishu_timeout_seconds) as client:
            app_token = _json(
                client.post(
                    f"{FEISHU_BASE}/auth/v3/app_access_token/internal",
                    json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
                ),
                "获取 app_access_token 失败",
            ).get("app_access_token")
            if not app_token:
                raise FeishuAuthError("获取 app_access_token 失败")
            user_token = (
                _json(
                    client.post(
                        f"{FEISHU_BASE}/authen/v1/oidc/access_token",
                        headers={"Authorization": f"Bearer {app_token}"},
                        json={"grant_type": "authorization_code", "code": code},
                    ),
                    "获取 user_access_token 失败",
                ).get("data")
                or {}
            ).get("access_token")
            if not user_token:
                raise FeishuAuthError("获取 user_access_token 失败")
            info = (
                _json(
                    client.get(
                        f"{FEISHU_BASE}/authen/v1/user_info",
                        headers={"Authorization": f"Bearer {user_token}"},
                    ),
                    "获取正泰飞讯用户信息失败",
                ).get("data")
                or {}
            )
    except httpx.HTTPError as exc:
        raise FeishuAuthError("无法连接正泰飞讯开放平台") from exc
    open_id = info.get("open_id")
    if not open_id:
        raise FeishuAuthError("获取正泰飞讯用户信息失败")
    return FeishuUser(open_id=open_id, name=info.get("name") or "", email=info.get("email") or "")
