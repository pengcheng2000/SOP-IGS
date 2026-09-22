from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS)).strip()


def inspect(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        body = document.find("w:body", NS)
        headings = []
        for index, element in enumerate(body):
            if element.tag != f"{{{NS['w']}}}p":
                continue
            style = element.xpath("string(w:pPr/w:pStyle/@w:val)", namespaces=NS)
            num_id = element.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS)
            level = element.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS)
            if style in {"2", "3"} and num_id == "2" and level:
                headings.append({"body_index": index, "title": text(element), "level": int(level)})
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": len(archive.namelist()),
            "paragraphs": len(document.xpath("//w:p", namespaces=NS)),
            "tables": len(document.xpath("//w:tbl", namespaces=NS)),
            "drawings": len(document.xpath("//w:drawing", namespaces=NS)),
            "inline_drawings": len(document.xpath("//wp:inline", namespaces=NS)),
            "floating_drawings": len(document.xpath("//wp:anchor", namespaces=NS)),
            "sections": len(document.xpath("//w:sectPr", namespaces=NS)),
            "headings": headings,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.docx), ensure_ascii=False, indent=2))

