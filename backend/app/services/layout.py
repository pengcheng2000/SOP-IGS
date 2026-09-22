from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from math import exp, log

LAYOUT_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class LayoutPhoto:
    id: str
    width: int
    height: int
    caption: str = ""

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


@dataclass(frozen=True, slots=True)
class LayoutPage:
    rows: tuple[int, ...]
    score: float


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    pages: tuple[LayoutPage, ...]
    score: float
    version: str = LAYOUT_VERSION


def row_partitions(total: int, max_columns: int = 3, max_rows: int = 3) -> tuple[tuple[int, ...], ...]:
    result: list[tuple[int, ...]] = []

    def visit(remaining: int, parts: list[int]) -> None:
        if remaining == 0:
            result.append(tuple(parts))
            return
        if len(parts) >= max_rows:
            return
        for count in range(1, min(max_columns, remaining) + 1):
            visit(remaining - count, [*parts, count])

    visit(total, [])
    return tuple(result)


def _caption_lines(text: str, columns: int) -> int:
    if not text:
        return 0
    characters = max(8, 34 // columns)
    return min(5, (len(text) + characters - 1) // characters)


def score_candidate(photos: Sequence[LayoutPhoto], rows: tuple[int, ...]) -> float:
    page_width = 1.0
    page_height = 1.0
    row_height = page_height / len(rows)
    areas: list[float] = []
    aspect_scores: list[float] = []
    upscale_penalty = 0.0
    caption_penalty = 0.0
    offset = 0
    for columns in rows:
        cell_width = page_width / columns
        for photo in photos[offset : offset + columns]:
            caption_height = 0.035 * _caption_lines(photo.caption, columns)
            cell_height = max(0.08, row_height - caption_height)
            cell_ratio = cell_width / cell_height
            scale = min(cell_width / photo.width, cell_height / photo.height)
            display_width, display_height = photo.width * scale, photo.height * scale
            areas.append(display_width * display_height)
            mismatch = abs(log(max(photo.aspect_ratio, 0.01) / max(cell_ratio, 0.01)))
            aspect_scores.append(exp(-mismatch))
            if max(photo.width, photo.height) < 600:
                upscale_penalty += 0.15
            caption_penalty += max(0, _caption_lines(photo.caption, columns) - 3) / 10
        offset += columns

    used_area = sum(areas)
    visible_area = min(1.0, used_area)
    utilization = min(1.0, used_area / (page_width * page_height))
    aspect_fit = sum(aspect_scores) / max(1, len(aspect_scores))
    mean_area = used_area / max(1, len(areas))
    variance = sum((value - mean_area) ** 2 for value in areas) / max(1, len(areas))
    balance = 1.0 / (1.0 + variance / max(mean_area * mean_area, 1e-9))
    orphan_penalty = 0.12 if len(photos) == 1 else 0.0
    row_imbalance_penalty = (max(rows) - min(rows)) / 2 if len(rows) > 1 else 0.0
    return (
        0.35 * visible_area
        + 0.20 * utilization
        + 0.15 * aspect_fit
        + 0.10 * balance
        - 0.10 * min(1.0, upscale_penalty)
        - 0.05 * orphan_penalty
        - 0.05 * min(1.0, caption_penalty)
        - 0.18 * row_imbalance_penalty
    )


def plan_layout(photos: Sequence[LayoutPhoto], max_per_page: int = 6) -> LayoutPlan:
    if not photos:
        return LayoutPlan(pages=(), score=0.0)

    @cache
    def solve(start: int) -> tuple[float, tuple[LayoutPage, ...]]:
        if start >= len(photos):
            return 0.0, ()
        best_score = float("-inf")
        best_pages: tuple[LayoutPage, ...] = ()
        remaining = len(photos) - start
        for count in range(1, min(max_per_page, remaining) + 1):
            batch = photos[start : start + count]
            for rows in row_partitions(count):
                candidate_score = score_candidate(batch, rows)
                future_score, future_pages = solve(start + count)
                # Candidate rewards are page-local. A fixed cost greater than a typical
                # single-photo score prevents the global DP from maximizing page count.
                page_cost = 1.00
                total = candidate_score + future_score - page_cost
                if total > best_score:
                    best_score = total
                    best_pages = (LayoutPage(rows=rows, score=candidate_score), *future_pages)
        return best_score, best_pages

    score, pages = solve(0)
    return LayoutPlan(pages=pages, score=score)
