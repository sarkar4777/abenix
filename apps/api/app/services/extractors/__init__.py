"""Document extraction pipeline. One extractor class per modality;
the `dispatch` function picks the right one and falls back to OCR when
the text-only path returns near-empty content.

Extracts text, tables, and figure captions into a normalized
list of `ExtractedBlock` records that downstream chunking can consume
without caring how the bytes arrived.
"""

from .base import ExtractedBlock, Extractor
from .dispatch import extract_document

__all__ = ["ExtractedBlock", "Extractor", "extract_document"]
