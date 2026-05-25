"""Tests for the validation engine. Run with: pytest -q"""
from datetime import date
from decimal import Decimal

from src.extraction.models import ExtractedInvoice, ExtractedLineItem
from src.validation.checks import (
    check_dates,
    check_line_item_math,
    check_subtotal_matches_lines,
    check_total_reconciliation,
)
from src.validation.models import Severity, ValidationStatus
from src.validation.validator import validate

TODAY = date(2026, 5, 25)


def make_invoice(**kwargs) -> ExtractedInvoice:
    """Build an ExtractedInvoice with the required fields filled; override freely."""
    base = {"doc_id": "test", "extracted_by": "test"}
    base.update(kwargs)
    return ExtractedInvoice(**base)


def codes(issues):
    return [i.code for i in issues]


# --- check_line_item_math --------------------------------------------------
def test_line_math_passes_when_correct():
    inv = make_invoice(line_items=[ExtractedLineItem(
        description="A", quantity=Decimal("2"), unit_price=Decimal("19.99"),
        line_total=Decimal("39.98"))])
    assert check_line_item_math(inv) == []


def test_line_math_flags_wrong_total():
    inv = make_invoice(line_items=[ExtractedLineItem(
        description="A", quantity=Decimal("3"), unit_price=Decimal("10.00"),
        line_total=Decimal("33.00"))])
    issues = check_line_item_math(inv)
    assert codes(issues) == ["LINE_MATH_MISMATCH"]
    assert issues[0].severity is Severity.ERROR


def test_line_math_skips_when_unit_price_missing():
    inv = make_invoice(line_items=[ExtractedLineItem(
        description="A", quantity=Decimal("3"), line_total=Decimal("129.00"))])
    issues = check_line_item_math(inv)
    assert codes(issues) == ["LINE_MATH_SKIPPED"]
    assert issues[0].severity is Severity.WARNING


# --- check_subtotal_matches_lines ------------------------------------------
def test_subtotal_matches_lines_ok():
    inv = make_invoice(subtotal=Decimal("90.00"), line_items=[
        ExtractedLineItem(line_total=Decimal("40.00")),
        ExtractedLineItem(line_total=Decimal("50.00"))])
    assert check_subtotal_matches_lines(inv) == []


def test_subtotal_mismatch_flagged():
    inv = make_invoice(subtotal=Decimal("100.00"), line_items=[
        ExtractedLineItem(line_total=Decimal("40.00")),
        ExtractedLineItem(line_total=Decimal("50.00"))])
    assert codes(check_subtotal_matches_lines(inv)) == ["SUBTOTAL_MISMATCH"]


def test_subtotal_check_skipped_without_subtotal():
    inv = make_invoice(line_items=[ExtractedLineItem(line_total=Decimal("40.00"))])
    assert check_subtotal_matches_lines(inv) == []


# --- check_total_reconciliation --------------------------------------------
def test_reconciliation_balances():
    inv = make_invoice(subtotal=Decimal("220.00"), shipping=Decimal("25.00"),
                       discount=Decimal("18.20"), adjustments=Decimal("0"),
                       tax_amount=Decimal("16.65"), grand_total=Decimal("243.45"))
    assert check_total_reconciliation(inv) == []


def test_reconciliation_mismatch_flagged():
    inv = make_invoice(subtotal=Decimal("220.00"), tax_amount=Decimal("16.65"),
                       grand_total=Decimal("243.45"))
    assert codes(check_total_reconciliation(inv)) == ["TOTAL_MISMATCH"]


def test_reconciliation_missing_grand_total():
    inv = make_invoice(subtotal=Decimal("100.00"))
    assert codes(check_total_reconciliation(inv)) == ["GRAND_TOTAL_MISSING"]


def test_reconciliation_falls_back_to_line_sum():
    inv = make_invoice(line_items=[ExtractedLineItem(line_total=Decimal("100.00"))],
                       tax_amount=Decimal("10.00"), grand_total=Decimal("110.00"))
    assert check_total_reconciliation(inv) == []


def test_reconciliation_within_tolerance():
    inv = make_invoice(subtotal=Decimal("100.00"), tax_amount=Decimal("0"),
                       grand_total=Decimal("100.01"))  # 1 cent off
    assert check_total_reconciliation(inv) == []


# --- check_dates -----------------------------------------------------------
def test_future_invoice_date_flagged():
    inv = make_invoice(invoice_date=date(2030, 1, 1))
    assert "INVOICE_DATE_FUTURE" in codes(check_dates(inv, today=TODAY))


def test_due_before_invoice_flagged():
    inv = make_invoice(invoice_date=date(2026, 3, 1), due_date=date(2026, 2, 1))
    assert "DUE_BEFORE_INVOICE" in codes(check_dates(inv, today=TODAY))


def test_missing_invoice_date_is_warning():
    issues = check_dates(make_invoice(), today=TODAY)
    assert codes(issues) == ["INVOICE_DATE_MISSING"]
    assert issues[0].severity is Severity.WARNING


def test_valid_dates_no_issues():
    inv = make_invoice(invoice_date=date(2026, 3, 1), due_date=date(2026, 4, 1))
    assert check_dates(inv, today=TODAY) == []


# --- validate (end-to-end verdict) -----------------------------------------
def test_validate_approves_clean_invoice():
    inv = make_invoice(subtotal=Decimal("220.00"), shipping=Decimal("25.00"),
                       discount=Decimal("18.20"), tax_amount=Decimal("16.65"),
                       grand_total=Decimal("243.45"),
                       invoice_date=date(2024, 1, 1), due_date=date(2024, 2, 1))
    result = validate(inv)
    assert result.status is ValidationStatus.APPROVED
    assert result.approved


def test_validate_flags_broken_total():
    inv = make_invoice(subtotal=Decimal("220.00"), tax_amount=Decimal("16.65"),
                       grand_total=Decimal("243.45"), invoice_date=date(2024, 1, 1))
    result = validate(inv)
    assert result.status is ValidationStatus.NEEDS_REVIEW
    assert "TOTAL_MISMATCH" in codes(result.errors)


def test_validate_warnings_do_not_block():
    inv = make_invoice(subtotal=Decimal("100.00"), tax_amount=Decimal("0"),
                       grand_total=Decimal("100.00"), invoice_date=date(2024, 1, 1),
                       notes=["Vendor name guessed; verify."])
    result = validate(inv)
    assert result.approved
    assert any(i.code == "EXTRACTION_NOTE" for i in result.warnings)