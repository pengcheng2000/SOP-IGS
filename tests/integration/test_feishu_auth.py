from __future__ import annotations

import importlib
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.testclient import TestClient


def _feishu_login(client: TestClient, monkeypatch, feishu, open_id: str, name: str):
    start = client.get("/api/auth/feishu/login", follow_redirects=False)
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    monkeypatch.setattr(
        feishu, "fetch_user", lambda settings, code: feishu.FeishuUser(open_id, name, "")
    )
    return client.get(
        "/api/auth/feishu/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )


def test_feishu_sso_and_admin_permission_control(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'feishu.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("SOP_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("SOP_PUBLIC_BASE_URL", "")
    monkeypatch.setenv("SOP_FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("SOP_FEISHU_APP_SECRET", "test-secret")
    monkeypatch.setenv("SOP_FEISHU_ADMIN_OPEN_IDS", "ou_boss")

    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")
    feishu = importlib.import_module("app.services.feishu")

    with TestClient(main.app) as client:
        assert client.get("/api/auth/providers").json() == {"local": True, "feishu": True}

        start = client.get("/api/auth/feishu/login", follow_redirects=False)
        location = urlparse(start.headers["location"])
        query = parse_qs(location.query)
        assert location.netloc == "open.feishu.cn"
        assert query["app_id"] == ["cli_test"]
        assert query["redirect_uri"] == ["http://testserver/api/auth/feishu/callback"]

        qr = client.get("/api/auth/feishu/qr").json()
        qr_url = urlparse(qr["goto"])
        assert qr_url.netloc == "passport.feishu.cn"
        assert parse_qs(qr_url.query)["client_id"] == ["cli_test"]
        assert parse_qs(qr_url.query)["redirect_uri"] == [
            "http://testserver/api/auth/feishu/callback"
        ]
        # Several QR codes rendered in one browser (tabs, re-renders) all stay valid.
        older_state = parse_qs(qr_url.query)["state"][0]
        client.get("/api/auth/feishu/qr")
        monkeypatch.setattr(
            feishu, "fetch_user", lambda settings, code: feishu.FeishuUser("ou_qr", "扫码用户", "")
        )
        scanned = client.get(
            "/api/auth/feishu/callback",
            params={"code": "qr-code", "state": older_state},
            follow_redirects=False,
        )
        assert scanned.headers["location"] == "/"
        assert client.get("/api/auth/me").json()["display_name"] == "扫码用户"
        client.cookies.clear()

        with TestClient(main.app) as stranger:
            stolen = stranger.get(
                "/api/auth/feishu/callback",
                params={"code": "x", "state": older_state},
                follow_redirects=False,
            )
            assert stolen.headers["location"].startswith("/login?error=")

        forged = client.get(
            "/api/auth/feishu/callback",
            params={"code": "x", "state": "forged"},
            follow_redirects=False,
        )
        assert forged.status_code == 302
        assert forged.headers["location"].startswith("/login?error=")

        def failing(settings, code):
            raise feishu.FeishuAuthError("获取 user_access_token 失败")

        state = parse_qs(
            urlparse(client.get("/api/auth/feishu/login", follow_redirects=False).headers["location"]).query
        )["state"][0]
        monkeypatch.setattr(feishu, "fetch_user", failing)
        failed = client.get(
            "/api/auth/feishu/callback",
            params={"code": "x", "state": state},
            follow_redirects=False,
        )
        assert "user_access_token" in unquote(failed.headers["location"])

        ok = _feishu_login(client, monkeypatch, feishu, "ou_alice", "张三")
        assert ok.status_code == 302 and ok.headers["location"] == "/"
        me = client.get("/api/auth/me").json()
        assert me["display_name"] == "张三"
        assert me["role"] == "user"
        assert me["can_change_password"] is False
        alice_id = me["id"]
        assert client.get("/api/admin/users").status_code == 403

    with TestClient(main.app) as boss:
        _feishu_login(boss, monkeypatch, feishu, "ou_boss", "老板")
        assert boss.get("/api/auth/me").json()["role"] == "admin"

    with TestClient(main.app) as bob:
        assert _feishu_login(bob, monkeypatch, feishu, "ou_bob", "李四").headers["location"] == "/"
        assert bob.get("/api/auth/me").json()["role"] == "user"

    with TestClient(main.app) as admin:
        login = admin.post(
            "/api/auth/login", json={"username": "admin", "password": "test-admin-password"}
        ).json()
        headers = {"X-CSRF-Token": login["csrf_token"]}
        assert login["can_change_password"] is True
        users = {u["display_name"]: u for u in admin.get("/api/admin/users").json()}
        assert users["张三"]["providers"] == ["feishu"]
        assert users["张三"]["feishu_open_id"] == "ou_alice"
        assert users["李四"]["is_active"] is True

        assert admin.patch(
            f"/api/admin/users/{login['id']}", json={"role": "user"}, headers=headers
        ).status_code == 409
        promoted = admin.patch(
            f"/api/admin/users/{alice_id}", json={"role": "admin"}, headers=headers
        )
        assert promoted.json()["role"] == "admin"

    with TestClient(main.app) as bob:
        assert _feishu_login(bob, monkeypatch, feishu, "ou_bob", "李四").headers["location"] == "/"
        assert bob.get("/api/auth/me").status_code == 200
        with TestClient(main.app) as admin:
            headers = {
                "X-CSRF-Token": admin.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "test-admin-password"},
                ).json()["csrf_token"]
            }
            admin.patch(
                f"/api/admin/users/{users['李四']['id']}", json={"is_active": False}, headers=headers
            )
        assert bob.get("/api/auth/me").status_code == 401
        blocked = _feishu_login(bob, monkeypatch, feishu, "ou_bob", "李四")
        assert "停用" in unquote(blocked.headers["location"])


def test_production_allows_plain_http_only_with_explicit_public_url():
    import pytest
    from app.config import Settings

    base = {
        "env": "production",
        "secret_key": "a-unique-production-secret",
        "bootstrap_admin_password": "a-strong-admin-password",
        "session_cookie_secure": False,
    }
    with pytest.raises(ValueError):
        Settings(**base)
    assert Settings(**base, public_base_url="http://10.122.3.224:8010").public_base_url
    with pytest.raises(ValueError):
        Settings(**{**base, "session_cookie_secure": True}, public_base_url="http://10.122.3.224:8010")
