"""Word COM acceptance matrix: full, reduced/reordered, long title, and page overflow.

Outputs stay in ignored tests/output/cabinet-plan. Uses an isolated Word process per
document, without connecting to the application database or a deployed worker.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cabinet_plan.docx.builder import generate_cabinet_plan_docx
from app.cabinet_plan.docx.content import validate_docx_body
from app.cabinet_plan.input import parse_workbook
from app.document_common.model import Chapter, DocumentModel, Heading, Paragraph
from app.document_common.validation import validate_docx


def main():
    output = ROOT / "tests/output/cabinet-plan"
    output.mkdir(parents=True, exist_ok=True)
    template = ROOT / "templates/cabinet-test-plan/v1"
    parsed = parse_workbook(template / "input-template.xlsx", output / "images")
    assert parsed.valid, parsed.issues
    fields = {
        key: entry["value"] for key, entry in parsed.document.extra["fields"].items()
    }
    reduced = DocumentModel(
        (
            parsed.document.chapters[12],
            parsed.document.chapters[0],
            parsed.document.chapters[15],
        ),
        parser_version=parsed.document.parser_version,
        extra=copy.deepcopy(parsed.document.extra),
    )
    cases = {
        "full": (parsed.document, fields, True),
        "reduced": (reduced, fields, True),
        "long-title": (
            reduced,
            {
                **fields,
                "document_title": "某地区分布式工商业储能示范项目（含多型号户外柜及配套控制设备）生产测试需求与出厂配置确认方案"
                * 2,
            },
            True,
        ),
        "all-heading-levels": (
            DocumentModel(
                (
                    Chapter(
                        "二级标题校验",
                        "校验",
                        (
                            Heading(3, "三级标题校验"),
                            Heading(4, "四级标题校验"),
                            Paragraph(
                                "验证全文四级标题的编号、字号、非加粗和与边框的距离。"
                            ),
                        ),
                    ),
                ),
                parser_version=parsed.document.parser_version,
                extra=copy.deepcopy(parsed.document.extra),
            ),
            fields,
            True,
        ),
        "overflow": (
            reduced,
            {**fields, "scope_text": "本项目包含多种机型，测试范围需确认。" * 300},
            False,
        ),
        "footer-boundary-overflow": (
            reduced,
            {**fields, "scope_text": "本项目测试范围需要逐项确认。" * 100},
            False,
        ),
    }
    reports = {}
    for name, (document, values, fits) in cases.items():
        path = output / f"{name}.docx"
        report = generate_cabinet_plan_docx(
            template / "master.docx",
            path,
            values,
            document,
            generation_date="2026-10-26",
        )
        validate_docx(path, 0)
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.cabinet_plan.docx.word",
                str(path),
                str(output / f"{name}.pdf"),
            ],
            cwd=ROOT / "backend",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.returncode == 0, process.stderr
        com = json.loads(process.stdout.strip().splitlines()[-1])
        content = validate_docx_body(path, document, values, "2026-10-26")
        assert com["layout_adjustments"]["orphan_headings"] == 0
        validate_docx(path, 0)
        actual = [
            [entry["number"].rstrip("."), entry["text"]]
            for entry in com["headings"]
            if entry["number"].startswith("5.") and "." in entry["number"].rstrip(".")
        ]
        assert actual == [list(pair) for pair in report["expected_headings"]]
        assert (
            com["bookmark_pages"] == {"CabinetSummary": 2, "CabinetBody": 3}
        ) == fits
        assert com["title_block_page"] == 1
        assert com["reopened"]
        reports[name] = {
            "pages": com["pages"],
            "content_validation": content,
            "layout_adjustments": com["layout_adjustments"],
            "reopened": True,
            "bookmark_pages": com["bookmark_pages"],
            "title_block_page": com["title_block_page"],
            "expected_layout_overflow": not fits,
            "headings": len(actual),
        }
        print(name, reports[name], flush=True)
    (output / "word-acceptance.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
