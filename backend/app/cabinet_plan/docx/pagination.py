"""Keep headings with their following content without heading-format control marks."""

import re

from ...document_common.ooxml import DocxGenerationError

HEADING_NUMBER = re.compile(r"\d+(?:\.\d+)*\.?")


def _orphans(document):
    found = []
    for paragraph in document.ListParagraphs:
        value = paragraph.Range
        if paragraph.OutlineLevel > 4 or not HEADING_NUMBER.fullmatch(
            str(value.ListFormat.ListString or "")
        ):
            continue
        end = value.End
        if end >= document.Content.End:
            continue
        heading_end = document.Range(end - 1, end - 1)
        following_start = document.Range(end, end)
        if heading_end.Information(3) < following_start.Information(3):
            found.append(value.Start)
    return sorted(set(found), reverse=True)


def keep_headings_with_content(document):
    moved = 0
    for _ in range(4):
        document.Repaginate()
        positions = _orphans(document)
        if not positions:
            return {"orphan_headings": 0, "headings_moved_to_next_page": moved}
        for start in positions:
            document.Range(start, start).InsertBefore("\f\r")
            gap = document.Range(start, start + 2)
            gap.Style = -1  # built-in Normal, independent of the Word UI language
            gap.ListFormat.RemoveNumbers()
            props = gap.ParagraphFormat
            props.OutlineLevel = 10
            props.KeepWithNext = False
            props.KeepTogether = False
            props.PageBreakBefore = False
            props.SpaceBefore = props.SpaceAfter = 0
            props.LineSpacingRule = 4  # exactly 1 pt for the break-only paragraph
            props.LineSpacing = 1
            gap.Font.Size = 1
            moved += 1
    document.Repaginate()
    if _orphans(document):
        raise DocxGenerationError("ORPHAN_HEADING", "标题分页调整未完成，请检查异常长标题或表格")
    return {"orphan_headings": 0, "headings_moved_to_next_page": moved}
