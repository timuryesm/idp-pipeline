"""A free, no-API extractor for text-based PDFs, built on pdfplumber.

What it does: opens the PDF, pulls out all the embedded text and any tables,
then uses label-based pattern matching to find the common invoice fields. It is
deliberately *honest* about its limits — when it can't find or read something it
leaves the field as ``None`` and records a note, rather than guessing. Scanned
or photographed invoices (no embedded text) come back nearly empty with a note
recommending the AI extractor.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pdfplumber
from dateutil import parser as date_parser

from src.extraction.base import ExtractionProvider
from src.extraction.models import ExtractedInvoice, ExtractedLineItem
from src.utils.logger import get_logger

logger = get_logger("idp.extraction.pdfplumber")

# Currency symbols/codes we recognise, mapped to a 3-letter code.
_CURRENCY_HINTS = {"$": "USD", "US$": "USD", "USD": "USD", "€": "EUR",
                   "EUR": "EUR", "£": "GBP", "GBP": "GBP"}


# --------------------------------------------------------------------------
# Small, single-purpose parsing helpers (pure functions, easy to test)
# --------------------------------------------------------------------------
def _to_decimal(raw: str) -> Optional[Decimal]:
    """Turn a money string like '$1,234.50' or '-$18.20' into a Decimal."""
    if raw is None:
        return None
    raw = raw.replace("\u2212", "-")  # normalise Unicode minus (−) to ASCII -
    cleaned = re.sub(r"[^0-9.\-]", "", raw)  # strip $, commas, spaces, etc.
    if cleaned in ("", "-", "."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _find_label(text: str, labels: list[str]) -> Optional[str]:
    """Return the value following any of the given labels on the same line.

    e.g. labels=['invoice number','invoice no'] matches 'Invoice Number: INV-1'
    and returns 'INV-1'.
    """
    for label in labels:
        # label, optional ':' or '#', then capture the rest of the line
        pattern = rf"{re.escape(label)}\s*[:#]?\s*(.+)"
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _find_amount(text: str, labels: list[str]) -> Optional[Decimal]:
    """Find a money amount that follows one of the labels.

    The value must *look like money* (optional currency symbol + digits) right
    after the label. This stops 'Tax' from wrongly matching 'Tax ID: 99-123...'.
    """
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:#]?\s*([-\u2212]?\s*[$€£]?\s*[\d,]+(?:\.\d+)?)"
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _to_decimal(m.group(1))
            if value is not None:
                return value
    return None


def _find_date(text: str, labels: list[str]) -> Optional[date]:
    """Find and parse a date following one of the labels."""
    value = _find_label(text, labels)
    if not value:
        return None
    try:
        # dateutil handles 'April 17, 2026', '2026-04-17', '17/04/2026', etc.
        return date_parser.parse(value, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def _detect_currency(text: str) -> Optional[str]:
    for hint, code in _CURRENCY_HINTS.items():
        if hint in text:
            return code
    return None


def _parse_line_items(tables: list) -> tuple[list[ExtractedLineItem], list[str]]:
    """Best-effort: map the biggest table's rows to line items by header names."""
    notes: list[str] = []
    if not tables:
        return [], ["No tables found; line items not extracted."]

    # Use the table with the most rows — usually the line-item table.
    table = max(tables, key=len)
    if len(table) < 2:
        return [], ["Largest table had no data rows."]

    header = [(c or "").strip().lower() for c in table[0]]

    def col(*keywords) -> Optional[int]:
        for i, name in enumerate(header):
            if any(k in name for k in keywords):
                return i
        return None

    i_desc = col("description", "item", "product")
    i_qty = col("quantity", "qty")
    i_price = col("unit price", "price", "rate")
    i_total = col("amount", "total", "line total")

    if i_desc is None and i_total is None:
        return [], ["Could not identify line-item columns by header."]

    items: list[ExtractedLineItem] = []
    for row in table[1:]:
        def cell(idx):
            return row[idx] if idx is not None and idx < len(row) else None
        items.append(ExtractedLineItem(
            description=(cell(i_desc) or "").strip() or None,
            quantity=_to_decimal(cell(i_qty)),
            unit_price=_to_decimal(cell(i_price)),
            line_total=_to_decimal(cell(i_total)),
        ))
    return items, notes


# --------------------------------------------------------------------------
# The provider
# --------------------------------------------------------------------------
class PdfPlumberProvider(ExtractionProvider):
    name = "pdfplumber"
    supported_content_types = {"application/pdf"}

    def extract(self, doc_id: str, file_path: Path, content_type: str) -> ExtractedInvoice:
        logger.info("Document %s: extracting with pdfplumber", doc_id)
        notes: list[str] = []

        # Open and pull text + tables from every page.
        text_parts: list[str] = []
        tables: list = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
                tables.extend(page.extract_tables() or [])
        full_text = "\n".join(text_parts).strip()

        # No embedded text == almost certainly a scan/photo. Bail out honestly.
        if not full_text:
            logger.warning("Document %s: no extractable text (likely scanned)", doc_id)
            return ExtractedInvoice(
                doc_id=doc_id,
                extracted_by=self.name,
                notes=["No embedded text found — likely a scanned image. "
                       "Route to an AI vision extractor."],
            )

        line_items, item_notes = _parse_line_items(tables)
        notes.extend(item_notes)

        # The first non-empty line is a decent guess at the vendor name.
        vendor = next((ln.strip() for ln in full_text.splitlines() if ln.strip()), None)
        if vendor:
            notes.append("Vendor name guessed from first line; verify.")

        # Discount is stored as a positive magnitude (schema convention), so we
        # take abs() of whatever we find (the document may show it negative).
        discount = _find_amount(full_text, ["discount"])
        if discount is not None:
            discount = abs(discount)

        invoice = ExtractedInvoice(
            doc_id=doc_id,
            extracted_by=self.name,
            vendor_name=vendor,
            vendor_tax_id=_find_label(full_text, ["tax id", "vat", "ein"]),
            invoice_number=_find_label(full_text, ["invoice number", "invoice no", "invoice #"]),
            invoice_date=_find_date(full_text, ["invoice date", "date of issue", "date"]),
            due_date=_find_date(full_text, ["due date", "payment due"]),
            currency=_detect_currency(full_text),
            line_items=line_items,
            subtotal=_find_amount(full_text, ["subtotal"]),
            shipping=_find_amount(full_text, ["shipping & handling", "shipping and handling", "shipping"]),
            discount=discount,
            # adjustments left to the AI provider; pdfplumber can't reliably net
            # refund/fee lines, so we leave it None and let Step 3 flag residuals.
            tax_amount=_find_amount(full_text, ["tax", "vat", "gst"]),
            grand_total=_find_amount(full_text, ["grand total", "total due", "amount due", "total"]),
            raw_text=full_text,
            notes=notes,
        )
        logger.info(
            "Document %s: extracted vendor=%r total=%s items=%d",
            doc_id, invoice.vendor_name, invoice.grand_total, len(invoice.line_items),
        )
        return invoice