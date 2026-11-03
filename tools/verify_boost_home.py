"""Build and audit the home-driven boost sample with native Microsoft Word."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.boost.docx.builder import generate_boost_docx
from app.boost.input import parse_workbook
from app.boost.worker import heading_mismatches
from app.document_common.word import finalize_document
from openpyxl import load_workbook


def main():
    import pythoncom
    import win32com.client

    directory = ROOT / "tests/output/boost-home"
    directory.mkdir(parents=True, exist_ok=True)
    template = ROOT / "templates/boost-integrated-unit/v1"
    book = load_workbook(template / "input-template.xlsx")
    book["首页"]["C52"] = "201090149MTR"
    book.save(directory / "sample.xlsx")
    result = parse_workbook(directory / "sample.xlsx", directory / "images")
    assert result.valid, result.issues
    output = directory / "boost-home.docx"
    report = generate_boost_docx(template / "master.docx", output, {}, result.document)
    com = finalize_document(output, pdf_path=directory / "boost-home.pdf")
    assert not heading_mismatches(report["expected_headings"], com)
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    doc = None
    try:
        doc = word.Documents.Open(str(output), False, True, False)
        lists = []
        two_digit = []
        for p in doc.ListParagraphs:
            label = str(p.Range.ListFormat.ListString)
            text = p.Range.Text.strip()
            if label == "10)":
                assert abs(p.Format.LeftIndent - 47.25) < 0.1
                assert abs(p.Format.FirstLineIndent + 15.75) < 0.1
                two_digit.append(
                    {"number": label, "text": text[:60], "page": p.Range.Information(3)}
                )
            if (
                text
                in [
                    "直流侧",
                    "交流侧",
                    "主变电压采样线（800V侧）",
                    "辅变电压采样线（380V侧）",
                ]
                or "电流互感器二次线圈接线检查" in text
            ):
                lists.append(
                    {
                        "text": text,
                        "number": label,
                        "left": p.Format.LeftIndent,
                        "first": p.Format.FirstLineIndent,
                    }
                )
        labels = {p["text"]: p["number"] for p in lists}
        assert labels["直流侧"] == "1)" and labels["交流侧"] == "2)"
        assert labels["主变电压采样线（800V侧）"] == "1)"
        assert labels["辅变电压采样线（380V侧）"] == "2)"
        find = doc.Content.Duplicate
        assert find.Find.Execute("版本修改记录")
        assert find.Paragraphs.Item(1).OutlineLevel == 1
        doc.Close(0)
        doc = None
        from dataclasses import replace

        from app.boost.input.model import Chapter, ListBlock, ListItem

        probe = replace(
            result.document,
            chapters=(
                Chapter(
                    "编号间距验证",
                    "验证",
                    (
                        ListBlock(
                            "decimal",
                            tuple(
                                ListItem(f"编号间距验证第{i}项") for i in range(1, 13)
                            ),
                        ),
                    ),
                ),
            ),
        )
        probe_path = directory / "two-digit.docx"
        generate_boost_docx(template / "master.docx", probe_path, {}, probe)
        doc = word.Documents.Open(str(probe_path), False, True, False)
        doc.Repaginate()
        for p in doc.ListParagraphs:
            if str(p.Range.ListFormat.ListString) == "10)":
                assert abs(p.Format.LeftIndent - 47.25) < 0.1
                assert abs(p.Format.FirstLineIndent + 15.75) < 0.1
                two_digit.append(
                    {
                        "number": "10)",
                        "text": p.Range.Text.strip(),
                        "page": p.Range.Information(3),
                    }
                )
        doc.ExportAsFixedFormat(str(directory / "two-digit.pdf"), 17)
        assert two_digit
        data = {
            "two_digit": two_digit,
            "word": com,
            "lists": lists,
            "summary": result.document.summary(),
        }
        (directory / "audit.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {"pages": com["pages"], "reopened": com["reopened"], "lists": lists},
                ensure_ascii=False,
            )
        )
    finally:
        if doc is not None:
            doc.Close(0)
        word.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
