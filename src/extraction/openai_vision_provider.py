"""An AI vision extractor for scanned/photographed invoices (images).

This is the second provider that plugs into the same ``ExtractionProvider``
contract. Where pdfplumber reads embedded text, this one *looks* at the image
with a vision model and returns the same ``ExtractedInvoice`` shape — so the
rest of the pipeline can't tell the difference.

Design notes:
  * The API key and model name come from config (.env), never hardcoded.
  * The ``openai`` package is imported lazily inside ``extract`` so the project
    still runs for users who only use the free pdfplumber provider.
  * We ask the model for plain JSON and let Pydantic coerce/validate it.
  * It NEVER crashes on a bad response — failures come back as notes, honouring
    the provider contract.
"""
import base64
import json
from pathlib import Path

from config.settings import settings
from src.extraction.base import ExtractionProvider
from src.extraction.models import ExtractedInvoice, ExtractedLineItem
from src.utils.logger import get_logger

logger = get_logger("idp.extraction.openai")

# The exact JSON shape we ask the model to return. Strings everywhere keeps the
# model's job simple; Pydantic converts "39.60" -> Decimal and "2026-04-17" ->
# date for us when we build the ExtractedInvoice.
_SYSTEM_PROMPT = """You extract data from invoice images.
Return ONLY a JSON object with this exact shape (use null when a field is absent):
{
  "vendor_name": string|null,
  "vendor_tax_id": string|null,
  "invoice_number": string|null,
  "invoice_date": "YYYY-MM-DD"|null,
  "due_date": "YYYY-MM-DD"|null,
  "currency": "ISO code like USD"|null,
  "line_items": [
    {"description": string|null, "quantity": string|null,
     "unit_price": string|null, "line_total": string|null}
  ],
  "tax_amount": string|null,
  "grand_total": string|null
}
Rules: Dates must be ISO YYYY-MM-DD. Numbers must be plain decimals with no
currency symbols or thousands separators (e.g. "1234.50"). Never invent values."""


class OpenAIVisionProvider(ExtractionProvider):
    name = "openai-vision"
    supported_content_types = {"image/png", "image/jpeg"}

    def __init__(self) -> None:
        self._api_key = settings.OPENAI_API_KEY
        self._model = settings.OPENAI_MODEL

    def extract(self, doc_id: str, file_path: Path, content_type: str) -> ExtractedInvoice:
        """Read an image file from disk and extract it."""
        return self.extract_from_bytes(doc_id, file_path.read_bytes(), content_type)

    def extract_from_bytes(
        self, doc_id: str, image_bytes: bytes, content_type: str
    ) -> ExtractedInvoice:
        """Extract from raw image bytes — works whether the image came from a
        file on disk or was rendered in-memory from a scanned PDF."""
        # Fail gracefully if the project isn't configured for AI extraction.
        if not self._api_key:
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=["OPENAI_API_KEY is not set; cannot run AI extraction."],
            )
        try:
            from openai import OpenAI  # lazy import: optional dependency
        except ImportError:
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=["The 'openai' package is not installed."],
            )

        logger.info("Document %s: extracting with %s", doc_id, self._model)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{content_type};base64,{b64}"

        try:
            client = OpenAI(api_key=self._api_key)
            response = client.chat.completions.create(
                model=self._model,
                temperature=0,  # deterministic extraction, not creativity
                response_format={"type": "json_object"},  # force valid JSON
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract this invoice as JSON."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]},
                ],
            )
            content = response.choices[0].message.content
        except Exception as exc:  # network, auth, rate-limit, etc.
            logger.exception("Document %s: OpenAI request failed", doc_id)
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=[f"AI request failed: {exc}"],
            )

        return self._json_to_invoice(doc_id, content)

    def _json_to_invoice(self, doc_id: str, content: str) -> ExtractedInvoice:
        """Turn the model's JSON string into a validated ExtractedInvoice.

        Separated out so it can be unit-tested with a mock response — no API
        call or network required.
        """
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=["AI returned output that was not valid JSON."],
            )

        try:
            items = [ExtractedLineItem(**row) for row in (data.get("line_items") or [])]
            invoice = ExtractedInvoice(
                doc_id=doc_id,
                extracted_by=self.name,
                vendor_name=data.get("vendor_name"),
                vendor_tax_id=data.get("vendor_tax_id"),
                invoice_number=data.get("invoice_number"),
                invoice_date=data.get("invoice_date"),
                due_date=data.get("due_date"),
                currency=data.get("currency"),
                line_items=items,
                tax_amount=data.get("tax_amount"),
                grand_total=data.get("grand_total"),
            )
        except Exception as exc:  # Pydantic validation/coercion failure
            return ExtractedInvoice(
                doc_id=doc_id, extracted_by=self.name,
                notes=[f"AI output did not fit the schema: {exc}"],
            )

        logger.info(
            "Document %s: AI extracted vendor=%r total=%s items=%d",
            doc_id, invoice.vendor_name, invoice.grand_total, len(invoice.line_items),
        )
        return invoice