from pathlib import Path
from zipfile import ZipFile

import pytest
from app.services.docx import (
    DocPhoto,
    DocPhotoGroup,
    GenerationInput,
    generate_docx,
    validate_docx,
)
from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "templates" / "liquid-cooled-cabinet" / "v1" / "master.docx"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}


def texts(path: Path) -> str:
    with ZipFile(path) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    return "".join(document.xpath("//w:t/text()", namespaces=NS))


def document_xml(path: Path):
    with ZipFile(path) as archive:
        return etree.fromstring(archive.read("word/document.xml"))


def assert_generated_image_tables_have_case_borders(document) -> None:
    image_tables = document.xpath(
        "/w:document/w:body/w:tbl[position() > 1][.//w:drawing]",
        namespaces=NS,
    )
    assert image_tables
    for table in image_tables:
        borders = table.xpath("./w:tblPr/w:tblBorders/*", namespaces=NS)
        assert {etree.QName(border).localname for border in borders} == {
            "top", "left", "bottom", "right", "insideH", "insideV"
        }
        assert all(border.get(f"{{{NS['w']}}}val") == "single" for border in borders)
        assert all(border.get(f"{{{NS['w']}}}sz") == "4" for border in borders)
        assert all(border.get(f"{{{NS['w']}}}color") == "auto" for border in borders)
        assert all(border.get(f"{{{NS['w']}}}space") == "0" for border in borders)


def heading_titles(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    return [
        "".join(paragraph.xpath(".//w:t/text()", namespaces=NS)).strip()
        for paragraph in document.xpath(
            "/w:document/w:body/w:p[w:pPr/w:numPr/w:numId[@w:val='2']]",
            namespaces=NS,
        )
    ]


def test_generates_partial_tree_and_removes_unselected_sections(tmp_path: Path):
    output = tmp_path / "partial.docx"
    report = generate_docx(
        MASTER,
        output,
        GenerationInput(
            project={"name": "PoC 项目", "document_title": "PoC 测试报告", "document_version": "V01"},
            selected_test_item_ids=("cabinet_strength_lifting",),
        ),
    )
    validation = validate_docx(output)
    headings = heading_titles(output)
    assert validation["valid"]
    assert report["display_numbers"]["cabinet_strength_lifting"] == "5.1.1"
    assert "机柜强度测试" in headings
    assert "起吊、称重" in headings
    assert "满载静置" not in headings
    assert "叉举" not in headings


def test_inserts_only_inline_images(tmp_path: Path):
    image_path = tmp_path / "portrait.jpg"
    Image.new("RGB", (800, 1200), "#2c7a70").save(image_path)
    output = tmp_path / "image.docx"
    generate_docx(
        MASTER,
        output,
        GenerationInput(
            project={"name": "图片 PoC", "document_title": "图片 PoC"},
            selected_test_item_ids=("visual_inspection",),
            photos_by_test_item={"visual_inspection": (DocPhoto("p1", image_path, "柜体正面"),)},
        ),
    )
    with ZipFile(output) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    assert len(document.xpath("//wp:inline", namespaces=NS)) == 2  # logo + uploaded photo
    assert len(document.xpath("//wp:anchor", namespaces=NS)) == 0
    assert "柜体正面" in texts(output)
    assert_generated_image_tables_have_case_borders(document)
    evidence_tables = document.xpath(
        "/w:document/w:body/w:tbl[position()>1][.//w:drawing]",
        namespaces=NS,
    )
    assert len(evidence_tables) == 1
    assert len(evidence_tables[0].xpath("./w:tr", namespaces=NS)) == 1
    assert not evidence_tables[0].xpath(".//w:t[text()='测试照片']", namespaces=NS)
    title = evidence_tables[0].getprevious()
    assert ''.join(title.xpath('.//w:t/text()', namespaces=NS)) == '测试照片'
    assert title.xpath('./w:pPr/w:keepNext[@w:val="1"]', namespaces=NS)


def test_fire_photo_groups_keep_category_boundaries_and_two_columns(tmp_path: Path):
    images = []
    for index in range(4):
        path = tmp_path / f"fire-{index}.jpg"
        Image.new("RGB", (1200, 700), (20 + index * 20, 100, 90)).save(path)
        images.append(path)
    output = tmp_path / "fire-groups.docx"
    generate_docx(
        MASTER,
        output,
        GenerationInput(
            project={"name": "消防分组 PoC", "document_title": "消防分组 PoC"},
            selected_test_item_ids=("alarm_fire",),
            photo_groups_by_test_item={
                "alarm_fire": (
                    DocPhotoGroup(
                        "smoke",
                        "smoke",
                        "烟感",
                        tuple(DocPhoto(f"s{index}", path) for index, path in enumerate(images[:3])),
                        "fire_two_column",
                        2,
                        sort_order=10,
                    ),
                    DocPhotoGroup(
                        "temperature",
                        "temperature",
                        "温感",
                        (DocPhoto("t1", images[3]),),
                        "fire_two_column",
                        2,
                        sort_order=20,
                    ),
                )
            },
        ),
    )
    document = document_xml(output)
    table_texts = [
        "".join(table.xpath(".//w:t/text()", namespaces=NS))
        for table in document.xpath("/w:document/w:body/w:tbl", namespaces=NS)
    ]
    grouped_tables = [
        table
        for table, value in zip(
            document.xpath("/w:document/w:body/w:tbl", namespaces=NS),
            table_texts,
            strict=True,
        )
        if "烟感" in value and "温感" in value
    ]
    assert len(grouped_tables) == 1
    assert "气溶胶喷洒" not in table_texts
    assert len(document.xpath("//wp:inline", namespaces=NS)) == 5  # logo + four photos
    assert len(document.xpath("//wp:anchor", namespaces=NS)) == 0
    assert_generated_image_tables_have_case_borders(document)
    smoke_rows = grouped_tables[0].xpath("./w:tr", namespaces=NS)[1:3]
    assert [len(cell.xpath(".//w:drawing", namespaces=NS)) for cell in smoke_rows[-1].xpath("./w:tc", namespaces=NS)] == [1, 0]


def test_temperature_curve_is_inserted_inside_existing_data_table(tmp_path: Path):
    curve = tmp_path / "curve.png"
    Image.new("RGB", (1800, 700), "white").save(curve)
    output = tmp_path / "temperature-curve.docx"
    generate_docx(
        MASTER,
        output,
        GenerationInput(
            project={"name": "温升 PoC", "document_title": "温升 PoC"},
            selected_test_item_ids=("temperature_rise",),
            photo_groups_by_test_item={
                "temperature_rise": (
                    DocPhotoGroup(
                        "curve",
                        "temperature_curve",
                        "温升曲线",
                        (DocPhoto("curve", curve),),
                        "temperature_curve",
                        1,
                    ),
                )
            },
        ),
    )
    with ZipFile(output) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    matching_rows = document.xpath(
        "//w:tr[.//w:t[contains(., '温升曲线')]]",
        namespaces=NS,
    )
    assert matching_rows
    assert len(matching_rows[-1].xpath(".//w:drawing", namespaces=NS)) == 1


def test_sanitized_master_removes_historical_photo_tables_but_keeps_temperature_data():
    document = document_xml(MASTER)
    assert len(document.xpath("/w:document/w:body/w:tbl", namespaces=NS)) == 27
    assert len(document.xpath("//w:drawing", namespaces=NS)) == 1
    content = "".join(document.xpath("//w:t/text()", namespaces=NS))
    assert "烟感温感气溶胶喷洒" not in content
    assert "温升曲线：" in content


@pytest.mark.parametrize("count", [0, 1, 4, 5])
def test_sample_photos_stay_inside_sample_section(tmp_path, count):
    image = tmp_path / 'sample.jpg'
    Image.new('RGB', (800, 500), 'green').save(image)
    out = tmp_path / 'sample.docx'
    photos = tuple(DocPhoto(f's{i}', image, f'样品证据{i}') for i in range(count))
    generate_docx(MASTER, out, GenerationInput(
        project={'name': '样品测试'}, selected_test_item_ids=('alarm_bms',),
        sample_photo_groups=(DocPhotoGroup('s', 'sample_diagonal', '对角 45°', photos, 'fixed_columns', 2),),
    ))
    root = document_xml(out)
    blocks = list(root.find('w:body', NS))
    text = lambda p: ''.join(p.xpath('.//w:t/text()', namespaces=NS))
    start = next(i for i,p in enumerate(blocks) if p.tag.endswith('}p') and text(p) == '样品照片')
    end = next(i for i,p in enumerate(blocks) if p.tag.endswith('}p') and text(p) == '样品尺寸及重量')
    tables = [p for p in blocks[start+1:end] if p.tag.endswith('}tbl')]
    assert len(tables) == (1 if count else 0)
    assert sum(len(p.xpath('.//w:drawing', namespaces=NS)) for p in blocks[start+1:end]) == count
    assert sum(len(p.xpath('.//w:drawing', namespaces=NS)) for p in blocks[end:]) == 0
    assert validate_docx(out)['valid']


def test_existing_test_photo_heading_reused_and_custom_titles_preserved(tmp_path):
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (600, 800), 'blue').save(image)
    out = tmp_path / 'reuse.docx'
    generate_docx(MASTER, out, GenerationInput(
        project={'name': '标题复用'}, selected_test_item_ids=('cabinet_strength_static',),
        photo_groups_by_test_item={'cabinet_strength_static': (
            DocPhotoGroup('g', 'test_photos', '测试照片', (DocPhoto('1', image),)),
            DocPhotoGroup('c', 'custom-evidence', '补充证据', (DocPhoto('2', image),), source='custom', sort_order=1000),
        )},
    ))
    root = document_xml(out)
    headings = root.xpath('/w:document/w:body/w:p[w:r/w:t="测试照片"]', namespaces=NS)
    assert len(headings) == 1
    assert headings[0].getnext().tag.endswith('}tbl')
    assert not root.xpath('//w:tbl//w:t[text()="测试照片"]', namespaces=NS)
    assert root.xpath('//w:tbl//w:t[text()="补充证据"]', namespaces=NS)
