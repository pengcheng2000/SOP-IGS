from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from app.cabinet_plan.docx.builder import generate_cabinet_plan_docx
from app.cabinet_plan.input import parse_workbook
from app.document_common.model import DocumentModel, Heading, Image, Table
from app.document_common.ooxml import NS
from app.document_common.validation import validate_docx
from fastapi.testclient import TestClient
from lxml import etree
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/cabinet-test-plan/v1/input-template.xlsx"
MASTER = TEMPLATE.with_name("master.docx")


def parse(path, tmp_path):
    return parse_workbook(path, tmp_path / "images")


def modified(tmp_path, change):
    book = load_workbook(TEMPLATE)
    change(book)
    path = tmp_path / "edited.xlsx"
    book.save(path)
    return path


def test_full_template_retains_content_and_excludes_instructions(tmp_path):
    result = parse(TEMPLATE, tmp_path)
    assert result.valid, result.issues
    assert result.summary() == {
        "chapter_count": 16,
        "heading_count": 41,
        "table_count": 21,
        "image_count": 1,
        "field_count": 6,
    }
    document = result.document
    assert document.extra["fields"]["archive_month"]["value"] == "2026-09"
    assert document.extra["fields"]["document_title"]["source"] == "首页!A1"
    text = json.dumps(document.to_dict(), ensure_ascii=False)
    assert "单元格留" not in text and "方案编辑人员" not in text
    assert "5.2.3." not in text and "4.14.3" not in text
    assert "恩玖PCS+凯迈液冷机" in text  # suspected offset is deliberately preserved
    assert "0.5≤P≤0.3" in text
    assert "8小时" in text
    assert "2026年9月2日" not in text  # generated revision date owns this slot
    assert {i.cell for i in result.issues if i.code == "SOURCE_CONTENT_REVIEW"} == {
        "D9",
        "E25",
    }
    assert len(DocumentModel.from_dict(document.to_dict()).image_refs()) == 1
    assert DocumentModel.from_dict(document.to_dict()).extra == document.extra


def test_delete_reorder_rename_and_level_four(tmp_path):
    def change(book):
        for s in list(book):
            if "、" in s.title and not s.title.startswith(("1、", "16、", "17、")):
                del book[s.title]
        sheet = book["16、UPS相关测试"]
        book.move_sheet(sheet, offset=-1)
        sheet.title = "UPS最终方案"
        sheet["A8"] = "5.16.1.1 自动关机测试"
        sheet["O8"] = "四级标题+段落"

    result = parse(modified(tmp_path, change), tmp_path)
    assert result.valid, result.issues
    assert {c.title for c in result.document.chapters} == {"外观检查", "UPS配置和测试"}
    assert any(
        isinstance(i, Heading) and i.level == 4
        for c in result.document.chapters
        for i in c.items
    )


def test_invalid_format_and_orphan_heading_are_located(tmp_path):
    def change(book):
        sheet = book["1、外观检查"]
        sheet["O3"] = "四级标题+段落"
        sheet["O4"] = "凭颜色识别"

    result = parse(modified(tmp_path, change), tmp_path)
    assert not result.valid
    assert {i.code for i in result.issues} >= {"ORPHAN_HEADING", "INVALID_FORMAT"}
    assert all(i.sheet and i.cell for i in result.issues)


def test_reserved_rows_and_merged_table_cells(tmp_path):
    result = parse(TEMPLATE, tmp_path)
    software = next(
        i for i in result.document.chapters[7].items if isinstance(i, Table)
    )
    assert len(software.rows) == 8  # header + six entries + marker, no blank padding
    assert software.rows[-1][0].text == "以下空白"
    insulation = [i for i in result.document.chapters[5].items if isinstance(i, Table)]
    assert len(insulation) == 4
    assert any(cell.row_span == 2 for row in insulation[1].rows for cell in row)
    assert insulation[-1].header_rows == 2
    assert any(isinstance(i, Image) for i in result.document.chapters[12].items)


def test_missing_binding_and_legacy_rejected(tmp_path):
    def change(book):
        del book.defined_names["sop_template_version"]

    result = parse(modified(tmp_path, change), tmp_path)
    assert not result.valid and result.issues[0].code == "UNSUPPORTED_TEMPLATE"
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not an xlsx")
    assert not parse(path, tmp_path).valid


def test_uncalculated_formula_does_not_silently_drop_content(tmp_path):
    def change(book):
        book["3、防水测试"]["A3"] = '=CONCAT("测试", "内容")'

    result = parse(modified(tmp_path, change), tmp_path)
    assert not result.valid
    assert any(
        i.code == "FORMULA_NOT_CALCULATED" and i.cell == "A3" for i in result.issues
    )


def test_new_table_can_start_in_column_a(tmp_path):
    def change(book):
        sheet = book.create_sheet("新增测试")
        sheet["O1"] = "格式"
        sheet["A2"] = "125kW新增章节"
        sheet["O2"] = "二级标题"
        sheet["A3"] = "参数"
        sheet["B3"] = "数值"
        sheet["O3"] = "表头"
        sheet["A4"] = "必须保留A列"
        sheet["B4"] = 123
        sheet["O4"] = "表格"

    result = parse(modified(tmp_path, change), tmp_path)
    assert result.valid, result.issues
    assert result.document.chapters[-1].title == "125kW新增章节"
    table = result.document.chapters[-1].items[0]
    assert isinstance(table, Table)
    assert [c.text for c in table.rows[1]] == ["必须保留A列", "123"]


def test_page_overflow_is_an_explicit_generation_error():
    from app.cabinet_plan.docx.validator import validate_pagination
    from app.document_common.ooxml import DocxGenerationError

    validate_pagination({"bookmark_pages": {"CabinetSummary": 2, "CabinetBody": 3}})
    with pytest.raises(DocxGenerationError) as error:
        validate_pagination({"bookmark_pages": {"CabinetSummary": 4, "CabinetBody": 5}})
    assert error.value.code == "PAGE_LAYOUT_OVERFLOW"
    with pytest.raises(DocxGenerationError):
        validate_pagination(
            {
                "bookmark_pages": {"CabinetSummary": 2, "CabinetBody": 3},
                "title_block_page": 2,
            }
        )


def test_generation_contains_live_fields_and_frozen_date(tmp_path):
    parsed = parse(TEMPLATE, tmp_path)
    fields = {k: v["value"] for k, v in parsed.document.extra["fields"].items()}
    target = tmp_path / "output.docx"
    report = generate_cabinet_plan_docx(
        MASTER, target, fields, parsed.document, generation_date="2026-10-26"
    )
    assert report["expected_headings"][0] == ("5.1", "外观检查")
    assert report["table_count"] == 22
    assert report["content_validation"]["valid"]
    assert validate_docx(target, 0)["valid"]
    with ZipFile(target) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        assert root.find("w:body/w:sectPr/w:pgBorders", NS) is None
        headers = [
            etree.fromstring(archive.read(part))
            for part in archive.namelist()
            if part.startswith("word/header") and part.endswith(".xml")
        ]
        frames = [
            frame
            for header in headers
            for frame in header.xpath("//*[@id='CabinetPageFrame']")
        ]
        assert len(frames) == 1
        margin_ns = {
            **NS,
            "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
        }
        copyright_boxes = [
            box
            for header in headers
            for box in header.xpath(
                "//w:txbxContent[not(ancestor::mc:Fallback)]", namespaces=margin_ns
            )
            if "版权所有" in "".join(box.xpath(".//w:t/text()", namespaces=NS))
        ]
        assert len(copyright_boxes) == 1
        assert "侵权必究" in "".join(
            copyright_boxes[0].xpath(".//w:t/text()", namespaces=NS)
        )
        assert "mso-position-vertical-relative:page" in frames[0].get("style")
        assert "height:782.35pt" in frames[0].get("style")
        text = "".join(root.xpath("//w:t/text()", namespaces=NS))
        assert "2026年10月26日A0版本。" in text
        assert "{{" not in text and "XXX" not in text and "方案编辑人员" not in text
        assert "2026年9月2日" not in text
        assert not any("comment" in n.lower() for n in archive.namelist())
        assert {"CabinetBody", "CabinetSummary"} <= set(
            root.xpath("//w:bookmarkStart/@w:name", namespaces=NS)
        )
        # The complete title block stays in the first-page footer, with its own
        # live total-page field and image relationship scope.
        first_rid = root.xpath(
            "//w:sectPr/w:footerReference[@w:type='first']/@r:id",
            namespaces={
                **NS,
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            },
        )[0]
        rels = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
        first_part = next(
            rel.get("Target") for rel in rels if rel.get("Id") == first_rid
        )
        footer = etree.fromstring(archive.read("word/" + first_part))
        assert "CabinetTitleBlock" in footer.xpath(
            "//w:bookmarkStart/@w:name", namespaces=NS
        )
        assert "批准" in "".join(footer.xpath("//w:t/text()", namespaces=NS))
        filename_boxes = footer.xpath(
            "//w:txbxContent[not(ancestor::mc:Fallback)]", namespaces=margin_ns
        )
        assert len(filename_boxes) == 1
        assert "电子文件名：" + fields["document_code"] in "".join(
            filename_boxes[0].xpath(".//w:t/text()", namespaces=NS)
        )
        for reference in root.xpath(
            "//w:sectPr/w:footerReference[@w:type='default']", namespaces=NS
        ):
            rid = reference.get("{" + NS["r"] + "}id")
            part = next(rel.get("Target") for rel in rels if rel.get("Id") == rid)
            normal_footer = etree.fromstring(archive.read("word/" + part))
            assert "电子文件名" not in "".join(
                normal_footer.xpath("//w:t/text()", namespaces=NS)
            )
        assert footer.xpath(
            "//w:fldSimple[contains(@w:instr, 'NUMPAGES')]", namespaces=NS
        )
        assert not root.xpath("//w:tbl[.//w:t[text()='批准']]", namespaces=NS)
        body = next(
            p
            for p in root.findall("w:body/w:p", NS)
            if "户外柜的外观检查" in "".join(p.xpath(".//w:t/text()", namespaces=NS))
        )
        indent = body.find("w:pPr/w:ind", NS)
        assert indent.get("{" + NS["w"] + "}left") == "840"
        assert indent.get("{" + NS["w"] + "}firstLine") == "0"
        numbering = etree.fromstring(archive.read("word/numbering.xml"))
        levels = numbering.xpath(
            "//w:abstractNum[@w:abstractNumId='9100']/w:lvl", namespaces=NS
        )
        for level in levels:
            indent = level.find("w:pPr/w:ind", NS)
            assert (
                int(indent.get("{" + NS["w"] + "}left"))
                - int(indent.get("{" + NS["w"] + "}hanging"))
                == 210
            )
            assert level.find("w:rPr/w:b", NS).get("{" + NS["w"] + "}val") == "0"
            assert level.find("w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == "24"
        root_level = levels[0]
        assert root_level.find("w:lvlText", NS).get("{" + NS["w"] + "}val") == "%1."
        assert root_level.find("w:pPr/w:ind", NS).get("{" + NS["w"] + "}left") == "630"
        for title in ["适用范围", "参考文献", "测试环境", "调试工装仪器明细"]:
            heading = next(
                p
                for p in root.findall("w:body/w:p", NS)
                if "".join(p.xpath(".//w:t/text()", namespaces=NS)) == title
            )
            assert heading.find("w:pPr/w:keepNext", NS) is None
            assert heading.find("w:pPr/w:keepLines", NS) is None
            assert (
                heading.find("w:r/w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == "24"
            )
        for heading in root.xpath(
            "./w:body/w:p[w:pPr/w:numPr/w:numId[@w:val='9100']]", namespaces=NS
        ):
            assert not heading.xpath(
                "./w:pPr/w:keepNext|./w:pPr/w:keepLines|./w:pPr/w:pageBreakBefore",
                namespaces=NS,
            )
            assert heading.find("w:r/w:rPr/w:b", NS).get("{" + NS["w"] + "}val") == "0"
            assert (
                heading.find("w:r/w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == "24"
            )
        from app.cabinet_plan.docx.content import validate_body_content
        from app.document_common.ooxml import DocxGenerationError

        duplicate = copy.deepcopy(body)
        root.find("w:body", NS).insert(1, duplicate)
        with pytest.raises(DocxGenerationError) as error:
            validate_body_content(root, parsed.document, fields, "2026-10-26")
        assert error.value.code == "CONTENT_MISMATCH"
        root.find("w:body", NS).remove(duplicate)
        root.find("w:body", NS).remove(body)
        missing = validate_body_content(
            root, parsed.document, fields, "2026-10-26", raise_on_error=False
        )
        assert missing["missing_paragraphs"] == 1
        list_indent = numbering.xpath(
            "//w:abstractNum[@w:abstractNumId='9201']/w:lvl[@w:ilvl='0']/w:pPr/w:ind",
            namespaces=NS,
        )[0]
        assert list_indent.get("{" + NS["w"] + "}left") == "1260"
        assert list_indent.get("{" + NS["w"] + "}hanging") == "420"


def test_api_excel_priority_snapshot_permissions_and_worker(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SOP_DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    )
    monkeypatch.setenv("SOP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOP_BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")
    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    main = importlib.import_module("app.main")
    assert main.engine.url.drivername == "sqlite"
    assert (
        Path(main.engine.url.database)
        .resolve()
        .is_relative_to(tmp_path.parent.resolve())
    ), "Refusing to bootstrap a non-test database"
    with TestClient(main.app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-password"},
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        base = "/api/cabinet-plans"
        assert client.get(base + "/config").json()["available"]
        assert client.get(base + "/config").json()["template_status"] == "approved"
        assert client.get(base + "/input-template").content[:2] == b"PK"
        p = client.post(base + "/projects", json={}, headers=headers).json()
        url = f"{base}/projects/{p['id']}"
        assert p["name"] == "未命名测试方案" and p["document_kind"] == "plan"
        assert client.get(url + "/preflight").json()["ready"] is False
        uploaded = client.post(
            url + "/source-file",
            files={"file": ("input.xlsx", TEMPLATE.read_bytes())},
            headers=headers,
        )
        assert uploaded.status_code == 201 and uploaded.json()["status"] == "parsed", (
            uploaded.text
        )
        source = uploaded.json()
        p = client.get(url).json()
        assert p["name"] == p["resolved_fields"]["document_title"]
        assert p["field_sources"]["document_title"]["kind"] == "excel"
        assert client.get(url + "/preflight").json()["ready"]
        image = next(
            i
            for c in source["document"]["chapters"]
            for i in c["items"]
            if i["type"] == "image"
        )["ref"]
        assert "path" not in image and client.get(image["url"]).status_code == 200
        assert (
            client.patch(
                url,
                json={
                    "revision": p["revision"],
                    "fields": {"document_title": "override"},
                },
                headers=headers,
            ).status_code
            == 422
        )
        p = client.patch(
            url,
            json={
                "revision": p["revision"],
                "fields": {"drafter": "补填人员"},
                "name": "自定义显示名称",
            },
            headers=headers,
        ).json()
        assert p["field_sources"]["drafter"]["kind"] == "supplement"
        stale = client.patch(
            url, json={"revision": 1, "name": "stale"}, headers=headers
        )
        assert stale.status_code == 409
        # Reproduce a running API after the master/manifest were rebuilt but
        # before the template registry was refreshed at startup.
        import hashlib

        from app.cabinet_plan.models import CabinetPlanGenerationTask
        from app.db import SessionLocal
        from app.models import Template

        with SessionLocal.begin() as db:
            from sqlalchemy import select

            template = db.scalar(
                select(Template).where(Template.key == "cabinet-test-plan")
            )
            template_id = template.id
            template.master_sha256 = "0" * 64
            template.status = "approved"
        current_config = client.get(base + "/config").json()
        assert current_config["available"]
        assert current_config["template_status"] == "approved"
        task = client.post(
            url + "/generations",
            json={"idempotency_key": "cabinet-task-original", "allow_warnings": True},
            headers=headers,
        )
        assert task.status_code == 202, task.text
        task_id = task.json()["id"]
        actual_hash = hashlib.sha256(MASTER.read_bytes()).hexdigest()
        with SessionLocal() as db:
            assert db.get(Template, template_id).master_sha256 == actual_hash
            assert db.get(Template, template_id).status == "approved"
            assert (
                db.get(CabinetPlanGenerationTask, task_id).input_snapshot[
                    "master_sha256"
                ]
                == actual_hash
            )
        edited = modified(
            tmp_path, lambda book: setattr(book["首页"]["C45"], "value", "Excel编制人")
        )
        assert (
            client.post(
                url + "/source-file",
                files={"file": ("edited.xlsx", edited.read_bytes())},
                headers=headers,
            ).json()["status"]
            == "parsed"
        )
        p = client.get(url).json()
        assert p["name"] == "自定义显示名称"
        assert p["resolved_fields"]["drafter"] == "Excel编制人"
        assert p["field_sources"]["drafter"]["kind"] == "excel"
        repeat = client.post(
            url + "/generations",
            json={"idempotency_key": "cabinet-task-original"},
            headers=headers,
        )
        assert repeat.json()["id"] == task_id
        from app.cabinet_plan.worker import (
            claim_cabinet_plan_task,
            run_cabinet_plan_task,
        )

        monkeypatch.setattr(config.get_settings(), "word_com_enabled", False)
        assert claim_cabinet_plan_task("test-cabinet") == task_id
        run_cabinet_plan_task(task_id)
        status = client.get(f"{base}/generations/{task_id}").json()
        assert status["status"] == "succeeded", status
        record = client.get(url + "/documents").json()[0]
        output = client.get(record["download_url"])
        from io import BytesIO

        with ZipFile(BytesIO(output.content)) as archive:
            text = "".join(
                text
                for part in archive.namelist()
                if part == "word/document.xml"
                or (part.startswith("word/footer") and part.endswith(".xml"))
                for text in etree.fromstring(archive.read(part)).xpath(
                    "//w:t/text()", namespaces=NS
                )
            )
            assert "补填人员" in text and "Excel编制人" not in text
        # A second user cannot access any source/task/document or reuse another user's key.
        created = client.post(
            "/api/admin/users",
            json={
                "username": "cabinet-user",
                "display_name": "方案测试",
                "password": "other-test-password",
                "role": "user",
            },
            headers=headers,
        )
        assert created.status_code in (200, 201), created.text
        client.post("/api/auth/logout", headers=headers)
        login = client.post(
            "/api/auth/login",
            json={"username": "cabinet-user", "password": "other-test-password"},
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        assert client.get(url).status_code == 404
        assert client.get(image["url"]).status_code == 404
        assert client.get(record["download_url"]).status_code == 404
        assert client.get(f"{base}/generations/{task_id}").status_code == 404
        own = client.post(base + "/projects", json={}, headers=headers).json()
        assert (
            client.post(
                f"{base}/projects/{own['id']}/generations",
                json={"idempotency_key": "cabinet-task-original"},
                headers=headers,
            ).status_code
            == 409
        )
