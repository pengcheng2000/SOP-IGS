from ...document_common.validation import DocumentValidationError as BoostValidationError
from ...document_common.validation import validate_docx as validate_boost_docx

__all__ = ['BoostValidationError', 'validate_boost_docx']
