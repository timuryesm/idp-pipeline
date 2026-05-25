"""The data contract for extraction.

Every extractor — the free pdfplumber one, the AI ones later — must return an
``ExtractedInvoice``. This is the "plug shape": the pipeline depends on *this*,
not on any specific extractor.

IMPORTANT: this is the *raw, best-effort* result. Every field is optional
because extraction can fail to find things. We do NOT check the math here —
that is Step 3's job (the strict, validated model). Keeping extraction lenient
and validation strict is a deliberate separation of concerns.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ExtractedLineItem(BaseModel):
    """One row from the invoice's table of goods/services."""

    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None


class ExtractedInvoice(BaseModel):
    """Everything an extractor managed to pull out of one document."""

    # --- Linkage back to Step 1 (always present) --------------------------
    doc_id: str = Field(..., description="The UUID assigned during ingestion")
    extracted_by: str = Field(..., description="Which provider produced this, e.g. 'pdfplumber'")

    # --- Header fields (best-effort, may be missing) ----------------------
    vendor_name: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    currency: Optional[str] = None

    # --- Money (Decimal, never float) --------------------
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    tax_amount: Optional[Decimal] = None
    grand_total: Optional[Decimal] = None

    # --- Aids for debugging and the future human-review screen ------------
    raw_text: Optional[str] = Field(
        default=None, description="The source text we parsed, kept for review"
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Anything the extractor wants to flag, e.g. 'date format unclear'",
    )