"""Derive the boost-integrated-unit master template from a case document.

Usage:
    python tools/build_boost_master.py --source <case.docx> --out templates/boost-integrated-unit/v1

The source document is project data and stays out of git (source.docx is ignored).
The script fails loudly when the source no longer has the expected structure.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

import yaml
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.boost.docx.ooxml import NS, DocxPackage, paragraph_text, q

MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

ANCHOR_CHAPTERS = "{{BOOST_CHAPTERS}}"
ANCHOR_REVISIONS = "{{REVISION_HISTORY}}"
PROTOTYPES_BEGIN = "{{PROTOTYPES_BEGIN}}"
PROTOTYPES_END = "{{PROTOTYPES_END}}"

HEADING_NUM_ID = "3"
HEADING_ABSTRACT_ID = "4"
LIST_ABSTRACT_IDS = {"decimal": "9001", "letter": "9002", "bullet": "9003"}

FIELDS = [
    {"key": "project_name", "label": "项目/站点名称", "required": True,
     "placeholder": "例如：某项目（某站点）"},
    {"key": "document_number", "label": "电子文件名", "column": "document_number", "required": True,
     "placeholder": "例如：201090149MTR（含后缀字母）"},
    {"key": "document_version", "label": "版本", "column": "document_version", "required": True},
    {"key": "title_subject", "label": "标题栏名称", "placeholder": "例如：CPS ESS-项目简称"},
    {"key": "document_code", "label": "编码"},
    {"key": "product_line", "label": "所属产品", "placeholder": "例如：CPS ESS"},
    {"key": "archive_month", "label": "归档年月", "type": "month"},
    {"key": "drafter", "label": "拟制"},
    {"key": "reviewer_1", "label": "审核 1"},
    {"key": "reviewer_2", "label": "审核 2"},
    {"key": "reviewer_3", "label": "审核 3"},
    {"key": "standardizer", "label": "标准化"},
    {"key": "approver", "label": "批准"},
    {"key": "project_references", "label": "项目参考文献", "multiline": True,
     "placeholder": "每行一条，只填项目专属文献，例如项目电气图、项目测试需求",
     "fixed_lines": []},  # filled with the lines already present in the master
]
FIXED_REFERENCES: list[str] = []


# Tokens whose original case text identifies a customer, project or person.
IDENTIFYING_TOKENS = {
    "project_name", "project_references", "title_subject", "document_number", "document_code",
    "drafter", "reviewer_1", "reviewer_2", "reviewer_3", "standardizer", "approver",
}
REPLACED: dict[str, set[str]] = {}


class StructureError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StructureError(message)


def num_props(paragraph: etree._Element) -> tuple[str, str]:
    return (
        paragraph.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS),
        paragraph.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS),
    )


def compact(value: str) -> str:
    return "".join(value.split())


def set_single_run_text(paragraph: etree._Element, value: str, keep_runs: int = 0) -> None:
    """Keep the first `keep_runs` runs, put `value` in the next run and drop the remaining runs."""
    runs = paragraph.xpath(".//w:r[w:t]", namespaces=NS)
    require(len(runs) > keep_runs, f"段落运行数不足：{paragraph_text(paragraph)}")
    original = "".join(text for run in runs[keep_runs:] for text in run.xpath("./w:t/text()", namespaces=NS)).strip()
    REPLACED.setdefault(value.strip("{}"), set()).add(original)
    target = runs[keep_runs]
    for text in target.findall("w:t", NS)[1:]:
        target.remove(text)
    node = target.find("w:t", NS)
    node.text = value
    node.attrib.pop("{http://www.w3.org/XML/1998/namespace}space", None)
    for run in runs[keep_runs + 1 :]:
        run.getparent().remove(run)


def plain_paragraph(prototype: etree._Element, value: str) -> etree._Element:
    paragraph = copy.deepcopy(prototype)
    for child in list(paragraph):
        if child.tag != q("w", "pPr"):
            paragraph.remove(child)
    run_props = prototype.find(".//w:r/w:rPr", NS)
    run = etree.SubElement(paragraph, q("w", "r"))
    if run_props is not None:
        run.append(copy.deepcopy(run_props))
    etree.SubElement(run, q("w", "t")).text = value
    return paragraph


def find_body_paragraph(body: list[etree._Element], predicate, description: str) -> int:
    for index, element in enumerate(body):
        if element.tag == q("w", "p") and predicate(element):
            return index
    raise StructureError(f"找不到{description}")


def tokenize_title_and_scope(body: list[etree._Element]) -> None:
    project_name = paragraph_text(body[0]).removesuffix("升压一体机测试需求")
    require(bool(project_name) and project_name != paragraph_text(body[0]), "标题应为「<项目>升压一体机测试需求」")
    REPLACED.setdefault("project_name", set()).add(project_name)
    replaced = 0
    for paragraph in body[:4]:
        for run in paragraph.xpath(".//w:r[w:t]", namespaces=NS):
            if "".join(run.xpath("./w:t/text()", namespaces=NS)) == project_name:
                run.find("w:t", NS).text = "{{project_name}}"
                for extra in run.findall("w:t", NS)[1:]:
                    run.remove(extra)
                replaced += 1
    require(replaced == 2, f"标题与适用范围中的项目名称应出现 2 次，实际 {replaced} 次")


def tokenize_references(package: DocxPackage) -> None:
    body = list(package.body)
    start = find_body_paragraph(body, lambda p: paragraph_text(p) == "参考文献", "参考文献章节")
    end = find_body_paragraph(body, lambda p: paragraph_text(p) == "调试环境", "调试环境章节")
    project_lines = [p for p in body[start + 1 : end] if p.tag == q("w", "p") and not paragraph_text(p).startswith("GB")]
    require(bool(project_lines), "参考文献中没有项目专属条目")
    FIXED_REFERENCES.extend(paragraph_text(p) for p in body[start + 1 : end] if p.tag == q("w", "p") and paragraph_text(p).startswith("GB"))
    REPLACED.setdefault("project_references", set()).update(paragraph_text(p) for p in project_lines)
    set_single_run_text(project_lines[0], "{{project_references}}")
    for paragraph in project_lines[1:]:
        package.body.remove(paragraph)


def numpages_field_runs(template_run: etree._Element) -> list[etree._Element]:
    run_props = template_run.find("w:rPr", NS)

    def run_with(child: etree._Element) -> etree._Element:
        run = etree.Element(q("w", "r"))
        if run_props is not None:
            run.append(copy.deepcopy(run_props))
        run.append(child)
        return run

    begin = etree.Element(q("w", "fldChar")); begin.set(q("w", "fldCharType"), "begin")
    instr = etree.Element(q("w", "instrText")); instr.text = " NUMPAGES "
    instr.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    separate = etree.Element(q("w", "fldChar")); separate.set(q("w", "fldCharType"), "separate")
    value = etree.Element(q("w", "t")); value.text = "1"
    end = etree.Element(q("w", "fldChar")); end.set(q("w", "fldCharType"), "end")
    return [run_with(node) for node in (begin, instr, separate, value, end)]


def tokenize_title_block(document: etree._Element) -> int:
    boxes = document.xpath("//w:txbxContent", namespaces=NS)
    tokenized = 0
    for box in boxes:
        paragraphs = box.xpath(".//w:p", namespaces=NS)
        texts = [paragraph_text(p) for p in paragraphs]
        if any(compact(text).startswith("电子文件名") for text in texts):
            index = next(i for i, text in enumerate(texts) if compact(text).startswith("电子文件名"))
            paragraph = paragraphs[index]
            set_single_run_text(paragraph, "{{document_number}}", keep_runs=1)
            label = paragraph.xpath(".//w:r/w:t", namespaces=NS)[0]
            label.text = "电子文件名： "
            label.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            tokenized += 1
            continue
        require(any(compact(text) == "拟制" for text in texts), "标题栏文本框结构异常")

        def after(label: str, occurrence: int = 1, texts=texts, paragraphs=paragraphs) -> etree._Element:
            seen = 0
            for i, text in enumerate(texts):
                if compact(text) == label:
                    seen += 1
                    if seen == occurrence:
                        following = next((j for j in range(i + 1, len(texts)) if texts[j]), None)
                        require(following is not None, f"标题栏缺少「{label}」的取值")
                        return paragraphs[following]
            raise StructureError(f"标题栏缺少标签「{label}」")

        version_index = next((i for i, text in enumerate(texts) if text), None)
        require(version_index is not None, "标题栏缺少版本")
        targets = {
            "{{document_version}}": paragraphs[version_index],
            "{{archive_month}}": next(p for p, t in zip(paragraphs, texts) if compact(t)[:2] == "20" and "-" in t),
            "{{drafter}}": after("拟制"),
            "{{reviewer_1}}": after("审核", 1),
            "{{reviewer_2}}": after("审核", 2),
            "{{reviewer_3}}": after("审核", 3),
            "{{standardizer}}": after("标准化"),
            "{{approver}}": after("批准"),
            "{{product_line}}": after("所属产品"),
            "{{document_code}}": next(p for p, t in zip(paragraphs, texts) if compact(t).replace(".", "").isdigit() and "." in t),
            "{{title_subject}}": next(p for p, t in zip(paragraphs, texts) if "-" in t and compact(t)[:3].isalpha() and not compact(t)[:2].isdigit()),
        }
        for token, paragraph in targets.items():
            set_single_run_text(paragraph, token)
        page = next((p for p, t in zip(paragraphs, texts) if "共" in t and "页" in t), None)
        require(page is not None, "标题栏缺少页码")
        total = next((r for r in page.xpath(".//w:r[w:t]", namespaces=NS) if "".join(r.xpath("./w:t/text()", namespaces=NS)).strip().isdigit()
                      and not r.getprevious().xpath("./w:fldChar[@w:fldCharType='separate']", namespaces=NS)), None)
        require(total is not None, "标题栏缺少总页数")
        for run in reversed(numpages_field_runs(total)):
            total.addnext(run)
        total.getparent().remove(total)
        tokenized += 1
    return tokenized


FILENAME_BOX_TOP_PT = 515.5  # measured in Word on the case: anchor paragraph at 414.6 pt + offset 100.9 pt


def pin_filename_box(document: etree._Element) -> None:
    """Anchor the vertical file-name text box to the page instead of the paragraph before the table of tools.

    The case positions it relative to that paragraph, so longer references above it push the box down until its
    label leaves the page. Both the DrawingML box and its VML fallback get the same absolute position.
    """
    ns = {**NS, "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006", "v": "urn:schemas-microsoft-com:vml"}
    pinned = 0
    for anchor in document.xpath("//wp:anchor", namespaces=ns):
        if "电子文件名" not in "".join(anchor.xpath(".//w:t/text()", namespaces=ns)):
            continue
        position = anchor.find("wp:positionV", ns)
        position.set("relativeFrom", "page")
        for child in list(position):
            position.remove(child)
        offset = etree.SubElement(position, q("wp", "posOffset"))
        offset.text = str(round(FILENAME_BOX_TOP_PT * 12700))
        pinned += 1
    for shape in document.xpath("//mc:Fallback//v:shape", namespaces=ns):
        if "电子文件名" not in "".join(shape.xpath(".//w:t/text()", namespaces=ns)):
            continue
        style = dict(item.split(":", 1) for item in shape.get("style").split(";") if ":" in item)
        style["margin-top"] = f"{FILENAME_BOX_TOP_PT}pt"
        style["mso-position-vertical-relative"] = "page"
        shape.set("style", ";".join(f"{key}:{value}" for key, value in style.items()) + ";")
        pinned += 1
    require(pinned == 2, f"找不到竖排电子文件名文本框（应有 2 份，实际 {pinned}）")


def build_prototypes(body: list[etree._Element]) -> list[etree._Element]:
    def by_text(predicate, description: str) -> etree._Element:
        return body[find_body_paragraph(body, predicate, description)]

    h3 = by_text(lambda p: num_props(p)[1] == "2" and paragraph_text(p) == "集装箱尺寸、标签检查", "三级标题样板")
    h4 = by_text(lambda p: num_props(p)[1] == "3", "四级标题样板")
    # The case document mixes several body layouts; the dominant one (1.5 line spacing, two-character first-line
    # indent) is the canonical body text, and the indented layout under list items is its own paragraph kind.
    text_body = by_text(lambda p: paragraph_text(p).startswith("箱门、柜门的开闭应灵活"), "正文样板")
    indent = by_text(lambda p: paragraph_text(p).startswith("耐压测试电压AC 2000V") and not num_props(p)[0], "缩进段落样板")
    list_item = by_text(lambda p: num_props(p)[0] and num_props(p)[1] == "0" and paragraph_text(p).startswith("按照"), "列表样板")
    note = by_text(lambda p: paragraph_text(p).startswith("★"), "注意事项样板")
    table = next((t for t in body if t.tag == q("w", "tbl") and paragraph_text(t).startswith("测试部位要求")), None)
    require(table is not None, "找不到表格样板")

    prototypes = []
    for name, source in (("h3", h3), ("h4", h4), ("body", text_body), ("indent", indent), ("list", list_item), ("note", note)):
        prototypes.append(plain_paragraph(source, f"{{{{PROTO:{name}}}}}"))
    rows = table.findall("w:tr", NS)
    require(len(rows) >= 3, "表格样板行数不足")
    proto_table = etree.Element(q("w", "tbl"))
    proto_table.append(copy.deepcopy(table.find("w:tblPr", NS)))
    grid = etree.SubElement(proto_table, q("w", "tblGrid"))
    etree.SubElement(grid, q("w", "gridCol")).set(q("w", "w"), "9360")
    for row, cell_index, token in ((rows[1], 1, "{{PROTO:table_header}}"), (rows[2], 0, "{{PROTO:table_body}}")):
        new_row = copy.deepcopy(row)
        cells = new_row.findall("w:tc", NS)
        keep = cells[cell_index]
        for cell in cells:
            if cell is not keep:
                new_row.remove(cell)
        for paragraph in keep.findall("w:p", NS)[1:]:
            keep.remove(paragraph)
        first = keep.find("w:p", NS)
        keep.replace(first, plain_paragraph(first, token))
        proto_table.append(new_row)
    prototypes.append(proto_table)
    return prototypes


def rebuild_chapter_five(package: DocxPackage) -> None:
    body = list(package.body)
    root = find_body_paragraph(body, lambda p: num_props(p) == ("2", "0") and paragraph_text(p) == "调试项目", "第 5 章「调试项目」")
    summary = body[root + 1]
    require(summary.tag == q("w", "tbl") and "调试项目" in paragraph_text(summary.find("w:tr", NS)), "找不到调试项目汇总表")
    for row in summary.findall("w:tr", NS)[2:]:
        summary.remove(row)
    fixed = body[root + 2]
    require(num_props(fixed) == (HEADING_NUM_ID, "1") and paragraph_text(fixed) == "调试中的注意事项", "5.1 标题结构异常")
    first_generated = next(
        (i for i in range(root + 3, len(body)) if body[i].tag == q("w", "p") and num_props(body[i]) == (HEADING_NUM_ID, "1")), None
    )
    require(first_generated is not None, "找不到 5.2 章节")
    revisions = find_body_paragraph(body, lambda p: num_props(p)[1] == "0" and paragraph_text(p) == "版本修改记录", "版本修改记录章节")
    require(revisions > first_generated, "版本修改记录位置异常")

    prototypes = build_prototypes(body)
    body_proto = body[root + 3]
    for element in body[first_generated:revisions]:
        package.body.remove(element)
    insert_at = package.body.index(body[revisions])
    marker_elements = [plain_paragraph(body_proto, ANCHOR_CHAPTERS), plain_paragraph(body_proto, PROTOTYPES_BEGIN),
                       *prototypes, plain_paragraph(body_proto, PROTOTYPES_END)]
    for offset, element in enumerate(marker_elements):
        package.body.insert(insert_at + offset, element)

    revision_body = [element for element in list(package.body)[package.body.index(body[revisions]) + 1 :] if element.tag == q("w", "p")]
    require(bool(revision_body), "版本修改记录缺少正文")
    set_single_run_text(revision_body[0], ANCHOR_REVISIONS)
    for paragraph in revision_body[1:]:
        package.body.remove(paragraph)


def abstract_num(abstract_id: str, levels: list[tuple[str, str, int, int, str | None]]) -> etree._Element:
    node = etree.Element(q("w", "abstractNum"))
    node.set(q("w", "abstractNumId"), abstract_id)
    etree.SubElement(node, q("w", "multiLevelType")).set(q("w", "val"), "hybridMultilevel")
    for level, (fmt, text, left, hanging, font) in enumerate(levels):
        lvl = etree.SubElement(node, q("w", "lvl"))
        lvl.set(q("w", "ilvl"), str(level))
        etree.SubElement(lvl, q("w", "start")).set(q("w", "val"), "1")
        etree.SubElement(lvl, q("w", "numFmt")).set(q("w", "val"), fmt)
        etree.SubElement(lvl, q("w", "lvlText")).set(q("w", "val"), text)
        etree.SubElement(lvl, q("w", "lvlJc")).set(q("w", "val"), "left")
        ppr = etree.SubElement(lvl, q("w", "pPr"))
        ind = etree.SubElement(ppr, q("w", "ind"))
        ind.set(q("w", "left"), str(left)); ind.set(q("w", "hanging"), str(hanging))
        if font:
            rpr = etree.SubElement(lvl, q("w", "rPr"))
            fonts = etree.SubElement(rpr, q("w", "rFonts"))
            for attr in ("ascii", "hAnsi", "hint"):
                fonts.set(q("w", attr), font if attr != "hint" else "default")
    return node


def update_numbering(package: DocxPackage) -> None:
    numbering = package.part("word/numbering.xml")
    headings = numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{HEADING_ABSTRACT_ID}']", namespaces=NS)
    require(len(headings) == 1, "找不到标题编号定义")
    # The case gives every chapter its own numbering whose level 2/3 numbers are set in SimSun with its own
    # indents; the shared definition only had the default font, which made heading numbers look heavier.
    donors = {"2": ("18", "5.%2.%3."), "3": ("26", "5.%2.%3.%4.")}
    for ilvl, (donor_id, text) in donors.items():
        target = headings[0].xpath(f"./w:lvl[@w:ilvl='{ilvl}']", namespaces=NS)
        donor = numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{donor_id}']/w:lvl[@w:ilvl='{ilvl}']", namespaces=NS)
        require(len(target) == 1 and len(donor) == 1, f"标题编号缺少第 {ilvl} 级")
        replacement = copy.deepcopy(donor[0])
        replacement.find("w:lvlText", NS).set(q("w", "val"), text)
        headings[0].replace(target[0], replacement)
    mapped = numbering.xpath(f"./w:num[@w:numId='{HEADING_NUM_ID}']/w:abstractNumId/@w:val", namespaces=NS)
    require(mapped == [HEADING_ABSTRACT_ID], "标题编号实例与定义不匹配")
    for abstract_id in LIST_ABSTRACT_IDS.values():
        for existing in numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{abstract_id}']", namespaces=NS):
            numbering.remove(existing)
    definitions = [
        abstract_num(LIST_ABSTRACT_IDS["decimal"], [("decimal", "%1)", 845, 425, None), ("lowerLetter", "%2)", 1265, 420, None)]),
        abstract_num(LIST_ABSTRACT_IDS["letter"], [("lowerLetter", "%1.", 1265, 425, None), ("lowerRoman", "%2.", 1685, 420, None)]),
        abstract_num(LIST_ABSTRACT_IDS["bullet"], [("bullet", "", 948, 420, "Wingdings"), ("bullet", "", 1368, 420, "Wingdings")]),
    ]
    last_abstract = numbering.xpath("./w:abstractNum[last()]", namespaces=NS)[0]
    for definition in reversed(definitions):
        last_abstract.addnext(definition)


def scrub_properties(package: DocxPackage) -> None:
    core_name = "docProps/core.xml"
    if core_name not in package.entries:
        return
    core = package.part(core_name)
    for node in core.iter():
        if etree.QName(node).localname in {"creator", "lastModifiedBy", "title", "subject", "description", "keywords"}:
            node.text = ""


def check_sanitized(path: Path) -> None:
    sensitive = {value for token in IDENTIFYING_TOKENS for value in REPLACED.get(token, ()) if len(compact(value)) >= 2}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            text = compact("".join(etree.fromstring(archive.read(name)).itertext()))
            for value in sensitive:
                require(compact(value) not in text, f"{name} 仍包含项目信息（{len(value)} 个字符的原文）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "templates" / "boost-integrated-unit" / "v1")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    source_copy = args.out / "source.docx"
    if args.source.resolve() != source_copy.resolve():
        shutil.copyfile(args.source, source_copy)
    package = DocxPackage(source_copy)

    tokenize_title_and_scope(list(package.body))
    tokenize_references(package)
    require(tokenize_title_block(package.document) == 4, "标题栏文本框应有 4 份（含兼容副本）")
    pin_filename_box(package.document)
    rebuild_chapter_five(package)
    update_numbering(package)
    scrub_properties(package)
    # The case document repeats drawing ids; generated drawings must start from unique ones.
    for index, node in enumerate(package.document.xpath("//wp:docPr", namespaces=NS), start=1):
        node.set("id", str(index))
    package.prune_orphan_media()

    master = args.out / "master.docx"
    package.save(master)
    check_sanitized(master)

    anchors = len(package.document.xpath("//wp:anchor", namespaces=NS))
    manifest = {
        "template_key": "boost-integrated-unit",
        "version": "1",
        "manifest_version": "1",
        "source_sha256": hashlib.sha256(source_copy.read_bytes()).hexdigest(),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "anchors": {
            "chapters": ANCHOR_CHAPTERS,
            "revision_history": ANCHOR_REVISIONS,
            "prototypes_begin": PROTOTYPES_BEGIN,
            "prototypes_end": PROTOTYPES_END,
        },
        "chapter_root": {"title": "调试项目", "number": "5", "fixed_sections": ["调试中的注意事项"]},
        "heading_numbering": {"num_id": HEADING_NUM_ID, "ilvl_by_level": {2: 1, 3: 2, 4: 3}},
        "list_abstract_nums": LIST_ABSTRACT_IDS,
        "summary_table": {"header_contains": "调试项目", "preserve_rows": 2},
        "floating_drawings": anchors,
        "fields": [
            {**field, "fixed_lines": list(FIXED_REFERENCES)} if "fixed_lines" in field else field for field in FIELDS
        ],
        "input": {"revision_sheet": "版本修改记录", "ignored_sheets": ["填写说明"]},
    }
    (args.out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"master.docx sha256={manifest['master_sha256']} floating_drawings={anchors}")


if __name__ == "__main__":
    main()
