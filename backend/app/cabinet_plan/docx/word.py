from ...document_common.word import finalize_document
from .pagination import keep_headings_with_content

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")
    report = finalize_document(
        Path(sys.argv[1]),
        bookmarks=("CabinetSummary", "CabinetBody", "CabinetTitleBlock"),
        pdf_path=Path(sys.argv[2]) if len(sys.argv) > 2 else None,
        layout_adjuster=keep_headings_with_content,
    )
    report["title_block_page"] = report["bookmark_pages"].pop("CabinetTitleBlock")
    print(json.dumps(report, ensure_ascii=False))
