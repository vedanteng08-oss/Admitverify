"""Plain data types shared by the extraction agents and the rules engine.

The extractor agent returns one ExtractedDocument per upload. Every field carries a
confidence, so the rules engine can say "Not able to read" instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class Result(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"  # could not decide: unreadable or missing input
    SKIPPED = "skipped"  # rule does not apply to this student


@dataclass
class Field:
    value: Any
    confidence: float = 1.0  # 0..1 from the extractor
    original_text: str | None = None  # text as printed (e.g. Devanagari, or date words)
    page: int | None = None


@dataclass
class ExtractedDocument:
    doc_type: str  # e.g. "HSC_MARKSHEET", "CASTE_CERT"
    variant: str | None = None  # e.g. "CBSE", "HSC_MH", "FORM_8"
    fields: dict[str, Field] = field(default_factory=dict)
    subjects: list[dict] = field(default_factory=list)  # marksheets only
    classifier_match: bool = True  # classifier agreed this is the declared doc type
    image_quality: float = 1.0  # 0..1 from the pre-processor

    def get(self, key: str, min_conf: float = 0.0) -> Any:
        f = self.fields.get(key)
        if f is None or f.value in (None, "") or f.confidence < min_conf:
            return None
        return f.value

    def field_state(self, key: str, min_conf: float) -> str:
        """'ok', 'low_confidence' or 'missing'."""
        f = self.fields.get(key)
        if f is None or f.value in (None, ""):
            return "missing"
        return "ok" if f.confidence >= min_conf else "low_confidence"


@dataclass
class Student:
    registration_id: str
    name: str
    category: str  # OPEN, OBC, SC, ST, VJ_A, NT_B, NT_C, NT_D, SBC, SEBC, EWS
    dob: str | None = None
    mother_name: str | None = None


@dataclass
class Finding:
    rule_code: str
    title: str
    severity: Severity
    result: Result
    message: str
    documents: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.severity == Severity.BLOCKER and self.result in (Result.FAIL, Result.REVIEW)
