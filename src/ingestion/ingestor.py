"""The ingestion orchestrator.

Public API is a single method, :meth:`Ingestor.ingest`, which takes a filename
and raw bytes and returns a :class:`DocumentRecord`. It never raises on bad
input — invalid files come back as a ``REJECTED`` record so the caller (the UI
or a watch-folder worker) can decide what to do.
"""
import uuid

from config.settings import settings
from src.ingestion.models import DocumentRecord, IngestionStatus, RejectionReason
from src.ingestion.validator import ValidationError, sanitize_filename, validate
from src.utils.logger import get_logger

logger = get_logger("idp.ingestion")


class Ingestor:
    def __init__(self) -> None:
        # Ensure storage directories exist on startup.
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        settings.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Ingestor ready | uploads=%s | quarantine=%s | max_size=%sMB",
            settings.UPLOAD_DIR,
            settings.QUARANTINE_DIR,
            settings.MAX_FILE_SIZE_MB,
        )

    def ingest(self, filename: str, data: bytes) -> DocumentRecord:
        """Validate, assign a tracking ID, and securely store one document."""
        doc_id = str(uuid.uuid4())
        logger.info(
            "Document %s received | name=%r | size=%d bytes",
            doc_id,
            filename,
            len(data),
        )

        # --- Gate 1: validation -------------------------------------------
        try:
            content_type = validate(filename, data)
        except ValidationError as exc:
            logger.error(
                "Document %s REJECTED | reason=%s | %s",
                doc_id,
                exc.reason.value,
                exc.detail,
            )
            return DocumentRecord(
                doc_id=doc_id,
                original_filename=filename,
                file_size_bytes=len(data),
                status=IngestionStatus.REJECTED,
                rejection_reason=exc.reason,
                detail=exc.detail,
            )
        except Exception as exc:  # defensive catch-all
            logger.exception("Document %s failed unexpectedly", doc_id)
            return DocumentRecord(
                doc_id=doc_id,
                original_filename=filename,
                file_size_bytes=len(data),
                status=IngestionStatus.REJECTED,
                rejection_reason=RejectionReason.UNKNOWN_ERROR,
                detail=str(exc),
            )

        # --- Gate 2: secure storage ---------------------------------------
        sanitized = sanitize_filename(filename)
        # Prefix with the UUID so two files named "invoice.pdf" never collide.
        stored_name = f"{doc_id}__{sanitized}"
        stored_path = settings.UPLOAD_DIR / stored_name
        try:
            stored_path.write_bytes(data)
        except OSError as exc:
            logger.exception("Document %s could not be written to disk", doc_id)
            return DocumentRecord(
                doc_id=doc_id,
                original_filename=filename,
                sanitized_filename=sanitized,
                content_type=content_type,
                file_size_bytes=len(data),
                status=IngestionStatus.REJECTED,
                rejection_reason=RejectionReason.UNKNOWN_ERROR,
                detail=f"Storage error: {exc}",
            )

        logger.info(
            "Document %s INGESTED | type=%s | stored=%s",
            doc_id,
            content_type,
            stored_path.name,
        )
        return DocumentRecord(
            doc_id=doc_id,
            original_filename=filename,
            sanitized_filename=sanitized,
            stored_path=str(stored_path),
            content_type=content_type,
            file_size_bytes=len(data),
            status=IngestionStatus.INGESTED,
        )
