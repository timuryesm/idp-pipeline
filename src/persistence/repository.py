"""The invoice repository — the ONLY place that touches the database.

Uses Python's built-in sqlite3. Each invoice is one row: a few queryable scalar
columns (for the dashboard's fast aggregations) plus two JSON columns holding
the complete ExtractedInvoice and ValidationResult (for the detail screen).
Swapping to PostgreSQL later would mean changing only this file.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from config.settings import settings
from src.extraction.models import ExtractedInvoice
from src.persistence.models import InvoiceSummary, StoredInvoice
from src.utils.logger import get_logger
from src.validation.models import ValidationResult

logger = get_logger("idp.persistence")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    doc_id          TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    extracted_by    TEXT,
    vendor_name     TEXT,
    currency        TEXT,
    invoice_date    TEXT,
    grand_total     TEXT,
    status          TEXT NOT NULL,
    error_count     INTEGER NOT NULL DEFAULT 0,
    processed_at    TEXT NOT NULL,
    invoice_json    TEXT NOT NULL,
    validation_json TEXT NOT NULL
)
"""


class InvoiceRepository:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or settings.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, and always close it."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # access columns by name
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def save(
        self,
        extracted: ExtractedInvoice,
        validation: ValidationResult,
        original_filename: str,
    ) -> None:
        """Insert or replace one processed invoice."""
        processed_at = datetime.now(timezone.utc).isoformat()
        row = (
            extracted.doc_id,
            original_filename,
            extracted.extracted_by,
            extracted.vendor_name,
            extracted.currency,
            extracted.invoice_date.isoformat() if extracted.invoice_date else None,
            str(extracted.grand_total) if extracted.grand_total is not None else None,
            validation.status.value,
            len(validation.errors),
            processed_at,
            extracted.model_dump_json(),
            validation.model_dump_json(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO invoices
                   (doc_id, original_filename, extracted_by, vendor_name, currency,
                    invoice_date, grand_total, status, error_count, processed_at,
                    invoice_json, validation_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        logger.info("Document %s saved (%s)", extracted.doc_id, validation.status.value)

    def list_summaries(self) -> list[InvoiceSummary]:
        """All invoices as lightweight rows, newest first (for the dashboard)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT doc_id, original_filename, vendor_name, currency, grand_total,
                          invoice_date, status, error_count, processed_at
                   FROM invoices ORDER BY processed_at DESC"""
            ).fetchall()
        # Pydantic coerces the stored strings back into Decimal/date/datetime/enum.
        return [InvoiceSummary(**dict(r)) for r in rows]

    def get(self, doc_id: str) -> Optional[StoredInvoice]:
        """One full record (extraction + validation) for the detail screen."""
        with self._connect() as conn:
            r = conn.execute(
                """SELECT doc_id, original_filename, processed_at, invoice_json, validation_json
                   FROM invoices WHERE doc_id = ?""",
                (doc_id,),
            ).fetchone()
        if r is None:
            return None
        return StoredInvoice(
            doc_id=r["doc_id"],
            original_filename=r["original_filename"],
            processed_at=r["processed_at"],
            extracted=ExtractedInvoice.model_validate_json(r["invoice_json"]),
            validation=ValidationResult.model_validate_json(r["validation_json"]),
        )