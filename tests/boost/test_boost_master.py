import hashlib
import zipfile
from pathlib import Path

import yaml
from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "boost-integrated-unit" / "v1"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def load() -> tuple[dict, etree._Element, etree._Element]:
    manifest = yaml.safe_load((TEMPLATE / "manifest.yaml").read_text(encoding="utf-8"))
    with zipfile.ZipFile(TEMPLATE / "master.docx") as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        numbering = etree.fromstring(archive.read("word/numbering.xml"))
    return manifest, document, numbering


def test_manifest_matches_master() -> None:
    manifest = yaml.safe_load((TEMPLATE / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["template_key"] == "boost-integrated-unit"
    assert hashlib.sha256((TEMPLATE / "master.docx").read_bytes()).hexdigest() == manifest["master_sha256"]


def test_every_placeholder_is_a_whole_text_run() -> None:
    manifest, document, _ = load()
    texts = document.xpath("//w:t/text()", namespaces=NS)
    for field in manifest["fields"]:
        token = "{{" + field["key"] + "}}"
        assert token in texts, token
        assert all(text == token for text in texts if token in text), token
    for anchor in manifest["anchors"].values():
        assert texts.count(anchor) == 1, anchor
    assert not [text for text in texts if "{{" in text and text.strip("{}") not in
                {field["key"] for field in manifest["fields"]} and text not in manifest["anchors"].values()
                and not text.startswith("{{PROTO:")]


def test_numbering_supports_continuous_chapter_five() -> None:
    manifest, document, numbering = load()
    num_id = manifest["heading_numbering"]["num_id"]
    abstract_id = numbering.xpath(f"string(./w:num[@w:numId='{num_id}']/w:abstractNumId/@w:val)", namespaces=NS)
    levels = {
        level.get(f"{{{NS['w']}}}ilvl"): level.xpath("string(w:lvlText/@w:val)", namespaces=NS)
        for level in numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{abstract_id}']/w:lvl", namespaces=NS)
    }
    assert levels["1"] == "5.%2." and levels["2"] == "5.%2.%3." and levels["3"] == "5.%2.%3.%4."
    for abstract in manifest["list_abstract_nums"].values():
        assert numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{abstract}']", namespaces=NS)
    assert len(document.xpath("//wp:anchor", namespaces=NS)) == manifest["floating_drawings"]


def test_summary_table_keeps_only_the_fixed_row() -> None:
    _, document, _ = load()
    summary = next(t for t in document.xpath("//w:body/w:tbl", namespaces=NS) if "调试项目" in "".join(t.xpath("./w:tr[1]//w:t/text()", namespaces=NS)))
    rows = ["".join(row.xpath(".//w:t/text()", namespaces=NS)) for row in summary.findall("w:tr", NS)]
    assert len(rows) == 2 and rows[1] == "5.1调试中的注意事项"


def test_filename_box_is_pinned_to_the_page_not_to_a_paragraph() -> None:
    """The case anchors it to the tool-table paragraph, so longer content above pushed its label off the page."""
    _, document, _ = load()
    ns = {**NS, "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006", "v": "urn:schemas-microsoft-com:vml"}
    anchors = [a for a in document.xpath("//mc:Choice//wp:anchor", namespaces=ns) if "电子文件名" in "".join(a.xpath(".//w:t/text()", namespaces=ns))]
    assert len(anchors) == 1
    vertical = anchors[0].find("wp:positionV", ns)
    assert vertical.get("relativeFrom") == "page"
    assert [child.tag.split("}")[1] for child in vertical] == ["posOffset"]
    fallback = next(s for s in document.xpath("//mc:Fallback//v:shape", namespaces=ns) if "电子文件名" in "".join(s.xpath(".//w:t/text()", namespaces=ns)))
    assert "mso-position-vertical-relative:page" in fallback.get("style")


def test_heading_numbers_use_the_case_simsun_look() -> None:
    manifest, _, numbering = load()
    abstract = numbering.xpath(
        f"string(./w:num[@w:numId='{manifest['heading_numbering']['num_id']}']/w:abstractNumId/@w:val)", namespaces=NS
    )
    for ilvl in ("2", "3"):
        font = numbering.xpath(
            f"string(./w:abstractNum[@w:abstractNumId='{abstract}']/w:lvl[@w:ilvl='{ilvl}']/w:rPr/w:rFonts/@w:eastAsia)", namespaces=NS
        )
        assert font == "宋体", ilvl


def test_prototypes_cover_every_paragraph_kind_and_use_the_dominant_body_layout() -> None:
    _, document, _ = load()
    body = {
        paragraph.xpath("string(.//w:t)", namespaces=NS): paragraph
        for paragraph in document.xpath("//w:body/w:p[contains(., '{{PROTO:')]", namespaces=NS)
    }
    assert set(body) == {f"{{{{PROTO:{name}}}}}" for name in ("h3", "h4", "body", "indent", "list", "note")}
    spacing = body["{{PROTO:body}}"].find("w:pPr/w:spacing", NS)
    assert spacing.get(f"{{{NS['w']}}}line") == "360"  # 1.5 line spacing as in most of the case


def test_manifest_describes_month_field_and_fixed_references() -> None:
    manifest, document, _ = load()
    fields = {field["key"]: field for field in manifest["fields"]}
    assert fields["archive_month"]["type"] == "month"
    fixed = fields["project_references"]["fixed_lines"]
    assert len(fixed) == 6 and all(line.startswith("GB") for line in fixed)
    kept = ["".join(p.xpath(".//w:t/text()", namespaces=NS)) for p in document.xpath("//w:body/w:p", namespaces=NS)]
    assert all(line in kept for line in fixed)
