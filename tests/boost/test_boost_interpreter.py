from app.boost.input.interpreter import interpret_workbook
from app.boost.input.model import ImageRef, ListBlock, Paragraph, Table
from app.boost.input.workbook import SheetGrid, SheetImage

A, B, C, D, J = 1, 2, 3, 4, 10


def grid(name: str, cells: dict, merges=(), images=()) -> SheetGrid:
    max_row = max([row for row, _ in cells] + [merge[2] for merge in merges] + [image.row for image in images] + [0])
    return SheetGrid(name, False, dict(cells), list(merges), list(images), {}, max_row)


def store(image: SheetImage) -> ImageRef:
    return ImageRef(f"{image.row}-{image.col}", f"/tmp/{image.name}", "0" * 64, image.display_w, image.display_h)


def codes(issues) -> list[tuple[str, str]]:
    return [(issue.code, issue.cell) for issue in issues]


def test_unknown_format_and_structure_errors_point_to_cells() -> None:
    sheet = grid("测试", {
        (1, B): "没有三级标题的四级标题", (1, J): "四级标题",
        (2, B): "子项", (2, J): "子列表",
        (3, B): "内容", (3, J): "表单",
    })
    document, issues = interpret_workbook([sheet], store)
    assert codes(issues) == [
        ("HEADING_LEVEL_SKIPPED", "J1"),
        ("SUBLIST_WITHOUT_LIST", "J2"),
        ("FORMAT_UNKNOWN", "J3"),
    ]
    assert isinstance(document.chapters[0].items[1], Paragraph)


def test_lists_restart_but_continue_after_an_image() -> None:
    sheet = grid("测试", {
        (1, B): "第一步", (1, J): "列表",
        (2, B): "第二步", (2, J): "列表",
        (3, B): "说明",
        (4, B): "新列表第一项", (4, J): "列表",
        (5, B): "带图步骤", (5, J): "列表",
        (6, B): "图后步骤", (6, J): "列表",
    }, images=[SheetImage(5, C, b"", "a.png", 100, 50)])
    document, issues = interpret_workbook([sheet], store)
    assert not issues
    lists = [item for item in document.chapters[0].items if isinstance(item, ListBlock)]
    assert [[entry.text for entry in block.items] for block in lists] == [["第一步", "第二步"], ["新列表第一项", "带图步骤"], ["图后步骤"]]
    assert [block.continues for block in lists] == [False, False, True]


def test_table_merge_crossing_boundary_is_an_error() -> None:
    sheet = grid("测试", {
        (1, B): "表头", (1, J): "表头",
        (2, B): "跨行内容", (2, J): "表格",
        (3, B): "表外",
    }, merges=[(2, B, 3, B)])
    document, issues = interpret_workbook([sheet], store)
    assert ("MERGE_CROSSES_TABLE", "B2") in codes(issues)
    table = document.chapters[0].items[0]
    assert isinstance(table, Table) and table.rows[1][0].row_span == 1


def test_new_header_after_body_rows_starts_a_new_table() -> None:
    sheet = grid("测试", {
        (1, B): "H1", (1, C): "H2", (1, J): "表头",
        (2, B): "1", (2, C): "2", (2, J): "表格",
        (3, B): "H3", (3, J): "表头",
        (4, B): "3", (4, J): "表格",
    })
    document, _ = interpret_workbook([sheet], store)
    tables = [item for item in document.chapters[0].items if isinstance(item, Table)]
    assert len(tables) == 2 and tables[0].header_rows == 1 and len(tables[1].rows[0]) == 1


def test_heading_merge_and_revision_and_hidden_sheets() -> None:
    chapter = grid("外观检查", {(1, A): "尺寸\n检查", (1, B): "内容一", (2, B): "内容二", (1, J): "段落"}, merges=[(1, A, 2, A)])
    hidden = grid("隐藏", {(1, B): "x"})
    hidden.hidden = True
    revisions = grid("版本修改记录", {(1, A): "2026年10月14日", (1, B): "A0"})
    document, issues = interpret_workbook([chapter, hidden, revisions], store)
    assert document.revision_history == ("2026年10月14日，A0",)
    assert [chapter.title for chapter in document.chapters] == ["外观检查"]
    assert document.chapters[0].items[0].text == "尺寸 检查"
    assert {issue.code for issue in issues} == {"HEADING_MULTILINE", "SHEET_HIDDEN"}


def test_free_form_workbook_without_format_markers_is_rejected() -> None:
    legacy = grid("外观检查", {(1, A): "集装箱检查", (1, B): "尺寸符合要求", (2, B): "铭牌正确"})
    _, issues = interpret_workbook([legacy], store)
    assert codes(issues) == [("NO_FORMAT_COLUMN", "")]
    assert "标准模板" in issues[0].message


def test_header_row_counts_as_a_marker_and_is_skipped() -> None:
    sheet = grid("外观检查", {(1, A): "三级标题", (1, B): "内容", (1, J): "格式",
                              (2, A): "尺寸检查", (2, B): "尺寸符合要求"})
    document, issues = interpret_workbook([sheet], store)
    assert not issues
    assert [type(item).__name__ for item in document.chapters[0].items] == ["Heading", "Paragraph"]


def test_content_format_splits_a_row_into_heading_and_item() -> None:
    sheet = grid("系统供电测试", {
        (1, A): "通讯测试",
        (2, B): "内部通讯测试", (2, D): "模块数据与 EMS 一致", (2, J): "四级标题+列表",
        (3, B): "外部通讯测试", (3, D): "网口通讯正常", (3, J): "四级标题+列表",
        (4, B): "仅一个单元格", (4, J): "四级标题+列表",
    })
    document, issues = interpret_workbook([sheet], store)
    kinds = [type(item).__name__ for item in document.chapters[0].items]
    assert kinds == ["Heading", "Heading", "ListBlock", "Heading", "ListBlock", "Heading"]
    assert [item.text for item in document.chapters[0].items if hasattr(item, "text")][1:3] == ["内部通讯测试", "外部通讯测试"]
    assert codes(issues) == [("FORMAT_COUNT_EXCEEDS_CELLS", "J4")]


def test_indented_paragraph_keeps_list_numbering_going() -> None:
    sheet = grid("绝缘", {
        (1, A): "测控电源柜",
        (2, B): "800V回路", (2, J): "列表",
        (3, B): "耐压测试电压 AC 2000V", (3, J): "缩进段落",
        (4, B): "380V回路", (4, J): "列表",
        (5, B): "耐压测试电压 AC 1890V", (5, J): "缩进段落",
    })
    document, _ = interpret_workbook([sheet], store)
    items = document.chapters[0].items
    assert [type(item).__name__ for item in items] == ["Heading", "ListBlock", "Paragraph", "ListBlock", "Paragraph"]
    assert [item.kind for item in items if isinstance(item, Paragraph)] == ["indent", "indent"]
    lists = [item for item in items if isinstance(item, ListBlock)]
    assert [block.continues for block in lists] == [False, True]


def test_long_heading_in_column_a_is_flagged_as_probably_body_text() -> None:
    sheet = grid("防水测试", {(1, A): "关闭升压一体机的门、翻板、进风口等部件，使用盖板封堵线缆进出口；", (1, B): "内容", (1, J): "列表"})
    _, issues = interpret_workbook([sheet], store)
    assert codes(issues) == [("HEADING_LOOKS_LIKE_TEXT", "A1")]


def test_workbook_without_chapters_is_invalid() -> None:
    _, issues = interpret_workbook([grid("版本修改记录", {(1, A): "A0"})], store)
    assert codes(issues) == [("NO_CHAPTERS", "")]


def test_table_column_widths_follow_the_text_not_the_sheet_columns() -> None:
    sheet = grid("表", {
        (1, B): "测试部位", (1, C): "要求", (1, J): "表头",
        (2, B): "短接三相或单相对地之间", (2, C): "无击穿、无飞弧，漏电流＜5mA 并且要求持续一分钟", (2, J): "表格",
    })
    sheet.col_widths = {B: 4.0, C: 60.0}  # the sheet gives the label column almost no room
    document, _ = interpret_workbook([sheet], store)
    table = next(item for item in document.chapters[0].items if isinstance(item, Table))
    assert table.col_widths[0] > 4.0 and table.col_widths[1] > table.col_widths[0]
    assert table.col_widths[1] <= 44.0
