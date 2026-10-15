"""Microsoft Word finalization for 升压一体机 documents (fields, pagination, heading numbers).

Each COM call costs tens of milliseconds on a typical office machine, so the heading scan only touches
numbered paragraphs instead of walking every paragraph of the document.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)
HEADING_NUMBER = re.compile(r"\d+(?:\.\d+)*\.?")


class WordComError(RuntimeError):
    code = "WORD_COM_FAILED"


def finalize_boost_with_word(path: Path) -> dict:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - platform-specific
        raise WordComError("pywin32 is not installed") from exc

    pythoncom.CoInitialize()
    word = document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3
        document = word.Documents.Open(str(path.resolve()), False, False, False)
        document.Fields.Update()
        for section_index in range(1, document.Sections.Count + 1):
            section = document.Sections.Item(section_index)
            for footer_index in range(1, section.Footers.Count + 1):
                section.Footers.Item(footer_index).Range.Fields.Update()
            for header_index in range(1, section.Headers.Count + 1):
                section.Headers.Item(header_index).Range.Fields.Update()
        document.Repaginate()
        # Fields inside text boxes (the title block's total page count) belong to their own stories that
        # Fields.Update() and the StoryRanges walk do not reach; update them per shape after pagination is final.
        for shape in document.Shapes:
            try:
                if shape.TextFrame.HasText:
                    shape.TextFrame.TextRange.Fields.Update()
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - shapes without text frames
                LOGGER.debug("skipped shape while updating text-frame fields: %s", exc)
        document.Save()
        pages = document.ComputeStatistics(2)

        found = []
        for paragraph in document.ListParagraphs:  # numbered paragraphs only; Word returns them unordered
            range_ = paragraph.Range
            number = str(range_.ListFormat.ListString or "")
            if not HEADING_NUMBER.fullmatch(number):
                continue  # 1) / a. style lists are body content, not headings
            found.append((range_.Start, number, range_.Text.strip("\r\n\t ")))
        found.sort()
        headings = [{"number": number, "text": text} for _, number, text in found if text]

        document.Close(0)
        document = None
        reopened = word.Documents.Open(str(path.resolve()), False, True, False)
        reopened.Close(0)
        return {"word_version": str(word.Version), "pages": pages, "reopened": True, "headings": headings}
    except Exception as exc:  # pragma: no cover - platform-specific
        raise WordComError(str(exc)) from exc
    finally:
        if document is not None:
            try:
                document.Close(0)
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                LOGGER.warning("failed to close Word document during cleanup: %s", exc)
        if word is not None:
            try:
                word.Quit()
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                LOGGER.warning("failed to quit Word during cleanup: %s", exc)
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(finalize_boost_with_word(Path(sys.argv[1])), ensure_ascii=False))
