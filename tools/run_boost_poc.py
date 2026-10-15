"""Generate a boost document and finalize it with Microsoft Word to verify numbering.

Usage:
    python tools/run_boost_poc.py --out tests/output/boost-poc [--workbook <xlsx>]

Without --workbook a small synthetic document is used. Requires Word on Windows.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.boost.docx.builder import generate_boost_docx
from app.boost.docx.validator import validate_boost_docx
from app.boost.docx.word import finalize_boost_with_word
from app.boost.input.model import (
    BoostDocument,
    Chapter,
    Heading,
    Image,
    ImageRef,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
)

MASTER = ROOT / "templates" / "boost-integrated-unit" / "v1" / "master.docx"


def synthetic_document(directory: Path) -> BoostDocument:
    directory.mkdir(parents=True, exist_ok=True)
    picture = directory / "figure.png"
    PILImage.new("RGB", (1600, 700), (40, 110, 70)).save(picture)
    ref = ImageRef("figure", str(picture), "0" * 64, 1600, 700)
    table = Table((2, 1, 1), (
        (TableCell("测试部位", 0, row_span=2), TableCell("要求", 1, col_span=2)),
        (TableCell("绝缘电阻", 1), TableCell("耐压测试", 2)),
        (TableCell("短接三相对地之间", 0), TableCell("≥1MΩ", 1), TableCell("无击穿", 2)),
    ), header_rows=2)
    return BoostDocument(
        chapters=(
            Chapter("外观检查", "外观检查", (
                Heading(3, "集装箱尺寸、标签检查"), Paragraph("正文一"),
                Heading(3, "箱门、柜门检查"), ListBlock("decimal", (ListItem("条目一"), ListItem("条目二"))),
            )),
            Chapter("系统供电测试", "系统供电测试", (
                Heading(3, "供电测试"), ListBlock("decimal", (ListItem("重新编号一"), ListItem("重新编号二"))),
                Heading(3, "通讯测试"), Heading(4, "内部通讯测试"), ListBlock("letter", (ListItem("字母一"),)),
                Heading(4, "外部通讯测试"), table, Image(ref), Paragraph("注意事项", kind="note"),
            )),
        ),
        revision_history=("2026年10月14日，A0。",),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "output" / "boost-poc")
    parser.add_argument("--workbook", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.workbook:
        from app.boost.input import parse_workbook

        result = parse_workbook(args.workbook, args.out / "images")
        for issue in result.issues:
            print(f"[{issue.severity}] {issue.sheet}!{issue.cell} {issue.code}: {issue.message}")
        if result.document is None:
            raise SystemExit("workbook has errors")
        document = result.document
    else:
        document = synthetic_document(args.out / "images")
    output = args.out / "boost-poc.docx"
    fields = {"project_name": "示例站点", "document_number": "201090149MTR", "document_version": "A0",
              "title_subject": "CPS ESS-示例", "document_code": "2.0109.0149", "product_line": "CPS ESS",
              "archive_month": "2026-10", "drafter": "拟制人", "project_references": "示例项目电气图\n示例项目测试需求"}
    report = generate_boost_docx(MASTER, output, fields, document)
    validate_boost_docx(output, report["floating_drawings_expected"])
    com = finalize_boost_with_word(output)
    actual = [[h["number"].rstrip("."), h["text"]] for h in com["headings"] if h["number"].startswith("5.") and "." in h["number"].rstrip(".")]
    print(json.dumps({"pages": com["pages"], "expected": report["expected_headings"], "actual": actual}, ensure_ascii=False, indent=1))
    print("MATCH" if actual == report["expected_headings"] else "MISMATCH", output)


if __name__ == "__main__":
    main()
