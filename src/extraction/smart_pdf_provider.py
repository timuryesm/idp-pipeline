"""A 'smart' PDF extractor that handles BOTH text and scanned PDFs.

A scanned PDF and a text PDF are both 'application/pdf' — you can't tell them
apart by type, only by trying. So this provider:
  1. Tries the free pdfplumber text extractor first.
  2. If that comes back empty (a scanned/image-only PDF), it renders the first
     page to an image and hands it to the AI vision extractor.

This 'cheap method first, AI fallback' approach keeps costs near zero for the
common text-PDF case while still handling scans. It composes the two providers
we already built rather than duplicating their logic.
"""
from pathlib import Path

import pymupdf  # PyMuPDF — renders PDF pages to images

from src.extraction.base import ExtractionProvider
from src.extraction.models import ExtractedInvoice
from src.extraction.openai_vision_provider import OpenAIVisionProvider
from src.extraction.pdfplumber_provider import PdfPlumberProvider
from src.utils.logger import get_logger

logger = get_logger("idp.extraction.smartpdf")


def _has_content(invoice: ExtractedInvoice) -> bool:
    """Did text extraction actually find anything useful?"""
    return bool(invoice.line_items) or invoice.grand_total is not None \
        or invoice.vendor_name is not None


def _render_first_page_to_png(file_path: Path) -> bytes:
    """Rasterise page 1 of the PDF to PNG bytes (in memory)."""
    with pymupdf.open(file_path) as doc:
        pixmap = doc[0].get_pixmap(dpi=150)  # 150 dpi is plenty for vision
        return pixmap.tobytes("png")


class SmartPdfProvider(ExtractionProvider):
    name = "smart-pdf"
    supported_content_types = {"application/pdf"}

    def __init__(self) -> None:
        self._text = PdfPlumberProvider()
        self._vision = OpenAIVisionProvider()

    def extract(self, doc_id: str, file_path: Path, content_type: str) -> ExtractedInvoice:
        # Step 1: try the cheap, free text extractor.
        result = self._text.extract(doc_id, file_path, content_type)
        if _has_content(result):
            return result

        # Step 2: no embedded text -> scanned PDF. Render to image, use vision.
        logger.info("Document %s: PDF has no text, falling back to AI vision", doc_id)
        try:
            png_bytes = _render_first_page_to_png(file_path)
        except Exception as exc:  # corrupt/unreadable PDF
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=[f"Could not render PDF to image: {exc}"],
            )

        result = self._vision.extract_from_bytes(doc_id, png_bytes, "image/png")
        result.notes.append("Text extraction was empty; used AI vision on the rendered page.")
        return result