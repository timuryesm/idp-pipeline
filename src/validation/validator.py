"""The validator — runs every check and produces the final verdict.

It does three things:
  1. Folds the extractor's own notes in as warnings (context for the reviewer).
  2. Runs every registered check and collects all issues.
  3. Stamps the status: any ERROR -> NEEDS_REVIEW, otherwise APPROVED.
"""
from src.extraction.models import ExtractedInvoice
from src.utils.logger import get_logger
from src.validation.checks import (
    check_dates,
    check_line_item_math,
    check_subtotal_matches_lines,
    check_total_reconciliation,
)
from src.validation.models import (
    Severity,
    ValidationIssue,
    ValidationResult,
    ValidationStatus,
)

logger = get_logger("idp.validation")

# The checks to run. Adding a new rule later = append it here, nothing else.
_CHECKS = [
    check_line_item_math,
    check_subtotal_matches_lines,
    check_total_reconciliation,
    check_dates,
]


def validate(invoice: ExtractedInvoice) -> ValidationResult:
    """Validate one extracted invoice and return the verdict."""
    issues: list[ValidationIssue] = []

    # 1. Surface the extractor's own notes (e.g. "vendor guessed") as warnings.
    for note in invoice.notes:
        issues.append(ValidationIssue(
            code="EXTRACTION_NOTE", message=note, severity=Severity.WARNING,
        ))

    # 2. Run every check and gather its findings.
    for check in _CHECKS:
        issues.extend(check(invoice))

    # 3. Verdict: a single ERROR is enough to require human review.
    has_error = any(i.severity is Severity.ERROR for i in issues)
    status = ValidationStatus.NEEDS_REVIEW if has_error else ValidationStatus.APPROVED

    n_err = sum(i.severity is Severity.ERROR for i in issues)
    n_warn = sum(i.severity is Severity.WARNING for i in issues)
    logger.info(
        "Document %s validated: %s (%d errors, %d warnings)",
        invoice.doc_id, status.value, n_err, n_warn,
    )
    return ValidationResult(doc_id=invoice.doc_id, status=status, issues=issues)