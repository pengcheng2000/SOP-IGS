"""Work out each Excel row's 格式 / 内容格式 from the structure of the original case Word document.

The case Excel holds the values and wording (it wins), the case Word shows how every piece is laid out
(heading, list style, indented paragraph, note, table). Rows are matched to Word items by their normalized
text; what cannot be matched is reported so it can be decided by hand in `OVERRIDES`.
"""
from __future__ import annotations

import difflib
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.boost.input.workbook import SheetGrid

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
CONTENT_COLUMNS = range(2, 10)
PUNCTUATION = re.compile(r"[\s，。,.:：；;、（）()\[\]【】“”\"'·\-—★&＜<>＞>]")
FUZZY = 0.82


def normalize(text: str) -> str:
    return PUNCTUATION.sub("", text).lower()


@dataclass
class WordItem:
    kind: str  # 三级标题 四级标题 段落 缩进段落 注意 列表 字母列表 符号列表 子列表 表格
    text: str
    table_rows: list[list[str]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return normalize(self.text)


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _text(element: etree._Element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS)).strip()


def _list_formats(numbering: etree._Element) -> dict[str, tuple[str, str]]:
    """numId -> (level-0 format, level-1 format)."""
    result: dict[str, tuple[str, str]] = {}
    for num in numbering.findall("w:num", NS):
        abstract = num.xpath("string(w:abstractNumId/@w:val)", namespaces=NS)
        levels = numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{abstract}']/w:lvl", namespaces=NS)
        formats = {lvl.get(_q("ilvl")): lvl.xpath("string(w:numFmt/@w:val)", namespaces=NS) for lvl in levels}
        result[num.get(_q("numId"))] = (formats.get("0", ""), formats.get("1", ""))
    return result


LIST_KIND = {"decimal": "列表", "lowerLetter": "字母列表", "bullet": "符号列表", "upperLetter": "字母列表"}


def _classify_paragraph(paragraph: etree._Element, formats: dict[str, tuple[str, str]]) -> str:
    text = _text(paragraph)
    outline = paragraph.xpath("string(w:pPr/w:outlineLvl/@w:val)", namespaces=NS)
    if outline == "2":
        return "三级标题"
    if outline == "3":
        return "四级标题"
    num_id = paragraph.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS)
    ilvl = paragraph.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS) or "0"
    if num_id and num_id != "0":
        level0, _ = formats.get(num_id, ("", ""))
        if ilvl == "0":
            return LIST_KIND.get(level0, "列表")
        return "子列表"
    if text.startswith("★"):
        return "注意"
    left = paragraph.xpath("string(w:pPr/w:ind/@w:left)", namespaces=NS)
    return "缩进段落" if left and int(left) >= 420 else "段落"


def read_word_chapters(path: Path) -> list[list[WordItem]]:
    """Items of each 5.x chapter (5.1 excluded) in document order; tables are single items."""
    archive = zipfile.ZipFile(path)
    document = etree.fromstring(archive.read("word/document.xml"))
    formats = _list_formats(etree.fromstring(archive.read("word/numbering.xml")))
    chapters: list[list[WordItem]] = []
    started = False
    for element in document.find("w:body", NS):
        if element.tag == _q("p"):
            text = _text(element)
            outline = element.xpath("string(w:pPr/w:outlineLvl/@w:val)", namespaces=NS)
            if text == "调试项目" and outline == "0":
                started = True
                continue
            if not started:
                continue
            if outline == "0" or text == "版本修改记录":
                break
            if outline == "1":
                chapters.append([])
                continue
            if not text or not chapters:
                continue
            chapters[-1].append(WordItem(_classify_paragraph(element, formats), text))
        elif element.tag == _q("tbl") and started and chapters:
            rows = []
            for row in element.findall("w:tr", NS):
                cells = []
                for cell in row.findall("w:tc", NS):
                    value = _text(cell)
                    if value:
                        cells.append(value)
                rows.append(cells)
            chapters[-1].append(WordItem("表格", " ".join(c for r in rows for c in r), rows))
    return chapters[1:]  # the first chapter is 5.1, which lives in the master


def row_values(grid: SheetGrid, row: int, include_a: bool = False) -> list[str]:
    columns = range(1 if include_a else 2, 10)
    values = []
    for col in columns:
        if grid.is_covered(row, col):
            continue
        text = grid.text(row, col)
        if text:
            values.append(text)
    return values


def join_values(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    return f"{values[0]}：{'；'.join(values[1:])}"


@dataclass
class Annotation:
    j: str = ""
    note: str = ""


def find_table_regions(grid: SheetGrid, tables: list[WordItem]) -> dict[int, tuple[int, int, int]]:
    """Excel row ranges for the Word tables: {first_row: (last_row, header_rows, word_table_index)}."""
    regions: dict[int, tuple[int, int, int]] = {}
    cursor = 1
    header_by_first = {"测试部位": 2, "PCS编号": 3, "Important": 0, "设置": 0}
    for index, table in enumerate(tables):
        first_cells = [normalize(c) for c in table.table_rows[0]]
        first_key = "".join(first_cells)
        for row in range(cursor, grid.max_row + 1):
            texts = [normalize(t) for t in row_values(grid, row, include_a=True)]
            if texts and ("".join(texts) == first_key or (first_cells and texts[0] == first_cells[0] and len(texts) >= min(2, len(first_cells)))):
                last = row + len(table.table_rows) - 1
                regions[row] = (last, header_by_first.get(table.table_rows[0][0] if table.table_rows[0] else "", 1), index)
                cursor = last + 1
                break
    return regions


def derive(grid: SheetGrid, items: list[WordItem], overrides: dict[int, Annotation]) -> tuple[dict[int, Annotation], list[str]]:
    """Annotate every content row of one sheet; returns the annotations and report lines."""
    annotations: dict[int, Annotation] = {}
    report: list[str] = []
    tables = [item for item in items if item.kind == "表格"]
    regions = find_table_regions(grid, tables)
    table_rows: set[int] = set()
    for first, (last, headers, _) in regions.items():
        for offset, row in enumerate(range(first, last + 1)):
            annotations[row] = Annotation("表头" if offset < headers else "表格")
            table_rows.add(row)

    words = [item for item in items if item.kind != "表格"]
    word_keys = [item.key for item in words]
    h3_keys = {item.key for item in words if item.kind == "三级标题"}

    rows = [r for r in range(1, grid.max_row + 1) if r not in table_rows]
    row_texts: dict[int, str] = {}
    for row in rows:
        values = row_values(grid, row)
        a_text = "" if grid.is_covered(row, 1) else grid.text(row, 1)
        if not values and a_text and normalize(a_text) not in h3_keys:
            values = [a_text]  # content written in column A (the rule: a set 格式 makes A content)
        if values:
            row_texts[row] = join_values(values)
    content_rows = [r for r in rows if r in row_texts]
    keys = [normalize(row_texts[r]) for r in content_rows]

    matched: dict[int, int] = {}  # excel row -> word index
    matcher = difflib.SequenceMatcher(None, keys, word_keys, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matched[content_rows[block.a + offset]] = block.b + offset

    used = set(matched.values())
    # Multi-item rows: the first cell and the following cells match consecutive Word items
    # (for example 四级标题 + 列表 + 缩进段落); the last format takes all remaining cells joined.
    split: dict[int, list[int]] = {}
    for position, row in enumerate(content_rows):
        if row in matched:
            continue
        values = row_values(grid, row)
        if len(values) < 2:
            continue
        lo = max((matched[r] for r in content_rows[:position] if r in matched), default=-1) + 1
        found = None
        for roles in range(len(values), 1, -1):
            parts = values[: roles - 1] + ["；".join(values[roles - 1:])]
            for index in range(lo, len(words)):
                if index in used or words[index].kind == "三级标题":
                    continue
                if difflib.SequenceMatcher(None, normalize(parts[0]), words[index].key).ratio() < FUZZY:
                    continue
                chain = [index]
                for part in parts[1:]:
                    # Later parts may skip up to two Word items (the Word has lead-in lines such as 测试条件：).
                    candidates = [i for i in range(chain[-1] + 1, min(chain[-1] + 4, len(words)))
                                  if i not in used and words[i].kind != "三级标题"]
                    best = max(candidates, key=lambda i: difflib.SequenceMatcher(None, normalize(part), words[i].key).ratio(), default=None)
                    if best is None or difflib.SequenceMatcher(None, normalize(part), words[best].key).ratio() < 0.55:
                        break
                    chain.append(best)
                if len(chain) == roles:
                    found = chain
                    break
            if found:
                break
        if found:
            split[row] = found
            used.update(found)

    # Fuzzy pass: unmatched rows against unmatched Word items lying between their matched neighbours.
    for position, row in enumerate(content_rows):
        if row in matched or row in split:
            continue
        lo = max((matched[r] for r in content_rows[:position] if r in matched), default=-1) + 1
        hi = min((matched[r] for r in content_rows[position + 1:] if r in matched), default=len(words))
        best, best_ratio = None, 0.0
        for index in range(lo, hi):
            if index in used or words[index].kind in ("三级标题",):
                continue
            ratio = difflib.SequenceMatcher(None, keys[position], word_keys[index]).ratio()
            if ratio > best_ratio:
                best, best_ratio = index, ratio
        if best is not None and best_ratio >= FUZZY:
            matched[row] = best
            used.add(best)

    for row in content_rows:
        a_text = "" if grid.is_covered(row, 1) else grid.text(row, 1)
        if row in matched:
            word = words[matched[row]]
            if word.kind == "三级标题":
                continue
            annotations[row] = Annotation(word.kind)
        elif row in split:
            annotations[row] = Annotation("+".join(words[i].kind for i in split[row]))
        else:
            annotations[row] = Annotation("", "无法在原案例 Word 中找到对应内容（Excel 独有或措辞不同）")
            report.append(f"  unmatched row {row}: {row_texts[row][:60]}")
    # Heading-only rows (A text that is a Word 三级标题) need no marker; A text that is no heading in Word does.
    for row in rows:
        a_text = "" if grid.is_covered(row, 1) else grid.text(row, 1)
        if a_text and normalize(a_text) not in h3_keys and row not in row_texts:
            report.append(f"  A{row} not a Word heading and no content: {a_text[:50]}")

    for row, annotation in overrides.items():
        annotations[row] = annotation
    return annotations, report
