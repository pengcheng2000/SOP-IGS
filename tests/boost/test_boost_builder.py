from pathlib import Path
from zipfile import ZipFile

import pytest
from app.boost.docx.builder import generate_boost_docx
from app.boost.docx.ooxml import DocxGenerationError
from app.boost.docx.validator import validate_boost_docx
from app.boost.input.model import (
    BoostDocument,
    Chapter,
    Heading,
    Image,
    ImageRef,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
)
from lxml import etree
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "templates" / "boost-integrated-unit" / "v1" / "master.docx"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def read_part(path: Path, name: str):
    with ZipFile(path) as archive:
        return etree.fromstring(archive.read(name))


def para_text(element) -> str:
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def make_image(path: Path, size: tuple[int, int]) -> ImageRef:
    PILImage.new("RGB", size, (30, 120, 60)).save(path)
    return ImageRef(id=path.stem, path=str(path), sha256="0" * 64, px_w=size[0], px_h=size[1])


def sample_document(tmp_path: Path) -> BoostDocument:
    icon = make_image(tmp_path / "icon.png", (60, 30))
    wide = make_image(tmp_path / "wide.png", (4000, 1000))
    table = Table(
        col_widths=(2.0, 1.0, 1.0),
        header_rows=2,
        rows=(
            (TableCell("测试部位", 0, row_span=2), TableCell("要求", 1, col_span=2)),
            (TableCell("绝缘电阻", 1), TableCell("耐压测试", 2)),
            (TableCell("短接三相对地之间", 0), TableCell("≥1MΩ", 1, images=(icon,)), TableCell("无击穿\n漏电流＜5mA", 2)),
        ),
        src="绝缘!B9",
    )
    return BoostDocument(
        chapters=(
            Chapter("外观检查", "外观检查", (
                Heading(3, "集装箱尺寸、标签检查", "外观检查!A1"),
                Paragraph("升压一体机符合尺寸", src="外观检查!B1"),
                Heading(3, "箱门、柜门检查", "外观检查!A3"),
                ListBlock("decimal", (ListItem("开闭灵活"), ListItem("密封良好"), ListItem("子项", level=1))),
                Paragraph("变压器高压侧不做耐压测试。", kind="note"),
            )),
            Chapter("系统供电测试", "系统供电测试", (
                Heading(3, "供电测试"),
                ListBlock("bullet", (ListItem("上电前确认"),)),
                Heading(4, "急停信号跳闸测试"),
                ListBlock("decimal", (ListItem("按下急停按钮"),)),
                table,
                table,
                Image(wide, "系统供电测试!C59"),
            )),
        ),
        revision_history=("2026年09月29日，A0。", "2026年10月10日，A1。"),
    )


FIELDS = {
    "project_name": "示例站点",
    "document_number": "DOC-001",
    "document_version": "A1",
    "drafter": "拟制人",
    "project_references": "示例电气图\n示例测试需求",
}


def test_generate_boost_document(tmp_path: Path) -> None:
    output = tmp_path / "boost.docx"
    report = generate_boost_docx(MASTER, output, FIELDS, sample_document(tmp_path))

    validation = validate_boost_docx(output, report["floating_drawings_expected"])
    assert validation["floating_drawings"] == 2
    document = read_part(output, "word/document.xml")
    all_text = para_text(document)
    assert "{{" not in all_text
    assert "PROTO" not in all_text
    assert "示例站点升压一体机测试需求" in all_text
    assert "DOC-001" in all_text and "拟制人" in all_text

    body = document.find("w:body", NS)
    paragraphs = [para_text(p) for p in body.findall("w:p", NS)]
    assert "示例电气图" in paragraphs and "示例测试需求" in paragraphs
    assert paragraphs[-2:] == ["2026年09月29日，A0。", "2026年10月10日，A1。"]

    summary = next(t for t in body.findall("w:tbl", NS) if "调试项目" in para_text(t.find("w:tr", NS)))
    rows = [[para_text(c) for c in row.findall("w:tc", NS)] for row in summary.findall("w:tr", NS)]
    assert [row[:2] for row in rows[1:]] == [["5.1", "调试中的注意事项"], ["5.2", "外观检查"], ["5.3", "系统供电测试"]]

    assert report["expected_headings"] == [
        ["5.1", "调试中的注意事项"],
        ["5.2", "外观检查"],
        ["5.2.1", "集装箱尺寸、标签检查"],
        ["5.2.2", "箱门、柜门检查"],
        ["5.3", "系统供电测试"],
        ["5.3.1", "供电测试"],
        ["5.3.1.1", "急停信号跳闸测试"],
    ]
    headings = [
        (para_text(p), p.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS), p.xpath("string(w:pPr/w:numPr/w:ilvl/@w:val)", namespaces=NS))
        for p in body.findall("w:p", NS)
        if p.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS) == "3"
    ]
    assert headings == [
        ("调试中的注意事项", "3", "1"), ("外观检查", "3", "1"), ("集装箱尺寸、标签检查", "3", "2"),
        ("箱门、柜门检查", "3", "2"), ("系统供电测试", "3", "1"), ("供电测试", "3", "2"), ("急停信号跳闸测试", "3", "3"),
    ]
    note = next(p for p in paragraphs if "不做耐压测试" in p)
    assert note.startswith("★")


def test_lists_restart_with_their_own_numbering(tmp_path: Path) -> None:
    output = tmp_path / "boost.docx"
    generate_boost_docx(MASTER, output, FIELDS, sample_document(tmp_path))
    document = read_part(output, "word/document.xml")
    numbering = read_part(output, "word/numbering.xml")
    list_ids = []
    for paragraph in document.xpath("//w:body/w:p", namespaces=NS):
        text = para_text(paragraph)
        if text in {"开闭灵活", "上电前确认", "按下急停按钮"}:
            list_ids.append(paragraph.xpath("string(w:pPr/w:numPr/w:numId/@w:val)", namespaces=NS))
            assert paragraph.find("w:pPr/w:ind", NS) is None
    assert len(set(list_ids)) == 3
    for num_id in list_ids:
        num = numbering.xpath(f"./w:num[@w:numId='{num_id}']", namespaces=NS)[0]
        assert num.xpath("string(w:lvlOverride/w:startOverride/@w:val)", namespaces=NS) == "1"
    children = [etree.QName(child).localname for child in numbering]
    assert children.index("num") > max(i for i, name in enumerate(children) if name == "abstractNum")


def test_tables_have_consistent_grid_and_merges(tmp_path: Path) -> None:
    output = tmp_path / "boost.docx"
    report = generate_boost_docx(MASTER, output, FIELDS, sample_document(tmp_path))
    assert report["table_count"] == 2
    assert report["image_count"] == 3
    document = read_part(output, "word/document.xml")
    tables = [t for t in document.xpath("//w:body/w:tbl", namespaces=NS) if "测试部位" in para_text(t)]
    assert len(tables) == 2
    separator = tables[0].getnext()
    assert separator.tag == f"{{{NS['w']}}}p"
    table = tables[0]
    grid = [int(c.get(f"{{{NS['w']}}}w")) for c in table.findall("w:tblGrid/w:gridCol", NS)]
    assert len(grid) == 3 and sum(grid) == 9360
    for row in table.findall("w:tr", NS):
        spans = [int(c.xpath("string(w:tcPr/w:gridSpan/@w:val)", namespaces=NS) or 1) for c in row.findall("w:tc", NS)]
        assert sum(spans) == 3
    first, second = table.findall("w:tr", NS)[:2]
    assert first.find("w:tc/w:tcPr/w:vMerge", NS).get(f"{{{NS['w']}}}val") == "restart"
    continuation = second.find("w:tc/w:tcPr/w:vMerge", NS)
    assert continuation is not None and continuation.get(f"{{{NS['w']}}}val") is None
    assert first.find("w:trPr/w:tblHeader", NS) is not None
    third = table.findall("w:tr", NS)[2]
    assert third.find("w:trPr/w:tblHeader", NS) is None
    cell_lines = [para_text(p) for p in third.findall("w:tc", NS)[2].findall("w:p", NS)]
    assert cell_lines == ["无击穿", "漏电流＜5mA"]

    inline = document.xpath("//wp:inline", namespaces=NS)
    ids = document.xpath("//wp:docPr/@id", namespaces=NS)
    assert len(inline) >= 3 and len(ids) == len(set(ids))
    icon_extent = int(table.xpath("string(.//wp:inline/wp:extent/@cx)", namespaces=NS))
    assert icon_extent == 60 * 9525
    wide_extents = [int(e.get("cx")) for e in document.xpath("//w:body/w:p//wp:inline/wp:extent", namespaces=NS)]
    assert max(wide_extents) <= 9360 * 635


def test_rejects_empty_document(tmp_path: Path) -> None:
    with pytest.raises(DocxGenerationError):
        generate_boost_docx(MASTER, tmp_path / "empty.docx", FIELDS, BoostDocument(chapters=()))


def test_model_round_trip(tmp_path: Path) -> None:
    document = sample_document(tmp_path)
    assert BoostDocument.from_dict(document.to_dict()).to_dict() == document.to_dict()
