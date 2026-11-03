from pathlib import Path
from zipfile import ZipFile

from app.boost.docx.builder import generate_boost_docx
from app.boost.docx.ooxml import NS, paragraph_text
from app.boost.input import parse_workbook
from app.boost.input.home import normalize
from app.boost.input.model import Heading, ListBlock, Paragraph
from lxml import etree
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/boost-integrated-unit/v1"


def test_home_and_template_roundtrip(tmp_path):
    book = load_workbook(TEMPLATE / "input-template.xlsx")
    assert [book["首页"][f"J{r}"].value for r in (20, 22, 24, 25)] == [
        "1/1",
        "3/3/1",
        "1/2",
        "1/1/1",
    ]
    for r in range(12, 18):
        assert book["互感器极性测试"][f"B{r}"].border.left.style
        assert book["互感器极性测试"][f"B{r}"].border.right.style
    book["首页"]["C52"] = "HOME-001"
    book["首页"]["A1"] = "专项站点升压一体机测试需求"
    book["首页"]["A6"] = "1.适用范围\n首页独立范围。"
    book["首页"]["A7"] = "2.参考文献\n专属参考一\n专属参考二"
    source = tmp_path / "source.xlsx"
    book.save(source)
    result = parse_workbook(source, tmp_path / "images")
    assert result.valid, result.issues
    document = result.document
    assert len(document.chapters) == 11
    assert document.summary()["image_count"] == 16
    assert document.extra["fields"]["document_number"] == {
        "value": "HOME-001",
        "source": "首页!C52",
    }
    assert document.extra["references"] == ["专属参考一", "专属参考二"]
    assert document.extra["environment"]["type"] == "table"
    assert normalize(document) == document
    output = tmp_path / "output.docx"
    generate_boost_docx(TEMPLATE / "master.docx", output, {}, document)
    with ZipFile(output) as archive:
        xml = etree.fromstring(archive.read("word/document.xml"))
    text = paragraph_text(xml)
    assert "专项站点升压一体机测试需求" in text
    assert "首页独立范围。" in text and "专属参考二" in text
    assert "升压一体机升压一体机" not in text
    assert "GB/T 7251" not in text  # full references replaced, never appended
    assert not xml.xpath(
        '/w:document/w:body/w:tbl//w:rPr/w:b[not(@w:val="0")]', namespaces=NS
    )
    revision = next(
        p for p in xml.findall("w:body/w:p", NS) if paragraph_text(p) == "版本修改记录"
    )
    assert revision.find("w:pPr/w:outlineLvl", NS).get("{" + NS["w"] + "}val") == "0"
    p = next(
        p for p in xml.findall("w:body/w:p", NS) if paragraph_text(p).startswith("铭牌")
    )
    assert p.find("w:pPr/w:ind", NS).get("{" + NS["w"] + "}left") == "210"


def test_parent_lists_continue_and_children_reset(tmp_path):
    document = parse_workbook(
        TEMPLATE / "input-template.xlsx", tmp_path / "images"
    ).document
    for title in ("绝缘电阻与耐压测试", "互感器极性测试"):
        chapter = next(c for c in document.chapters if c.title == title)
        seen = False
        for item in chapter.items:
            if isinstance(item, Heading):
                seen = False
            elif isinstance(item, ListBlock) and item.style == "decimal":
                assert item.continues == seen
                seen = True
    appearance = document.chapters[0]
    assert (
        next(
            i
            for i in appearance.items
            if isinstance(i, Paragraph) and i.text.startswith("铭牌")
        ).kind
        == "body"
    )
