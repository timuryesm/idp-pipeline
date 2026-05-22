"""Strict, defensive file validation.

We do **not** trust the file extension alone — that is trivially spoofed
(``malware.exe`` renamed to ``invoice.pdf``). Instead we sniff the leading
"magic bytes" of the payload and confirm the real content type matches the
declared extension. We also block path traversal in the supplied filename.
"""
import re
from pathlib import Path

from config.settings import settings
from src.ingestion.models import RejectionReason

# Leading byte signatures for each MIME type we accept.
_SIGNATURES = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
}

# Map the trusted extensions to the MIME type we expect the bytes to prove.
_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Everything that is not an alphanumeric, dot, dash or underscore gets replaced.
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class ValidationError(Exception):
    """Raised when a file fails any validation gate."""

    def __init__(self, reason: RejectionReason, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(detail)


def sanitize_filename(name: str) -> str:
    """Strip directory components (anti path-traversal) and unsafe characters."""
    # Path(...).name discards anything like ``../../etc/passwd`` -> ``passwd``.
    base = Path(name).name
    cleaned = _UNSAFE_CHARS.sub("_", base).lstrip(".")
    return cleaned or "unnamed"


def detect_content_type(data: bytes) -> str | None:
    """Return the real MIME type from magic bytes, or None if unrecognised."""
    for mime, signatures in _SIGNATURES.items():
        if any(data.startswith(sig) for sig in signatures):
            return mime
    return None


def validate(filename: str, data: bytes) -> str:
    """Run every gate. Returns the verified MIME type, or raises ValidationError.

    Gates, in order:
      1. Not empty / corrupt (size floor)
      2. Not oversized (size ceiling)
      3. Extension is on the allow-list
      4. Magic bytes are recognised
      5. Magic bytes match the declared extension (no spoofing)
    """
    size = len(data)

    if size < settings.MIN_FILE_SIZE_BYTES:
        raise ValidationError(
            RejectionReason.EMPTY_FILE,
            f"File is {size} bytes; minimum is {settings.MIN_FILE_SIZE_BYTES}.",
        )

    if size > settings.MAX_FILE_SIZE_BYTES:
        raise ValidationError(
            RejectionReason.FILE_TOO_LARGE,
            f"File is {size / 1_048_576:.2f} MB; limit is "
            f"{settings.MAX_FILE_SIZE_MB} MB.",
        )

    ext = Path(filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise ValidationError(
            RejectionReason.UNSUPPORTED_EXTENSION,
            f"Extension {ext!r} is not allowed. "
            f"Allowed: {sorted(settings.ALLOWED_EXTENSIONS)}.",
        )

    detected = detect_content_type(data)
    if detected is None:
        raise ValidationError(
            RejectionReason.CONTENT_MISMATCH,
            "File content does not match any supported document type.",
        )

    expected = _EXT_TO_MIME[ext]
    if detected != expected:
        raise ValidationError(
            RejectionReason.CONTENT_MISMATCH,
            f"Extension {ext!r} claims {expected} but the bytes are {detected}.",
        )

    return detected
