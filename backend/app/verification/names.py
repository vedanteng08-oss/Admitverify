"""Name normalisation and order-free matching for Indian admission documents.

Observed in the sample documents:
- SSC prints the name surname first ("SURNAME First Middle"), HSC / CBSE print it
  first-name first.
- Caste, NCL and EWS certificates add prefixes: Kumar, Kumari, Shri, Shrimati, Smt,
  Mr, Mrs, Ms, and template text such as "Shri/Shrimati/Kumari".
- HSC prints only the mother's first name.

The score is 0-100 and does not depend on token order. Initials ("S") match the
full token they abbreviate ("SURESH").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Honorifics and template words removed before matching. Compared in upper case.
PREFIXES = {
    "KUMAR", "KUMARI", "KUM", "SHRI", "SHREE", "SHRIMATI", "SMT", "SMT.", "SOU",
    "MR", "MRS", "MS", "MISS", "MASTER", "KU", "SAU", "DR",
}

# Common spelling variants that should count as the same token.
SPELLING_VARIANTS = [
    {"LAXMI", "LAKSHMI", "LAKSHAMI", "LAXHMI"},
    {"LAKSHMAN", "LAXMAN", "LAKSHIMAN", "LAKSHMANA"},
    {"SHREYASH", "SHREYAS", "SHRIYASH"},
    {"VITTHAL", "VITHAL", "VITTAL"},
    {"SURYAKANT", "SURYAKANTH"},
    {"PRAJWAL", "PRAJVAL"},
    {"MOHAMMAD", "MOHAMMED", "MOHAMAD", "MUHAMMAD"},
]
_VARIANT_KEY = {name: min(group) for group in SPELLING_VARIANTS for name in group}

_NON_LETTERS = re.compile(r"[^A-Z\s]")
_SPACES = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def has_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def normalize(name: str | None) -> list[str]:
    """Return the meaningful name tokens in upper case, prefixes removed."""
    if not name:
        return []
    text = _strip_accents(name).upper().replace("/", " ").replace(".", " ")
    text = _NON_LETTERS.sub(" ", text)
    tokens = [t for t in _SPACES.split(text) if t]
    return [t for t in tokens if t not in PREFIXES]


def _canonical(token: str) -> str:
    return _VARIANT_KEY.get(token, token)


def _token_similarity(a: str, b: str) -> float:
    """Similarity of two tokens, 0..1."""
    if a == b or _canonical(a) == _canonical(b):
        return 1.0
    if len(a) == 1 or len(b) == 1:  # initial vs full token
        return 1.0 if a[0] == b[0] else 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class NameMatch:
    score: int  # 0-100
    verdict: str  # "match" | "near" | "mismatch" | "unreadable"
    reason: str
    tokens_a: list[str] = field(default_factory=list)
    tokens_b: list[str] = field(default_factory=list)


def _best_pairing_score(short: list[str], long: list[str]) -> tuple[float, list[str]]:
    """Greedy best one-to-one pairing of tokens of `short` into `long`."""
    remaining = list(long)
    total = 0.0
    weak: list[str] = []
    for tok in sorted(short, key=len, reverse=True):
        best_i, best_s = -1, 0.0
        for i, cand in enumerate(remaining):
            s = _token_similarity(tok, cand)
            if s > best_s:
                best_i, best_s = i, s
        if best_i >= 0:
            remaining.pop(best_i)
        if best_s < 0.85:
            weak.append(tok)
        total += best_s
    return total / max(len(short), 1), weak


def match_names(
    a: str | None,
    b: str | None,
    *,
    match_threshold: int = 90,
    near_threshold: int = 75,
) -> NameMatch:
    """Compare two names regardless of token order.

    Extra tokens on one side (e.g. a middle name missing on one document) reduce the
    score a little but do not by themselves make it a mismatch.
    """
    ta, tb = normalize(a), normalize(b)
    if not ta or not tb:
        return NameMatch(0, "unreadable", "Name missing or not readable", ta, tb)
    if (a and has_devanagari(a)) or (b and has_devanagari(b)):
        return NameMatch(
            0, "unreadable", "Name is in Devanagari; transliterate before matching", ta, tb
        )

    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    pair_score, weak = _best_pairing_score(short, long)
    missing = len(long) - len(short)
    # Each extra token costs 5 points, so "First Last" vs "First Middle Last" = 95.
    score = round(pair_score * 100) - 5 * missing
    score = max(0, min(100, score))
    # One badly matching name part (e.g. surname misread) must never pass as a full match.
    if weak and score >= match_threshold:
        score = match_threshold - 1

    if score >= match_threshold:
        verdict, reason = "match", "Names match"
    elif score >= near_threshold:
        verdict = "near"
        reason = "Names are similar but not identical"
    else:
        verdict = "mismatch"
        reason = "Names do not match"
    if weak:
        reason += f" (check: {', '.join(sorted(weak))})"
    if missing and verdict != "mismatch":
        reason += f"; {missing} extra name part(s) on one document"
    return NameMatch(score, verdict, reason, ta, tb)


def first_name_matches(full_name: str | None, first_only: str | None) -> bool:
    """For documents that print only a first name (e.g. mother's name on HSC/SSC)."""
    tokens = normalize(full_name)
    target = normalize(first_only)
    if not tokens or not target:
        return False
    return any(_token_similarity(target[0], t) >= 0.9 for t in tokens)
