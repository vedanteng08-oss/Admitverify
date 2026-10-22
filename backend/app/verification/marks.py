"""PCM / PCB calculation and 'group clear' for each board.

Board formats seen in the samples:
- CBSE 12th: per subject THEORY + PR/IA = TOTAL (out of 100). Use TOTAL.
- Maharashtra HSC: per subject marks out of 100 already; Maths is printed as
  "MATHEMATICS & STATISTICS" (code 40), Physics 54, Chemistry 55.
- ICSE / ISC: marks out of 100 per subject; pass mark 33% printed on the sheet.

Subject names are matched through aliases, so the admin can extend them per board.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical subject -> aliases (upper case, compared after cleaning).
SUBJECT_ALIASES: dict[str, set[str]] = {
    "PHYSICS": {"PHYSICS"},
    "CHEMISTRY": {"CHEMISTRY"},
    "MATHEMATICS": {
        "MATHEMATICS", "MATHS", "MATHEMATICS & STATISTICS", "MATHEMATICS AND STATISTICS",
        "MATHEMATICS STANDARD", "MATHEMATICS BASIC",
    },
    "BIOLOGY": {"BIOLOGY", "BIOLOGY (BOTANY & ZOOLOGY)"},
    "BIOTECHNOLOGY": {"BIOTECHNOLOGY"},
}

# Third subject candidates for engineering (Physics + Maths compulsory).
THIRD_SUBJECTS = ["CHEMISTRY", "BIOTECHNOLOGY", "BIOLOGY"]

# Default board pass marks per subject (out of 100). Editable by admin in the rules table.
DEFAULT_PASS_MARK = {"CBSE": 33, "ICSE": 33, "ISC": 35, "HSC_MH": 35, "OTHER": 33}


def _clean(name: str) -> str:
    name = re.sub(r"^\s*\d+\s+", "", name.upper())  # drop leading subject code "54 "
    return re.sub(r"\s+", " ", name).strip()


def canonical_subject(name: str) -> str | None:
    cleaned = _clean(name)
    for canon, aliases in SUBJECT_ALIASES.items():
        if cleaned in aliases:
            return canon
    return None


@dataclass
class SubjectMark:
    name: str
    obtained: float | None  # total out of max
    max_marks: float = 100
    theory: float | None = None
    practical: float | None = None

    @property
    def percent(self) -> float | None:
        if self.obtained is None or not self.max_marks:
            return None
        return self.obtained / self.max_marks * 100


@dataclass
class EligibilityResult:
    board: str
    marks: dict[str, float | None] = field(default_factory=dict)  # canonical -> percent
    pcm_percent: float | None = None
    pcb_percent: float | None = None
    best_three: list[str] = field(default_factory=list)
    best_three_percent: float | None = None
    group_clear: bool | None = None
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def compute_eligibility(board: str, subjects: list[SubjectMark]) -> EligibilityResult:
    res = EligibilityResult(board=board)
    by_canon: dict[str, SubjectMark] = {}
    for s in subjects:
        canon = canonical_subject(s.name)
        if canon and canon not in by_canon:
            by_canon[canon] = s

    # Re-add theory + practical where both are printed (catches mis-reads).
    for canon, s in by_canon.items():
        if s.theory is not None and s.practical is not None and s.obtained is not None:
            if abs((s.theory + s.practical) - s.obtained) > 0.01:
                res.problems.append(
                    f"{canon.title()}: theory {s.theory:g} + practical {s.practical:g} "
                    f"does not equal total {s.obtained:g}"
                )

    for canon in ("PHYSICS", "CHEMISTRY", "MATHEMATICS", "BIOLOGY", "BIOTECHNOLOGY"):
        s = by_canon.get(canon)
        res.marks[canon] = round(s.percent, 2) if s and s.percent is not None else None

    def avg(keys: list[str]) -> float | None:
        vals = [res.marks.get(k) for k in keys]
        if any(v is None for v in vals):
            return None
        return round(sum(vals) / len(vals), 2)  # type: ignore[arg-type]

    res.pcm_percent = avg(["PHYSICS", "CHEMISTRY", "MATHEMATICS"])
    res.pcb_percent = avg(["PHYSICS", "CHEMISTRY", "BIOLOGY"])

    for compulsory in ("PHYSICS", "MATHEMATICS"):
        if res.marks.get(compulsory) is None:
            res.missing.append(compulsory.title())
    thirds = [(k, res.marks[k]) for k in THIRD_SUBJECTS if res.marks.get(k) is not None]
    if not thirds:
        res.missing.append("Chemistry / Biotechnology / Biology")

    if not res.missing:
        best_third, _ = max(thirds, key=lambda kv: kv[1])
        res.best_three = ["PHYSICS", "MATHEMATICS", best_third]
        res.best_three_percent = avg(res.best_three)
        pass_mark = DEFAULT_PASS_MARK.get(board, DEFAULT_PASS_MARK["OTHER"])
        res.group_clear = all(res.marks[k] >= pass_mark for k in res.best_three)  # type: ignore[operator]
    return res
