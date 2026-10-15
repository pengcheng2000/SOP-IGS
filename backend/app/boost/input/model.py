"""Intermediate document model for the boost-integrated-unit workbook.

The model is independent of both Excel and Word: the interpreter produces it from a
workbook, the DOCX builder consumes it, and it is stored as JSON in uploads and snapshots.
Every item keeps `src` ("Sheet!B12") so problems can be traced back to the workbook.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    severity: str
    code: str
    message: str
    sheet: str = ""
    cell: str = ""

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message,
                "sheet": self.sheet, "cell": self.cell}

    @classmethod
    def from_dict(cls, data: dict) -> Issue:
        return cls(data["severity"], data["code"], data["message"], data.get("sheet", ""), data.get("cell", ""))


@dataclass(frozen=True, slots=True)
class ImageRef:
    id: str
    path: str
    sha256: str
    px_w: int
    px_h: int

    def to_dict(self) -> dict:
        return {"id": self.id, "path": self.path, "sha256": self.sha256, "px_w": self.px_w, "px_h": self.px_h}

    @classmethod
    def from_dict(cls, data: dict) -> ImageRef:
        return cls(data["id"], data["path"], data["sha256"], int(data["px_w"]), int(data["px_h"]))


@dataclass(frozen=True, slots=True)
class Heading:
    level: int  # 3 = 5.x.y, 4 = 5.x.y.z
    text: str
    src: str = ""


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str
    kind: str = "body"  # body | indent | note
    src: str = ""


@dataclass(frozen=True, slots=True)
class ListItem:
    text: str
    level: int = 0
    src: str = ""


@dataclass(frozen=True, slots=True)
class ListBlock:
    style: str  # decimal | letter | bullet
    items: tuple[ListItem, ...]
    src: str = ""
    continues: bool = False  # keep numbering from the previous list of the same style


@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    col: int
    col_span: int = 1
    row_span: int = 1
    images: tuple[ImageRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Table:
    col_widths: tuple[float, ...]
    rows: tuple[tuple[TableCell, ...], ...]  # covered cells are omitted
    header_rows: int = 0
    src: str = ""


@dataclass(frozen=True, slots=True)
class Image:
    ref: ImageRef
    src: str = ""


Item = Heading | Paragraph | ListBlock | Table | Image


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    sheet: str
    items: tuple[Item, ...] = ()


@dataclass(frozen=True, slots=True)
class BoostDocument:
    chapters: tuple[Chapter, ...]
    revision_history: tuple[str, ...] = ()
    parser_version: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "parser_version": self.parser_version,
            "revision_history": list(self.revision_history),
            "chapters": [
                {"title": chapter.title, "sheet": chapter.sheet, "items": [_item_to_dict(item) for item in chapter.items]}
                for chapter in self.chapters
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> BoostDocument:
        return cls(
            chapters=tuple(
                Chapter(chapter["title"], chapter.get("sheet", ""), tuple(_item_from_dict(item) for item in chapter["items"]))
                for chapter in data.get("chapters", [])
            ),
            revision_history=tuple(data.get("revision_history", [])),
            parser_version=data.get("parser_version", ""),
        )

    def image_refs(self) -> list[ImageRef]:
        refs: list[ImageRef] = []
        for chapter in self.chapters:
            for item in chapter.items:
                if isinstance(item, Image):
                    refs.append(item.ref)
                elif isinstance(item, Table):
                    refs.extend(image for row in item.rows for cell in row for image in cell.images)
        return refs

    def summary(self) -> dict:
        items = [item for chapter in self.chapters for item in chapter.items]
        return {
            "chapter_count": len(self.chapters),
            "heading_count": sum(isinstance(item, Heading) for item in items),
            "table_count": sum(isinstance(item, Table) for item in items),
            "image_count": len(self.image_refs()),
        }


def _item_to_dict(item: Item) -> dict:
    if isinstance(item, Heading):
        return {"type": "heading", "level": item.level, "text": item.text, "src": item.src}
    if isinstance(item, Paragraph):
        return {"type": "paragraph", "kind": item.kind, "text": item.text, "src": item.src}
    if isinstance(item, ListBlock):
        return {"type": "list", "style": item.style, "src": item.src, "continues": item.continues,
                "items": [{"text": entry.text, "level": entry.level, "src": entry.src} for entry in item.items]}
    if isinstance(item, Table):
        return {
            "type": "table",
            "col_widths": list(item.col_widths),
            "header_rows": item.header_rows,
            "src": item.src,
            "rows": [
                [
                    {"text": cell.text, "col": cell.col, "col_span": cell.col_span, "row_span": cell.row_span,
                     "images": [image.to_dict() for image in cell.images]}
                    for cell in row
                ]
                for row in item.rows
            ],
        }
    if isinstance(item, Image):
        return {"type": "image", "ref": item.ref.to_dict(), "src": item.src}
    raise TypeError(f"unsupported item: {item!r}")


def _item_from_dict(data: dict) -> Item:
    kind = data["type"]
    if kind == "heading":
        return Heading(int(data["level"]), data["text"], data.get("src", ""))
    if kind == "paragraph":
        return Paragraph(data["text"], data.get("kind", "body"), data.get("src", ""))
    if kind == "list":
        return ListBlock(
            data["style"],
            tuple(ListItem(entry["text"], int(entry.get("level", 0)), entry.get("src", "")) for entry in data["items"]),
            data.get("src", ""),
            bool(data.get("continues", False)),
        )
    if kind == "table":
        return Table(
            tuple(float(width) for width in data["col_widths"]),
            tuple(
                tuple(
                    TableCell(cell["text"], int(cell["col"]), int(cell.get("col_span", 1)), int(cell.get("row_span", 1)),
                              tuple(ImageRef.from_dict(image) for image in cell.get("images", [])))
                    for cell in row
                )
                for row in data["rows"]
            ),
            int(data.get("header_rows", 0)),
            data.get("src", ""),
        )
    if kind == "image":
        return Image(ImageRef.from_dict(data["ref"]), data.get("src", ""))
    raise ValueError(f"unsupported item type: {kind}")
