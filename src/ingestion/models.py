"""Data contracts for the ingestion layer.

A ``DocumentRecord`` is the single source of truth for what happened to a file
as it entered the pipeline. Downstream steps (extraction, validation,
analytics) will attach to this same ``doc_id``.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IngestionStatus(str, Enum):
    INGESTED = "INGESTED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_EXTENSION = "UNSUPPORTED_EXTENSION"
    CONTENT_MISMATCH = "CONTENT_MISMATCH"  # extension lies about the real bytes
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class DocumentRecord(BaseModel):
    """The receipt for every file the pipeline sees — accepted or not."""

    doc_id: str = Field(..., description="UUIDv4 tracking ID for the whole pipeline")
    original_filename: str
    sanitized_filename: Optional[str] = None
    stored_path: Optional[str] = None
    content_type: Optional[str] = None
    file_size_bytes: int = 0
    status: IngestionStatus
    rejection_reason: Optional[RejectionReason] = None
    detail: Optional[str] = None
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def ok(self) -> bool:
        return self.status is IngestionStatus.INGESTED
