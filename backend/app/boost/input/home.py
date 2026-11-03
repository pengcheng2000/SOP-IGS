"""Explicit home bindings and non-destructive upgrades of boost document models."""

import re
from dataclasses import replace

from .model import Heading, ListBlock, Paragraph, Table, TableCell, _item_to_dict

HOME_FIELDS = {
    "document_title": "A1",
    "scope_text": "A6",
    "document_version": "A42",
    "archive_month": "D42",
    "drafter": "C45",
    "reviewer_1": "C46",
    "reviewer_2": "C47",
    "reviewer_3": "C48",
    "standardizer": "C49",
    "approver": "C50",
    "title_subject": "E45",
    "document_code": "E49",
    "product_line": "K49",
    "document_number": "C52",
}


def normalize(document):
    """Upgrade preview/new snapshots without rewriting historical uploads."""
    chapters = []
    for chapter in document.chapters:
        seen = set()
        items = []
        for item in chapter.items:
            if isinstance(item, Heading):
                seen.clear()
            elif isinstance(item, ListBlock):
                item = replace(item, continues=item.style in seen)
                seen.add(item.style)
                if item.style == "decimal":
                    seen.discard("letter")
            elif isinstance(item, Paragraph) and item.kind == "indent" and not seen:
                item = replace(item, kind="body")
            items.append(item)
        chapters.append(replace(chapter, items=tuple(items)))
    return replace(document, chapters=tuple(chapters))


def read_home(path, grids):
    from openpyxl import load_workbook
    from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

    grid = next((g for g in grids if g.name == "首页"), None)
    if grid is None:
        return {}
    if (
        not grid.text(1, 1)
        or "适用范围" not in grid.text(6, 1)
        or "参考文献" not in grid.text(7, 1)
        or grid.text(14, 3) != "序号"
    ):
        raise ValueError("首页结构与标准模板不一致，请恢复首页标题和表格位置")
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        fields = {}
        for key, address in HOME_FIELDS.items():
            binding = book.defined_names.get("sop_" + key)
            if binding:
                sheet, area = next(binding.destinations)
                if sheet != "首页":
                    raise ValueError("首页命名区域必须指向首页")
                address = area.split(":")[0].replace("$", "")
            row, col = coordinate_to_tuple(address)
            value = grid.text(row, col)
            if key == "scope_text":
                value = re.sub(r"^\s*1[.、]?\s*适用范围\s*", "", value).strip()
            fields[key] = {"value": value, "source": f"首页!{address}"}

        def table(start, end, columns, widths):
            rows = []
            for row in range(start, end + 1):
                values = [grid.text(row, col) for col in columns]
                if any(values) and "以下空白" not in values:
                    rows.append(tuple(TableCell(v, c) for c, v in enumerate(values)))
            return _item_to_dict(Table(tuple(widths), tuple(rows), 1, f"首页!C{start}"))

        def area(key, default):
            binding = book.defined_names.get("sop_" + key)
            sheet, address = next(binding.destinations) if binding else ("首页", default)
            if sheet != "首页":
                raise ValueError("首页表格绑定必须指向首页")
            return range_boundaries(address)

        rc, rr, _, _ = area("references", "A7")
        ec, er, _, ee = area("environment", "C9:J10")
        ic, ir, _, ie = area("instruments", "C14:J34")
        references = re.sub(r"^\s*2[.、]?\s*参考文献\s*", "", grid.text(rr, rc)).strip()
        return {
            "fields": fields,
            "references": [s.strip() for s in references.splitlines() if s.strip()],
            "environment": table(er, ee, [ec, ec + 2, ec + 4, ec + 6], [1, 1, 1, 1]),
            "instruments": table(ir, ie, [ic, ic + 1, ic + 4, ic + 7], [1, 3, 4, 1]),
        }
    finally:
        book.close()
