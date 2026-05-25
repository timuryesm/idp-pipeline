"""The extractor contract — the 'plug shape' for behaviour.

``ExtractedInvoice`` (in models.py) defined the shape of the *output*. This
file defines the shape of the *extractor itself*: any class that wants to count
as an extractor must inherit from ``ExtractionProvider`` and implement
``extract()``. Python enforces this at runtime — a subclass that forgets
``extract()`` cannot even be instantiated.

This is the Strategy pattern: the pipeline depends on this abstract contract,
never on a concrete extractor, so providers can be swapped freely.
"""
from abc import ABC, abstractmethod
from pathlib import Path

from src.extraction.models import ExtractedInvoice


class ExtractionProvider(ABC):
    """Base class every concrete extractor must inherit from."""

    #: Short identifier, recorded in ExtractedInvoice.extracted_by
    name: str = "base"

    #: The MIME types this provider can handle (filled in by subclasses)
    supported_content_types: set[str] = set()

    def supports(self, content_type: str) -> bool:
        """Can this provider handle a file of the given MIME type?"""
        return content_type in self.supported_content_types

    @abstractmethod
    def extract(
        self, doc_id: str, file_path: Path, content_type: str
    ) -> ExtractedInvoice:
        """Read the document and return a best-effort ``ExtractedInvoice``.

        Contract for implementers:
          * ``doc_id`` and the provider's ``name`` MUST be copied into the result.
          * A readable-but-messy document MUST NOT raise — return an
            ``ExtractedInvoice`` with explanatory ``notes`` instead.
          * Raise only for genuinely unreadable input (e.g. missing file).
        """
        ...