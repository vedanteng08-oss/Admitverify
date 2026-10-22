"""AdmitVerify verification core: name matching, dates, eligibility and rules."""

from .models import ExtractedDocument, Field, Finding, Result, Severity, Student
from .rules import RuleConfig, VerificationResult, verify

__all__ = [
    "ExtractedDocument", "Field", "Finding", "Result", "Severity", "Student",
    "RuleConfig", "VerificationResult", "verify",
]
