"""The individual validation checks.

Each function takes an ``ExtractedInvoice`` and returns a list of
``ValidationIssue`` (empty if all good). They are pure functions — no state, no
side effects — which makes them trivial to test in isolation. Piece 3 (the
validator) simply runs them all and collects the issues.

Guiding rule: a check only raises an ERROR for something it can actually verify
and finds wrong. If the data needed for a check is missing, it SKIPS (often with
a WARNING) rather than failing — "can't check" is not "failed".
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from src.extraction.models import ExtractedInvoice
from src.validation.models import Severity, ValidationIssue

# Money comparisons allow a small tolerance for real-world rounding.
MONEY_TOLERANCE = Decimal("0.01")


def _close(a: Decimal, b: Decimal, tol: Decimal = MONEY_TOLERANCE) -> bool:
    return abs(a - b) <= tol


def check_line_item_math(
    invoice: ExtractedInvoice, tol: Decimal = MONEY_TOLERANCE
) -> list[ValidationIssue]:
    """For each line: quantity x unit_price should equal line_total."""
    issues: list[ValidationIssue] = []
    for idx, item in enumerate(invoice.line_items, start=1):
        label = item.description or f"line {idx}"
        if item.quantity is None or item.unit_price is None or item.line_total is None:
            issues.append(ValidationIssue(
                code="LINE_MATH_SKIPPED",
                message=f"{label}: missing quantity/unit price/total, math not checked.",
                severity=Severity.WARNING,
            ))
            continue
        expected = item.quantity * item.unit_price
        if not _close(expected, item.line_total, tol):
            issues.append(ValidationIssue(
                code="LINE_MATH_MISMATCH",
                message=(f"{label}: {item.quantity} x {item.unit_price} = {expected}, "
                         f"but line total is {item.line_total}."),
            ))
    return issues


def check_subtotal_matches_lines(
    invoice: ExtractedInvoice, tol: Decimal = MONEY_TOLERANCE
) -> list[ValidationIssue]:
    """The line totals should sum to the stated subtotal (when both exist)."""
    line_totals = [li.line_total for li in invoice.line_items if li.line_total is not None]
    if invoice.subtotal is None or not line_totals:
        return []  # can't compare -> skip silently
    summed = sum(line_totals, Decimal("0"))
    if not _close(summed, invoice.subtotal, tol):
        return [ValidationIssue(
            code="SUBTOTAL_MISMATCH",
            message=f"Line items sum to {summed}, but stated subtotal is {invoice.subtotal}.",
        )]
    return []


def check_total_reconciliation(
    invoice: ExtractedInvoice, tol: Decimal = MONEY_TOLERANCE
) -> list[ValidationIssue]:
    """subtotal + shipping - discount + tax + adjustments should equal grand_total."""
    if invoice.grand_total is None:
        return [ValidationIssue(
            code="GRAND_TOTAL_MISSING",
            message="No grand total found; cannot validate the invoice total.",
        )]

    # Prefer the stated subtotal; fall back to summing the line items.
    subtotal = invoice.subtotal
    if subtotal is None:
        line_totals = [li.line_total for li in invoice.line_items if li.line_total is not None]
        if not line_totals:
            return [ValidationIssue(
                code="SUBTOTAL_MISSING",
                message="No subtotal and no line totals; cannot reconcile the total.",
                severity=Severity.WARNING,
            )]
        subtotal = sum(line_totals, Decimal("0"))

    shipping = invoice.shipping or Decimal("0")
    discount = invoice.discount or Decimal("0")
    adjustments = invoice.adjustments or Decimal("0")
    tax = invoice.tax_amount or Decimal("0")

    expected = subtotal + shipping - discount + tax + adjustments
    if not _close(expected, invoice.grand_total, tol):
        return [ValidationIssue(
            code="TOTAL_MISMATCH",
            message=(f"Computed {expected} (subtotal {subtotal} + shipping {shipping} "
                     f"- discount {discount} + tax {tax} + adjustments {adjustments}) "
                     f"!= grand total {invoice.grand_total}."),
        )]
    return []


def check_dates(
    invoice: ExtractedInvoice, today: Optional[date] = None
) -> list[ValidationIssue]:
    """Invoice date shouldn't be in the future; due date shouldn't precede it."""
    issues: list[ValidationIssue] = []
    today = today or date.today()

    if invoice.invoice_date is None:
        issues.append(ValidationIssue(
            code="INVOICE_DATE_MISSING",
            message="No invoice date found.",
            severity=Severity.WARNING,
        ))
    elif invoice.invoice_date > today:
        issues.append(ValidationIssue(
            code="INVOICE_DATE_FUTURE",
            message=f"Invoice date {invoice.invoice_date} is in the future.",
        ))

    if (invoice.invoice_date and invoice.due_date
            and invoice.due_date < invoice.invoice_date):
        issues.append(ValidationIssue(
            code="DUE_BEFORE_INVOICE",
            message=f"Due date {invoice.due_date} is before invoice date {invoice.invoice_date}.",
        ))
    return issues