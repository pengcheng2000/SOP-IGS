from __future__ import annotations

import hashlib
import os
import re
import zipfile
from pathlib import Path

from lxml import etree

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


class DocxPackage:
    def __init__(self, source: Path):
        with zipfile.ZipFile(source) as archive:
            self.entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        self.document = etree.fromstring(self.entries["word/document.xml"])
        self.relationships = etree.fromstring(self.entries["word/_rels/document.xml.rels"])
        self.content_types = etree.fromstring(self.entries["[Content_Types].xml"])
        self._parts: dict[str, etree._Element] = {}
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

    def part(self, name: str) -> etree._Element:
        """Parse another XML part (numbering, headers, footers) once; it is written back on save."""
        if name not in self._parts:
            if name not in self.entries:
                raise DocxGenerationError("TEMPLATE_STRUCTURE_MISMATCH", f"母版缺少部件：{name}")
            self._parts[name] = etree.fromstring(self.entries[name])
        return self._parts[name]

    def numbering_new_num(self, abstract_id: str, restart: bool = True) -> str:
        """Create a new numbering instance; with restart its first level starts again at 1."""
        numbering = self.part("word/numbering.xml")
        existing = [int(value) for value in numbering.xpath("./w:num/@w:numId", namespaces=NS) if value.isdigit()]
        num_id = str(max(existing or [0]) + 1)
        num = etree.Element(q("w", "num"))
        num.set(q("w", "numId"), num_id)
        abstract = etree.SubElement(num, q("w", "abstractNumId"))
        abstract.set(q("w", "val"), str(abstract_id))
        if restart:
            override = etree.SubElement(num, q("w", "lvlOverride"))
            override.set(q("w", "ilvl"), "0")
            start = etree.SubElement(override, q("w", "startOverride"))
            start.set(q("w", "val"), "1")
        # Schema order requires every w:num after the abstract numbering definitions.
        last_num = numbering.xpath("./w:num[last()]", namespaces=NS)
        if last_num:
            last_num[0].addnext(num)
        else:
            last_abstract = numbering.xpath("./w:abstractNum[last()]", namespaces=NS)
            if last_abstract:
                last_abstract[0].addnext(num)
            else:
                numbering.append(num)
        return num_id

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
        for name, root in self._parts.items():
            self.entries[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
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
