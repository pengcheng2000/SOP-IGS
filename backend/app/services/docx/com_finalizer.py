from __future__ import annotations

import logging
from pathlib import Path

from .toc import normalize_toc_spacing

LOGGER = logging.getLogger(__name__)


class WordComError(RuntimeError):
    pass


def finalize_with_word(path: Path) -> dict:
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
        for toc_index in range(1, document.TablesOfContents.Count + 1):
            document.TablesOfContents.Item(toc_index).Update()
        document.Fields.Update()
        for section_index in range(1, document.Sections.Count + 1):
            section = document.Sections.Item(section_index)
            for footer_index in range(1, section.Footers.Count + 1):
                section.Footers.Item(footer_index).Range.Fields.Update()
            for header_index in range(1, section.Headers.Count + 1):
                section.Headers.Item(header_index).Range.Fields.Update()
        toc_spacing_changes = normalize_toc_spacing(document)
        document.Repaginate()
        for toc_index in range(1, document.TablesOfContents.Count + 1):
            document.TablesOfContents.Item(toc_index).UpdatePageNumbers()
        document.Save()
        pages = document.ComputeStatistics(2)
        headings = []
        for index in range(1, document.Paragraphs.Count + 1):
            paragraph = document.Paragraphs.Item(index)
            value = paragraph.Range.Text.strip("\r\n\t ")
            number = paragraph.Range.ListFormat.ListString
            outline_level = int(paragraph.OutlineLevel)
            if value and number and 1 <= outline_level <= 4:
                headings.append({"number": str(number), "text": value})
        document.Close(0)
        document = None
        reopened = word.Documents.Open(str(path.resolve()), False, True, False)
        reopened.Close(0)
        return {
            "word_version": str(word.Version),
            "pages": pages,
            "reopened": True,
            "headings": headings,
            "toc_spacing_changes": toc_spacing_changes,
        }
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
