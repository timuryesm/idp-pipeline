"""The shapes of a stored invoice.

Two views of the same stored data:
  * ``InvoiceSummary`` — the lightweight row the dashboard's pipeline-queue table
    needs (vendor, total, status, date). Cheap to list many of.
  * ``StoredInvoice`` — the full record (extraction + validation) for the
    detail / review screen, where you need everything.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from src.extraction.models import ExtractedInvoice
from src.validation.models import ValidationResult, ValidationStatus


class InvoiceSummary(BaseModel):
    """One row in the dashboard's pipeline queue."""

    doc_id: str
    original_filename: str
    vendor_name: Optional[str] = None
    currency: Optional[str] = None
    grand_total: Optional[Decimal] = None
    invoice_date: Optional[date] = None
    status: ValidationStatus
    error_count: int = 0
    processed_at: datetime


class StoredInvoice(BaseModel):
    """The complete stored record, for the detail / human-review screen."""

    doc_id: str
    original_filename: str
    processed_at: datetime
    extracted: ExtractedInvoice
    validation: ValidationResult