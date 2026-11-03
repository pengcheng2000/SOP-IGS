"""DOCX builder for the boost-integrated-unit test-requirement document.

The master (templates/boost-integrated-unit/v1) carries the fixed chapters, a summary
table with the fixed 5.1 row, a `{{BOOST_CHAPTERS}}` anchor, a prototype region with one
sample of every generated block type, and `{{token}}` field placeholders (including the
title-block text boxes).
"""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from .model import (
    Heading,
    Image,
    ImageRef,
    ListBlock,
    Paragraph,
    Table,
    TableCell,
)
from .ooxml import (
    NS,
    DocxGenerationError,
    DocxPackage,
    _drawing,
    _table_separator_paragraph,
    paragraph_text,
    q,
)

BOOST_LAYOUT_VERSION = "boost-1"
TABLE_WIDTH = 9360  # dxa, matches the master's fixed tables
CELL_MARGIN = 216  # left + right cell margins in dxa
EMU_PER_PX = 9525  # 96 dpi
EMU_PER_DXA = 635
MAX_IMAGE_HEIGHT_EMU = 8_500_000
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _num_props(paragraph: etree._Element) -> tuple[str, str]:
    return (
        paragraph.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS),
        paragraph.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS),
    )


def _first_run_props(element: etree._Element) -> etree._Element | None:
    props = element.find(".//w:r/w:rPr", NS)
    return copy.deepcopy(props) if props is not None else None


def _text_run(
    value: str, run_props: etree._Element | None, *, bold: bool = False
) -> etree._Element:
    run = etree.Element(q("w", "r"))
    props = copy.deepcopy(run_props) if run_props is not None else None
    if bold:
        if props is None:
            props = etree.Element(q("w", "rPr"))
        if props.find("w:b", NS) is None:
            props.insert(0, etree.Element(q("w", "b")))
    if props is not None:
        run.append(props)
    text = etree.SubElement(run, q("w", "t"))
    if value != value.strip():
        text.set(XML_SPACE, "preserve")
    text.text = value
    return run


def _paragraph_like(prototype: etree._Element, value: str, *, bold: bool = False) -> etree._Element:
    """Copy a prototype paragraph's properties and first run style with new text."""
    paragraph = etree.Element(q("w", "p"))
    props = prototype.find("w:pPr", NS)
    if props is not None:
        paragraph.append(copy.deepcopy(props))
    if value:
        paragraph.append(_text_run(value, _first_run_props(prototype), bold=bold))
    return paragraph


def _set_num(
    paragraph: etree._Element, num_id: str, ilvl: int, *, drop_indent: bool = False
) -> None:
    props = paragraph.find("w:pPr", NS)
    if props is None:
        props = etree.Element(q("w", "pPr"))
        paragraph.insert(0, props)
    for existing in props.findall("w:numPr", NS):
        props.remove(existing)
    num_pr = etree.Element(q("w", "numPr"))
    etree.SubElement(num_pr, q("w", "ilvl")).set(q("w", "val"), str(ilvl))
    etree.SubElement(num_pr, q("w", "numId")).set(q("w", "val"), str(num_id))
    style = props.find("w:pStyle", NS)
    if style is not None:
        style.addnext(num_pr)
    else:
        props.insert(0, num_pr)
    if drop_indent:
        for indent in props.findall("w:ind", NS):
            props.remove(indent)


class _Prototypes:
    def __init__(self, package: DocxPackage, begin: str, end: str):
        body = list(package.body)
        texts = [
            paragraph_text(element) if element.tag == q("w", "p") else None for element in body
        ]
        try:
            start = texts.index(begin)
            stop = texts.index(end)
        except ValueError:
            raise DocxGenerationError(
                "TEMPLATE_STRUCTURE_MISMATCH", "母版缺少样式样板区域"
            ) from None
        found: dict[str, etree._Element] = {}
        for element in body[start + 1 : stop]:
            if element.tag == q("w", "tbl"):
                found["table"] = element
            else:
                found[paragraph_text(element).removeprefix("{{PROTO:").removesuffix("}}")] = element
        for element in body[start : stop + 1]:
            package.body.remove(element)
        missing = {"h3", "h4", "body", "indent", "list", "note", "table"} - set(found)
        if missing:
            raise DocxGenerationError(
                "TEMPLATE_STRUCTURE_MISMATCH", f"母版缺少样式样板：{sorted(missing)}"
            )
        self.h3 = found["h3"]
        self.h4 = found["h4"]
        self.body = found["body"]
        self.indent = found["indent"]
        self.list = found["list"]
        self.note = found["note"]
        table = found["table"]
        rows = table.findall("w:tr", NS)
        if len(rows) < 2:
            raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "表格样板行数不足")
        self.table_props = table.find("w:tblPr", NS)
        self.header_row, self.body_row = rows[0], rows[1]


class _Builder:
    def __init__(
        self,
        package: DocxPackage,
        manifest: dict,
        prototypes: _Prototypes,
        chapter_heading: etree._Element,
    ):
        self.package = package
        self.prototypes = prototypes
        self.chapter_heading = chapter_heading
        numbering = manifest["heading_numbering"]
        self.heading_num_id = str(numbering["num_id"])
        self.ilvl_by_level = {
            int(level): int(ilvl) for level, ilvl in numbering["ilvl_by_level"].items()
        }
        self.list_abstract_nums = manifest["list_abstract_nums"]
        self.table_header_bold = manifest.get("table_header_bold", True)
        self.image_count = 0
        self.table_count = 0
        self.last_list_num: dict[str, str] = {}

    def heading(self, level: int, text: str) -> etree._Element:
        if level == 2:
            paragraph = _paragraph_like(self.chapter_heading, text)
        else:
            prototype = self.prototypes.h3 if level == 3 else self.prototypes.h4
            paragraph = _paragraph_like(prototype, text)
        _set_num(paragraph, self.heading_num_id, self.ilvl_by_level[level])
        return paragraph

    def paragraph(self, item: Paragraph) -> list[etree._Element]:
        prototype = {"note": self.prototypes.note, "indent": self.prototypes.indent}.get(
            item.kind, self.prototypes.body
        )
        lines = item.text.split("\n")
        if item.kind == "note" and not lines[0].startswith("★"):
            lines[0] = "★" + lines[0]
        return [_paragraph_like(prototype, line) for line in lines]

    def list_block(self, item: ListBlock) -> list[etree._Element]:
        abstract = self.list_abstract_nums.get(item.style)
        if abstract is None:
            raise DocxGenerationError("INVALID_SOURCE_DOCUMENT", f"不支持的列表样式：{item.style}")
        num_id = self.last_list_num.get(item.style) if item.continues else None
        if num_id is None:
            num_id = self.package.numbering_new_num(str(abstract), restart=True)
            self.last_list_num[item.style] = num_id
        elements = []
        for entry in item.items:
            paragraph = _paragraph_like(self.prototypes.list, entry.text)
            _set_num(paragraph, num_id, min(max(entry.level, 0), 1), drop_indent=True)
            elements.append(paragraph)
        return elements

    def image_paragraph(
        self, ref: ImageRef, max_width_emu: int, prototype: etree._Element | None = None
    ) -> etree._Element:
        paragraph = etree.Element(q("w", "p"))
        source_props = prototype.find("w:pPr", NS) if prototype is not None else None
        props = (
            copy.deepcopy(source_props)
            if source_props is not None
            else etree.Element(q("w", "pPr"))
        )
        for node in (
            props.findall("w:ind", NS) + props.findall("w:jc", NS) + props.findall("w:numPr", NS)
        ):
            props.remove(node)
        justification = etree.Element(q("w", "jc"))
        justification.set(q("w", "val"), "center")
        run_props = props.find("w:rPr", NS)
        if run_props is not None:
            run_props.addprevious(justification)
        else:
            props.append(justification)
        paragraph.append(props)
        run = etree.SubElement(paragraph, q("w", "r"))
        width = max(1, ref.px_w) * EMU_PER_PX
        height = max(1, ref.px_h) * EMU_PER_PX
        scale = min(1.0, max_width_emu / width, MAX_IMAGE_HEIGHT_EMU / height)
        path = Path(ref.path)
        if not path.is_file():
            raise DocxGenerationError("SOURCE_IMAGE_MISSING", f"找不到图片文件：{ref.id}")
        rid, media_name = self.package.add_image(path)
        run.append(
            _drawing(
                self.package,
                rid,
                media_name,
                max(1, int(width * scale)),
                max(1, int(height * scale)),
            )
        )
        self.image_count += 1
        return paragraph

    def table(self, item: Table) -> etree._Element:
        column_count = max(
            (cell.col + cell.col_span for row in item.rows for cell in row), default=0
        )
        if column_count == 0:
            raise DocxGenerationError("INVALID_SOURCE_DOCUMENT", f"空表格：{item.src}")
        weights = list(item.col_widths[:column_count]) + [1.0] * max(
            0, column_count - len(item.col_widths)
        )
        weights = [weight if weight > 0 else 1.0 for weight in weights]
        total = sum(weights)
        widths = [int(TABLE_WIDTH * weight / total) for weight in weights]
        widths[-1] += TABLE_WIDTH - sum(widths)

        table = etree.Element(q("w", "tbl"))
        props = copy.deepcopy(self.prototypes.table_props)
        for node in props.findall("w:tblW", NS) + props.findall("w:tblLook", NS):
            props.remove(node)
        table_width = etree.Element(q("w", "tblW"))
        table_width.set(q("w", "w"), str(TABLE_WIDTH))
        table_width.set(q("w", "type"), "dxa")
        style = props.find("w:tblStyle", NS)
        if style is not None:
            style.addnext(table_width)
        else:
            props.insert(0, table_width)
        table.append(props)
        grid = etree.SubElement(table, q("w", "tblGrid"))
        for width in widths:
            etree.SubElement(grid, q("w", "gridCol")).set(q("w", "w"), str(width))

        # Cells covered by a vertical merge from an earlier row: row index -> {col: span}
        continuations: dict[int, dict[int, int]] = {}
        for row_index, row in enumerate(item.rows):
            header = row_index < item.header_rows
            row_proto = self.prototypes.header_row if header else self.prototypes.body_row
            row_element = etree.SubElement(table, q("w", "tr"))
            for node in row_proto:
                if node.tag in {q("w", "tblPrEx"), q("w", "trPr")}:
                    row_element.append(copy.deepcopy(node))
            if header:
                row_props = row_element.find("w:trPr", NS)
                if row_props is None:
                    row_props = etree.Element(q("w", "trPr"))
                    insert_at = 1 if row_element.find("w:tblPrEx", NS) is not None else 0
                    row_element.insert(insert_at, row_props)
                if row_props.find("w:tblHeader", NS) is None:
                    marker = etree.Element(q("w", "tblHeader"))
                    following = next(
                        (
                            node
                            for name in ("tblCellSpacing", "jc", "hidden")
                            for node in row_props.findall(f"w:{name}", NS)
                        ),
                        None,
                    )
                    if following is not None:
                        following.addprevious(marker)
                    else:
                        row_props.append(marker)
            cell_proto = row_proto.find("w:tc", NS)
            starts = {cell.col: cell for cell in row}
            covered = continuations.get(row_index, {})
            column = 0
            while column < column_count:
                if column in starts:
                    cell = starts[column]
                    row_element.append(
                        self._cell(
                            cell_proto,
                            cell,
                            widths,
                            header,
                            "restart" if cell.row_span > 1 else None,
                        )
                    )
                    for offset in range(1, cell.row_span):
                        continuations.setdefault(row_index + offset, {})[column] = cell.col_span
                    column += cell.col_span
                elif column in covered:
                    span = covered[column]
                    row_element.append(
                        self._cell(
                            cell_proto, TableCell("", column, span), widths, header, "continue"
                        )
                    )
                    column += span
                else:
                    row_element.append(
                        self._cell(cell_proto, TableCell("", column), widths, header, None)
                    )
                    column += 1
        self.table_count += 1
        return table

    def _cell(
        self,
        prototype: etree._Element,
        cell: TableCell,
        widths: list[int],
        header: bool,
        merge: str | None,
    ) -> etree._Element:
        element = etree.Element(q("w", "tc"))
        source_props = prototype.find("w:tcPr", NS)
        props = (
            copy.deepcopy(source_props)
            if source_props is not None
            else etree.Element(q("w", "tcPr"))
        )
        for name in ("tcW", "gridSpan", "vMerge", "hMerge"):
            for node in props.findall(f"w:{name}", NS):
                props.remove(node)
        span = max(1, cell.col_span)
        width = sum(widths[cell.col : cell.col + span])
        cell_width = etree.Element(q("w", "tcW"))
        cell_width.set(q("w", "w"), str(width))
        cell_width.set(q("w", "type"), "dxa")
        additions = [cell_width]
        if span > 1:
            grid_span = etree.Element(q("w", "gridSpan"))
            grid_span.set(q("w", "val"), str(span))
            additions.append(grid_span)
        if merge:
            vertical = etree.Element(q("w", "vMerge"))
            if merge == "restart":
                vertical.set(q("w", "val"), "restart")
            additions.append(vertical)
        for node in reversed(additions):
            props.insert(0, node)
        element.append(props)
        paragraph_proto = prototype.find("w:p", NS)
        lines = cell.text.split("\n") if merge != "continue" else [""]
        for line in lines:
            element.append(_paragraph_like(paragraph_proto, line, bold=header and bool(line) and self.table_header_bold))
        max_width = max(EMU_PER_DXA, (width - CELL_MARGIN) * EMU_PER_DXA)
        for image in cell.images:
            element.append(self.image_paragraph(image, max_width, paragraph_proto))
        return element

    def chapter(self, number: int, chapter) -> tuple[list[etree._Element], list[tuple[str, str]]]:
        elements = [self.heading(2, chapter.title)]
        headings = [(f"5.{number}", chapter.title)]
        level3 = level4 = 0
        for item in chapter.items:
            if isinstance(item, Heading):
                if item.level == 3:
                    level3 += 1
                    level4 = 0
                    headings.append((f"5.{number}.{level3}", item.text))
                elif item.level == 4:
                    if level3 == 0:
                        raise DocxGenerationError(
                            "INVALID_SOURCE_DOCUMENT", f"四级标题缺少上级标题：{item.src}"
                        )
                    level4 += 1
                    headings.append((f"5.{number}.{level3}.{level4}", item.text))
                else:
                    raise DocxGenerationError(
                        "INVALID_SOURCE_DOCUMENT", f"不支持的标题级别：{item.src}"
                    )
                elements.append(self.heading(item.level, item.text))
            elif isinstance(item, Paragraph):
                elements.extend(self.paragraph(item))
            elif isinstance(item, ListBlock):
                elements.extend(self.list_block(item))
            elif isinstance(item, Table):
                if elements and elements[-1].tag == q("w", "tbl"):
                    elements.append(_table_separator_paragraph())
                elements.append(self.table(item))
            elif isinstance(item, Image):
                elements.append(
                    self.image_paragraph(item.ref, TABLE_WIDTH * EMU_PER_DXA, self.prototypes.body)
                )
        return elements, headings
