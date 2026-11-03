"""Explicit cabinet-plan workbook contract. No runtime inference from colours/fonts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from ..document_common.model import (
    ERROR,
    WARNING,
    Chapter,
    DocumentModel,
    Heading,
    Image,
    ImageRef,
    Issue,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
    _item_to_dict,
)
from ..document_common.workbook import SheetGrid, SheetImage, WorkbookError, coord, read_workbook
from ..services.image_pipeline import process_image

PARSER_VERSION = "cabinet-plan-v1"
FIELDS = (
    "document_title",
    "scope_text",
    "document_code",
    "document_version",
    "archive_month",
    "product_line",
    "drafter",
    "reviewer_1",
    "reviewer_2",
    "reviewer_3",
    "standardizer",
    "approver",
)
FORMATS = {
    "一级标题",
    "二级标题",
    "三级标题",
    "四级标题",
    "段落",
    "缩进段落",
    "列表",
    "子列表",
    "注意",
    "表头",
    "表格",
    "图片",
}
IGNORED = {"填写说明", "内容核对", "首页", "目录"}
HEADING_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*(?:[、\s]+|\.(?!\d))")
LIST_PREFIX = re.compile(r"^\s*(?:\d+[)）.]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*")


@dataclass(frozen=True)
class ParseResult:
    document: DocumentModel | None
    issues: tuple[Issue, ...]

    @property
    def valid(self) -> bool:
        return self.document is not None and not any(i.severity == ERROR for i in self.issues)

    def summary(self) -> dict:
        if self.document is None:
            return {}
        return {
            **self.document.summary(),
            "field_count": sum(bool(v["value"]) for v in self.document.extra["fields"].values()),
        }


def parse_workbook(
    path: Path,
    image_dir: Path,
    *,
    max_image_bytes=30 * 1024 * 1024,
    max_image_pixels=100_000_000,
    max_images=150,
    **_unused,
) -> ParseResult:
    try:
        grids, issues = read_workbook(path)
    except WorkbookError as exc:
        return ParseResult(None, (Issue(ERROR, exc.code, str(exc)),))
    issues = list(issues)
    by_name = {g.name: g for g in grids}
    book = load_workbook(path, data_only=False)

    def named(key: str):
        defined = book.defined_names.get("sop_" + key)
        if defined is None:
            issues.append(
                Issue(ERROR, "MISSING_NAMED_RANGE", f"缺少命名区域 sop_{key}，请使用标准模板")
            )
            return None
        try:
            destinations = list(defined.destinations)
            if len(destinations) != 1:
                raise ValueError()
            sheet, area = destinations[0]
            bounds = range_boundaries(area)
            if sheet not in by_name or any(v is None for v in bounds):
                raise ValueError()
            return by_name[sheet], bounds
        except (ValueError, TypeError, KeyError, AttributeError):
            issues.append(
                Issue(ERROR, "INVALID_NAMED_RANGE", f"命名区域 sop_{key} 无效，请恢复标准模板绑定")
            )
            return None

    version = named("template_version")
    if version is None or version[0].text(version[1][1], version[1][0]) != PARSER_VERSION:
        book.close()
        return ParseResult(
            None,
            (
                Issue(
                    ERROR,
                    "UNSUPPORTED_TEMPLATE",
                    "请下载工商业柜测试方案标准模板，原始未标注表格无法可靠识别标题与表格",
                ),
            ),
        )

    fields = {}
    for key in FIELDS:
        found = named(key)
        if found is None:
            continue
        grid, (c, r, _, _) = found
        value = grid.text(r, c)
        if key == "scope_text":
            value = re.sub(r"^\s*1[.、]?\s*适用范围\s*", "", value).strip()
        if key == "archive_month" and value:
            match = re.fullmatch(r"(\d{4})[-年/](\d{1,2})(?:月|(?:-\d{1,2}).*)?", value)
            if match:
                value = f"{match[1]}-{int(match[2]):02d}"
        fields[key] = {"value": value, "source": f"{grid.name}!{coord(r, c)}"}

    image_count = 0

    def store_image(image: SheetImage) -> ImageRef:
        nonlocal image_count
        image_count += 1
        if image_count > max_images:
            raise WorkbookError("TOO_MANY_IMAGES", "正文图片数量超过限制")
        processed = process_image(
            image.data, max_bytes=max_image_bytes, max_pixels=max_image_pixels
        )
        image_dir.mkdir(parents=True, exist_ok=True)
        target = image_dir / f"{image_count:03d}{processed.output_extension}"
        target.write_bytes(processed.data)
        return ImageRef(
            f"img{image_count:03d}",
            str(target.resolve()),
            processed.sha256,
            image.display_w or processed.processed_width,
            image.display_h or processed.processed_height,
        )

    def make_table(grid: SheetGrid, start: int, end: int, headers: int, bounds=None):
        if bounds:
            left, right = bounds
        else:
            cols = set()
            for row in range(start, end + 1):
                for col in range(1, 15):
                    if grid.text(row, col):
                        merge = grid.merge_at(row, col)
                        cols.update(range(col, (merge[3] if merge else col) + 1))
            cols.update(
                image.col
                for image in grid.images
                if start <= image.row <= end and 1 <= image.col <= 14
            )
            if not cols:
                issues.append(
                    Issue(ERROR, "EMPTY_TABLE", "表格没有内容", grid.name, coord(start, 15))
                )
                return None
            left, right = min(cols), max(cols)
        rows = []
        kept = []
        marker = None
        for r in range(start, end + 1):
            values = [grid.text(r, c) for c in range(left, right + 1)]
            if "以下空白" in values:
                marker = r
                continue
            covered = any(m[0] < r <= m[2] and m[1] >= left and m[3] <= right for m in grid.merges)
            has_image = any(i.row == r and left <= i.col <= right for i in grid.images)
            if any(values) or covered or has_image or r < start + headers:
                if marker is not None:
                    issues.append(
                        Issue(
                            ERROR,
                            "CONTENT_AFTER_BLANK_MARKER",
                            "以下空白之后仍有数据，请将标记移至数据末尾",
                            grid.name,
                            coord(r, left),
                        )
                    )
                kept.append(r)
        for r in kept:
            cells = []
            c = left
            while c <= right:
                merge = grid.merge_at(r, c)
                if merge and (merge[0], merge[1]) != (r, c):
                    c += 1
                    continue
                span = 1
                row_span = 1
                if merge:
                    if merge[0] < start or merge[2] > end or merge[1] < left or merge[3] > right:
                        issues.append(
                            Issue(
                                ERROR,
                                "MERGE_CROSSES_TABLE",
                                "合并单元格跨越表格边界",
                                grid.name,
                                coord(r, c),
                            )
                        )
                    span = min(merge[3], right) - c + 1
                    row_span = sum(r <= k <= merge[2] for k in kept)
                refs = []
                for img in grid.images:
                    m = grid.merge_at(img.row, img.col)
                    anchor = (m[0], m[1]) if m else (img.row, img.col)
                    if anchor == (r, c):
                        refs.append(store_image(img))
                cells.append(
                    TableCell(
                        grid.text(r, c).replace("£是£否", "□是 □否"),
                        c - left,
                        span,
                        row_span,
                        tuple(refs),
                    )
                )
                c += span
            rows.append(tuple(cells))
        if marker is not None:
            rows.append((TableCell("以下空白", 0, right - left + 1),))
        weights = [1.0 for _ in range(left, right + 1)]
        for cells in rows:
            for cell in cells:
                if cell.text == "以下空白":
                    continue
                length = max(
                    (
                        sum(2 if ord(ch) > 0x2E80 else 1 for ch in line)
                        for line in cell.text.splitlines()
                    ),
                    default=0,
                )
                per_column = max(8, min(44, length)) / cell.col_span
                for col in range(cell.col, cell.col + cell.col_span):
                    weights[col] = max(weights[col], per_column)
        return Table(tuple(weights), tuple(rows), headers, f"{grid.name}!{coord(start, left)}")

    extra = {"fields": fields, "closing": [], "references": []}
    references = named("references")
    if references:
        grid, (c, r, _, _) = references
        value = re.sub(r"^\s*2[.、]?\s*参考文献\s*", "", grid.text(r, c))
        extra["references"] = [line.strip() for line in value.splitlines() if line.strip()]
    for key in ("environment", "instruments"):
        found = named(key)
        if found:
            grid, (c1, r1, c2, r2) = found
            table = make_table(grid, r1, r2, 1, (c1, c2))
            if table:
                extra[key] = _item_to_dict(table)
    ignored = set(IGNORED)
    for key in ("home", "summary", "template_version"):
        found = named(key)
        if found:
            ignored.add(found[0].name)
    for sheet in book:
        if sheet.title in {"目录", "填写说明", "内容核对"} or "待整理" in sheet.title:
            continue
        for row in sheet:
            for cell in row[:14]:
                if cell.data_type == "f" and not by_name[sheet.title].text(cell.row, cell.column):
                    issues.append(
                        Issue(
                            ERROR,
                            "FORMULA_NOT_CALCULATED",
                            "公式没有已计算的值，请在 Excel 中重新计算并保存后上传",
                            sheet.title,
                            cell.coordinate,
                        )
                    )
    book.close()
    chapters = []

    try:
        for grid in grids:
            if grid.name in ignored or "待整理" in grid.name or not any(grid.cells.values()):
                continue
            if grid.text(1, 15) != "格式":
                issues.append(
                    Issue(
                        ERROR,
                        "NO_FORMAT_COLUMN",
                        "正文缺少O列格式标记；参考资料请放到待整理工作表",
                        grid.name,
                        "O1",
                    )
                )
                continue
            items = []
            title = None
            closing = False
            revision = False
            level3 = False
            seen_lists = set()
            row = 2
            while row <= grid.max_row:
                fmt = grid.text(row, 15)
                values = [(c, grid.text(row, c)) for c in range(1, 15) if grid.text(row, c)]
                images = [i for i in grid.images if i.row == row and i.col <= 14]
                source = f"{grid.name}!{coord(row, values[0][0] if values else 1)}"
                if fmt in {"表头", "表格"}:
                    start = row
                    headers = 0
                    while row <= grid.max_row and grid.text(row, 15) in {"表头", "表格"}:
                        if grid.text(row, 15) == "表头" and row == start + headers:
                            headers += 1
                        row += 1
                    table = make_table(grid, start, row - 1, headers)
                    if table:
                        items.append(table)
                    continue
                if not values and not images:
                    row += 1
                    continue
                formats = fmt.split("+")
                if not fmt or any(f not in FORMATS for f in formats):
                    issues.append(
                        Issue(
                            ERROR,
                            "INVALID_FORMAT",
                            "有内容的行必须填写有效格式",
                            grid.name,
                            coord(row, 15),
                        )
                    )
                    row += 1
                    continue
                if fmt != "图片" and len(formats) != len(values):
                    issues.append(
                        Issue(
                            ERROR,
                            "FORMAT_COUNT_MISMATCH",
                            "格式数量须与非空内容单元格数量一致；表格请选表头或表格",
                            grid.name,
                            coord(row, 15),
                        )
                    )
                    row += 1
                    continue
                for (col, value), format_ in zip(values, formats):
                    src = f"{grid.name}!{coord(row, col)}"
                    if format_.endswith("级标题"):
                        text = HEADING_PREFIX.sub("", value).strip()
                        if not text:
                            issues.append(Issue(ERROR, "EMPTY_HEADING", "标题不能只有编号", grid.name, coord(row, col)))
                            continue
                        if format_ == "二级标题":
                            if title is not None or items or closing:
                                issues.append(
                                    Issue(
                                        ERROR,
                                        "MULTIPLE_CHAPTERS",
                                        "每张测试工作表只允许一个二级标题，放在正文开头",
                                        grid.name,
                                        coord(row, col),
                                    )
                                )
                            title = text
                        elif format_ == "一级标题":
                            if text.startswith("出厂配置"):
                                closing = True
                            elif text == "版本修改记录":
                                revision = True
                            else:
                                issues.append(
                                    Issue(
                                        ERROR,
                                        "INVALID_ROOT_HEADING",
                                        "一级标题仅用于出厂配置确认、版本修改记录",
                                        grid.name,
                                        coord(row, col),
                                    )
                                )
                        else:
                            level = 3 if format_ == "三级标题" else 4
                            if level == 4 and not level3:
                                issues.append(
                                    Issue(
                                        ERROR,
                                        "ORPHAN_HEADING",
                                        "四级标题前缺少三级标题",
                                        grid.name,
                                        coord(row, col),
                                    )
                                )
                            level3 = level3 or level == 3
                            items.append(Heading(level, text, src))
                        seen_lists.clear()
                    elif not revision:
                        lines = [line.strip() for line in value.splitlines() if line.strip()]
                        if format_ in {"列表", "子列表"}:
                            style = "decimal" if format_ == "列表" else "circle"
                            first = bool(re.match(r"^(?:1[)）.]|①)", value.strip()))
                            continues = style in seen_lists and not first
                            items.append(
                                ListBlock(
                                    style,
                                    (ListItem(LIST_PREFIX.sub("", lines[0]), 0, src),),
                                    src,
                                    continues,
                                )
                            )
                            seen_lists.add(style)
                            items.extend(Paragraph(line, "indent", src) for line in lines[1:])
                        elif format_ != "图片":
                            p_kind = {"注意": "note", "缩进段落": "indent"}.get(format_, "body")
                            items.extend(Paragraph(line, p_kind, src) for line in lines)
                if not revision:
                    items.extend(Image(store_image(img), source) for img in images)
                row += 1
            if closing:
                if extra["closing"]:
                    issues.append(
                        Issue(ERROR, "DUPLICATE_CLOSING", "出厂配置章节重复", grid.name, "A2")
                    )
                extra["closing"] = [_item_to_dict(i) for i in items]
            elif title:
                chapters.append(Chapter(title, grid.name, tuple(items)))
            else:
                issues.append(
                    Issue(ERROR, "MISSING_CHAPTER_TITLE", "缺少二级测试章节标题", grid.name, "A2")
                )
    except (ValueError, WorkbookError) as exc:
        issues.append(Issue(ERROR, getattr(exc, "code", "INVALID_WORKBOOK"), str(exc)))
    if not chapters:
        issues.append(Issue(ERROR, "NO_CHAPTERS", "至少保留一个测试章节"))
    # Specific source concerns remain warnings, not guessed engineering corrections.
    for grid in grids:
        if grid.name in ignored or "待整理" in grid.name:
            continue
        values = [value for (r, c), value in grid.cells.items() if c <= 14]
        standards = [v for v in values if re.match(r"^(GB|IEC|UL|JET)[：:]", v)]
        if len(standards) > 1:
            issues.append(
                Issue(
                    WARNING,
                    "ALTERNATIVES_REMAIN",
                    "仍保留多个相色标准，请确认已按项目取舍；系统将按 Excel 全部输出",
                    grid.name,
                    "A2",
                )
            )
        if "1P260S" in values and "1P416S" in values:
            issues.append(
                Issue(
                    WARNING,
                    "ALTERNATIVES_REMAIN",
                    "仍保留两种电池簇测试表，请确认已按项目取舍；系统将按 Excel 全部输出",
                    grid.name,
                    "A2",
                )
            )
        for (r, c), value in grid.cells.items():
            if c <= 14 and (
                value == "0.5≤P≤0.3"
                or (
                    value == "从控参数-主控通讯协议使能"
                    and "恩玖" in " ".join(grid.text(r, k) for k in range(c + 1, 15))
                )
            ):
                issues.append(
                    Issue(
                        WARNING,
                        "SOURCE_CONTENT_REVIEW",
                        "此处原始工程内容疑似有误，已保留原文，请与研发资料核对",
                        grid.name,
                        coord(r, c),
                    )
                )
    return ParseResult(
        DocumentModel(tuple(chapters), parser_version=PARSER_VERSION, extra=extra), tuple(issues)
    )
