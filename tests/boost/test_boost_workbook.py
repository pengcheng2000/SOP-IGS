from pathlib import Path

import pytest
from app.boost.input import parse_workbook
from app.boost.input.model import Heading, Image, ListBlock, Paragraph, Table
from app.boost.input.workbook import WorkbookError, format_value, read_workbook

ROOT = Path(__file__).resolve().parents[2]
CASE_WORKBOOK = ROOT / "SOP_case" / "升压一体机案例" / "升压一体机测试项分类表.xlsx"


@pytest.mark.parametrize(
    ("value", "number_format", "expected"),
    [
        (1.01, "0%", "101%"),
        (-0.01, "0%", "-1%"),
        (0.125, "0.0%", "12.5%"),
        (43.0, "0.0_ ", "43.0"),
        (9600, "General", "9600"),
        (0.9, "General", "0.9"),
        (10.0, "General", "10"),
        ("0002", "@", "0002"),
        (" 文本_x000D_\r\n第二行 ", "General", "文本\n第二行"),
    ],
)
def test_format_value(value, number_format, expected) -> None:
    text, supported = format_value(value, number_format)
    assert text == expected and supported


def test_unknown_number_format_falls_back_with_flag() -> None:
    text, supported = format_value(1234.5, "#,##0.00")
    assert text == "1234.5" and not supported


def test_reader_collects_cells_merges_and_images(sample_workbook: Path) -> None:
    grids, issues = read_workbook(sample_workbook)
    assert not issues
    names = [grid.name for grid in grids]
    assert names == ["外观检查", "绝缘电阻与耐压测试", "版本修改记录", "填写说明"]
    insulation = grids[1]
    assert insulation.text(4, 4) == "101%"
    assert insulation.text(7, 3) == "0002"
    assert (2, 2, 3, 2) in insulation.merges and insulation.is_covered(3, 2)
    assert [(image.coord, image.display_w, image.display_h) for image in insulation.images] == [("C4", 40, 20), ("B8", 600, 300)]
    assert insulation.width(2) == 30


def test_rejects_legacy_and_corrupt_files(tmp_path: Path) -> None:
    legacy = tmp_path / "old.xls"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(WorkbookError) as error:
        read_workbook(legacy)
    assert error.value.code == "XLS_NOT_SUPPORTED"
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip")
    result = parse_workbook(broken, tmp_path / "images")
    assert not result.valid and result.issues[0].code == "WORKBOOK_UNREADABLE"


def test_parse_sample_workbook(sample_workbook: Path, tmp_path: Path) -> None:
    result = parse_workbook(sample_workbook, tmp_path / "images")
    assert result.valid, result.issues
    document = result.document
    assert [chapter.title for chapter in document.chapters] == ["外观检查", "绝缘电阻与耐压测试"]
    assert document.revision_history == ("2026年10月14日，A0",)

    appearance = document.chapters[0].items
    assert appearance[0] == Heading(3, "集装箱尺寸检查", "外观检查!A1")
    assert appearance[1] == Paragraph("尺寸符合要求", "body", "外观检查!B1")
    assert appearance[2].kind == "note"
    assert isinstance(appearance[4], ListBlock)
    assert [(item.text, item.level) for item in appearance[4].items] == [("开闭灵活", 0), ("密封良好", 0), ("子项", 1)]
    assert appearance[5].text == "GB项目：L1（黄）"

    insulation = document.chapters[1].items
    table = next(item for item in insulation if isinstance(item, Table))
    assert table.header_rows == 2
    assert [[(cell.text, cell.col, cell.col_span, cell.row_span) for cell in row] for row in table.rows] == [
        [("测试部位", 0, 1, 2), ("要求", 1, 2, 1)],
        [("绝缘电阻", 1, 1, 1), ("耐压测试", 2, 1, 1)],
        [("短接对地", 0, 1, 1), ("≥1MΩ", 1, 1, 1), ("101%", 2, 1, 1)],
    ]
    assert len(table.rows[2][1].images) == 1
    assert len(table.col_widths) == 3 and all(width > 0 for width in table.col_widths)
    kinds = [type(item).__name__ for item in insulation]
    assert kinds == ["Heading", "Paragraph", "Table", "Heading", "ListBlock", "Paragraph", "Image"]
    assert insulation[3] == Heading(4, "急停信号跳闸测试", "绝缘电阻与耐压测试!B5")
    standalone = insulation[-1]
    assert isinstance(standalone, Image) and Path(standalone.ref.path).is_file()
    assert (standalone.ref.px_w, standalone.ref.px_h) == (600, 300)
    assert result.summary() == {"chapter_count": 2, "heading_count": 4, "table_count": 1, "image_count": 2}


@pytest.mark.skipif(not CASE_WORKBOOK.is_file(), reason="case workbook is project data and not in git")
def test_case_workbook_is_readable(tmp_path: Path) -> None:
    result = parse_workbook(CASE_WORKBOOK, tmp_path / "images")
    assert result.document is not None
    assert result.summary()["image_count"] == 16
    assert result.document.chapters[7].title == "系统供电测试"
