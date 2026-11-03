"""Cabinet page orchestration; body blocks use the shared deterministic renderer."""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from ...document_common.binding import _bind_fields
from ...document_common.blocks import (
    EMU_PER_DXA,
    TABLE_WIDTH,
    _Builder,
    _paragraph_like,
    _Prototypes,
    _set_num,
)
from ...document_common.model import (
    DocumentModel,
    Heading,
    Image,
    ListBlock,
    Paragraph,
    Table,
    TableCell,
    _item_from_dict,
)
from ...document_common.ooxml import (
    NS,
    DocxGenerationError,
    DocxPackage,
    _table_separator_paragraph,
    paragraph_text,
    q,
)
from ..settings import load_manifest
from .content import validate_body_content


class CabinetBlockBuilder(_Builder):
    def table(self, item: Table) -> etree._Element:
        table = super().table(item)
        for row in table.findall("w:tr", NS):
            props = row.find("w:trPr", NS)
            if props is None:
                props = etree.Element(q("w", "trPr"))
                row.insert(0, props)
            if props.find("w:cantSplit", NS) is None:
                props.insert(0, etree.Element(q("w", "cantSplit")))
        return table


def generate_cabinet_plan_docx(
    master: Path,
    destination: Path,
    fields: dict[str, str],
    document: DocumentModel,
    progress_callback=None,
    *,
    generation_date: str,
) -> dict:
    if not document.chapters:
        raise DocxGenerationError("INVALID_SOURCE_DOCUMENT", "至少保留一个测试章节")
    package = DocxPackage(master)
    manifest = load_manifest(master.parent)

    def find(text):
        found = next(
            (p for p in package.body.findall("w:p", NS) if paragraph_text(p) == text), None
        )
        if found is None:
            raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", f"母版缺少{text}")
        return found

    h1 = copy.deepcopy(find("{{PROTO:h1}}"))
    h2 = copy.deepcopy(find("{{PROTO:h2}}"))
    prototypes = _Prototypes(package, "{{PROTOTYPES_BEGIN}}", "{{PROTOTYPES_END}}")
    builder = CabinetBlockBuilder(package, manifest, prototypes, h2)

    def root_heading(text):
        p = _paragraph_like(h1, text)
        _set_num(p, builder.heading_num_id, 0)
        return p

    def compact(elements):
        """Keep tables compact while retaining the case's home heading/text styles."""
        for element in elements:
            in_table = element.tag == q("w", "tbl")
            for p in element.iter(q("w", "p")):
                props = p.find("w:pPr", NS)
                is_heading = props is not None and props.find("w:outlineLvl", NS) is not None
                if props is not None:
                    if is_heading:
                        # The four fixed home headings do not need pagination
                        # constraints, which otherwise show margin squares when
                        # Word's formatting marks are enabled.
                        for tag in ("keepNext", "keepLines"):
                            for node in props.findall(f"w:{tag}", NS):
                                props.remove(node)
                    for s in props.findall("w:spacing", NS):
                        s.set(q("w", "line"), "240" if in_table else "360")
                        s.set(q("w", "after"), "0")
                        s.set(q("w", "before"), "0")
                    for ind in props.findall("w:ind", NS):
                        props.remove(ind)
                for rp in p.findall("w:r/w:rPr", NS):
                    for s in rp.findall("w:sz", NS) + rp.findall("w:szCs", NS):
                        s.set(q("w", "val"), "24" if is_heading else "18" if in_table else "21")
        return elements

    home = [root_heading("适用范围")]
    scope_paragraphs = builder.paragraph(Paragraph(fields.get("scope_text", "")))
    home.extend(scope_paragraphs)
    home.append(root_heading("参考文献"))
    reference_paragraphs = []
    for line in document.extra.get("references", []):
        reference_paragraphs.extend(builder.paragraph(Paragraph(line)))
    home.extend(reference_paragraphs)
    home.append(root_heading("测试环境"))
    if not document.extra.get("environment") or not document.extra.get("instruments"):
        raise DocxGenerationError("INVALID_SOURCE_DOCUMENT", "首页缺少测试环境或仪器表")
    home.append(builder.table(_item_from_dict(document.extra["environment"])))
    home.append(root_heading("调试工装仪器明细"))
    home.append(builder.table(_item_from_dict(document.extra["instruments"])))
    anchor = find("{{HOME_CONTENT}}")
    compact(home)
    for paragraph in scope_paragraphs + reference_paragraphs:
        props = paragraph.find("w:pPr", NS)
        indent = etree.SubElement(props, q("w", "ind"))
        indent.set(q("w", "left"), "0")
        indent.set(q("w", "firstLine"), "420")
        run_props = props.find("w:rPr", NS)
        if run_props is not None:
            run_props.addprevious(indent)
    for element in home:
        anchor.addprevious(element)
    anchor.addprevious(_table_separator_paragraph())
    package.body.remove(anchor)

    def page_start(paragraph, name, bookmark_id):
        pr = paragraph.find("w:pPr", NS)
        if pr is None:
            pr = etree.Element(q("w", "pPr"))
            paragraph.insert(0, pr)
        start = etree.Element(q("w", "bookmarkStart"))
        start.set(q("w", "id"), str(bookmark_id))
        start.set(q("w", "name"), name)
        end = etree.Element(q("w", "bookmarkEnd"))
        end.set(q("w", "id"), str(bookmark_id))
        paragraph.insert(1, start)
        paragraph.append(end)

    def page_break():
        paragraph = _table_separator_paragraph()
        run = etree.SubElement(paragraph, q("w", "r"))
        etree.SubElement(run, q("w", "br")).set(q("w", "type"), "page")
        return paragraph

    summary_title = root_heading("测试项目")
    page_start(summary_title, "CabinetSummary", 9001)
    rows = [(TableCell("序号", 0), TableCell("测试项目", 1))]
    rows.extend(
        (TableCell(f"5.{i}", 0), TableCell(ch.title, 1))
        for i, ch in enumerate(document.chapters, 1)
    )
    rows.append((TableCell("以下空白", 0, 2),))
    summary = builder.table(Table((1, 5), tuple(rows), 1, "目录"))
    anchor = find("{{SUMMARY_PAGE}}")
    anchor.addprevious(page_break())
    anchor.addprevious(summary_title)
    anchor.addprevious(summary)
    package.body.remove(anchor)
    body = []
    expected = []
    for index, chapter in enumerate(document.chapters, 1):
        if progress_callback:
            progress_callback(index, len(document.chapters), chapter.title)
        elements, headings = builder.chapter(index, chapter)
        if index == 1:
            page_start(elements[0], "CabinetBody", 9002)
            body.append(page_break())
        body.extend(elements)
        expected.extend(headings)
    body.append(root_heading("出厂配置确认"))
    for data in document.extra.get("closing", []):
        item = _item_from_dict(data)
        if isinstance(item, Paragraph):
            body.extend(builder.paragraph(item))
        elif isinstance(item, ListBlock):
            body.extend(builder.list_block(item))
        elif isinstance(item, Table):
            body.append(builder.table(item))
        elif isinstance(item, Image):
            body.append(
                builder.image_paragraph(item.ref, TABLE_WIDTH * EMU_PER_DXA, prototypes.body)
            )
        elif isinstance(item, Heading):
            body.append(builder.heading(item.level, item.text))
    body.append(root_heading("版本修改记录"))
    year, month, day = map(int, generation_date.split("-"))
    body.extend(
        builder.paragraph(
            Paragraph(f"{year}年{month}月{day}日{fields.get('document_version', '')}版本。")
        )
    )
    anchor = find("{{BODY_CONTENT}}")
    previous = None
    for element in body:
        if previous is not None and previous.tag == element.tag == q("w", "tbl"):
            anchor.addprevious(_table_separator_paragraph())
        anchor.addprevious(element)
        previous = element
    package.body.remove(anchor)
    _bind_fields(
        package, {field["key"]: fields.get(field["key"], "") for field in manifest["fields"]}
    )
    for name in ["word/document.xml"] + [
        n
        for n in package.entries
        if n.startswith(("word/header", "word/footer")) and n.endswith(".xml")
    ]:
        root = package.document if name == "word/document.xml" else package.part(name)
        if any("{{" in t for t in root.xpath("//w:t/text()", namespaces=NS)):
            raise DocxGenerationError("UNRESOLVED_FIELD", "母版含未替换字段")
    content_validation = validate_body_content(package.document, document, fields, generation_date)
    package.prune_orphan_media()
    package.save(destination)
    return {
        "expected_headings": expected,
        "chapter_count": len(document.chapters),
        "table_count": builder.table_count,
        "image_count": builder.image_count,
        "floating_drawings_expected": 0,
        "content_validation": content_validation,
    }
