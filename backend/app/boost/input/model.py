"""Compatibility exports for the unchanged boost input contract."""
from ...document_common.model import (
    ERROR,
    WARNING,
    Chapter,
    DocumentModel,
    Heading,
    Image,
    ImageRef,
    Issue,
    Item,
    ListBlock,
    ListItem,
    Paragraph,
    Table,
    TableCell,
    _item_from_dict,
    _item_to_dict,
)

BoostDocument = DocumentModel

__all__ = ['ERROR', 'WARNING', 'BoostDocument', 'Chapter', 'DocumentModel', 'Heading', 'Image', 'ImageRef', 'Issue', 'Item', 'ListBlock', 'ListItem', 'Paragraph', 'Table', 'TableCell', '_item_from_dict', '_item_to_dict']
