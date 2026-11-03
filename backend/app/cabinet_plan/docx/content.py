"""Check every body paragraph against the immutable generation input.

Counts are compared rather than deduplicated: repeated instructions in different
tests/phases must survive, but an extra generated copy must never pass unnoticed.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from ...document_common.model import (
    DocumentModel,
    Heading,
    ListBlock,
    Paragraph,
    Table,
    _item_from_dict,
)
from ...document_common.ooxml import NS, DocxGenerationError


def _text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _item_paragraphs(item) -> list[str]:
    if isinstance(item, Heading):
        return [item.text]
    if isinstance(item, Paragraph):
        lines = item.text.split("\n")
        if item.kind == "note" and not lines[0].startswith("★"):
            lines[0] = "★" + lines[0]
        return lines
    if isinstance(item, ListBlock):
        return [entry.text for entry in item.items]
    if isinstance(item, Table):
        return [line for row in item.rows for cell in row for line in cell.text.split("\n")]
    return []


def expected_body(document: DocumentModel, fields: dict[str, str], generation_date: str) -> Counter:
    paragraphs = [
        fields.get("document_title", ""),
        "适用范围",
        "参考文献",
        "测试环境",
        "调试工装仪器明细",
    ]
    paragraphs.extend(fields.get("scope_text", "").split("\n"))
    paragraphs.extend(
        line for ref in document.extra.get("references", []) for line in ref.split("\n")
    )
    for key in ("environment", "instruments"):
        if key in document.extra:
            paragraphs.extend(_item_paragraphs(_item_from_dict(document.extra[key])))
    paragraphs.extend(["测试项目", "序号", "测试项目", "以下空白"])
    for index, chapter in enumerate(document.chapters, 1):
        paragraphs.extend([f"5.{index}", chapter.title, chapter.title])  # summary and body
        for item in chapter.items:
            paragraphs.extend(_item_paragraphs(item))
    paragraphs.append("出厂配置确认")
    for item in document.extra.get("closing", []):
        paragraphs.extend(_item_paragraphs(_item_from_dict(item)))
    year, month, day = map(int, generation_date.split("-"))
    paragraphs.extend(
        ["版本修改记录", f"{year}年{month}月{day}日{fields.get('document_version', '')}版本。"]
    )
    return Counter(_text(p) for p in paragraphs if _text(p))


def validate_body_content(
    root: etree._Element,
    document: DocumentModel,
    fields: dict[str, str],
    generation_date: str,
    *,
    raise_on_error=True,
) -> dict:
    body = root.find("w:body", NS)
    actual = Counter()
    for paragraph in body.xpath(".//w:p[not(ancestor::w:txbxContent)]", namespaces=NS):
        value = _text("".join(paragraph.xpath(".//w:t/text()", namespaces=NS)))
        if value:
            actual[value] += 1
    expected = expected_body(document, fields, generation_date)
    extra, missing = actual - expected, expected - actual
    report = {
        "valid": not extra and not missing,
        "expected_paragraphs": sum(expected.values()),
        "actual_paragraphs": sum(actual.values()),
        "extra_paragraphs": sum(extra.values()),
        "missing_paragraphs": sum(missing.values()),
    }
    if not report["valid"]:
        report["extra_samples"] = [{"text": t[:160], "count": n} for t, n in extra.most_common(8)]
        report["missing_samples"] = [
            {"text": t[:160], "count": n} for t, n in missing.most_common(8)
        ]
        if raise_on_error:
            raise DocxGenerationError(
                "CONTENT_MISMATCH",
                f"正文一致性校验失败：额外 {report['extra_paragraphs']} 段，缺失 {report['missing_paragraphs']} 段",
            )
    return report


def validate_docx_body(
    path: Path,
    document: DocumentModel,
    fields: dict[str, str],
    generation_date: str,
    *,
    raise_on_error=True,
) -> dict:
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    return validate_body_content(
        root, document, fields, generation_date, raise_on_error=raise_on_error
    )
