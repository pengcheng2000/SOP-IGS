"""Boost-specific master binding and chapter orchestration."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from ...document_common.binding import _bind_fields, _expand_multiline, _replace_paragraph_text
from ...document_common.blocks import (
    _Builder,
    _num_props,
    _Prototypes,
)
from ..input.home import normalize
from ..input.model import BoostDocument, Paragraph, _item_from_dict
from ..settings import load_manifest
from .layout import fix_layout, set_body_indent
from .ooxml import NS, DocxGenerationError, DocxPackage, paragraph_text, q

BOOST_LAYOUT_VERSION = "boost-1"


def _rebuild_summary_table(package: DocxPackage, manifest: dict, titles: list[str]) -> None:
    locator = manifest["summary_table"]
    summary = next(
        (
            table
            for table in package.body.xpath("./w:tbl", namespaces=NS)
            if locator["header_contains"] in paragraph_text(table.find("w:tr", NS))
        ),
        None,
    )
    if summary is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "找不到调试项目汇总表")
    rows = summary.findall("w:tr", NS)
    preserved = int(locator["preserve_rows"])
    if len(rows) < preserved:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "调试项目汇总表结构异常")
    template_row = rows[preserved - 1]
    for row in rows[preserved:]:
        summary.remove(row)
    fixed = len(manifest["chapter_root"].get("fixed_sections", []))
    for index, title in enumerate(titles, start=fixed + 1):
        row = copy.deepcopy(template_row)
        cells = row.findall("w:tc", NS)
        if len(cells) < 2:
            raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "汇总表样板行列数异常")
        for cell, value in ((cells[0], f"5.{index}"), (cells[1], title)):
            paragraphs = cell.findall("w:p", NS)
            for extra in paragraphs[1:]:
                cell.remove(extra)
            _replace_paragraph_text(paragraphs[0], value)
        summary.append(row)


def generate_boost_docx(
    master: Path,
    destination: Path,
    fields: dict[str, str],
    document: BoostDocument,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    document = normalize(document)
    fields = dict(fields)
    fields.update({k: v["value"] for k, v in document.extra.get("fields", {}).items()})
    if not document.chapters:
        raise DocxGenerationError("INVALID_SOURCE_DOCUMENT", "测试项分类表没有可生成的章节")
    manifest = load_manifest(master.parent)
    anchors = manifest["anchors"]
    package = DocxPackage(master)
    prototypes = _Prototypes(package, anchors["prototypes_begin"], anchors["prototypes_end"])

    fixed_titles = manifest["chapter_root"].get("fixed_sections", [])
    heading_num_id = str(manifest["heading_numbering"]["num_id"])
    chapter_heading = next(
        (
            paragraph
            for paragraph in package.body.xpath("./w:p", namespaces=NS)
            if _num_props(paragraph) == (heading_num_id, "1")
            and paragraph_text(paragraph) in fixed_titles
        ),
        None,
    )
    if chapter_heading is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "找不到 5.1 固定章节标题")

    fields = {field["key"]: "" for field in manifest.get("fields", [])} | {
        key: value or "" for key, value in fields.items()
    }
    base = re.sub(r"升压一体机(?:测试需求)?$", "", fields.get("project_name", "")).rstrip()
    fields["document_title"] = fields.get("document_title") or base + "升压一体机测试需求"
    fields["scope_text"] = fields.get("scope_text") or f"本调试说明适用于{base}升压一体机的调试。"
    single_line = {key: " ".join(value.split("\n")).strip() for key, value in fields.items()}
    if document.extra.get("fields"):
        # Home title_subject already contains the complete title-block wording.
        for box in package.document.xpath("//w:txbxContent", namespaces=NS):
            paragraphs = box.findall("w:p", NS)
            for index, p in enumerate(paragraphs[:-1]):
                if (
                    paragraph_text(p) == "{{title_subject}}"
                    and paragraph_text(paragraphs[index + 1]) == "升压一体机测试需求"
                ):
                    box.remove(paragraphs[index + 1])
    multiline = {key for key, value in fields.items() if "\n" in value}
    for key in multiline:
        _expand_multiline(
            package,
            "{{" + key + "}}",
            [line.strip() for line in fields[key].split("\n") if line.strip()],
        )
    for p in package.body.findall("w:p", NS):
        text = paragraph_text(p)
        if text == "{{project_name}}升压一体机测试需求":
            _replace_paragraph_text(
                p,
                fields.get("document_title")
                or text.replace("{{project_name}}", fields.get("project_name", "")),
            )
        elif "{{project_name}}" in text:
            _replace_paragraph_text(
                p,
                fields.get("scope_text")
                or text.replace("{{project_name}}", fields.get("project_name", "")),
            )
    _bind_fields(package, single_line)
    _rebuild_summary_table(package, manifest, [chapter.title for chapter in document.chapters])

    builder = _Builder(package, manifest, prototypes, chapter_heading)
    if document.extra.get("fields"):
        body = list(package.body)
        start = next(i for i, p in enumerate(body) if paragraph_text(p) == "参考文献")
        end = next(i for i, p in enumerate(body) if paragraph_text(p) == "调试环境")
        for p in body[start + 1 : end]:
            package.body.remove(p)
        for line in document.extra.get("references", []):
            for p in builder.paragraph(Paragraph(line)):
                body[end].addprevious(p)
        _replace_paragraph_text(body[end], "测试环境")
        tables = [
            p
            for p in package.body.findall("w:tbl", NS)
            if "环境温度范围" in paragraph_text(p) or "FLUKE" in paragraph_text(p)
        ]
        for old, key in zip(tables, ("environment", "instruments"), strict=True):
            package.body.replace(old, builder.table(_item_from_dict(document.extra[key])))
    expected_headings = [(f"5.{index}", title) for index, title in enumerate(fixed_titles, start=1)]
    generated: list[etree._Element] = []
    total = len(document.chapters)
    for offset, chapter in enumerate(document.chapters):
        if progress_callback:
            progress_callback(offset + 1, total, chapter.title)
        elements, headings = builder.chapter(len(fixed_titles) + offset + 1, chapter)
        generated.extend(elements)
        expected_headings.extend(headings)

    anchor = next(
        (
            p
            for p in package.body.xpath("./w:p", namespaces=NS)
            if paragraph_text(p) == anchors["chapters"]
        ),
        None,
    )
    if anchor is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "母版缺少章节插入点")
    for element in generated:
        anchor.addprevious(element)
    if generated and generated[-1].tag == q("w", "tbl"):
        _replace_paragraph_text(anchor, "")
    else:
        package.body.remove(anchor)
    _expand_multiline(package, anchors["revision_history"], list(document.revision_history))

    leftovers = [
        value for value in package.document.xpath("//w:t/text()", namespaces=NS) if "{{" in value
    ]
    if leftovers:
        raise DocxGenerationError(
            "TEMPLATE_STRUCTURE_MISMATCH", f"母版仍有未替换的占位符：{leftovers[:5]}"
        )
    # Normalize every generated ordinary paragraph, including fixed chapter text.
    for p in package.body.findall("w:p", NS):
        props = p.find("w:pPr", NS)
        if (
            props is not None
            and props.find("w:numPr", NS) is None
            and props.find("w:outlineLvl", NS) is None
            and props.find("w:ind", NS) is not None
        ):
            set_body_indent(p, "body")
    # List explanations retain their hanging alignment.
    indent_texts = {
        i.text
        for c in document.chapters
        for i in c.items
        if isinstance(i, Paragraph) and i.kind == "indent"
    }
    for p in package.body.findall("w:p", NS):
        if paragraph_text(p) in indent_texts:
            set_body_indent(p, "indent")
    fix_layout(package)
    package.prune_orphan_media()
    package.save(destination)
    summary = document.summary()
    return {
        "expected_headings": [[number, text] for number, text in expected_headings],
        "chapter_count": summary["chapter_count"],
        "table_count": builder.table_count,
        "image_count": builder.image_count,
        "floating_drawings_expected": int(manifest.get("floating_drawings", 0)),
    }
