from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select


def test_owner_deletes_cabinet_report_and_boost_projects_with_their_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'delete.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")
    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")
    from app.boost.models import BoostProject, BoostSourceFile
    from app.db import SessionLocal
    from app.models import (
        AuditEvent,
        DocumentGenerationTask,
        Photo,
        PhotoGroup,
        Project,
        ProjectTestItem,
    )

    with TestClient(main.app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        # --- cabinet report ---
        project = client.post("/api/projects", json={"name": "待删除报告"}, headers=headers).json()
        pid = project["id"]
        client.put(
            f"/api/projects/{pid}/selection",
            json={"revision": project["revision"], "test_item_ids": ["alarm_bms"], "source": "manual"},
            headers=headers,
        )
        group = next(g for g in client.get(f"/api/projects/{pid}/photo-groups").json() if g["key"] == "alarm_evidence")
        image = BytesIO()
        Image.new("RGB", (40, 30), "red").save(image, format="JPEG")
        uploaded = client.post(
            f"/api/projects/{pid}/photos",
            data={"photo_group_id": group["id"]},
            files={"files": ("a.jpg", image.getvalue(), "image/jpeg")},
            headers=headers,
        )
        assert uploaded.status_code == 201
        settings = config.get_settings()
        assert (settings.originals_dir / pid).is_dir() and (settings.processed_dir / pid).is_dir()

        queued = client.post(
            f"/api/projects/{pid}/generations",
            json={"idempotency_key": "delete-guard-key", "allow_warnings": True},
            headers=headers,
        )
        assert queued.status_code == 202
        guarded = client.delete(f"/api/projects/{pid}", headers=headers)
        assert guarded.status_code == 409 and "正在生成" in guarded.json()["detail"]
        with SessionLocal.begin() as db:
            db.get(DocumentGenerationTask, queued.json()["id"]).status = "failed"

        # Another user cannot delete it.
        client.post(
            "/api/admin/users",
            json={"username": "other", "display_name": "其他人", "password": "other-test-password", "role": "user"},
            headers=headers,
        )
        client.post("/api/auth/logout", headers=headers)
        other = client.post("/api/auth/login", json={"username": "other", "password": "other-test-password"})
        other_headers = {"X-CSRF-Token": other.json()["csrf_token"]}
        assert client.delete(f"/api/projects/{pid}", headers=other_headers).status_code == 404
        client.post("/api/auth/logout", headers=other_headers)
        login = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        assert client.delete(f"/api/projects/{pid}", headers=headers).status_code == 204
        assert client.get(f"/api/projects/{pid}").status_code == 404
        assert client.delete(f"/api/projects/{pid}", headers=headers).status_code == 404
        assert not (settings.originals_dir / pid).exists()
        assert not (settings.processed_dir / pid).exists()
        with SessionLocal() as db:
            assert db.get(Project, pid) is None
            assert db.scalar(select(func.count()).select_from(PhotoGroup).where(PhotoGroup.project_id == pid)) == 0
            assert db.scalar(select(func.count()).select_from(Photo).where(Photo.id == uploaded.json()[0]["id"])) == 0
            assert db.scalar(select(func.count()).select_from(ProjectTestItem).where(ProjectTestItem.project_id == pid)) == 0
            assert db.scalar(
                select(func.count()).select_from(DocumentGenerationTask).where(DocumentGenerationTask.project_id == pid)
            ) == 0
            assert db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "project.delete", AuditEvent.resource_id == pid)
            ) == 1

        # --- boost plan ---
        boost = client.post("/api/boost/projects", json={"name": "待删除升压"}, headers=headers).json()
        bid = boost["id"]
        client.post(
            f"/api/boost/projects/{bid}/source-file",
            files={"file": ("broken.xlsx", b"not a workbook")},
            headers=headers,
        )
        from app.boost.settings import get_boost_settings

        sources = get_boost_settings().sources_dir / bid
        assert sources.is_dir()
        assert client.delete(f"/api/boost/projects/{bid}", headers=headers).status_code == 204
        assert client.get(f"/api/boost/projects/{bid}").status_code == 404
        assert not sources.exists()
        with SessionLocal() as db:
            assert db.get(BoostProject, bid) is None
            assert db.scalar(select(func.count()).select_from(BoostSourceFile).where(BoostSourceFile.project_id == bid)) == 0
        assert all(item["id"] != bid for item in client.get("/api/boost/projects").json())
