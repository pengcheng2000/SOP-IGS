"""Build an annotated cabinet workbook from the private, business-authored source.

Original values are preserved. Only layout, numbering metadata, and explanatory areas
change. The downloadable template uses a neutral title/scope; --case keeps the original.
"""

from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import quote_sheetname
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
VERSION = "cabinet-plan-v1"
FORMATS = [
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
]
# Source coordinates, before the explanatory header row is inserted.
TABLES = {
    6: [(6, 10, 1), (19, 21, 1), (23, 25, 1), (29, 32, 2)],
    8: [(3, 13, 1), (20, 35, 1)],
    9: [(8, 28, 1), (30, 37, 1), (49, 52, 1), (55, 76, 1)],
    11: [(4, 19, 1), (21, 31, 1)],
    12: [(12, 20, 1)],
    13: [(22, 25, 1), (30, 31, 0), (34, 90, 1)],
    14: [(14, 18, 0), (20, 23, 0), (34, 40, 1)],
}
NOTE_COLUMNS = {
    1: 4,
    2: 4,
    3: 3,
    4: 4,
    5: 3,
    6: 14,
    7: 4,
    8: 15,
    9: 15,
    10: 15,
    11: 14,
    12: 15,
    13: 15,
    14: 15,
    15: 15,
    16: 15,
    17: 14,
}
FIELD_CELLS = {
    "document_title": "A1",
    "scope_text": "A6",
    "document_version": "A42",
    "archive_month": "D42",
    "document_code": "E49",
    "product_line": "K49",
    "drafter": "C45",
    "reviewer_1": "C46",
    "reviewer_2": "C47",
    "reviewer_3": "C48",
    "standardizer": "C49",
    "approver": "C50",
}


def name(workbook, key: str, sheet: str, area: str) -> None:
    workbook.defined_names.add(
        DefinedName(key, attr_text=f"{quote_sheetname(sheet)}!{area}")
    )


def kind(value: str) -> str:
    value = value.strip()
    if value.startswith(("★", "注：")):
        return "注意" if value.startswith("★") else "缩进段落"
    if re.match(r"\d+[)）]", value):
        return "列表"
    if re.match(r"[①②③④⑤⑥⑦⑧⑨⑩]", value):
        return "子列表"
    return "段落"


def annotate(sheet, number: int) -> None:
    notes = {}
    cutoff = NOTE_COLUMNS[number]
    # Move only the declared explanatory area, never infer it from colour or wording.
    for row in sheet:
        values = [
            str(c.value) for c in row if c.column >= cutoff and c.value is not None
        ]
        if values:
            notes[row[0].row] = "\n".join(values)
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_col >= cutoff:
            sheet.unmerge_cells(str(merged))
    for row in sheet:
        for cell in row:
            if cell.column >= cutoff:
                cell.value = None

    formats = {}
    for row in sheet:
        entries = []
        for cell in row[:14]:
            if cell.value is None:
                continue
            text = str(cell.value).strip()
            if cell.column == 1 and re.match(r"\d+(?:\.\d+)*[.、 ]", text):
                if cell.row == 1:
                    entries.append("一级标题" if number == 17 else "二级标题")
                elif number == 17 and cell.row == 7:
                    entries.append("一级标题")
                else:
                    entries.append("三级标题")
            else:
                entries.append(kind(text))
        if entries:
            formats[row[0].row] = "+".join(entries)
    for start, end, headers in TABLES.get(number, []):
        for r in range(start, end + 1):
            formats[r] = "表头" if r < start + headers else "表格"
    # The curve has no text in its anchor row.
    for image in sheet._images:
        formats.setdefault(image.anchor._from.row + 1, "图片")

    # openpyxl insert_rows does not adjust merges/drawings; handle both explicitly.
    merges = list(sheet.merged_cells.ranges)
    for merged in merges:
        sheet.unmerge_cells(str(merged))
    dimensions = {r: copy.copy(d) for r, d in sheet.row_dimensions.items()}
    sheet.insert_rows(1)
    sheet.row_dimensions.clear()
    for r, dimension in dimensions.items():
        dimension.index = r + 1
        sheet.row_dimensions[r + 1] = dimension
    sheet.row_dimensions[1].height = 28
    for merged in merges:
        merged.shift(row_shift=1)
        sheet.merge_cells(str(merged))
    for image in sheet._images:
        image.anchor._from.row += 1
        if hasattr(image.anchor, "to"):
            image.anchor.to.row += 1
    sheet["A1"] = "标题 / 测试内容（原编号由系统重排）"
    sheet["O1"] = "格式"
    sheet["P1"] = "填写说明（不导出）"
    for r, fmt in formats.items():
        sheet.cell(r + 1, 15, fmt)
    for r, text in notes.items():
        sheet.cell(r + 1, 16, text)
    sheet.freeze_panes = "B3"
    sheet.column_dimensions["O"].width = 24
    sheet.column_dimensions["P"].width = 62
    sheet.print_area = f"A1:N{sheet.max_row}"
    validation = DataValidation(
        type="list", formula1='"' + ",".join(FORMATS) + '"', allow_blank=True
    )
    validation.showInputMessage = True
    validation.promptTitle = "格式"
    validation.prompt = (
        "标题与正文同一行时以 + 连接，例如：三级标题+列表。详见填写说明。"
    )
    sheet.add_data_validation(validation)
    validation.add(f"O2:O{sheet.max_row + 100}")
    for row in sheet:
        row[14].fill = PatternFill("solid", fgColor="FFF2CC")
        row[14].alignment = Alignment(wrap_text=True, vertical="top")
        row[15].alignment = Alignment(wrap_text=True, vertical="top")
    sheet["O1"].comment = Comment(
        "每个正文行都填写格式；多项以 + 连接，依次对应非空内容单元格。表格整行只写表头或表格。",
        "SOP",
    )


def build(source: Path, destination: Path, case: bool = False) -> None:
    workbook = load_workbook(source)
    for sheet in list(workbook):
        match = re.match(r"(\d+)、", sheet.title)
        if match:
            annotate(sheet, int(match[1]))
            name(workbook, f"sop_sheet_{int(match[1])}", sheet.title, "$A$1")
    home = workbook["首页"]
    # Keep the source's fixed page mock-up. Screenshots are private explanatory
    # material; the downloadable copy carries equivalent written instructions.
    if not case:
        home._images = home._images[:1]
        home["A1"] = "示例客户工商业储能项目生产测试需求"
        home["A6"] = (
            "1.适用范围\n本测试需求适用于示例储能户外柜项目的外观、机柜强度、防护等级、绝缘耐压、通讯配置及通讯测试、保护功能、电性能等测试项目，描述了相应的试验方法与技术要求。"
        )
        home["E45"] = home["A1"].value
    for field, coord in FIELD_CELLS.items():
        name(workbook, f"sop_{field}", "首页", home[coord].coordinate)
    name(workbook, "sop_references", "首页", "$A$7")
    name(workbook, "sop_environment", "首页", "$C$9:$J$10")
    name(workbook, "sop_instruments", "首页", "$C$14:$J$34")
    name(workbook, "sop_home", "首页", "$A$1")
    name(workbook, "sop_summary", "目录", "$A$1")
    home["A1"].comment = Comment(
        "文档标题唯一来源；标题栏与下载文档自动使用此标题。已填写的信息无需在网页重填。",
        "SOP",
    )
    home["E45"].comment = Comment("此处为版式示意；输出统一采用 A1 的文档标题。", "SOP")
    home["A6"].comment = Comment(
        "填写完整适用范围。网页不会要求重复填写客户或项目名称。", "SOP"
    )
    home["N3"] = (
        "首页有值的字段直接读取；网页只补缺项。标题栏与主标题一致，页码及页数由系统生成。"
    )
    home["N3"].comment = None
    instructions = workbook.create_sheet("填写说明", 0)
    rows = [
        ["工商业柜测试方案 · 填写说明", VERSION],
        ["流程", "下载模板→编辑并删去不适用项目→上传→补齐缺项→生成Word。"],
        [
            "首页",
            "保留可视化首页。直接修改标题、完整适用范围、编码、版本、归档年月、所属产品和签署栏。命名区域用于读取，勿删除。",
        ],
        ["目录", "保留30行作为示意；系统根据实际保留的二级测试标题重新生成目录。"],
        [
            "正文区域",
            "A–N列内容；O列格式；P列以后仅说明。先复制整张测试工作表，再按需编辑可增加章节。",
        ],
        [
            "格式",
            "一级/二级/三级/四级标题、段落、缩进段落、列表、子列表、注意、表头、表格、图片。",
        ],
        [
            "组合格式",
            "同一行标题和正文分别成条目时用+连接，顺序对应从左到右的非空单元格。例如：三级标题+列表。",
        ],
        [
            "编号",
            "系统按标题层级、保留顺序重新编号。正文可保留原列表前缀，输出时自动连续编号。",
        ],
        [
            "表格",
            "连续表头/表格行组成表格，支持合并单元格。预留行只用于Excel编辑，Word不补空白行。指定表格保留一行以下空白。",
        ],
        [
            "取舍",
            "相色标准、电池簇二选一、品牌、热管理、UPS等由编辑人员在Excel中删除或修改；网页不再二次勾选。",
        ],
        ["Word批注1", "接线标准由方案编辑人员选择对应国家/地区标准。"],
        ["Word批注2", "电池簇耐压表由方案编辑人员根据户外柜电池簇情况选择。"],
        ["Word批注3", "软件版本由方案编辑人员根据研发项目及后期更新情况填写最终版本。"],
        [
            "图片",
            "PNG/JPEG按所在行输出；图片独占行标记图片。删除测试项时一起删除其图片。首页说明截图不输出。",
        ],
        [
            "参考页",
            "首页、目录、填写说明、内容核对、待整理及空工作表不作为测试章节。未标记格式的非空正文工作表会报错。",
        ],
        [
            "分页",
            "首页与目录各一页A4；正文各章连续排版。首页/目录内容超限会明确报错，请缩减这些区域的内容。",
        ],
        [
            "版本日期",
            "第7章日期由系统按生成任务创建时的北京时间生成；归档年月仍取首页。",
        ],
        [
            "示例值",
            "表内工程参数来自需求提供方的示例，不由生成器校核。请按项目确认后上传，详见内容核对。",
        ],
    ]
    for row in rows:
        instructions.append(row)
    name(workbook, "sop_template_version", "填写说明", "$B$1")
    review = workbook.create_sheet("内容核对")
    for row in [
        ["位置（标准模板）", "待核对内容；工程原文未自动修改"],
        [
            "9、保护测试!D9:J26",
            "BMS表首行参数名称与值疑似错位，且有重复参数名；请与研发阈值表核对。Word案例与Excel不一致。",
        ],
        [
            "13、系统功能测试!E25",
            "噪声测试倍率区间0.5≤P≤0.3疑似不成立；保持原文，需业务确认。",
        ],
        [
            "12、热管理系统!B7",
            "除湿启动/停止阈值描述的大小关系需业务核对，生成器不修改。",
        ],
        [
            "4、接线检查 / 6、绝缘耐压测试",
            "删除不适用的相色标准、电池簇测试表；所有参数由编辑人员确认。",
        ],
        [
            "目录与正文编号",
            "原目录与实际章节不一致，且部分标题编号有误；仅结构编号由系统重排。",
        ],
        ["17、出厂配置", "Excel与Word的UPS补电时长不同；按已确认规则保留Excel内容。"],
    ]:
        review.append(row)
    for sheet in (instructions, review):
        sheet.column_dimensions["A"].width = 32
        sheet.column_dimensions["B"].width = 105
        for row in sheet:
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
                c.font = Font(name="宋体", size=11, bold=c.row == 1)
            sheet.row_dimensions[row[0].row].height = 38
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "SOP_case/工商业柜测试方案/工商业储能项目生产测试需求.xlsx",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "templates/cabinet-test-plan/v1/input-template.xlsx",
    )
    parser.add_argument("--case", action="store_true")
    args = parser.parse_args()
    build(args.source, args.out, args.case)
