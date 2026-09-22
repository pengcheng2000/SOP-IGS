from __future__ import annotations

import copy
import hashlib
import os
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from ...domain.catalog import BY_TITLE, CATALOG, display_numbers, selected_with_ancestors
from ..image_pipeline import image_dimensions
from ..layout import LayoutPhoto, plan_layout

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}


def q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def paragraph_text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS)).strip()


class DocxGenerationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DocPhoto:
    id: str
    path: Path
    caption: str = ""


@dataclass(frozen=True, slots=True)
class DocPhotoGroup:
    id: str
    key: str
    title: str
    photos: tuple[DocPhoto, ...]
    layout_profile: str = "adaptive_grid"
    preferred_columns: int | None = None
    source: str = "template"
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class GenerationInput:
    project: dict
    selected_test_item_ids: tuple[str, ...]
    photos_by_test_item: dict[str, tuple[DocPhoto, ...]] = field(default_factory=dict)
    photo_groups_by_test_item: dict[str, tuple[DocPhotoGroup, ...]] = field(default_factory=dict)
    sample_photo_groups: tuple[DocPhotoGroup, ...] = ()


class DocxPackage:
    def __init__(self, source: Path):
        with zipfile.ZipFile(source) as archive:
            self.entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        self.document = etree.fromstring(self.entries["word/document.xml"])
        self.photo_title_prototype = next(
            (copy.deepcopy(p) for p in self.document.xpath('/w:document/w:body/w:p', namespaces=NS)
             if paragraph_text(p) == '测试照片'), None
        )
        self.relationships = etree.fromstring(self.entries["word/_rels/document.xml.rels"])
        self.content_types = etree.fromstring(self.entries["[Content_Types].xml"])
        self._rid = max(
            [int(match.group(1)) for rel in self.relationships for match in [re.fullmatch(r"rId(\d+)", rel.get("Id", ""))] if match]
            or [0]
        )
        self._drawing_id = max(
            [int(value) for value in self.document.xpath("//wp:docPr/@id", namespaces=NS) if value.isdigit()]
            or [0]
        )

    @property
    def body(self) -> etree._Element:
        return self.document.find("w:body", NS)

    def add_image(self, path: Path) -> tuple[str, str]:
        extension = path.suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png"}:
            raise DocxGenerationError("IMAGE_PROCESSING_FAILED", f"DOCX 不支持处理后的格式：{extension}")
        self._rid += 1
        rid = f"rId{self._rid}"
        media_name = f"generated-{self._rid}-{hashlib.sha1(path.read_bytes()).hexdigest()[:12]}{extension}"
        target = f"media/{media_name}"
        rel = etree.SubElement(self.relationships, q("pr", "Relationship"))
        rel.set("Id", rid)
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image")
        rel.set("Target", target)
        self.entries[f"word/{target}"] = path.read_bytes()
        self._ensure_content_type(extension)
        return rid, media_name

    def next_drawing_id(self) -> int:
        self._drawing_id += 1
        return self._drawing_id

    def _ensure_content_type(self, extension: str) -> None:
        normalized = extension.removeprefix(".")
        values = self.content_types.xpath("./ct:Default/@Extension", namespaces=NS)
        if normalized in values or (normalized == "jpg" and "jpeg" in values):
            return
        node = etree.SubElement(self.content_types, q("ct", "Default"))
        node.set("Extension", normalized)
        node.set("ContentType", "image/png" if normalized == "png" else "image/jpeg")

    def prune_orphan_media(self) -> None:
        used = set(self.document.xpath("//a:blip/@r:embed", namespaces=NS))
        for rel in list(self.relationships):
            if not rel.get("Type", "").endswith("/image") or rel.get("Id") in used:
                continue
            target = rel.get("Target")
            self.relationships.remove(rel)
            if target:
                self.entries.pop(f"word/{target}", None)

    def save(self, destination: Path) -> None:
        self.entries["word/document.xml"] = etree.tostring(
            self.document, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        self.entries["word/_rels/document.xml.rels"] = etree.tostring(
            self.relationships, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        self.entries["[Content_Types].xml"] = etree.tostring(
            self.content_types, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.entries.items():
                archive.writestr(name, data)
        os.replace(temporary, destination)


def _set_paragraph_text(paragraph: etree._Element, value: str) -> None:
    ppr = paragraph.find("w:pPr", NS)
    for child in list(paragraph):
        if child is not ppr:
            paragraph.remove(child)
    run = etree.SubElement(paragraph, q("w", "r"))
    text = etree.SubElement(run, q("w", "t"))
    if value.startswith(" ") or value.endswith(" "):
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = value


def _set_cell_text(cell: etree._Element, value: str) -> None:
    paragraphs = cell.xpath("./w:p", namespaces=NS)
    if paragraphs:
        _set_paragraph_text(paragraphs[0], value)
        for extra in paragraphs[1:]:
            cell.remove(extra)
    else:
        paragraph = etree.SubElement(cell, q("w", "p"))
        _set_paragraph_text(paragraph, value)


def _direct_tables(package: DocxPackage) -> list[etree._Element]:
    return package.body.xpath("./w:tbl", namespaces=NS)


def _apply_project_bindings(package: DocxPackage, project: dict) -> None:
    tables = _direct_tables(package)
    if len(tables) < 8:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "母版表格数量不足")

    cover_rows = tables[0].xpath("./w:tr", namespaces=NS)
    if len(cover_rows) >= 3:
        values = cover_rows[1].xpath("./w:tc", namespaces=NS)
        if len(values) >= 4:
            _set_cell_text(values[1], project.get("document_number", ""))
            _set_cell_text(values[3], project.get("document_version", "V01"))
        title_cells = cover_rows[2].xpath("./w:tc", namespaces=NS)
        if len(title_cells) >= 2:
            _set_cell_text(title_cells[1], project.get("document_title") or project.get("name", ""))

    approval_rows = tables[1].xpath("./w:tr", namespaces=NS)
    fields = ["", "product_phase", "test_period", "test_location", "testers"]
    for row, key in zip(approval_rows[:5], fields, strict=False):
        cells = row.xpath("./w:tc", namespaces=NS)
        if len(cells) >= 2:
            _set_cell_text(cells[1], project.get(key, "") if key else "")
    for row in approval_rows[5:]:
        cells = row.xpath("./w:tc", namespaces=NS)
        if len(cells) >= 4:
            _set_cell_text(cells[1], "")
            _set_cell_text(cells[3], "")

    sample_rows = tables[7].xpath("./w:tr", namespaces=NS)
    if len(sample_rows) >= 2:
        cells = sample_rows[0].xpath("./w:tc", namespaces=NS)
        if len(cells) >= 2:
            _set_cell_text(cells[1], project.get("product_model", ""))
        cells = sample_rows[1].xpath("./w:tc", namespaces=NS)
        if len(cells) >= 2:
            _set_cell_text(cells[1], project.get("product_serial_no", ""))


def _heading_records(package: DocxPackage) -> list[dict]:
    records = []
    for index, element in enumerate(list(package.body)):
        if element.tag != q("w", "p"):
            continue
        title = paragraph_text(element)
        item = BY_TITLE.get(title)
        if not item:
            continue
        num_id = element.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS)
        level = element.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS)
        if num_id != "2" or level == "":
            continue
        records.append({"index": index, "element": element, "item": item, "level": int(level)})
    return records


def _remove_unselected_sections(package: DocxPackage, selected_leaf_ids: tuple[str, ...]) -> None:
    kept = selected_with_ancestors(selected_leaf_ids)
    removal_roots = [
        item for item in CATALOG if item.id not in kept and (item.parent_id is None or item.parent_id in kept)
    ]
    for removal in sorted(removal_roots, key=lambda item: item.order, reverse=True):
        records = _heading_records(package)
        current = next((record for record in records if record["item"].id == removal.id), None)
        if current is None:
            raise DocxGenerationError(
                "TEMPLATE_STRUCTURE_MISMATCH", f"找不到测试章节：{removal.title}"
            )
        end = len(package.body) - 1
        for record in records:
            if record["index"] > current["index"] and record["level"] <= current["level"]:
                end = record["index"]
                break
        blocks = list(package.body)
        for element in blocks[current["index"] : end]:
            package.body.remove(element)


def _rebuild_summary_table(package: DocxPackage, selected_leaf_ids: tuple[str, ...]) -> None:
    tables = _direct_tables(package)
    summary = next(
        (
            table
            for table in tables
            if "测试项目" in [paragraph_text(cell) for cell in table.xpath("./w:tr[1]/w:tc", namespaces=NS)]
            and len(table.xpath("./w:tr", namespaces=NS)) >= 30
        ),
        None,
    )
    if summary is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "找不到测试项目汇总表")
    rows = summary.xpath("./w:tr", namespaces=NS)
    if len(rows) < 7:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "测试项目汇总表结构异常")
    template_row = copy.deepcopy(rows[6])
    for row in rows[6:]:
        summary.remove(row)
    kept = selected_with_ancestors(selected_leaf_ids)
    numbers = display_numbers(selected_leaf_ids)
    for item in CATALOG:
        if item.id not in kept:
            continue
        row = copy.deepcopy(template_row)
        cells = row.xpath("./w:tc", namespaces=NS)
        if len(cells) < 5:
            raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "汇总表样板行列数异常")
        _set_cell_text(cells[0], numbers[item.id])
        _set_cell_text(cells[1], item.title)
        for cell in cells[2:]:
            _set_cell_text(cell, "")
        summary.append(row)


def _paragraph(value: str = "", *, page_break: bool = False, centered: bool = False) -> etree._Element:
    node = etree.Element(q("w", "p"))
    ppr = etree.SubElement(node, q("w", "pPr"))
    if centered:
        justification = etree.SubElement(ppr, q("w", "jc"))
        justification.set(q("w", "val"), "center")
    run = etree.SubElement(node, q("w", "r"))
    if page_break:
        br = etree.SubElement(run, q("w", "br"))
        br.set(q("w", "type"), "page")
    elif value:
        text = etree.SubElement(run, q("w", "t"))
        text.text = value
    return node


def _table_separator_paragraph() -> etree._Element:
    paragraph = _paragraph()
    props = paragraph.find("w:pPr", NS)
    spacing = etree.SubElement(props, q("w", "spacing"))
    spacing.set(q("w", "before"), "0")
    spacing.set(q("w", "after"), "0")
    spacing.set(q("w", "line"), "20")
    spacing.set(q("w", "lineRule"), "exact")
    run = paragraph.find("w:r", NS)
    run_props = etree.SubElement(run, q("w", "rPr"))
    size = etree.SubElement(run_props, q("w", "sz"))
    size.set(q("w", "val"), "2")
    return paragraph


def _drawing(package: DocxPackage, rid: str, name: str, cx: int, cy: int) -> etree._Element:
    drawing = etree.Element(q("w", "drawing"))
    inline = etree.SubElement(drawing, q("wp", "inline"), distT="0", distB="0", distL="0", distR="0")
    extent = etree.SubElement(inline, q("wp", "extent"))
    extent.set("cx", str(cx)); extent.set("cy", str(cy))
    effect = etree.SubElement(inline, q("wp", "effectExtent"))
    for side in ("l", "t", "r", "b"):
        effect.set(side, "0")
    doc_pr = etree.SubElement(inline, q("wp", "docPr"))
    doc_pr.set("id", str(package.next_drawing_id())); doc_pr.set("name", name)
    frame = etree.SubElement(inline, q("wp", "cNvGraphicFramePr"))
    locks = etree.SubElement(frame, q("a", "graphicFrameLocks"))
    locks.set("noChangeAspect", "1")
    graphic = etree.SubElement(inline, q("a", "graphic"))
    data = etree.SubElement(graphic, q("a", "graphicData"))
    data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    picture = etree.SubElement(data, q("pic", "pic"))
    nv = etree.SubElement(picture, q("pic", "nvPicPr"))
    cnv = etree.SubElement(nv, q("pic", "cNvPr")); cnv.set("id", "0"); cnv.set("name", name)
    etree.SubElement(nv, q("pic", "cNvPicPr"))
    fill = etree.SubElement(picture, q("pic", "blipFill"))
    blip = etree.SubElement(fill, q("a", "blip")); blip.set(q("r", "embed"), rid)
    stretch = etree.SubElement(fill, q("a", "stretch")); etree.SubElement(stretch, q("a", "fillRect"))
    shape = etree.SubElement(picture, q("pic", "spPr"))
    xfrm = etree.SubElement(shape, q("a", "xfrm"))
    off = etree.SubElement(xfrm, q("a", "off")); off.set("x", "0"); off.set("y", "0")
    ext = etree.SubElement(xfrm, q("a", "ext")); ext.set("cx", str(cx)); ext.set("cy", str(cy))
    geometry = etree.SubElement(shape, q("a", "prstGeom")); geometry.set("prst", "rect")
    etree.SubElement(geometry, q("a", "avLst"))
    return drawing


EVIDENCE_GRID_COLUMNS = 6
EVIDENCE_TABLE_WIDTH = 8306


def _new_evidence_table() -> etree._Element:
    table = etree.Element(q("w", "tbl"))
    props = etree.SubElement(table, q("w", "tblPr"))
    width = etree.SubElement(props, q("w", "tblW"))
    width.set(q("w", "w"), str(EVIDENCE_TABLE_WIDTH))
    width.set(q("w", "type"), "dxa")
    layout = etree.SubElement(props, q("w", "tblLayout"))
    layout.set(q("w", "type"), "fixed")
    borders = etree.SubElement(props, q("w", "tblBorders"))
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = etree.SubElement(borders, q("w", name))
        border.set(q("w", "val"), "single")
        border.set(q("w", "sz"), "4")
        border.set(q("w", "color"), "auto")
        border.set(q("w", "space"), "0")
    margins = etree.SubElement(props, q("w", "tblCellMar"))
    for name, value in (("top", "80"), ("left", "80"), ("bottom", "80"), ("right", "80")):
        margin = etree.SubElement(margins, q("w", name))
        margin.set(q("w", "w"), value)
        margin.set(q("w", "type"), "dxa")
    grid = etree.SubElement(table, q("w", "tblGrid"))
    base_width = EVIDENCE_TABLE_WIDTH // EVIDENCE_GRID_COLUMNS
    for index in range(EVIDENCE_GRID_COLUMNS):
        column = etree.SubElement(grid, q("w", "gridCol"))
        width_value = base_width + (EVIDENCE_TABLE_WIDTH % EVIDENCE_GRID_COLUMNS if index == EVIDENCE_GRID_COLUMNS - 1 else 0)
        column.set(q("w", "w"), str(width_value))
    return table


def _new_unsplittable_row(table: etree._Element) -> etree._Element:
    row = etree.SubElement(table, q("w", "tr"))
    row_props = etree.SubElement(row, q("w", "trPr"))
    etree.SubElement(row_props, q("w", "cantSplit"))
    return row


def _new_evidence_cell(row: etree._Element, span: int) -> etree._Element:
    cell = etree.SubElement(row, q("w", "tc"))
    cell_props = etree.SubElement(cell, q("w", "tcPr"))
    width = etree.SubElement(cell_props, q("w", "tcW"))
    width.set(q("w", "w"), str(round(EVIDENCE_TABLE_WIDTH * span / EVIDENCE_GRID_COLUMNS)))
    width.set(q("w", "type"), "dxa")
    if span > 1:
        grid_span = etree.SubElement(cell_props, q("w", "gridSpan"))
        grid_span.set(q("w", "val"), str(span))
    valign = etree.SubElement(cell_props, q("w", "vAlign"))
    valign.set(q("w", "val"), "center")
    return cell


def _append_group_title(table: etree._Element, title: str) -> None:
    row = _new_unsplittable_row(table)
    cell = _new_evidence_cell(row, EVIDENCE_GRID_COLUMNS)
    title_paragraph = _paragraph(title, centered=True)
    title_run = title_paragraph.find("w:r", NS)
    run_props = etree.SubElement(title_run, q("w", "rPr"))
    etree.SubElement(run_props, q("w", "b"))
    cell.append(title_paragraph)


def _append_photo_row(
    package: DocxPackage,
    table: etree._Element,
    photos: list[DocPhoto],
    columns: int,
    max_row_height: int,
) -> None:
    row = _new_unsplittable_row(table)
    span = EVIDENCE_GRID_COLUMNS // columns
    available_width_emu = max(
        350000,
        (round(EVIDENCE_TABLE_WIDTH * span / EVIDENCE_GRID_COLUMNS) - 160) * 635,
    )
    for column_index in range(columns):
        cell = _new_evidence_cell(row, span)
        paragraph = _paragraph(centered=True)
        if column_index >= len(photos):
            cell.append(paragraph)
            continue
        photo = photos[column_index]
        run = paragraph.find("w:r", NS)
        width_px, height_px = image_dimensions(photo.path)
        caption_reserve = 420000 if photo.caption else 0
        available_height = max(500000, max_row_height - caption_reserve)
        scale = min(available_width_emu / width_px, available_height / height_px)
        rid, media_name = package.add_image(photo.path)
        run.append(
            _drawing(
                package,
                rid,
                media_name,
                max(1, int(width_px * scale)),
                max(1, int(height_px * scale)),
            )
        )
        cell.append(paragraph)
        if photo.caption:
            caption = _paragraph(photo.caption, centered=True)
            caption_props = caption.find("w:pPr", NS)
            spacing = etree.SubElement(caption_props, q("w", "spacing"))
            spacing.set(q("w", "before"), "60")
            spacing.set(q("w", "after"), "0")
            caption_run = caption.find("w:r", NS)
            run_props = etree.SubElement(caption_run, q("w", "rPr"))
            size = etree.SubElement(run_props, q("w", "sz"))
            size.set(q("w", "val"), "18")
            cell.append(caption)


def _append_group_rows(
    package: DocxPackage,
    table: etree._Element,
    group: DocPhotoGroup,
) -> None:
    if not (group.key == "test_photos" and group.source == "template"):
        _append_group_title(table, group.title)
    if group.layout_profile in {"fixed_columns", "fire_two_column"}:
        columns = group.preferred_columns or 2
        max_height = 2_700_000
        for offset in range(0, len(group.photos), columns):
            _append_photo_row(
                package,
                table,
                list(group.photos[offset : offset + columns]),
                columns,
                max_height,
            )
        return
    if group.layout_profile == "full_width_figure":
        for photo in group.photos:
            _append_photo_row(package, table, [photo], 1, 5_800_000)
        return
    layout_photos = []
    for photo in group.photos:
        width, height = image_dimensions(photo.path)
        layout_photos.append(LayoutPhoto(photo.id, width, height, photo.caption))
    plan = plan_layout(layout_photos)
    cursor = 0
    for page in plan.pages:
        row_height = 6_800_000 // len(page.rows)
        for row_size in page.rows:
            _append_photo_row(
                package,
                table,
                list(group.photos[cursor : cursor + row_size]),
                row_size,
                row_height,
            )
            cursor += row_size


def _build_evidence_table(
    package: DocxPackage,
    groups: list[DocPhotoGroup],
) -> etree._Element:
    table = _new_evidence_table()
    for group in groups:
        _append_group_rows(package, table, group)
    return table


def _append_full_width_photos_to_cell(
    package: DocxPackage,
    cell: etree._Element,
    photos: tuple[DocPhoto, ...],
) -> None:
    for photo in photos:
        paragraph = _paragraph(centered=True)
        run = paragraph.find("w:r", NS)
        width_px, height_px = image_dimensions(photo.path)
        scale = min(7_400_000 / width_px, 4_800_000 / height_px)
        rid, media_name = package.add_image(photo.path)
        run.append(
            _drawing(
                package,
                rid,
                media_name,
                max(1, int(width_px * scale)),
                max(1, int(height_px * scale)),
            )
        )
        cell.append(paragraph)
        if photo.caption:
            cell.append(_paragraph(photo.caption, centered=True))


def _insert_temperature_curve(package: DocxPackage, group: DocPhotoGroup) -> bool:
    records = _heading_records(package)
    current_position = next(
        (index for index, record in enumerate(records) if record["item"].id == "temperature_rise"),
        None,
    )
    if current_position is None:
        return False
    current = records[current_position]
    end_index = (
        records[current_position + 1]["index"]
        if current_position + 1 < len(records)
        else len(package.body) - 1
    )
    for block in list(package.body)[current["index"] + 1 : end_index]:
        if block.tag != q("w", "tbl"):
            continue
        for row in block.xpath("./w:tr", namespaces=NS):
            if not paragraph_text(row).startswith("温升曲线"):
                continue
            cells = row.xpath("./w:tc", namespaces=NS)
            if not cells:
                continue
            row_props = row.find("w:trPr", NS)
            if row_props is None:
                row_props = etree.Element(q("w", "trPr"))
                row.insert(0, row_props)
            if not row_props.xpath("./w:cantSplit", namespaces=NS):
                etree.SubElement(row_props, q("w", "cantSplit"))
            _append_full_width_photos_to_cell(package, cells[0], group.photos)
            return True
    return False


def _insert_photo_groups(
    package: DocxPackage,
    groups_by_item: dict[str, tuple[DocPhotoGroup, ...]],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    nonempty = [
        group for groups in groups_by_item.values() for group in groups if group.photos
    ]
    completed = 0
    for item in CATALOG:
        groups = sorted(groups_by_item.get(item.id, ()), key=lambda group: group.sort_order)
        groups = [group for group in groups if group.photos]
        if not groups:
            continue
        records = _heading_records(package)
        current_pos = next((i for i, record in enumerate(records) if record["item"].id == item.id), None)
        if current_pos is None:
            continue
        current = records[current_pos]
        end_index = records[current_pos + 1]["index"] if current_pos + 1 < len(records) else len(package.body) - 1
        blocks = list(package.body)
        anchor = blocks[end_index]
        for candidate in blocks[current["index"] + 1 : end_index]:
            if candidate.tag == q("w", "p") and paragraph_text(candidate).startswith("测试结论"):
                anchor = candidate
                break
        insertion_index = package.body.index(anchor)
        regular_groups: list[DocPhotoGroup] = []
        for group in groups:
            if group.layout_profile == "temperature_curve" and _insert_temperature_curve(package, group):
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(nonempty), group.title)
                continue
            regular_groups.append(group)
            completed += 1
            if progress_callback:
                progress_callback(completed, len(nonempty), group.title)
        if regular_groups:
            if any(g.key == "test_photos" and g.source == "template" for g in regular_groups):
                section_blocks = list(package.body)[current["index"] + 1 : end_index]
                existing = next((p for p in section_blocks if p.tag == q("w", "p") and paragraph_text(p) == "测试照片"), None)
                prototype = package.photo_title_prototype
                title = existing if existing is not None else copy.deepcopy(prototype) if prototype is not None else _paragraph("测试照片")
                if existing is None:
                    # Preserve template typography but never duplicate its bookmarks or field ranges.
                    run_props = title.find("w:r/w:rPr", NS)
                    run_props = copy.deepcopy(run_props) if run_props is not None else None
                    _set_paragraph_text(title, "测试照片")
                    if run_props is not None:
                        title.find("w:r", NS).insert(0, run_props)
                elif title.getparent() is package.body:
                    package.body.remove(title)
                props = title.find("w:pPr", NS)
                if props is None:
                    props = etree.Element(q("w", "pPr"))
                    title.insert(0, props)
                keep = props.find("w:keepNext", NS)
                if keep is None:
                    keep = etree.SubElement(props, q("w", "keepNext"))
                keep.set(q("w", "val"), "1")
                insertion_index = package.body.index(anchor)
                package.body.insert(insertion_index, title)
                insertion_index += 1
            if insertion_index > 0 and list(package.body)[insertion_index - 1].tag == q("w", "tbl"):
                package.body.insert(insertion_index, _table_separator_paragraph())
                insertion_index += 1
            package.body.insert(
                insertion_index,
                _build_evidence_table(package, regular_groups),
            )


def _insert_sample_photos(package: DocxPackage, groups: tuple[DocPhotoGroup, ...]) -> None:
    nonempty = sorted((g for g in groups if g.photos), key=lambda g: g.sort_order)
    if not nonempty:
        return
    blocks = list(package.body)
    start = next((i for i, p in enumerate(blocks) if p.tag == q("w", "p") and paragraph_text(p) == "样品照片"), None)
    if start is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "找不到样品照片章节")
    end = next((i for i in range(start + 1, len(blocks)) if blocks[i].xpath("./w:pPr/w:numPr", namespaces=NS)), None)
    if end is None:
        raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", "找不到样品照片章节结束位置")
    package.body.insert(end, _build_evidence_table(package, nonempty))


def generate_docx(
    master: Path,
    destination: Path,
    request: GenerationInput,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    if not request.selected_test_item_ids:
        raise DocxGenerationError("INVALID_SELECTION", "至少选择一个测试项目")
    selected_with_ancestors(request.selected_test_item_ids)
    package = DocxPackage(master)
    _apply_project_bindings(package, request.project)
    _remove_unselected_sections(package, request.selected_test_item_ids)
    _rebuild_summary_table(package, request.selected_test_item_ids)
    _insert_sample_photos(package, request.sample_photo_groups)
    groups_by_item = request.photo_groups_by_test_item
    if not groups_by_item:
        groups_by_item = {
            item_id: (
                DocPhotoGroup(
                    id=f"legacy:{item_id}",
                    key="test_photos",
                    title="测试照片",
                    photos=photos,
                ),
            )
            for item_id, photos in request.photos_by_test_item.items()
        }
    _insert_photo_groups(package, groups_by_item, progress_callback)
    package.prune_orphan_media()
    package.save(destination)
    return {
        "display_numbers": display_numbers(request.selected_test_item_ids),
        "selected_test_item_ids": list(request.selected_test_item_ids),
        "photo_count": sum(
            len(group.photos) for groups in groups_by_item.values() for group in groups
        ) + sum(len(group.photos) for group in request.sample_photo_groups),
        "sample_photo_count": sum(len(group.photos) for group in request.sample_photo_groups),
        "photo_group_count": sum(
            bool(group.photos) for groups in groups_by_item.values() for group in groups
        ),
    }
