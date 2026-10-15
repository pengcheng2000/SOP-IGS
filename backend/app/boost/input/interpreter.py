"""Turn workbook grids into a BoostDocument according to the input-file spec.

This is the only module that depends on the filling spec:

* one sheet per 5.x chapter, sheet order = chapter order, sheet name = chapter title;
  the revision sheet becomes the version history and ignored sheets are skipped;
* an optional header row (J1 =「格式」) is skipped; the standard template has one;
* column A: level-3 heading (5.x.y), optionally merged down over its rows; a row whose only text is in
  column A and that has a format is content, not a heading;
* columns B–I: content (tables use B–I as well);
* column J「格式」: blank/段落, 缩进段落, 列表, 字母列表, 符号列表, 子列表, 四级标题, 注意, 表头, 表格.
  Consecutive list rows form one list; an indented paragraph or an image between list rows keeps
  the numbering going; consecutive 表头/表格 rows form one table whose merged cells become spans.
  Several cells in a non-table row are joined as「标签：值」.
* a row can hold several items: J lists one format per content cell joined by "+", for example
  「四级标题+列表+缩进段落」; cells beyond the listed formats are joined into the last item.
* a workbook with no format marker at all is rejected: it is the old free-form layout, which cannot be
  turned into the right headings, lists and tables.
* images are placed by their anchor row: inside a table row they go into that cell,
  otherwise they follow the row's text.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .model import (
    ERROR,
    WARNING,
    BoostDocument,
    Chapter,
    Heading,
    Image,
    ImageRef,
    Issue,
    Item,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
)
from .workbook import SheetGrid, SheetImage, coord

PARSER_VERSION = "v1"
HEADING_COLUMN = 1
CONTENT_COLUMNS = range(2, 10)  # B..I
FORMAT_COLUMN = 10  # J
HEADER_LABEL = "格式"
MAX_HEADING_CHARS = 30

FORMATS = {
    "": "paragraph",
    "段落": "paragraph",
    "缩进段落": "indent",
    "列表": "decimal",
    "字母列表": "letter",
    "符号列表": "bullet",
    "子列表": "sublist",
    "四级标题": "h4",
    "注意": "note",
    "表头": "table_header",
    "表格": "table",
}
LIST_KINDS = {"decimal", "letter", "bullet"}
TABLE_KINDS = {"table_header", "table"}

ImageStore = Callable[[SheetImage], ImageRef]


@dataclass(slots=True)
class _SheetState:
    grid: SheetGrid
    store_image: ImageStore
    issues: list[Issue]
    items: list[Item] = field(default_factory=list)
    list_style: str | None = None
    list_items: list[ListItem] = field(default_factory=list)
    list_src: str = ""
    list_continues: bool = False
    interrupted_list: str | None = None
    table_rows: list[tuple[int, str]] = field(default_factory=list)
    has_level3: bool = False

    def issue(self, severity: str, code: str, message: str, row: int, col: int) -> None:
        self.issues.append(Issue(severity, code, message, self.grid.name, coord(row, col)))

    def flush_list(self) -> None:
        if self.list_style and self.list_items:
            self.items.append(ListBlock(self.list_style, tuple(self.list_items), self.list_src, self.list_continues))
        self.list_style = None
        self.list_items = []
        self.list_continues = False

    def image(self, image: SheetImage) -> ImageRef | None:
        try:
            return self.store_image(image)
        except ValueError as exc:
            self.issue(ERROR, getattr(exc, "code", "IMAGE_UNREADABLE"), f"图片无法处理：{exc}", image.row, image.col)
            return None


def _join(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    return f"{values[0]}：{'；'.join(values[1:])}"


def _row_content(grid: SheetGrid, row: int) -> list[str]:
    values = []
    for col in CONTENT_COLUMNS:
        if grid.is_covered(row, col):
            continue
        text = grid.text(row, col)
        if text:
            values.append(text)
    return values


MIN_COLUMN_WEIGHT = 8.0
MAX_COLUMN_WEIGHT = 44.0


def _visual_length(text: str) -> int:
    return sum(2 if ord(char) > 0x2E80 else 1 for char in text)


def _column_weights(grid: SheetGrid, rows: list[int], min_col: int, max_col: int) -> tuple[float, ...]:
    """Relative column widths from the longest text in each column, like Word's auto-fit.

    Excel column widths say nothing about how the table should look in Word (a wide label column is often
    narrow in the sheet), so they are only used for columns that hold no text at all, such as picture columns.
    """
    weights = []
    for col in range(min_col, max_col + 1):
        longest = 0
        for row in rows:
            merge = grid.merge_at(row, col)
            if grid.is_covered(row, col) or (merge and merge[3] > merge[1]):
                continue  # covered cells and cells spanning several columns say nothing about this column
            for line in grid.text(row, col).split("\n"):
                longest = max(longest, _visual_length(line))
        if longest == 0:
            weights.append(min(max(grid.width(col), MIN_COLUMN_WEIGHT), 30.0))
        else:
            weights.append(min(max(float(longest), MIN_COLUMN_WEIGHT), MAX_COLUMN_WEIGHT))
    return tuple(weights)


def _flush_table(state: _SheetState) -> None:
    rows = state.table_rows
    state.table_rows = []
    if not rows:
        return
    grid = state.grid
    numbers = [row for row, _ in rows]
    first_row, last_row = numbers[0], numbers[-1]
    header_rows = 0
    for _, kind in rows:
        if kind != "table_header":
            break
        header_rows += 1

    columns: set[int] = set()
    for row in numbers:
        for col in CONTENT_COLUMNS:
            merge = grid.merge_at(row, col)
            if grid.text(row, col) or (merge and merge[0] == row and merge[1] == col):
                columns.add(col)
                if merge:
                    columns.update(range(merge[1], min(merge[3], CONTENT_COLUMNS[-1]) + 1))
    if not columns:
        state.issue(WARNING, "EMPTY_TABLE", "表格行没有内容，已忽略", first_row, FORMAT_COLUMN)
        return
    min_col, max_col = min(columns), max(columns)

    cell_images: dict[tuple[int, int], list[ImageRef]] = {}
    trailing: list[ImageRef] = []
    for image in grid.images:
        if not first_row <= image.row <= last_row:
            continue
        ref = state.image(image)
        if ref is None:
            continue
        merge = grid.merge_at(image.row, image.col)
        anchor = (merge[0], merge[1]) if merge else (image.row, image.col)
        if min_col <= anchor[1] <= max_col and first_row <= anchor[0] <= last_row:
            cell_images.setdefault(anchor, []).append(ref)
        else:
            trailing.append(ref)

    table_rows: list[tuple[TableCell, ...]] = []
    for row in numbers:
        cells = []
        col = min_col
        while col <= max_col:
            merge = grid.merge_at(row, col)
            if merge and (merge[0], merge[1]) != (row, col):
                col = merge[3] + 1 if merge[0] == row else col + 1
                if merge[0] < first_row:
                    state.issue(ERROR, "MERGE_CROSSES_TABLE", "合并单元格跨越了表格边界", merge[0], merge[1])
                continue
            col_span = row_span = 1
            if merge:
                if merge[1] < min_col or merge[3] > max_col:
                    state.issue(ERROR, "MERGE_CROSSES_TABLE", "合并单元格超出表格列范围", row, col)
                if merge[2] > last_row:
                    state.issue(ERROR, "MERGE_CROSSES_TABLE", "合并单元格跨越了表格边界", row, col)
                col_span = min(merge[3], max_col) - col + 1
                row_span = min(merge[2], last_row) - row + 1
            cells.append(TableCell(grid.text(row, col), col - min_col, col_span, row_span,
                                   tuple(cell_images.get((row, col), ()))))
            col += col_span
        table_rows.append(tuple(cells))
    widths = _column_weights(grid, numbers, min_col, max_col)
    state.items.append(Table(widths, tuple(table_rows), header_rows, f"{grid.name}!{coord(first_row, min_col)}"))
    state.items.extend(Image(ref, f"{grid.name}!{coord(first_row, min_col)}") for ref in trailing)


def first_data_row(grid: SheetGrid) -> int:
    return 2 if grid.text(1, FORMAT_COLUMN) == HEADER_LABEL else 1


def _parse_formats(state: _SheetState, raw: str, row: int) -> list[str]:
    """Format names of a J cell ("列表" or "四级标题+列表") as kinds; unknown names are reported."""
    kinds: list[str] = []
    for name in (part.strip() for part in raw.replace("＋", "+").split("+")):
        kind = FORMATS.get(name)
        if kind is None:
            state.issue(ERROR, "FORMAT_UNKNOWN", f"格式「{name}」无法识别，可选：{'、'.join(k for k in FORMATS if k)}", row, FORMAT_COLUMN)
            kind = "paragraph"
        kinds.append(kind)
    if len(kinds) > 1 and any(kind in TABLE_KINDS for kind in kinds):
        state.issue(ERROR, "FORMAT_UNKNOWN", "表头、表格不能和其他格式用 + 组合", row, FORMAT_COLUMN)
        kinds = ["paragraph"]
    return kinds


def _row_segments(state: _SheetState, row: int, kinds: list[str], values: list[str]) -> list[tuple[str, str]]:
    """The row's items: one joined text, or one item per content cell when J lists several formats."""
    if not values:
        return []
    if len(kinds) == 1:
        return [(kinds[0], _join(values))]
    if len(values) < len(kinds):
        state.issue(WARNING, "FORMAT_COUNT_EXCEEDS_CELLS",
                    f"格式写了 {len(kinds)} 项，但该行只有 {len(values)} 个内容单元格，多出的格式已忽略", row, FORMAT_COLUMN)
        kinds = kinds[: len(values)]
    segments = [(kind, values[index]) for index, kind in enumerate(kinds[:-1])]
    segments.append((kinds[-1], "；".join(values[len(kinds) - 1:])))
    return segments


def _emit(state: _SheetState, kind: str, text: str, src: str, row: int) -> None:
    if kind in LIST_KINDS:
        if state.list_style != kind:
            state.flush_list()
            state.list_style = kind
            state.list_src = src
            state.list_continues = state.interrupted_list == kind
        state.list_items.append(ListItem(text, 0, src))
        state.interrupted_list = None
    elif kind == "sublist":
        if state.list_style is None:
            state.issue(ERROR, "SUBLIST_WITHOUT_LIST", "子列表前面没有列表行", row, FORMAT_COLUMN)
            state.items.append(Paragraph(text, "body", src))
        else:
            state.list_items.append(ListItem(text, 1, src))
    elif kind == "indent":
        # An indented paragraph hangs under the previous list item, so the numbering carries on after it.
        if state.list_style:
            state.interrupted_list = state.list_style
            state.flush_list()
        state.items.append(Paragraph(text, "indent", src))
    else:
        state.flush_list()
        state.interrupted_list = None
        if kind == "h4":
            if not state.has_level3:
                state.issue(ERROR, "HEADING_LEVEL_SKIPPED", "四级标题前面没有三级标题（A 列）", row, FORMAT_COLUMN)
            if "\n" in text:
                state.issue(WARNING, "HEADING_MULTILINE", "标题包含换行，已合并为一行", row, FORMAT_COLUMN)
            state.items.append(Heading(4, " ".join(text.split()), src))
        else:
            state.items.append(Paragraph(text, "note" if kind == "note" else "body", src))


def has_format_markers(grid: SheetGrid) -> bool:
    if grid.text(1, FORMAT_COLUMN) == HEADER_LABEL:
        return True
    return any(col == FORMAT_COLUMN and text for (_, col), text in grid.cells.items())


def _interpret_sheet(grid: SheetGrid, store_image: ImageStore, issues: list[Issue]) -> Chapter:
    state = _SheetState(grid, store_image, issues)
    images_by_row: dict[int, list[SheetImage]] = {}
    for image in grid.images:
        images_by_row.setdefault(image.row, []).append(image)

    for row in range(first_data_row(grid), grid.max_row + 1):
        heading = "" if grid.is_covered(row, HEADING_COLUMN) else grid.text(row, HEADING_COLUMN)
        raw_format = grid.anchor_text(row, FORMAT_COLUMN)
        kinds = _parse_formats(state, raw_format, row)
        kind = kinds[0]
        values = [] if kind in TABLE_KINDS else _row_content(grid, row)
        if heading and raw_format and not values and kind not in TABLE_KINDS:
            # A format on a row whose only text is in column A: that text is content, not a heading.
            values, heading = [heading], ""

        if heading:
            state.flush_list()
            _flush_table(state)
            if "\n" in heading:
                state.issue(WARNING, "HEADING_MULTILINE", "标题包含换行，已合并为一行", row, HEADING_COLUMN)
            heading = " ".join(heading.split())
            if len(heading) > MAX_HEADING_CHARS or heading.endswith(("。", "；", ";")):
                state.issue(WARNING, "HEADING_LOOKS_LIKE_TEXT",
                            f"A 列标题有 {len(heading)} 个字，更像正文；正文请填在 B 列，A 列只填三级标题", row, HEADING_COLUMN)
            state.items.append(Heading(3, heading, f"{grid.name}!{coord(row, HEADING_COLUMN)}"))
            state.has_level3 = True
            state.interrupted_list = None

        if kind in TABLE_KINDS:
            state.flush_list()
            if kind == "table_header" and any(existing == "table" for _, existing in state.table_rows):
                _flush_table(state)
            state.table_rows.append((row, kind))
            continue
        _flush_table(state)

        row_images = [image for image in images_by_row.get(row, [])]
        if not values and not row_images:
            inside_merge = any(grid.is_covered(row, col) for col in CONTENT_COLUMNS)
            if raw_format and not inside_merge:
                state.issue(WARNING, "EMPTY_FORMATTED_ROW", "该行设置了格式但没有内容", row, FORMAT_COLUMN)
            continue
        src = f"{grid.name}!{coord(row, CONTENT_COLUMNS[0])}"
        for segment_kind, text in _row_segments(state, row, kinds, values):
            if text:
                _emit(state, segment_kind, text, src, row)
        if row_images:
            if state.list_style:
                state.interrupted_list = state.list_style
                state.flush_list()
            for image in row_images:
                ref = state.image(image)
                if ref is not None:
                    state.items.append(Image(ref, f"{grid.name}!{image.coord}"))
    state.flush_list()
    _flush_table(state)
    if not state.items:
        issues.append(Issue(WARNING, "EMPTY_SHEET", "工作表没有内容，只会生成章节标题", grid.name, "A1"))
    return Chapter(grid.name.strip(), grid.name, tuple(state.items))


def interpret_workbook(
    grids: list[SheetGrid],
    store_image: ImageStore,
    *,
    revision_sheet: str = "版本修改记录",
    ignored_sheets: tuple[str, ...] = ("填写说明",),
) -> tuple[BoostDocument, list[Issue]]:
    issues: list[Issue] = []
    chapters: list[Chapter] = []
    revisions: list[str] = []
    for grid in grids:
        name = grid.name.strip()
        if name in ignored_sheets:
            continue
        if grid.hidden:
            issues.append(Issue(WARNING, "SHEET_HIDDEN", "隐藏的工作表不会生成", grid.name, "A1"))
            continue
        if name == revision_sheet:
            for row in range(1, grid.max_row + 1):
                values = [grid.text(row, col) for col in range(1, FORMAT_COLUMN + 1) if not grid.is_covered(row, col) and grid.text(row, col)]
                if values:
                    revisions.append("".join(values) if len(values) == 1 else "，".join(values))
            continue
        chapters.append(_interpret_sheet(grid, store_image, issues))
    chapter_grids = [
        grid for grid in grids if grid.name.strip() not in ignored_sheets and grid.name.strip() != revision_sheet
    ]
    if not chapters:
        issues.append(Issue(ERROR, "NO_CHAPTERS", "工作簿中没有可生成的章节工作表"))
    elif not any(has_format_markers(grid) for grid in chapter_grids):
        issues.append(Issue(
            ERROR, "NO_FORMAT_COLUMN",
            "未检测到「格式」列（J 列）。这是旧的自由格式表格，无法确定哪些是标题、列表和表格；"
            "请下载标准模板，按「填写说明」在 J 列填写每一行的格式后重新上传",
        ))
    return BoostDocument(tuple(chapters), tuple(revisions), PARSER_VERSION), issues
