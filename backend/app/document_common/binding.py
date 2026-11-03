from __future__ import annotations

import copy

from lxml import etree

from .blocks import XML_SPACE, _first_run_props, _text_run
from .ooxml import NS, DocxPackage, paragraph_text, q


def _replace_paragraph_text(paragraph: etree._Element, value: str) -> None:
    run_props = _first_run_props(paragraph)
    for child in list(paragraph):
        if child.tag != q("w", "pPr"):
            paragraph.remove(child)
    paragraph.append(_text_run(value, run_props))


def _expand_multiline(package: DocxPackage, token: str, lines: list[str]) -> None:
    for paragraph in package.body.xpath("./w:p", namespaces=NS):
        if paragraph_text(paragraph) != token:
            continue
        if not lines:
            package.body.remove(paragraph)
            continue
        anchor = paragraph
        for line in lines[1:]:
            clone = copy.deepcopy(paragraph)
            _replace_paragraph_text(clone, line)
            anchor.addnext(clone)
            anchor = clone
        _replace_paragraph_text(paragraph, lines[0])


def _bind_fields(package: DocxPackage, fields: dict[str, str]) -> None:
    roots = [package.document] + [
        package.part(name)
        for name in sorted(package.entries)
        if name.startswith(("word/header", "word/footer")) and name.endswith(".xml")
    ]
    for root in roots:
        for text in root.xpath("//w:t", namespaces=NS):
            value = text.text or ""
            if "{{" not in value:
                continue
            for key, replacement in fields.items():
                value = value.replace("{{" + key + "}}", replacement)
            text.text = value
            if value != value.strip():
                text.set(XML_SPACE, "preserve")
