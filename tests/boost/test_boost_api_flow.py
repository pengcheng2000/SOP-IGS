from __future__ import annotations

import importlib
from pathlib import Path

from conftest import build_sample_workbook
from fastapi.testclient import TestClient


def test_boost_project_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'boost.db').as_posix()}")
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")
    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")
    workbook = build_sample_workbook(tmp_path / "input.xlsx")

    with TestClient(main.app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        boost_config = client.get("/api/boost/config").json()
        assert boost_config["available"] and boost_config["template_status"] == "approved"
        assert {field["key"] for field in boost_config["fields"]} >= {"project_name", "document_number", "drafter"}
        assert boost_config["input_template_available"]
        template = client.get("/api/boost/input-template")
        assert template.status_code == 200 and template.content[:2] == b"PK"
        references = next(field for field in boost_config["fields"] if field["key"] == "project_references")
        assert len(references["fixed_lines"]) == 6

        created = client.post("/api/boost/projects", json={"name": "意大利站点"}, headers=headers)
        assert created.status_code == 201
        project = created.json()
        project_id = project["id"]
        assert project["source_file"] is None and project["document_version"] == "A0"

        # The two products do not see each other's projects.
        cabinet = client.post("/api/projects", json={"name": "工商业柜项目"}, headers=headers).json()
        assert all(item["id"] != project_id for item in client.get("/api/projects").json())
        assert all(item["id"] != cabinet["id"] for item in client.get("/api/boost/projects").json())
        assert client.get(f"/api/projects/{project_id}").status_code == 404
        assert client.get(f"/api/projects/{project_id}/photo-groups").status_code == 404
        assert client.get(f"/api/boost/projects/{cabinet['id']}").status_code == 404

        bad = client.patch(f"/api/boost/projects/{project_id}",
                           json={"revision": project["revision"], "fields": {"not_a_field": "x"}}, headers=headers)
        assert bad.status_code == 422
        bad_month = client.patch(f"/api/boost/projects/{project_id}",
                                 json={"revision": project["revision"], "fields": {"archive_month": "2026年10月"}}, headers=headers)
        assert bad_month.status_code == 422 and "YYYY-MM" in bad_month.json()["detail"]
        updated = client.patch(
            f"/api/boost/projects/{project_id}",
            json={"revision": project["revision"], "document_number": "DOC-001",
                  "fields": {"project_name": "意大利站点", "drafter": "拟制人", "archive_month": "2026-10",
                             "project_references": "电气图\n测试需求"}},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["fields"]["drafter"] == "拟制人"

        preflight = client.get(f"/api/boost/projects/{project_id}/preflight").json()
        assert [item["code"] for item in preflight["blockers"]] == ["MISSING_SOURCE_FILE"]

        invalid = client.post(f"/api/boost/projects/{project_id}/source-file",
                              files={"file": ("broken.xlsx", b"not a workbook")}, headers=headers)
        assert invalid.status_code == 201 and invalid.json()["status"] == "invalid"
        assert client.get(f"/api/boost/projects/{project_id}/preflight").json()["blockers"][0]["code"] == "SOURCE_FILE_INVALID"

        from openpyxl import Workbook

        legacy = Workbook()
        legacy.active.title = "外观检查"
        legacy.active["A1"] = "集装箱检查"
        legacy.active["B1"] = "尺寸符合要求"
        legacy_path = tmp_path / "legacy.xlsx"
        legacy.save(legacy_path)
        rejected = client.post(f"/api/boost/projects/{project_id}/source-file",
                               files={"file": ("legacy.xlsx", legacy_path.read_bytes())}, headers=headers).json()
        assert rejected["status"] == "invalid"
        assert "NO_FORMAT_COLUMN" in [issue["code"] for issue in rejected["issues"]]
        assert client.get(f"/api/boost/projects/{project_id}/preflight").json()["blockers"][0]["code"] == "SOURCE_FILE_INVALID"

        uploaded = client.post(f"/api/boost/projects/{project_id}/source-file",
                               files={"file": ("测试项分类表.xlsx", workbook.read_bytes())}, headers=headers)
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()
        assert source["status"] == "parsed" and source["chapter_count"] == 2 and source["image_count"] == 2
        image_item = next(item for item in source["document"]["chapters"][1]["items"] if item["type"] == "image")
        assert "path" not in image_item["ref"]
        assert client.get(image_item["ref"]["url"]).status_code == 200
        assert client.get(f"/api/boost/source-files/{source['id']}/original").content == workbook.read_bytes()
        assert client.get(f"/api/boost/projects/{project_id}").json()["source_file"]["id"] == source["id"]
        assert client.get(f"/api/boost/projects/{project_id}/preflight").json()["ready"]

        task = client.post(f"/api/boost/projects/{project_id}/generations",
                           json={"idempotency_key": "boost-generation-1"}, headers=headers)
        assert task.status_code == 202, task.text

        from app.boost.worker import claim_boost_task, run_boost_task

        monkeypatch.setattr(config.get_settings(), "word_com_enabled", False)
        claimed = claim_boost_task("test-worker")
        assert claimed == task.json()["id"]
        run_boost_task(claimed)
        assert claim_boost_task("test-worker") is None
        finished = client.get(f"/api/boost/generations/{claimed}").json()
        assert finished["status"] == "succeeded", finished["error_detail"]
        assert finished["events"][-1]["phase"] == "succeeded"

        documents = client.get(f"/api/boost/projects/{project_id}/documents").json()
        download = client.get(documents[0]["download_url"])
        assert download.status_code == 200 and download.content[:2] == b"PK"

        approved = client.post("/api/boost/admin/template/approve", headers=headers)
        assert approved.status_code == 200 and approved.json()["status"] == "approved"
