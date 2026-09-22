"""Only locate the separator after a numbered TOC entry, never the page-number tab."""
import re

NUMBERED_ENTRY = re.compile(r"^[ \t]*(\d+(?:\.\d+)*\.?)([ \t\u00a0]+)(?=[^\s\d])")


def number_separator_span(text: str) -> tuple[int, int] | None:
    match = NUMBERED_ENTRY.match(text)
    if match is None or match.group(2) == " ":
        return None
    return match.span(2)


def normalize_toc_spacing(document) -> int:
    changed = 0
    for index in range(1, document.TablesOfContents.Count + 1):
        paragraphs = document.TablesOfContents.Item(index).Range.Paragraphs
        for paragraph_index in range(paragraphs.Count, 0, -1):
            paragraph = paragraphs.Item(paragraph_index).Range
            span = number_separator_span(paragraph.Text)
            if span is None:
                continue
            # Range.Text excludes hidden HYPERLINK field codes, while Range.Start
            # counts them. Locate the visible prefix with Find instead of offsets.
            prefix = paragraph.Text[:span[1]].lstrip(' \t')
            found = paragraph.Duplicate
            found.Find.ClearFormatting()
            if not found.Find.Execute(FindText=prefix.replace('\t', '^t'), Forward=True,
                                      Wrap=0, MatchWildcards=False):
                raise RuntimeError('Could not locate numbered TOC separator')
            separator = found.Duplicate
            separator.SetRange(found.End - (span[1] - span[0]), found.End)
            separator.Text = " "
            changed += 1
    return changed
