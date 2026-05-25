"""Data contracts for validation results.

A ``ValidationResult`` is the verdict on one invoice: an overall status plus a
list of specific ``ValidationIssue`` items explaining anything that's wrong or
worth noting. The issue list is what the Step 4 review screen will display so a
human knows exactly what to check.
"""
from enum import Enum

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    APPROVED = "APPROVED"          # all checks passed (or only warnings)
    NEEDS_REVIEW = "NEEDS_REVIEW"  # at least one blocking error -> send to a human


class Severity(str, Enum):
    ERROR = "ERROR"      # a real problem; forces NEEDS_REVIEW
    WARNING = "WARNING"  # worth surfacing, but does not block approval


class ValidationIssue(BaseModel):
    code: str = Field(..., description="Machine-readable tag, e.g. 'TOTAL_MISMATCH'")
    message: str = Field(..., description="Human-readable explanation for a reviewer")
    severity: Severity = Severity.ERROR


class ValidationResult(BaseModel):
    doc_id: str
    status: ValidationStatus
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def approved(self) -> bool:
        return self.status is ValidationStatus.APPROVED