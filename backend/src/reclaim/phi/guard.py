"""Baseline structured-PHI guard (regex layer).

Ported unchanged from Healtcare-RCM-Denial-Recovery-Agent@4129fdd
(backend/src/services/phi_guard.py).

Conservative and fast: redacts structured identifiers (SSN, NPI, DOB-shaped dates,
phone, email, MRN). Note the date and 10-digit patterns also match service dates and
provider NPIs, so those must be injected by code after scrubbing, not left in LLM prose.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED-PHI]"

# Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("npi", re.compile(r"\b\d{10}\b")),
    ("dob", re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("mrn", re.compile(r"\bMRN[:#\s-]*[A-Za-z0-9]{4,}\b", re.IGNORECASE)),
]


def redact_text(text: str) -> str:
    """Return `text` with structured PHI patterns replaced by a redaction token."""
    if not text:
        return text
    out = text
    for _label, pattern in _PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def find_spans(text: str) -> list[tuple[str, int, int, str]]:
    """Return non-overlapping (label, start, end, value) PHI spans, left to right.

    Earlier patterns win on overlap (patterns are ordered most-specific first).
    """
    if not text:
        return []
    claimed: list[tuple[int, int]] = []
    spans: list[tuple[str, int, int, str]] = []
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(s < end and start < e for s, e in claimed):
                continue
            claimed.append((start, end))
            spans.append((label, start, end, m.group(0)))
    spans.sort(key=lambda s: s[1])
    return spans


def redact(value: Any) -> Any:
    """Recursively redact structured PHI from arbitrary JSON-like structures."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def contains_phi(text: str) -> bool:
    return any(pattern.search(text) for _label, pattern in _PATTERNS)


def assert_phi_free(value: Any) -> Any:
    """Defensive pass for the audit trail: always redact before persistence.

    Redacts rather than raises, so a logging mistake degrades to a redacted entry
    instead of dropping the audit record.
    """
    return redact(value)
