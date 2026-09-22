from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path

from lxml import etree

from .generator import NS


class DocxValidationError(RuntimeError):
    pass


def validate_docx(path: Path) -> dict:
    issues: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        xml_names = [name for name in names if name.endswith((".xml", ".rels"))]
        parsed: dict[str, etree._Element] = {}
        for name in xml_names:
            try:
                parsed[name] = etree.fromstring(archive.read(name))
            except etree.XMLSyntaxError as exc:
                issues.append(f"XML_PARSE:{name}:{exc}")
        for rel_name, root in parsed.items():
            if not rel_name.endswith(".rels"):
                continue
            base = "" if rel_name == "_rels/.rels" else posixpath.dirname(posixpath.dirname(rel_name))
            for rel in root:
                if rel.get("TargetMode") == "External":
                    continue
                target = posixpath.normpath(posixpath.join(base, rel.get("Target", "")))
                if target not in names:
                    issues.append(f"MISSING_RELATIONSHIP:{rel_name}:{rel.get('Id')}:{target}")
        document = parsed.get("word/document.xml")
        if document is None:
            issues.append("MISSING_DOCUMENT_XML")
            drawing_ids: list[str] = []
            drawings = anchors = 0
        else:
            drawing_ids = document.xpath("//wp:docPr/@id", namespaces=NS)
            drawings = len(document.xpath("//w:drawing", namespaces=NS))
            anchors = len(document.xpath("//wp:anchor", namespaces=NS))
            if len(drawing_ids) != len(set(drawing_ids)):
                issues.append("DUPLICATE_DRAWING_ID")
            if anchors:
                issues.append("FLOATING_DRAWING_PRESENT")
    report = {
        "valid": not issues,
        "issues": issues,
        "xml_parts": len(xml_names),
        "drawings": drawings,
        "floating_drawings": anchors,
        "drawing_ids": len(drawing_ids),
    }
    if issues:
        raise DocxValidationError("; ".join(issues))
    return report

