"""Tests for the ingestion layer. Run with: pytest -q"""
import pytest

from src.ingestion.ingestor import Ingestor
from src.ingestion.models import IngestionStatus, RejectionReason
from src.ingestion.validator import (
    ValidationError,
    sanitize_filename,
    validate,
)

# --- Minimal but valid file payloads for each type ----------------------
PDF_BYTES = b"%PDF-1.4\n" + b"x" * 200
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 200
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"x" * 200


def test_sanitize_blocks_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("my invoice!.pdf") == "my_invoice_.pdf"
    assert sanitize_filename("") == "unnamed"


@pytest.mark.parametrize(
    "name,data,mime",
    [
        ("invoice.pdf", PDF_BYTES, "application/pdf"),
        ("scan.png", PNG_BYTES, "image/png"),
        ("photo.jpg", JPEG_BYTES, "image/jpeg"),
        ("photo.JPEG", JPEG_BYTES, "image/jpeg"),
    ],
)
def test_valid_files_pass(name, data, mime):
    assert validate(name, data) == mime


def test_empty_file_rejected():
    with pytest.raises(ValidationError) as e:
        validate("invoice.pdf", b"%PDF")
    assert e.value.reason is RejectionReason.EMPTY_FILE


def test_oversize_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "MAX_FILE_SIZE_BYTES", 50)
    with pytest.raises(ValidationError) as e:
        validate("invoice.pdf", PDF_BYTES)
    assert e.value.reason is RejectionReason.FILE_TOO_LARGE


def test_bad_extension_rejected():
    with pytest.raises(ValidationError) as e:
        validate("invoice.exe", PDF_BYTES)
    assert e.value.reason is RejectionReason.UNSUPPORTED_EXTENSION


def test_extension_spoofing_rejected():
    # PNG bytes wearing a .pdf extension must be caught.
    with pytest.raises(ValidationError) as e:
        validate("invoice.pdf", PNG_BYTES)
    assert e.value.reason is RejectionReason.CONTENT_MISMATCH


def test_ingestor_happy_path(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path)
    rec = Ingestor().ingest("invoice.pdf", PDF_BYTES)
    assert rec.status is IngestionStatus.INGESTED
    assert rec.doc_id in rec.stored_path
    assert (tmp_path / f"{rec.doc_id}__invoice.pdf").exists()


def test_ingestor_rejects_without_raising(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path)
    rec = Ingestor().ingest("invoice.exe", PDF_BYTES)
    assert rec.status is IngestionStatus.REJECTED
    assert rec.rejection_reason is RejectionReason.UNSUPPORTED_EXTENSION
