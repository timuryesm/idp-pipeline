"""The pipeline orchestrator — the conductor that runs a document end to end.

process_document() chains every stage you've built:
    ingest (Step 1) -> extract (Step 2) -> validate (Step 3) -> save (persistence)

If a file is rejected at ingestion (wrong type, too big, spoofed), the pipeline
short-circuits: there's nothing to extract or validate, so it reports the
rejection and does not save anything.
"""
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.extraction.factory import get_provider
from src.ingestion.ingestor import Ingestor
from src.ingestion.models import IngestionStatus
from src.persistence.repository import InvoiceRepository
from src.utils.logger import get_logger
from src.validation.validator import validate

logger = get_logger("idp.pipeline")


class ProcessingResult(BaseModel):
    """A compact outcome for showing the user what happened to one upload."""

    doc_id: str
    original_filename: str
    status: str   # "REJECTED" | "APPROVED" | "NEEDS_REVIEW"
    detail: str


def process_document(
    filename: str, data: bytes, repo: Optional[InvoiceRepository] = None
) -> ProcessingResult:
    """Run one document through the whole pipeline and return the outcome."""
    repo = repo or InvoiceRepository()
    ingestor = Ingestor()

    # --- Stage 1: ingest -------------------------------------------------
    record = ingestor.ingest(filename, data)
    if record.status is IngestionStatus.REJECTED:
        logger.info("Document %s stopped at ingestion: %s", record.doc_id, record.rejection_reason)
        return ProcessingResult(
            doc_id=record.doc_id, original_filename=filename,
            status="REJECTED", detail=record.detail or "Rejected at ingestion.",
        )

    # --- Stage 2: extract (factory picks the provider by content type) ---
    provider = get_provider(record.content_type)
    extracted = provider.extract(record.doc_id, Path(record.stored_path), record.content_type)

    # --- Stage 3: validate ----------------------------------------------
    validation = validate(extracted)

    # --- Stage 4: persist ------------------------------------------------
    repo.save(extracted, validation, filename)

    detail = "; ".join(i.message for i in validation.errors) or "All checks passed."
    logger.info("Document %s processed end-to-end: %s", record.doc_id, validation.status.value)
    return ProcessingResult(
        doc_id=record.doc_id, original_filename=filename,
        status=validation.status.value, detail=detail,
    )