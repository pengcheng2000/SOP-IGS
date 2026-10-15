from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...services.image_pipeline import process_image
from .interpreter import PARSER_VERSION, interpret_workbook
from .model import ERROR, BoostDocument, ImageRef, Issue
from .workbook import SheetImage, WorkbookError, read_workbook

__all__ = ["PARSER_VERSION", "ParseResult", "WorkbookError", "parse_workbook"]


@dataclass(frozen=True, slots=True)
class ParseResult:
    document: BoostDocument | None
    issues: tuple[Issue, ...]

    @property
    def valid(self) -> bool:
        return self.document is not None and not any(issue.severity == ERROR for issue in self.issues)

    def summary(self) -> dict:
        return self.document.summary() if self.document is not None else {}


def parse_workbook(
    path: Path,
    image_dir: Path,
    *,
    max_image_bytes: int = 30 * 1024 * 1024,
    max_image_pixels: int = 100_000_000,
    max_images: int = 150,
    revision_sheet: str = "版本修改记录",
    ignored_sheets: tuple[str, ...] = ("填写说明",),
) -> ParseResult:
    """Read and interpret a workbook; images are normalized and written to `image_dir`."""
    try:
        grids, issues = read_workbook(path)
    except WorkbookError as exc:
        return ParseResult(None, (Issue(ERROR, exc.code, str(exc)),))
    total_images = sum(len(grid.images) for grid in grids)
    if total_images > max_images:
        return ParseResult(None, (*issues, Issue(ERROR, "TOO_MANY_IMAGES", f"图片数量 {total_images} 超过上限 {max_images}")))

    image_dir.mkdir(parents=True, exist_ok=True)
    stored: list[ImageRef] = []

    def store_image(image: SheetImage) -> ImageRef:
        processed = process_image(image.data, max_bytes=max_image_bytes, max_pixels=max_image_pixels)
        index = len(stored) + 1
        target = image_dir / f"{index:03d}{processed.output_extension}"
        target.write_bytes(processed.data)
        width = image.display_w or processed.processed_width
        height = image.display_h or processed.processed_height
        ref = ImageRef(f"img{index:03d}", str(target.resolve()), processed.sha256, width, height)
        stored.append(ref)
        return ref

    document, interpretation_issues = interpret_workbook(
        grids, store_image, revision_sheet=revision_sheet, ignored_sheets=ignored_sheets
    )
    return ParseResult(document, (*issues, *interpretation_issues))
