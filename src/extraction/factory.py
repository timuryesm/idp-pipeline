"""The provider factory — the single place that knows which extractor to use.

The pipeline should never import a concrete provider or write
``if content_type == 'application/pdf': ...``. Instead it asks the factory
"give me a provider for this file type" and gets back something that fits the
``ExtractionProvider`` contract. That keeps routing logic in ONE place.

Adding a new provider later means appending one line to ``_PROVIDERS`` — no
other file changes. (That's the "open for extension, closed for modification"
principle.)
"""
from src.extraction.base import ExtractionProvider
from src.extraction.openai_vision_provider import OpenAIVisionProvider
from src.extraction.smart_pdf_provider import SmartPdfProvider

# The registry of available providers. For a given content type, the first
# provider that supports it wins, so order = priority.
_PROVIDERS: list[ExtractionProvider] = [
    SmartPdfProvider(),       # PDFs: text first, AI-vision fallback for scans
    OpenAIVisionProvider(),   # PNG / JPEG -> AI vision
]


def get_provider(content_type: str) -> ExtractionProvider:
    """Return the right extractor for a file's content type.

    Raises ValueError if nothing can handle the type, so the caller fails
    loudly rather than silently doing nothing.
    """
    for provider in _PROVIDERS:
        if provider.supports(content_type):
            return provider
    raise ValueError(f"No extraction provider supports content type: {content_type!r}")