from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def test_authenticated_project_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")

    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")

    with TestClient(main.app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-password"},
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        project_response = client.post(
            "/api/projects",
            json={"name": "API 验证", "description": "integration"},
            headers=headers,
        )
        assert project_response.status_code == 201
        project = project_response.json()
        assert project["created_at"].endswith("Z")

        selection = client.put(
            f"/api/projects/{project['id']}/selection",
            json={
                "revision": project["revision"],
                "test_item_ids": ["alarm_bms"],
                "source": "manual",
            },
            headers=headers,
        )
        assert selection.status_code == 200
        assert selection.json()["display_numbers"]["alarm_bms"] == "5.1.1.1"

        preflight = client.get(f"/api/projects/{project['id']}/preflight")
        assert preflight.status_code == 200
        assert preflight.json()["ready"] is True
        assert len(preflight.json()["without_photos"]) == 1

        groups = client.get(f"/api/projects/{project['id']}/photo-groups").json()
        alarm_group = next(group for group in groups if group["key"] == "alarm_evidence")
        custom = client.post(
            f"/api/projects/{project['id']}/photo-groups",
            json={"test_item_id": "alarm_bms", "title": "项目补充证据"},
            headers=headers,
        )
        assert custom.status_code == 201

        image_bytes = BytesIO()
        Image.new("RGB", (80, 50), "green").save(image_bytes, format="JPEG")
        upload = client.post(
            f"/api/projects/{project['id']}/photos",
            data={"photo_group_id": alarm_group["id"]},
            files={"files": ("alarm.jpg", image_bytes.getvalue(), "image/jpeg")},
            headers=headers,
        )
        assert upload.status_code == 201
        photo = upload.json()[0]
        moved = client.patch(
            f"/api/photos/{photo['id']}",
            json={"photo_group_id": custom.json()["id"], "caption": "报警触发"},
            headers=headers,
        )
        assert moved.status_code == 200
        assert moved.json()["caption"] == "报警触发"
        assert client.delete(
            f"/api/photo-groups/{custom.json()['id']}", headers=headers
        ).status_code == 409

        user = client.post(
            "/api/admin/users",
            json={
                "username": "tester",
                "display_name": "测试用户",
                "password": "long-test-password",
                "role": "user",
            },
            headers=headers,
        )
        assert user.status_code == 201

        generation = client.post(
            f"/api/projects/{project['id']}/generations",
            json={"idempotency_key": "integration-generation-1", "allow_warnings": True},
            headers=headers,
        )
        assert generation.status_code == 202
        assert generation.json()["status"] == "queued"
        assert generation.json()["progress_message"] == "等待 Word Worker"
        assert generation.json()["created_at"].endswith("Z")

        second_project = client.post(
            "/api/projects",
            json={"name": "必填照片验证", "description": "integration"},
            headers=headers,
        ).json()
        client.put(
            f"/api/projects/{second_project['id']}/selection",
            json={
                "revision": second_project["revision"],
                "test_item_ids": ["cabinet_strength_lifting"],
                "source": "manual",
            },
            headers=headers,
        )
        required_preflight = client.get(
            f"/api/projects/{second_project['id']}/preflight"
        ).json()
        assert required_preflight["ready"] is False
        assert any(
            blocker["code"] == "MISSING_REQUIRED_PHOTO_GROUP"
            for blocker in required_preflight["blockers"]
        )

        sample_groups = [g for g in groups if g["scope"] == "sample"]
        assert [g["min_photos"] for g in sample_groups] == [1, 1, 2]
        assert all(g["test_item_id"] is None for g in sample_groups)
        assert len(client.get(f"/api/projects/{project['id']}/photo-groups").json()) == len(groups) + 1
        assert client.delete(f"/api/photo-groups/{sample_groups[0]['id']}", headers=headers).status_code == 409
        sample_photo_ids = []
        for group in sample_groups:
            response = client.post(
                f"/api/projects/{project['id']}/photos", data={"photo_group_id": group["id"]},
                files={"files": ("sample.jpg", image_bytes.getvalue(), "image/jpeg")}, headers=headers,
            )
            assert response.status_code == 201
            sample_photo_ids.append(response.json()[0]["id"])
        partial = client.get(f"/api/projects/{project['id']}/preflight").json()
        assert partial["selected_count"] == 1
        assert partial["ready"] is True
        diagonal = next(g for g in partial["sample_group_completeness"] if g["key"] == "sample_diagonal")
        assert diagonal["photo_count"] == 1 and not diagonal["complete"]
        denied = client.post(f"/api/projects/{project['id']}/generations", headers=headers,
                             json={"idempotency_key": "unconfirmed-samples", "allow_warnings": False})
        assert denied.status_code == 409
        more = client.post(f"/api/projects/{project['id']}/photos", headers=headers,
                           data={"photo_group_id": sample_groups[2]["id"]},
                           files={"files": ("diagonal-2.jpg", image_bytes.getvalue(), "image/jpeg")})
        assert more.status_code == 201
        sample_photo_ids.append(more.json()[0]["id"])
        complete = client.get(f"/api/projects/{project['id']}/preflight").json()
        assert all(g["complete"] for g in complete["sample_group_completeness"])
        assert complete["photo_count"] == 5
        assert client.patch(f"/api/photos/{sample_photo_ids[0]}", headers=headers,
                            json={"photo_group_id": alarm_group["id"]}).status_code == 422
        other_groups = client.get(f"/api/projects/{second_project['id']}/photo-groups").json()
        other_sample = next(g for g in other_groups if g["scope"] == "sample")
        assert client.patch(f"/api/photos/{sample_photo_ids[0]}", headers=headers,
                            json={"photo_group_id": other_sample["id"]}).status_code == 422
        assert client.post(f"/api/projects/{second_project['id']}/photos", headers=headers,
                           data={"photo_group_id": sample_groups[0]["id"]},
                           files={"files": ("wrong.jpg", image_bytes.getvalue(), "image/jpeg")}).status_code == 404
        reorder = client.put(f"/api/photo-groups/{sample_groups[2]['id']}/order", headers=headers,
                             json={"photo_ids": [sample_photo_ids[3], sample_photo_ids[2]]})
        assert reorder.status_code == 200
        client.patch(f"/api/photos/{sample_photo_ids[3]}", headers=headers, json={"caption": "后侧对角"})
        full_task = client.post(f"/api/projects/{project['id']}/generations", headers=headers,
                               json={"idempotency_key": "complete-sample-snapshot", "allow_warnings": True})
        assert full_task.status_code == 202
        from app.db import SessionLocal
        from app.models import DocumentGenerationTask
        with SessionLocal() as session:
            snap = session.get(DocumentGenerationTask, full_task.json()["id"]).input_snapshot
            assert len(snap["sample_photo_groups"]) == 3
            assert all(g["test_item_id"] is not None for g in snap["photo_groups"])
            diagonal_snap = snap["sample_photo_groups"][2]
            assert diagonal_snap["photos"][0]["id"] == sample_photo_ids[3]
            assert diagonal_snap["photos"][0]["caption"] == "后侧对角"
        from app.models import GeneratedDocument
        from app.worker.word_worker import run_task
        from sqlalchemy import select
        monkeypatch.setattr(config.get_settings(), "word_com_enabled", False)
        run_task(full_task.json()["id"])
        with SessionLocal() as session:
            task_row = session.get(DocumentGenerationTask, full_task.json()["id"])
            assert task_row.status == 'succeeded', task_row.error_detail
            document = session.scalar(select(GeneratedDocument).where(GeneratedDocument.task_id == task_row.id))
            assert document.validation_report['generation']['sample_photo_count'] == 4
            assert document.validation_report['generation']['photo_count'] == 5
        monkeypatch.setattr(config.get_settings(), "max_project_photos", 5)
        assert client.post(f"/api/projects/{project['id']}/photos", headers=headers,
                           data={"photo_group_id": sample_groups[0]["id"]},
                           files={"files": ("extra.jpg", image_bytes.getvalue(), "image/jpeg")}).status_code == 413


def test_projects_are_isolated_per_user_and_password_can_change(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")

    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")

    def login(client: TestClient, username: str, password: str) -> dict:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    with TestClient(main.app) as admin, TestClient(main.app) as tester:
        admin_headers = login(admin, "admin", "test-admin-password")
        assert admin.post(
            "/api/admin/users",
            json={"username": "isolation-tester", "display_name": "隔离用户", "password": "long-test-password"},
            headers=admin_headers,
        ).status_code == 201
        project = admin.post(
            "/api/projects", json={"name": "管理员项目", "description": ""}, headers=admin_headers
        ).json()
        admin.put(
            f"/api/projects/{project['id']}/selection",
            json={"revision": project["revision"], "test_item_ids": ["alarm_bms"], "source": "manual"},
            headers=admin_headers,
        )
        group = next(
            g for g in admin.get(f"/api/projects/{project['id']}/photo-groups").json()
            if g["key"] == "alarm_evidence"
        )
        image_bytes = BytesIO()
        Image.new("RGB", (40, 30), "green").save(image_bytes, format="JPEG")
        photo = admin.post(
            f"/api/projects/{project['id']}/photos",
            data={"photo_group_id": group["id"]},
            files={"files": ("alarm.jpg", image_bytes.getvalue(), "image/jpeg")},
            headers=admin_headers,
        ).json()[0]
        note_url = f"/api/projects/{project['id']}/test-items/alarm_bms/result-note"
        assert admin.put(note_url, json={"note": "  报警功能正常  "}, headers=admin_headers).json()["note"] == "报警功能正常"
        assert admin.get(f"/api/projects/{project['id']}/test-result-notes").json() == {"alarm_bms": "报警功能正常"}
        assert admin.put(
            f"/api/projects/{project['id']}/test-items/no_such_item/result-note", json={"note": "x"}, headers=admin_headers
        ).status_code == 404
        task = admin.post(
            f"/api/projects/{project['id']}/generations",
            json={"idempotency_key": "isolation-task", "allow_warnings": True},
            headers=admin_headers,
        ).json()
        assert admin.get(f"/api/generations/{task['id']}").status_code == 200

        tester_headers = login(tester, "isolation-tester", "long-test-password")
        assert tester.get("/api/projects").json() == []
        own = tester.post(
            "/api/projects", json={"name": "测试用户项目", "description": ""}, headers=tester_headers
        ).json()
        assert [p["id"] for p in tester.get("/api/projects").json()] == [own["id"]]
        admin_ids = {p["id"] for p in admin.get("/api/projects").json()}
        assert project["id"] in admin_ids and own["id"] not in admin_ids

        pid = project["id"]
        assert tester.put(f"/api/projects/{pid}/test-items/alarm_bms/result-note", json={"note": "x"}, headers=tester_headers).status_code == 404
        assert tester.get(f"/api/projects/{pid}/test-result-notes").status_code == 404
        for path in (
            f"/api/projects/{pid}",
            f"/api/projects/{pid}/preflight",
            f"/api/projects/{pid}/photo-groups",
            f"/api/projects/{pid}/photos",
            f"/api/projects/{pid}/generated-documents",
            f"/api/projects/{pid}/ai-advice",
            f"/api/photos/{photo['id']}/content",
            f"/api/generations/{task['id']}",
        ):
            assert tester.get(path).status_code == 404, path
        assert tester.patch(
            f"/api/projects/{pid}", json={"revision": project["revision"], "name": "篡改"}, headers=tester_headers
        ).status_code == 404
        assert tester.patch(
            f"/api/photos/{photo['id']}", json={"caption": "篡改"}, headers=tester_headers
        ).status_code == 404
        assert tester.delete(f"/api/photos/{photo['id']}", headers=tester_headers).status_code == 404
        assert tester.put(
            f"/api/photo-groups/{group['id']}/order", json={"photo_ids": [photo["id"]]}, headers=tester_headers
        ).status_code == 404
        assert admin.get(f"/api/photos/{photo['id']}/content").status_code == 200

        wrong = tester.post(
            "/api/auth/password",
            json={"current_password": "not-the-password", "new_password": "brand-new-password"},
            headers=tester_headers,
        )
        assert wrong.status_code == 400
        with TestClient(main.app) as other_device:
            login(other_device, "isolation-tester", "long-test-password")
            changed = tester.post(
                "/api/auth/password",
                json={"current_password": "long-test-password", "new_password": "brand-new-password"},
                headers=tester_headers,
            )
            assert changed.status_code == 204
            assert tester.get("/api/auth/me").status_code == 200
            assert other_device.get("/api/auth/me").status_code == 401
        assert tester.post(
            "/api/auth/login", json={"username": "isolation-tester", "password": "long-test-password"}
        ).status_code == 401
        login(tester, "isolation-tester", "brand-new-password")



def test_worker_status_reflects_heartbeat(tmp_path: Path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'worker.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")

    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")
    models = importlib.import_module("app.models")
    db_module = importlib.import_module("app.db")

    with TestClient(main.app) as client:
        assert client.get("/api/worker/status").status_code == 401
        assert client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"}).status_code == 200
        assert client.get("/api/worker/status").json() == {"online": False, "last_seen": None}
        with db_module.SessionLocal.begin() as db:
            db.add(models.WorkerHeartbeat(worker_id="w1", updated_at=datetime.now(UTC) - timedelta(minutes=5)))
        assert client.get("/api/worker/status").json()["online"] is False
        with db_module.SessionLocal.begin() as db:
            db.get(models.WorkerHeartbeat, "w1").updated_at = datetime.now(UTC)
        status = client.get("/api/worker/status").json()
        assert status["online"] is True and status["last_seen"]
