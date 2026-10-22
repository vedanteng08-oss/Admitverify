"""Deterministic rules engine.

Takes what the extractor agents read from each document and returns findings.
No AI model makes a pass/fail decision: every decision is here, in plain code,
driven by the admin-editable configuration (seeded from document_catalog.json).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .dates import academic_year_covers, parse_date
from .marks import SubjectMark, compute_eligibility
from .models import ExtractedDocument, Finding, Result, Severity, Student
from .names import first_name_matches, match_names

CATALOG_PATH = Path(__file__).parent / "data" / "document_catalog.json"

Docs = dict[str, ExtractedDocument]


@dataclass
class RuleConfig:
    catalog: dict[str, Any]
    rule_set_version: str = "2026-27.v1"

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> "RuleConfig":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    # Convenience accessors -------------------------------------------------
    @property
    def doc_types(self) -> dict[str, dict]:
        return {d["code"]: d for d in self.catalog["document_types"]}

    def doc_name(self, code: str) -> str:
        return self.doc_types.get(code, {}).get("name", code)

    def required_docs(self, category: str) -> list[str]:
        return self.catalog["category_requirements"].get(category, [])

    def category_from_text(self, text: str | None) -> str | None:
        if not text:
            return None
        cleaned = re.sub(r"\s+", " ", text.upper()).strip()
        aliases = self.catalog["category_aliases"]
        if cleaned in aliases:
            return aliases[cleaned]
        for alias in sorted(aliases, key=len, reverse=True):  # longest alias first
            if alias in cleaned:
                return aliases[alias]
        return None


@dataclass
class VerificationResult:
    findings: list[Finding] = field(default_factory=list)
    eligibility: dict[str, Any] = field(default_factory=dict)
    rule_set_version: str = ""

    @property
    def overall_status(self) -> str:
        if any(f.is_blocking for f in self.findings):
            return "Action required"
        if any(
            f.result in (Result.FAIL, Result.REVIEW) and f.severity == Severity.WARNING
            for f in self.findings
        ):
            return "Needs attention"
        return "Ready"

    def by_code(self, code: str) -> list[Finding]:
        return [f for f in self.findings if f.rule_code == code]


# --------------------------------------------------------------------------- helpers
def _fail(code, title, sev, msg, docs=(), **ev) -> Finding:
    return Finding(code, title, sev, Result.FAIL, msg, list(docs), ev)


def _ok(code, title, sev, msg, docs=(), **ev) -> Finding:
    return Finding(code, title, sev, Result.PASS, msg, list(docs), ev)


def _review(code, title, sev, msg, docs=(), **ev) -> Finding:
    return Finding(code, title, sev, Result.REVIEW, msg, list(docs), ev)


def _digits(text: Any) -> str:
    return re.sub(r"\D", "", str(text or ""))


# --------------------------------------------------------------------------- rules
def rule_read_quality(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """Q1-Q3: wrong document, poor image, fields not readable."""
    out: list[Finding] = []
    for code, doc in docs.items():
        name = cfg.doc_name(code)
        if not doc.classifier_match:
            out.append(_fail("Q2", "Wrong document", Severity.BLOCKER,
                             f"Uploaded file does not look like a {name}. Please re-upload.", [code]))
            continue
        if doc.image_quality < 0.5:
            out.append(_fail("Q3", "Poor image", Severity.WARNING,
                             f"{name}: image unclear; please upload a clearer scan.", [code]))
        for fdef in cfg.doc_types.get(code, {}).get("fields", []):
            if fdef["type"] == "subject_table":
                continue
            state = doc.field_state(fdef["key"], fdef["min_confidence"])
            if state == "ok":
                continue
            if state == "missing" and not fdef["mandatory"]:
                continue
            out.append(_review(
                "Q1", "Field not readable",
                Severity.BLOCKER if fdef["mandatory"] else Severity.WARNING,
                f"{name}: not able to read {fdef['label'].lower()}, please verify correctly.",
                [code], field=fdef["key"], state=state,
            ))
    return out


def rule_required_documents(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    missing = [c for c in cfg.required_docs(student.category) if c not in docs]
    if missing:
        names = ", ".join(cfg.doc_name(c) for c in missing)
        return [_fail("C1", "Required documents", Severity.BLOCKER,
                      f"Missing for {student.category}: {names}.", missing, missing=missing)]
    return [_ok("C1", "Required documents", Severity.BLOCKER,
                "All required documents uploaded.")]


def rule_eligibility(student: Student, docs: Docs, cfg: RuleConfig,
                     result: VerificationResult) -> list[Finding]:
    """E1-E6 from the 12th marksheet."""
    hsc = docs.get("HSC_MARKSHEET")
    if not hsc or not hsc.classifier_match:
        return []
    out: list[Finding] = []
    subjects = [
        SubjectMark(s["name"], s.get("obtained"), s.get("max", 100), s.get("theory"), s.get("practical"))
        for s in hsc.subjects
    ]
    low_conf = [s["name"] for s in hsc.subjects if s.get("confidence", 1.0) < 0.9]
    board = hsc.variant or "OTHER"
    el = compute_eligibility(board, subjects)
    result.eligibility = {
        "board": board,
        "marks": el.marks,
        "pcm_percent": el.pcm_percent,
        "pcb_percent": el.pcb_percent,
        "best_three": el.best_three,
        "best_three_percent": el.best_three_percent,
        "group_clear": el.group_clear,
    }
    if low_conf:
        out.append(_review("Q1", "Field not readable", Severity.BLOCKER,
                           "12th Marksheet: not able to read marks for "
                           f"{', '.join(low_conf)}, please verify correctly.",
                           ["HSC_MARKSHEET"], subjects=low_conf))
    if el.missing:
        out.append(_fail("E1", "Compulsory subjects", Severity.BLOCKER,
                         f"Not found on 12th marksheet: {', '.join(el.missing)}.",
                         ["HSC_MARKSHEET"]))
        return out
    for problem in el.problems:
        out.append(_fail("E6", "Marks re-added", Severity.WARNING, problem, ["HSC_MARKSHEET"]))

    out.append(
        _ok("E3", "Group clear", Severity.BLOCKER, "Each of the three subjects passed.", ["HSC_MARKSHEET"])
        if el.group_clear else
        _fail("E3", "Group clear", Severity.BLOCKER,
              "One of Physics, Maths or the third subject is below the pass mark.", ["HSC_MARKSHEET"])
    )

    elig = cfg.catalog["eligibility"]
    reserved = student.category in elig["reserved_categories"]
    minimum = elig["min_percent_reserved"] if reserved else elig["min_percent_open"]
    pct = el.best_three_percent or 0
    subjects_used = " + ".join(s.title() for s in el.best_three)
    msg = f"{subjects_used} = {pct:.2f}% (minimum {minimum}% for {student.category})."
    out.append(
        _ok("E4", "Aggregate percentage", Severity.BLOCKER, msg, ["HSC_MARKSHEET"], percent=pct)
        if pct >= minimum else
        _fail("E4", "Aggregate percentage", Severity.BLOCKER, msg, ["HSC_MARKSHEET"], percent=pct)
    )

    res_text = (hsc.get("result") or "").upper()
    if "PASS" in res_text or "QUALIFIED" in res_text:
        out.append(_ok("E5", "Result", Severity.BLOCKER, "Result: PASS.", ["HSC_MARKSHEET"]))
    elif res_text:
        out.append(_fail("E5", "Result", Severity.BLOCKER,
                         f"12th result reads '{hsc.get('result')}'.", ["HSC_MARKSHEET"]))
    return out


def rule_category_on_certificate(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """C10: category printed on the caste certificate equals the chosen category."""
    cc = docs.get("CASTE_CERT")
    if not cc or student.category in ("OPEN", "EWS"):
        return []
    printed = cfg.category_from_text(cc.get("category", 0.85))
    if printed is None:
        return [_review("C10", "Category on certificate", Severity.BLOCKER,
                        "Caste Certificate: not able to read the category, please verify correctly.",
                        ["CASTE_CERT"])]
    if printed != student.category:
        return [_fail("C10", "Category on certificate", Severity.BLOCKER,
                      f"Student chose {student.category} but the caste certificate says {printed}.",
                      ["CASTE_CERT"], printed=printed)]
    return [_ok("C10", "Category on certificate", Severity.BLOCKER,
                f"Caste certificate category {printed} matches.", ["CASTE_CERT"])]


def rule_validity_matches_caste_cert(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """C3 + C7: validity names the same caste and quotes the caste certificate's number and date."""
    cc, cv = docs.get("CASTE_CERT"), docs.get("CASTE_VALIDITY")
    if not cc or not cv:
        return []
    out: list[Finding] = []
    docs_pair = ["CASTE_CERT", "CASTE_VALIDITY"]

    cc_no, cv_no = _digits(cc.get("certificate_no", 0.9)), _digits(cv.get("cc_number", 0.9))
    if not cc_no or not cv_no:
        out.append(_review("C7", "Validity quotes caste certificate", Severity.BLOCKER,
                           "Not able to read the caste certificate number on one of the two "
                           "documents, please verify correctly.", docs_pair))
    elif cc_no != cv_no:
        out.append(_fail("C7", "Validity quotes caste certificate", Severity.BLOCKER,
                         f"Validity quotes caste certificate no. {cv_no}, but the uploaded caste "
                         f"certificate is no. {cc_no}.", docs_pair))
    else:
        cc_date = parse_date(cc.get("issue_date", 0.85)).value
        cv_date = parse_date(cv.get("cc_date", 0.85)).value
        if cc_date and cv_date and cc_date != cv_date:
            out.append(_fail("C7", "Validity quotes caste certificate", Severity.WARNING,
                             f"Certificate number matches, but the dates differ "
                             f"({cc_date:%d-%m-%Y} vs {cv_date:%d-%m-%Y}).", docs_pair))
        else:
            out.append(_ok("C7", "Validity quotes caste certificate", Severity.BLOCKER,
                           f"Validity quotes caste certificate no. {cc_no}; matches.", docs_pair))

    cc_caste = re.sub(r"[^A-Z]", "", (cc.get("caste", 0.85) or "").upper())
    cv_caste = re.sub(r"[^A-Z]", "", (cv.get("caste", 0.85) or "").upper())
    if cc_caste and cv_caste:
        if cc_caste in cv_caste or cv_caste in cc_caste:
            out.append(_ok("C3", "Caste on validity", Severity.BLOCKER,
                           "Caste on validity matches caste certificate.", docs_pair))
        else:
            out.append(_fail("C3", "Caste on validity", Severity.BLOCKER,
                             f"Caste differs: '{cc.get('caste')}' vs '{cv.get('caste')}'.", docs_pair))
    return out


def rule_ncl_valid(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """C8: NCL valid-up-to date covers the admission year."""
    ncl = docs.get("NCL")
    if not ncl:
        return []
    cutoff = date.fromisoformat(cfg.catalog["admission_year"]["ncl_valid_until_min"])
    parsed = parse_date(ncl.get("valid_upto", 0.9))
    if not parsed.ok:
        return [_review("C8", "NCL validity", Severity.BLOCKER,
                        "Non-Creamy Layer: not able to read the valid-up-to date, please verify correctly.",
                        ["NCL"])]
    if parsed.value < cutoff:  # type: ignore[operator]
        return [_fail("C8", "NCL validity", Severity.BLOCKER,
                      f"NCL valid only up to {parsed.value:%d-%m-%Y}; it must be valid up to at least "
                      f"{cutoff:%d-%m-%Y}. Obtain a new certificate.", ["NCL"])]
    return [_ok("C8", "NCL validity", Severity.BLOCKER,
                f"NCL valid up to {parsed.value:%d-%m-%Y}.", ["NCL"])]


def rule_ews_year(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """C9: EWS certificate is for the admission year."""
    ews = docs.get("EWS_CERT")
    if not ews:
        return []
    year = cfg.catalog["admission_year"]["start_year"]
    text = ews.get("valid_for_year", 0.9)
    if not text:
        return [_review("C9", "EWS year", Severity.BLOCKER,
                        "EWS Certificate: not able to read the year it is valid for, please verify correctly.",
                        ["EWS_CERT"])]
    if academic_year_covers(text, year):
        return [_ok("C9", "EWS year", Severity.BLOCKER, f"EWS certificate {text}.", ["EWS_CERT"])]
    return [_fail("C9", "EWS year", Severity.BLOCKER,
                  f"EWS certificate is '{text}', not for {cfg.catalog['admission_year']['label']}.",
                  ["EWS_CERT"])]


def rule_name_consistency(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """X1: candidate name on every document vs the 12th marksheet (or registered name)."""
    ref_code = cfg.catalog.get("name_reference", "HSC_MARKSHEET")
    ref_doc = docs.get(ref_code)
    ref_name = ref_doc.get("name", 0.85) if ref_doc else None
    ref_label = cfg.doc_name(ref_code) if ref_name else "registered name"
    ref_name = ref_name or student.name
    th = cfg.catalog["name_match"]
    out: list[Finding] = []
    for code, doc in docs.items():
        if code == ref_code or not doc.classifier_match:
            continue
        name = doc.get("name", 0.85)
        if not name:
            continue  # already reported by Q1
        m = match_names(ref_name, name, match_threshold=th["match"], near_threshold=th["near"])
        label = f"Name on {cfg.doc_name(code)} vs {ref_label}"
        ev = {"score": m.score, "a": ref_name, "b": name}
        if m.verdict == "match":
            out.append(_ok("X1", label, Severity.BLOCKER, f"{m.reason} ({m.score}).", [ref_code, code], **ev))
        elif m.verdict == "near":
            out.append(_fail("X1", label, Severity.WARNING,
                             f"{m.reason} ({m.score}): '{name}' vs '{ref_name}'.", [ref_code, code], **ev))
        elif m.verdict == "unreadable":
            out.append(_review("X1", label, Severity.WARNING, m.reason, [ref_code, code], **ev))
        else:
            out.append(_fail("X1", label, Severity.BLOCKER,
                             f"{m.reason} ({m.score}): '{name}' vs '{ref_name}'.", [ref_code, code], **ev))
    return out


def rule_dob_consistency(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """X2 + X4: every DOB printed on a document must be identical (and match registration)."""
    found: dict[str, date] = {}
    for code in cfg.catalog.get("dob_sources", []):
        doc = docs.get(code)
        if doc:
            p = parse_date(doc.get("dob", 0.9))
            if p.ok:
                found[code] = p.value  # type: ignore[assignment]
    out: list[Finding] = []
    if not found:
        return [_review("X2", "Date of birth", Severity.WARNING,
                        "No date of birth could be read from the Leaving Certificate, 10th "
                        "marksheet or Domicile; please verify manually.", [])]
    distinct = set(found.values())
    if len(distinct) > 1:
        detail = "; ".join(f"{cfg.doc_name(c)}: {d:%d-%m-%Y}" for c, d in found.items())
        out.append(_fail("X2", "Date of birth", Severity.BLOCKER,
                         f"Date of birth differs between documents ({detail}).", list(found)))
    else:
        (dob,) = distinct
        out.append(_ok("X2", "Date of birth", Severity.BLOCKER,
                       f"Date of birth {dob:%d-%m-%Y} on {len(found)} document(s).", list(found)))
        reg = parse_date(student.dob)
        if reg.ok and reg.value != dob:
            out.append(_fail("X4", "Registered date of birth", Severity.WARNING,
                             f"Registered DOB {reg.value:%d-%m-%Y} differs from documents "
                             f"({dob:%d-%m-%Y}).", list(found)))
    return out


def rule_mother_name(student: Student, docs: Docs, cfg: RuleConfig) -> list[Finding]:
    """X5: mother's (first) name is the same on the marksheets that print it."""
    names = {c: d.get("mother_name", 0.8) for c, d in docs.items() if d.get("mother_name", 0.8)}
    if len(names) < 2:
        return []
    codes = list(names)
    base_code = max(codes, key=lambda c: len(names[c].split()))  # most complete version
    bad = [c for c in codes if c != base_code and not first_name_matches(names[base_code], names[c])]
    if bad:
        return [_fail("X5", "Mother's name", Severity.WARNING,
                      "Mother's name differs on " + ", ".join(cfg.doc_name(c) for c in bad) + ".",
                      [base_code, *bad])]
    return [_ok("X5", "Mother's name", Severity.WARNING,
                f"Mother's name consistent on {len(codes)} documents.", codes)]


RULES: list[Callable[..., list[Finding]]] = [
    rule_read_quality,
    rule_required_documents,
    rule_category_on_certificate,
    rule_validity_matches_caste_cert,
    rule_ncl_valid,
    rule_ews_year,
    rule_name_consistency,
    rule_dob_consistency,
    rule_mother_name,
]


def verify(student: Student, docs: Docs, cfg: RuleConfig | None = None) -> VerificationResult:
    cfg = cfg or RuleConfig.load()
    result = VerificationResult(rule_set_version=cfg.rule_set_version)
    result.findings.extend(rule_eligibility(student, docs, cfg, result))
    for rule in RULES:
        result.findings.extend(rule(student, docs, cfg))
    order = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}
    status = {Result.FAIL: 0, Result.REVIEW: 1, Result.PASS: 2, Result.SKIPPED: 3}
    result.findings.sort(key=lambda f: (status[f.result], order[f.severity], f.rule_code))
    return result
