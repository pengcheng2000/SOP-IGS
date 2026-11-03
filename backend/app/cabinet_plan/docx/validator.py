from ...document_common.ooxml import DocxGenerationError
from ...document_common.validation import validate_docx as validate_cabinet_plan_docx

__all__ = ["validate_cabinet_plan_docx", "validate_pagination"]


def validate_pagination(report: dict) -> None:
    if (
        report.get("bookmark_pages") != {"CabinetSummary": 2, "CabinetBody": 3}
        or report.get("title_block_page", 1) != 1
    ):
        raise DocxGenerationError(
            "PAGE_LAYOUT_OVERFLOW",
            "首页或目录超出一页，请精简对应内容后重新生成；实际页码："
            + str(report.get("bookmark_pages")),
        )
