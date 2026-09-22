from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
W = f"{{{NS['w']}}}"


def text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS)).strip()


def set_text(cell: etree._Element, value: str) -> None:
    paragraphs = cell.xpath("./w:p", namespaces=NS)
    paragraph = paragraphs[0] if paragraphs else etree.SubElement(cell, W + "p")
    ppr = paragraph.find("w:pPr", NS)
    for child in list(paragraph):
        if child is not ppr:
            paragraph.remove(child)
    run = etree.SubElement(paragraph, W + "r")
    node = etree.SubElement(run, W + "t")
    node.text = value
    for extra in paragraphs[1:]:
        cell.remove(extra)


def normalize(source: Path, destination: Path) -> str:
    with zipfile.ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    document = etree.fromstring(entries["word/document.xml"])
    relationships = etree.fromstring(entries["word/_rels/document.xml.rels"])
    settings = etree.fromstring(entries["word/settings.xml"])
    body = document.find("w:body", NS)

    first_table = body.xpath("./w:tbl", namespaces=NS)[0]
    dynamic_photo_tables: list[etree._Element] = []
    current_section = ""
    for block in list(body):
        if block.tag == W + "p":
            title = text(block)
            if block.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS) == "2" and title:
                current_section = title
        elif block.tag == W + "tbl" and block is not first_table:
            if block.xpath(".//w:drawing", namespaces=NS) and current_section != "温升测试":
                dynamic_photo_tables.append(block)

    drawings = document.xpath("//w:drawing", namespaces=NS)
    for drawing in drawings[1:]:  # first drawing is the company logo
        run = drawing.getparent()
        while run is not None and run.tag != W + "r":
            run = run.getparent()
        if run is not None and run.getparent() is not None:
            run.getparent().remove(run)

    # Photo classifications are represented by the manifest and rebuilt from project data.
    # Keeping historical image tables would leave empty borders beside newly generated tables.
    for table in dynamic_photo_tables:
        if table.getparent() is body:
            body.remove(table)

    tables = body.xpath("./w:tbl", namespaces=NS)
    if len(tables) < 8:
        raise RuntimeError("Template structure changed while normalizing")

    cover = tables[0].xpath("./w:tr", namespaces=NS)
    values = cover[1].xpath("./w:tc", namespaces=NS)
    if len(values) >= 4:
        set_text(values[1], ""); set_text(values[2], ""); set_text(values[3], "V01")
    title_cells = cover[2].xpath("./w:tc", namespaces=NS)
    if len(title_cells) >= 2:
        set_text(title_cells[1], "液冷户外柜测试报告")

    approval = tables[1].xpath("./w:tr", namespaces=NS)
    for row in approval:
        cells = row.xpath("./w:tc", namespaces=NS)
        for index in range(1, len(cells), 2):
            set_text(cells[index], "")

    summary = next((table for table in tables if len(table.xpath("./w:tr", namespaces=NS)) >= 30), None)
    if summary is None:
        raise RuntimeError("Summary table not found")
    for row in summary.xpath("./w:tr", namespaces=NS)[1:]:
        cells = row.xpath("./w:tc", namespaces=NS)
        for cell in cells[2:]:
            set_text(cell, "")

    sample = tables[7].xpath("./w:tr", namespaces=NS)
    for row in sample[:2]:
        cells = row.xpath("./w:tc", namespaces=NS)
        if len(cells) >= 2:
            set_text(cells[1], "")

    used_rids = set(document.xpath("//a:blip/@r:embed", namespaces=NS))
    for rel in list(relationships):
        if rel.get("Type", "").endswith("/image") and rel.get("Id") not in used_rids:
            target = rel.get("Target")
            relationships.remove(rel)
            if target:
                entries.pop(f"word/{target}", None)

    if not settings.xpath("./w:updateFields", namespaces=NS):
        update = etree.SubElement(settings, W + "updateFields")
        update.set(W + "val", "true")

    entries["word/document.xml"] = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)
    entries["word/_rels/document.xml.rels"] = etree.tostring(relationships, xml_declaration=True, encoding="UTF-8", standalone=True)
    entries["word/settings.xml"] = etree.tostring(settings, xml_declaration=True, encoding="UTF-8", standalone=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.docx")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    os.replace(temporary, destination)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(normalize(args.source, args.destination))
