"""Boost-only layout corrections; cabinet layouts keep their existing defaults."""

from lxml import etree

from ...document_common.ooxml import NS, paragraph_text, q


def regular(element):
    for props in element.findall(".//w:rPr", NS):
        for tag in ("b", "bCs"):
            for node in props.findall("w:" + tag, NS):
                props.remove(node)
            etree.SubElement(props, q("w", tag)).set(q("w", "val"), "0")


def fix_layout(package):
    numbering = package.part("word/numbering.xml")
    for abstract, positions in [
        ("9001", [(945, 315), (1260, 315)]),
        ("9002", [(1260, 315), (1575, 315)]),
    ]:
        for index, (left, hanging) in enumerate(positions):
            for level in numbering.xpath(
                f'./w:abstractNum[@w:abstractNumId="{abstract}"]/w:lvl[@w:ilvl="{index}"]',
                namespaces=NS,
            ):
                suff = level.find("w:suff", NS)
                if suff is None:
                    suff = etree.Element(q("w", "suff"))
                    level.find("w:lvlText", NS).addprevious(suff)
                suff.set(q("w", "val"), "tab")
                props = level.find("w:pPr", NS)
                props.clear()
                tabs = etree.SubElement(props, q("w", "tabs"))
                tab = etree.SubElement(tabs, q("w", "tab"))
                tab.set(q("w", "val"), "num")
                tab.set(q("w", "pos"), str(left))
                ind = etree.SubElement(props, q("w", "ind"))
                ind.set(q("w", "left"), str(left))
                ind.set(q("w", "hanging"), str(hanging))
    for table in package.body.findall("w:tbl", NS):
        regular(table)
    mapped = {}
    for p in package.body.findall("w:p", NS):
        props = p.find("w:pPr", NS)
        if props is None:
            continue
        if paragraph_text(p) == "版本修改记录":
            # Heading 1 inherits keepNext: Word displays its black paragraph-
            # formatting square in the margin. Override pagination flags while
            # retaining the actual heading style and outline level.
            for tag in ("keepNext", "keepLines", "pageBreakBefore"):
                flag = props.find("w:" + tag, NS)
                if flag is None:
                    flag = etree.SubElement(props, q("w", tag))
                flag.set(q("w", "val"), "0")
            outline = props.find("w:outlineLvl", NS)
            if outline is None:
                outline = etree.SubElement(props, q("w", "outlineLvl"))
            outline.set(q("w", "val"), "0")
            style = props.find("w:pStyle", NS)
            if style is None:
                style = etree.Element(q("w", "pStyle"))
                props.insert(0, style)
            style.set(q("w", "val"), "2")
        num = props.find("w:numPr/w:numId", NS)
        if num is not None and props.find("w:outlineLvl", NS) is None:
            old = num.get(q("w", "val"))
            abstract = numbering.xpath(
                f'string(./w:num[@w:numId="{old}"]/w:abstractNumId/@w:val)', namespaces=NS
            )
            if abstract not in ("9001", "9002", "9003"):
                if old not in mapped:
                    mapped[old] = package.numbering_new_num("9001")
                num.set(q("w", "val"), mapped[old])


def set_body_indent(p, kind):
    props = p.find("w:pPr", NS)
    if props is None:
        props = etree.Element(q("w", "pPr"))
        p.insert(0, props)
    for node in props.findall("w:ind", NS):
        props.remove(node)
    ind = etree.SubElement(props, q("w", "ind"))
    ind.set(q("w", "left"), "945" if kind == "indent" else "210")
    ind.set(q("w", "firstLine"), "0" if kind == "indent" else "420")
