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
from sqlalchemy import func, select

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
        "D7",
        "E23",
    }
    # Chapter titles are the sheet names; the workbook has no 目录 page or title rows.
    assert [c.title for c in document.chapters][:3] == ["外观检查", "机械强度测试", "防水测试"]
    assert "目录" not in load_workbook(TEMPLATE, read_only=True).sheetnames
    assert len(DocumentModel.from_dict(document.to_dict()).image_refs()) == 1
    assert DocumentModel.from_dict(document.to_dict()).extra == document.extra


def test_delete_reorder_rename_and_level_four(tmp_path):
    def change(book):
        for name in book.sheetnames[2:18]:
            if name not in {"外观检查", "UPS相关测试"}:
                del book[name]
        sheet = book["UPS相关测试"]
        book.move_sheet(sheet, offset=-1)
        sheet.title = "UPS最终方案"
        sheet["A6"] = "5.16.1.1 自动关机测试"
        sheet["O6"] = "四级标题+段落"

    result = parse(modified(tmp_path, change), tmp_path)
    assert result.valid, result.issues
    assert [c.title for c in result.document.chapters] == ["UPS最终方案", "外观检查"]
    assert any(
        isinstance(i, Heading) and i.level == 4
        for c in result.document.chapters
        for i in c.items
    )


def test_invalid_format_and_orphan_heading_are_located(tmp_path):
    def change(book):
        sheet = book["外观检查"]
        sheet["O1"] = "四级标题+段落"
        sheet["O2"] = "凭颜色识别"

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
        book["防水测试"]["A1"] = '=CONCAT("测试", "内容")'

    result = parse(modified(tmp_path, change), tmp_path)
    assert not result.valid
    assert any(
        i.code == "FORMULA_NOT_CALCULATED" and i.cell == "A1" for i in result.issues
    )


def test_new_table_can_start_in_column_a(tmp_path):
    def change(book):
        sheet = book.create_sheet("125kW新增章节")
        sheet["A1"] = "参数"
        sheet["B1"] = "数值"
        sheet["O1"] = "表头"
        sheet["A2"] = "必须保留A列"
        sheet["B2"] = 123
        sheet["O2"] = "表格"

    result = parse(modified(tmp_path, change), tmp_path)
    assert result.valid, result.issues
    assert result.document.chapters[-1].title == "125kW新增章节"
    table = result.document.chapters[-1].items[0]
    assert isinstance(table, Table)
    assert [c.text for c in table.rows[1]] == ["必须保留A列", "123"]


def test_sheet_name_is_chapter_title_and_legacy_layout_still_uploads(tmp_path):
    def change(book):
        book["外观检查"].title = "1、外观检查"
        # Older workbooks: a 目录 sheet, a header row (O1=格式) and a 二级标题 row.
        contents = book.create_sheet("目录")
        contents["C3"] = 5.1
        contents["E3"] = "不应成为章节"
        legacy = book.create_sheet("旧版章节")
        legacy["A1"] = "标题 / 测试内容"
        legacy["O1"] = "格式"
        legacy["A2"] = "5.9 以工作表名称为准的旧标题"
        legacy["O2"] = "二级标题"
        legacy["A3"] = "说明文字"
        legacy["O3"] = "段落"

    result = parse(modified(tmp_path, change), tmp_path)
    assert result.valid, result.issues
    titles = [c.title for c in result.document.chapters]
    assert titles[0] == "外观检查" and titles[-1] == "旧版章节"
    assert "不应成为章节" not in json.dumps(result.document.to_dict(), ensure_ascii=False)
    legacy = result.document.chapters[-1]
    assert [i.text for i in legacy.items] == ["说明文字"]


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
        # Headers use a self-contained legacy textbox, not case-specific Office/WPS shapes.
        for header in headers:
            assert not header.xpath("//mc:AlternateContent", namespaces=margin_ns)
            assert not header.xpath("//*[local-name()='imagedata']")
            assert not header.xpath("//*[@type='#_x0000_t202']")
        assert any(header.xpath("//*[@id='CabinetCopyright']") for header in headers)
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
        title_p = root.find("w:body/w:p", NS)
        assert title_p.find("w:r/w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == "32"
        assert (
            title_p.find("w:r/w:rPr/w:rFonts", NS).get("{" + NS["w"] + "}eastAsia")
            == "楷体"
        )
        body = next(
            p
            for p in root.findall("w:body/w:p", NS)
            if "户外柜的外观检查" in "".join(p.xpath(".//w:t/text()", namespaces=NS))
        )
        indent = body.find("w:pPr/w:ind", NS)
        assert indent.get("{" + NS["w"] + "}left") == "210"
        assert indent.get("{" + NS["w"] + "}firstLine") == "420"
        numbering = etree.fromstring(archive.read("word/numbering.xml"))
        levels = numbering.xpath(
            "//w:abstractNum[@w:abstractNumId='9100']/w:lvl", namespaces=NS
        )
        expected_levels = [
            ("%1.", 0, "425", True, "24"),
            ("%1.%2.", 0, "630", True, "24"),
            ("%1.%2.%3.", 210, "960", False, "21"),
            ("%1.%2.%3.%4.", 420, "1320", False, "21"),
        ]
        for level, (lvl_text, start_x, text_left, is_bold, sz) in zip(
            levels, expected_levels, strict=True
        ):
            assert level.find("w:lvlText", NS).get("{" + NS["w"] + "}val") == lvl_text
            indent = level.find("w:pPr/w:ind", NS)
            assert indent.get("{" + NS["w"] + "}left") == text_left
            assert (
                int(indent.get("{" + NS["w"] + "}left"))
                - int(indent.get("{" + NS["w"] + "}hanging"))
                == start_x
            )
            bold_node = level.find("w:rPr/w:b", NS)
            assert (bold_node is not None and bold_node.get("{" + NS["w"] + "}val") != "0") == is_bold
            assert level.find("w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == sz
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
            bold_node = heading.find("w:r/w:rPr/w:b", NS)
            assert bold_node is not None and bold_node.get("{" + NS["w"] + "}val") != "0"
        for heading in root.xpath(
            "./w:body/w:p[w:pPr/w:numPr/w:numId[@w:val='9100']]", namespaces=NS
        ):
            assert not heading.xpath(
                "./w:pPr/w:keepNext|./w:pPr/w:keepLines|./w:pPr/w:pageBreakBefore",
                namespaces=NS,
            )
            ilvl = int(
                heading.find("w:pPr/w:numPr/w:ilvl", NS).get("{" + NS["w"] + "}val")
            )
            bold_node = heading.find("w:r/w:rPr/w:b", NS)
            is_bold = bold_node is not None and bold_node.get("{" + NS["w"] + "}val") != "0"
            assert is_bold == (ilvl in (0, 1))
            assert heading.find("w:r/w:rPr/w:sz", NS).get("{" + NS["w"] + "}val") == (
                "24" if ilvl in (0, 1) else "21"
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
        assert list_indent.get("{" + NS["w"] + "}left") == "945"
        assert list_indent.get("{" + NS["w"] + "}hanging") == "315"


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
        # A project whose generation is still queued cannot be deleted under the worker.
        busy = client.delete(url, headers=headers)
        assert busy.status_code == 409, busy.text
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
        # Other users cannot delete it; the owner deletes rows and stored files.
        assert client.delete(url, headers=headers).status_code == 404
        assert client.delete(f"{base}/projects/{own['id']}", headers=headers).status_code == 204
        assert client.get(f"{base}/projects/{own['id']}").status_code == 404
        client.post("/api/auth/logout", headers=headers)
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "test-admin-password"},
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        from app.cabinet_plan.models import (
            CabinetPlanGeneratedDocument,
            CabinetPlanProject,
            CabinetPlanSourceFile,
        )

        with SessionLocal() as db:
            document_path = Path(
                db.scalar(
                    select(CabinetPlanGeneratedDocument.file_path).where(
                        CabinetPlanGeneratedDocument.project_id == p["id"]
                    )
                )
            )
            source_path = Path(
                db.scalar(
                    select(CabinetPlanSourceFile.original_path)
                    .where(CabinetPlanSourceFile.project_id == p["id"])
                    .limit(1)
                )
            )
        assert document_path.is_file() and source_path.is_file()
        assert client.delete(url, headers=headers).status_code == 204
        assert client.get(url).status_code == 404
        assert not document_path.parent.exists() and not source_path.parents[1].exists()
        with SessionLocal() as db:
            for model in (
                CabinetPlanProject,
                CabinetPlanSourceFile,
                CabinetPlanGenerationTask,
                CabinetPlanGeneratedDocument,
            ):
                column = model.id if model is CabinetPlanProject else model.project_id
                assert db.scalar(select(func.count()).where(column == p["id"])) == 0
        assert all(item["id"] != p["id"] for item in client.get(base + "/projects").json())
