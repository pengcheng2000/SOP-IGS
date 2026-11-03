"""Derive the cabinet plan page furniture and styles from the private Word case."""

from __future__ import annotations

import argparse
import copy
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import yaml
from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.document_common.blocks import _Builder, _paragraph_like
from app.document_common.model import Table, TableCell
from app.document_common.ooxml import (
    NS,
    DocxPackage,
    _drawing,
    paragraph_text,
    q,
)

FIELDS = [
    {"key": "document_title", "label": "文档标题", "required": True},
    {"key": "scope_text", "label": "适用范围", "required": True, "multiline": True},
    {"key": "document_code", "label": "编码", "required": True},
    {"key": "document_version", "label": "版本", "required": True},
    {"key": "archive_month", "label": "归档年月", "type": "month", "required": True},
    {"key": "product_line", "label": "所属产品"},
    *[
        {"key": key, "label": label}
        for key, label in [
            ("drafter", "拟制"),
            ("reviewer_1", "审核1"),
            ("reviewer_2", "审核2"),
            ("reviewer_3", "审核3"),
            ("standardizer", "标准化"),
            ("approver", "批准"),
        ]
    ],
]


def set_prop(parent, tag, **attrs):
    for node in parent.findall(f"w:{tag}", NS):
        parent.remove(node)
    node = E.Element(q("w", tag))
    following = parent.find("w:rPr", NS) if parent.tag == q("w", "pPr") else None
    if following is not None:
        following.addprevious(node)
    else:
        parent.append(node)
    for key, value in attrs.items():
        node.set(q("w", key), str(value))
    return node


def clean_paragraph(prototype, text, size=21, bold=False, heading=None):
    p = _paragraph_like(prototype, text)
    pr = p.find("w:pPr", NS)
    if pr is None:
        pr = E.Element(q("w", "pPr"))
        p.insert(0, pr)
    for tag in (
        "numPr",
        "sectPr",
        "pageBreakBefore",
        "pStyle",
        "keepNext",
        "keepLines",
        "tabs",
        "ind",
        "spacing",
        "outlineLvl",
    ):
        for n in pr.findall(f"w:{tag}", NS):
            pr.remove(n)
    set_prop(pr, "spacing", before=0, after=0, line=300, lineRule="auto")
    if heading:
        set_prop(pr, "outlineLvl", val=heading - 1)
    for run in p.findall("w:r", NS):
        rp = run.find("w:rPr", NS)
        if rp is None:
            rp = E.Element(q("w", "rPr"))
            run.insert(0, rp)
        for tag in (
            "b",
            "bCs",
            "color",
            "sz",
            "szCs",
            "rFonts",
            "highlight",
            "vertAlign",
        ):
            for n in rp.findall(f"w:{tag}", NS):
                rp.remove(n)
        set_prop(
            rp,
            "rFonts",
            ascii="Times New Roman",
            eastAsia="宋体",
            hAnsi="Times New Roman",
        )
        set_prop(rp, "sz", val=size)
        set_prop(rp, "szCs", val=size)
        if bold:
            set_prop(rp, "b")
        elif heading is not None:
            set_prop(rp, "b", val=0)
            set_prop(rp, "bCs", val=0)
    return p


def sanitize_table(table, size=18):
    for row in table.findall("w:tr", NS):
        pr = row.find("w:trPr", NS)
        if pr is not None:
            for n in pr.findall("w:trHeight", NS):
                pr.remove(n)
        for cell in row.findall("w:tc", NS):
            tcpr = cell.find("w:tcPr", NS)
            if tcpr is not None:
                for tag in ("noWrap", "tcFitText"):
                    for n in tcpr.findall(f"w:{tag}", NS):
                        tcpr.remove(n)
            for p in list(cell.findall("w:p", NS)):
                replacement = clean_paragraph(p, paragraph_text(p), size=size)
                p.addprevious(replacement)
                cell.remove(p)
    return table


def field(p, instruction):
    node = E.SubElement(p, q("w", "fldSimple"))
    node.set(q("w", "instr"), f" {instruction} ")
    r = E.SubElement(node, q("w", "r"))
    E.SubElement(r, q("w", "t")).text = "1"


def margin_label(
    document, contains: str, *, name: str, left: float, top: float, filename=False
):
    """Copy the case's rotated text box, pinning both OOXML representations to paper."""
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    v = "urn:schemas-microsoft-com:vml"
    ns = {**NS, "mc": mc, "v": v}
    boxes = document.xpath("//w:txbxContent[not(ancestor::mc:Fallback)]", namespaces=ns)
    box = next(box for box in boxes if contains in paragraph_text(box))
    alternate = next(
        node
        for node in box.iterancestors()
        if node.tag == "{" + mc + "}AlternateContent"
    )
    result = copy.deepcopy(alternate)
    for content in result.xpath(".//w:txbxContent", namespaces=ns):
        if filename:
            for text in content.xpath(".//w:t", namespaces=ns):
                if "1.0105.0117" in (text.text or ""):
                    text.text = text.text.replace("1.0105.0117", "{{document_code}}")
        else:
            texts = content.xpath(".//w:t", namespaces=ns)
            texts[0].text = "版权所有：侵权必究"
            for text in texts[1:]:
                text.text = ""
    for anchor in result.xpath(".//wp:anchor", namespaces=ns):
        anchor.set("layoutInCell", "0")
        for axis, offset in (("H", left), ("V", top)):
            position = anchor.find("wp:position" + axis, ns)
            position.set("relativeFrom", "page")
            for child in list(position):
                position.remove(child)
            E.SubElement(position, q("wp", "posOffset")).text = str(
                round(offset * 12700)
            )
        for child in list(anchor):
            if E.QName(child).localname.startswith("wrap"):
                anchor.remove(child)
        anchor.find("wp:docPr", ns).addprevious(E.Element(q("wp", "wrapNone")))
        anchor.find("wp:docPr", ns).set("name", name)
    for shape in result.xpath(".//v:shape", namespaces=ns):
        shape.attrib.pop("{urn:schemas-microsoft-com:office:office}gfxdata", None)
        style = dict(
            item.split(":", 1)
            for item in shape.get("style", "").split(";")
            if ":" in item
        )
        style.update(
            {
                "left": "0pt",
                "top": "0pt",
                "margin-left": f"{left}pt",
                "margin-top": f"{top}pt",
                "mso-position-horizontal-relative": "page",
                "mso-position-vertical-relative": "page",
            }
        )
        shape.set(
            "style", ";".join(f"{key}:{value}" for key, value in style.items()) + ";"
        )
    return result


def build(source: Path, out: Path):
    package = DocxPackage(source)
    copyright_label = margin_label(
        package.document, "版权所有", name="CabinetCopyright", left=4.7, top=74
    )
    filename_label = margin_label(
        package.document,
        "电子文件名：1.0105.0117",
        name="CabinetFilename",
        left=4.0,
        top=590,
        filename=True,
    )
    original = list(package.body)
    body_proto = copy.deepcopy(original[23])
    table_proto = sanitize_table(copy.deepcopy(original[100]), 21)
    approval = sanitize_table(copy.deepcopy(original[16]), 18)
    section = copy.deepcopy(original[-1])
    # Draw the outside frame at fixed paper coordinates. Text-relative page
    # borders can stop at a tall first-page footer, while page-relative border
    # spacing is limited to 31 pt and cannot retain the case's left margin.
    margins = section.find("w:pgMar", NS)
    size = section.find("w:pgSz", NS)
    frame_left = int(margins.get(q("w", "left"))) / 20 - 4
    frame_top = int(margins.get(q("w", "top"))) / 20 - 1
    frame_right = int(margins.get(q("w", "right"))) / 20 - 4
    frame_bottom = 18
    for border in section.findall("w:pgBorders", NS):
        section.remove(border)
    # Case page margins remain; old case labels and personal comments do not.
    for root in [package.document]:
        for node in root.xpath(
            "//w:drawing|//w:pict|//w:commentRangeStart|//w:commentRangeEnd|//w:commentReference",
            namespaces=NS,
        ):
            node.getparent().remove(node)
    for node in approval.xpath(".//w:drawing|.//w:pict", namespaces=NS):
        node.getparent().remove(node)
    for name in list(package.entries):
        if "comment" in name.lower() or name.startswith("customXml/"):
            del package.entries[name]
    for rel in list(package.relationships):
        if any(x in rel.get("Type", "").lower() for x in ("comment", "customxml")):
            package.relationships.remove(rel)
    for node in list(package.content_types):
        if "comment" in node.get("PartName", "").lower() or node.get(
            "PartName", ""
        ).startswith("/customXml/"):
            package.content_types.remove(node)
    for node in list(package.body):
        package.body.remove(node)
    title = clean_paragraph(body_proto, "{{document_title}}", size=30)
    for rp in title.findall("w:r/w:rPr", NS):
        set_prop(rp, "b", val=0)
        set_prop(rp, "bCs", val=0)
    set_prop(title.find("w:pPr", NS), "jc", val="center")
    package.body.append(title)

    def p(text, size=18):
        return clean_paragraph(body_proto, text, size=size)

    for token in ["{{HOME_CONTENT}}"]:
        package.body.append(p(token))
    # Rebuild the case title block on one consistent grid; the original has
    # incompatible row widths and side labels stored in floating text boxes.
    rows = [
        tuple(
            TableCell(v, i * 3, 3)
            for i, v in enumerate(
                ["{{document_version}}", "/", "新归档", "{{archive_month}}"]
            )
        ),
        tuple(
            TableCell(v, i * 3, 3)
            for i, v in enumerate(["版本", "更改方式", "更改单号", "日期"])
        ),
        (
            TableCell("拟制", 0, 2),
            TableCell("{{drafter}}", 2, 2),
            TableCell("{{document_title}}", 4, 4, 3),
            TableCell("上海正泰电源系统有限公司", 8, 4, 3),
        ),
        (TableCell("审核", 0, 2), TableCell("{{reviewer_1}}", 2, 2)),
        (TableCell("审核", 0, 2), TableCell("{{reviewer_2}}", 2, 2)),
        (
            TableCell("审核", 0, 2),
            TableCell("{{reviewer_3}}", 2, 2),
            TableCell("编码", 4, 4),
            TableCell("页码", 8, 4),
        ),
        (
            TableCell("标准化", 0, 2),
            TableCell("{{standardizer}}", 2, 2),
            TableCell("{{document_code}}", 4, 4, 2),
            TableCell("所属产品", 8, 2, 2),
            TableCell("{{product_line}}", 10, 2, 2),
        ),
        (TableCell("批准", 0, 2), TableCell("{{approver}}", 2, 2)),
    ]
    proto = sanitize_table(copy.deepcopy(original[100]), 18)
    props = proto.find("w:tblPr", NS)
    for tag in ("tblInd", "tblpPr"):
        for n in props.findall(f"w:{tag}", NS):
            props.remove(n)
    set_prop(props, "jc", val="center")
    borders = set_prop(props, "tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        set_prop(borders, edge, val="single", sz=4, color="000000")
    prototypes = SimpleNamespace(
        table_props=props,
        header_row=proto.findall("w:tr", NS)[0],
        body_row=proto.findall("w:tr", NS)[1],
    )
    renderer = _Builder(
        package,
        {
            "heading_numbering": {"num_id": "9100", "ilvl_by_level": {}},
            "list_abstract_nums": {},
        },
        prototypes,
        body_proto,
    )
    approval = renderer.table(Table((1,) * 12, tuple(rows), 0))
    for cell in approval.xpath(".//w:tc", namespaces=NS):
        set_prop(cell.find("w:tcPr", NS), "vAlign", val="center")
    page_cell = approval.findall("w:tr", NS)[5].findall("w:tc", NS)[3]
    page_p = page_cell.find("w:p", NS)
    for n in list(page_p):
        if n.tag != q("w", "pPr"):
            page_p.remove(n)
    E.SubElement(E.SubElement(page_p, q("w", "r")), q("w", "t")).text = "第 "
    field(page_p, "PAGE")
    E.SubElement(E.SubElement(page_p, q("w", "r")), q("w", "t")).text = " 页 共 "
    field(page_p, "NUMPAGES")
    E.SubElement(E.SubElement(page_p, q("w", "r")), q("w", "t")).text = " 页"
    company = approval.findall("w:tr", NS)[2].findall("w:tc", NS)[3]
    logo_data = package.entries.get("word/media/image1.png")
    if logo_data:
        with tempfile.TemporaryDirectory() as temp:
            logo = Path(temp) / "logo.png"
            logo.write_bytes(logo_data)
            rid, media_name = package.add_image(logo)
        image_p = p("")
        set_prop(image_p.find("w:pPr", NS), "jc", val="center")
        run = E.SubElement(image_p, q("w", "r"))
        run.append(_drawing(package, rid, media_name, 1_500_000, 500_000))
        company.insert(1, image_p)
    # The title block belongs to the first-page footer so its complete merged
    # grid stays together at the bottom as titles and signature names wrap.
    first_paragraph = approval.find("w:tr/w:tc/w:p", NS)
    start = E.Element(q("w", "bookmarkStart"))
    start.set(q("w", "id"), "9003")
    start.set(q("w", "name"), "CabinetTitleBlock")
    end = E.Element(q("w", "bookmarkEnd"))
    end.set(q("w", "id"), "9003")
    first_paragraph.insert(1, start)
    first_paragraph.append(end)
    approval_rows = approval.findall("w:tr", NS)
    for index, row in enumerate(approval_rows):
        row_props = row.find("w:trPr", NS)
        if row_props is None:
            row_props = E.Element(q("w", "trPr"))
            row.insert(0, row_props)
        set_prop(row_props, "cantSplit")
        for paragraph in row.findall("w:tc/w:p", NS):
            set_prop(
                paragraph.find("w:pPr", NS),
                "keepNext",
                val=0 if index == len(approval_rows) - 1 else 1,
            )
    package.body.append(p("{{SUMMARY_PAGE}}"))
    package.body.append(p("{{BODY_CONTENT}}"))
    package.body.append(p("{{PROTOTYPES_BEGIN}}"))
    for key, level in [("h1", 1), ("h2", 2), ("h3", 3), ("h4", 4)]:
        package.body.append(
            clean_paragraph(
                body_proto,
                "{{PROTO:" + key + "}}",
                size=24,
                bold=False,
                heading=level,
            )
        )
    for key in ["body", "indent", "list", "note"]:
        para = clean_paragraph(body_proto, "{{PROTO:" + key + "}}", size=21)
        set_prop(
            para.find("w:pPr", NS),
            "spacing",
            before=0,
            after=0,
            line=360,
            lineRule="auto",
        )
        if key in {"body", "note"}:
            set_prop(para.find("w:pPr", NS), "ind", left=840, firstLine=0)
        if key == "indent":
            set_prop(para.find("w:pPr", NS), "ind", left=1260, firstLine=0)
        package.body.append(para)
    for row in list(table_proto.findall("w:tr", NS))[2:]:
        table_proto.remove(row)
    package.body.append(table_proto)
    package.body.append(p("{{PROTOTYPES_END}}"))
    for n in section.findall("w:headerReference", NS) + section.findall(
        "w:footerReference", NS
    ):
        section.remove(n)
    # Reuse the first footer relationship, replacing its case text with live fields.
    footer_rel = next(
        rel for rel in package.relationships if rel.get("Type", "").endswith("/footer")
    )
    footer_path = "word/" + footer_rel.get("Target")
    footer = package.part(footer_path)
    for n in list(footer):
        footer.remove(n)
    fp = p("第 ")
    set_prop(fp.find("w:pPr", NS), "jc", val="center")
    field(fp, "PAGE")
    E.SubElement(E.SubElement(fp, q("w", "r")), q("w", "t")).text = " 页 共 "
    field(fp, "NUMPAGES")
    E.SubElement(E.SubElement(fp, q("w", "r")), q("w", "t")).text = " 页"
    footer.append(fp)
    fr = E.Element(q("w", "footerReference"))
    fr.set(q("w", "type"), "default")
    fr.set(q("r", "id"), footer_rel.get("Id"))
    section.insert(0, fr)
    first_footer_rel = next(
        rel
        for rel in package.relationships
        if rel.get("Type", "").endswith("/footer") and rel is not footer_rel
    )
    first_footer_path = "word/" + first_footer_rel.get("Target")
    first_footer = package.part(first_footer_path)
    for node in list(first_footer):
        first_footer.remove(node)
    first_footer.append(approval)
    filename_paragraph = p("")
    set_prop(
        filename_paragraph.find("w:pPr", NS),
        "spacing",
        before=0,
        after=0,
        line=225,
        lineRule="exact",
    )
    E.SubElement(filename_paragraph, q("w", "r")).append(filename_label)
    first_footer.append(filename_paragraph)
    first_reference = E.Element(q("w", "footerReference"))
    first_reference.set(q("w", "type"), "first")
    first_reference.set(q("r", "id"), first_footer_rel.get("Id"))
    section.insert(1, first_reference)
    if section.find("w:titlePg", NS) is None:
        cols = section.find("w:cols", NS)
        title_page = E.Element(q("w", "titlePg"))
        cols.addnext(title_page)
    if logo_data:
        # Images in a footer have their own relationship scope. Transfer only
        # this relationship; the media bytes remain shared in the package.
        logo_rel = next(rel for rel in package.relationships if rel.get("Id") == rid)
        footer_rels = E.Element(q("pr", "Relationships"), nsmap={None: NS["pr"]})
        footer_rels.append(copy.deepcopy(logo_rel))
        rel_path = "word/_rels/" + Path(first_footer_path).name + ".rels"
        package.entries[rel_path] = E.tostring(
            footer_rels, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        package.relationships.remove(logo_rel)
    header_rel = next(
        rel for rel in package.relationships if rel.get("Type", "").endswith("/header")
    )
    header = package.part("word/" + header_rel.get("Target"))
    for child in list(header):
        header.remove(child)
    frame_paragraph = p("")
    set_prop(
        frame_paragraph.find("w:pPr", NS),
        "spacing",
        before=0,
        after=0,
        line=20,
        lineRule="exact",
    )
    run = E.SubElement(frame_paragraph, q("w", "r"))
    pict = E.SubElement(run, q("w", "pict"))
    vns = "urn:schemas-microsoft-com:vml"
    ons = "urn:schemas-microsoft-com:office:office"
    w10ns = "urn:schemas-microsoft-com:office:word"
    frame = E.SubElement(
        pict, "{" + vns + "}rect", nsmap={"v": vns, "o": ons, "w10": w10ns}
    )
    frame.set("id", "CabinetPageFrame")
    width = int(size.get(q("w", "w"))) / 20 - frame_left - frame_right
    height = int(size.get(q("w", "h"))) / 20 - frame_top - frame_bottom
    frame.set(
        "style",
        f"position:absolute;margin-left:{frame_left:.2f}pt;margin-top:{frame_top:.2f}pt;width:{width:.2f}pt;height:{height:.2f}pt;z-index:-251654144;mso-position-horizontal-relative:page;mso-position-vertical-relative:page",
    )
    frame.set("filled", "f")
    frame.set("strokecolor", "#000000")
    frame.set("strokeweight", "1.5pt")
    frame.set("{" + ons + "}allowincell", "f")
    frame.set("{" + ons + "}allowoverlap", "t")
    wrap = E.SubElement(frame, "{" + w10ns + "}wrap")
    wrap.set("type", "none")
    wrap.set("anchorx", "page")
    wrap.set("anchory", "page")
    header.append(frame_paragraph)
    E.SubElement(frame_paragraph, q("w", "r")).append(copyright_label)
    for kind in ("default", "first", "even"):
        reference = E.Element(q("w", "headerReference"))
        reference.set(q("w", "type"), kind)
        reference.set(q("r", "id"), header_rel.get("Id"))
        section.insert(0, reference)
    package.body.append(section)
    numbering = package.part("word/numbering.xml")
    for aid, styles in [
        (
            "9100",
            [
                (
                    "decimal",
                    "%1."
                    if level == 0
                    else ".".join("%" + str(i + 1) for i in range(level + 1)),
                )
                for level in range(4)
            ],
        ),
        ("9201", [("decimal", "%1）"), ("lowerLetter", "%2)")]),
        ("9202", [("decimalEnclosedCircle", "%1"), ("lowerLetter", "%2)")]),
    ]:
        abstract = E.Element(q("w", "abstractNum"))
        abstract.set(q("w", "abstractNumId"), aid)
        for level, (fmt, text) in enumerate(styles):
            lvl = E.SubElement(abstract, q("w", "lvl"))
            lvl.set(q("w", "ilvl"), str(level))
            set_prop(lvl, "start", val=1)
            set_prop(lvl, "numFmt", val=fmt)
            set_prop(lvl, "lvlText", val=text)
            set_prop(lvl, "lvlJc", val="left")
            pp = E.SubElement(lvl, q("w", "pPr"))
            if aid == "9100":
                # All heading numbers share the same inset from the frame;
                # longer hierarchical numbers get wider hanging-indent slots.
                text_left = 630 if level == 0 else 690 + level * 240
                tabs = set_prop(pp, "tabs")
                set_prop(tabs, "tab", val="num", pos=text_left)
                set_prop(pp, "ind", left=text_left, hanging=text_left - 210)
                suffix = E.Element(q("w", "suff"))
                suffix.set(q("w", "val"), "tab")
                lvl.find("w:lvlText", NS).addprevious(suffix)
            else:
                # Four characters before the number; wrapped text aligns at the
                # tab stop, with a deeper position for circled sub-items.
                text_left = 1260 if aid == "9201" else 1680
                if level:
                    text_left += 420
                set_prop(pp, "ind", left=text_left, hanging=420)
                tabs = set_prop(pp, "tabs")
                set_prop(tabs, "tab", val="num", pos=text_left)
                pp.find("w:ind", NS).addprevious(tabs)
                suffix = E.Element(q("w", "suff"))
                suffix.set(q("w", "val"), "tab")
                lvl.find("w:lvlText", NS).addprevious(suffix)
            rp = E.SubElement(lvl, q("w", "rPr"))
            set_prop(
                rp,
                "rFonts",
                ascii="Times New Roman" if aid == "9100" else "宋体",
                eastAsia="宋体",
            )
            if aid == "9100":
                set_prop(rp, "b", val=0)
                set_prop(rp, "bCs", val=0)
                set_prop(rp, "sz", val=24)
                set_prop(rp, "szCs", val=24)
        numbering.insert(0, abstract)
    num = E.SubElement(numbering, q("w", "num"))
    num.set(q("w", "numId"), "9100")
    set_prop(num, "abstractNumId", val="9100")
    # Remove source author/document properties from the distributable master.
    if "docProps/core.xml" in package.entries:
        core = package.part("docProps/core.xml")
        for node in list(core):
            core.remove(node)
    package.prune_orphan_media()
    out.mkdir(parents=True, exist_ok=True)
    master = out / "master.docx"
    package.save(master)
    manifest = {
        "template_key": "cabinet-test-plan",
        "version": "1",
        "manifest_version": "1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "fields": FIELDS,
        "heading_numbering": {
            "num_id": "9100",
            "ilvl_by_level": {1: 0, 2: 1, 3: 2, 4: 3},
        },
        "list_abstract_nums": {"decimal": "9201", "circle": "9202"},
        "floating_drawings": 0,
    }
    (out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(master)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=next((ROOT / "SOP_case/工商业柜测试方案").glob("*.docx")),
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "templates/cabinet-test-plan/v1"
    )
    args = parser.parse_args()
    build(args.source, args.out)
