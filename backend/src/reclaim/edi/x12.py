"""X12 5010 tokenizer shared by the 835 and 837 parsers.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/edi/parser.py).
No maintained Python library handles 5010 plus payer quirks, so this is a small
hand-written tokenizer: delimiters are detected from the fixed-width ISA segment.

PHI note: this module never logs segment content. Errors carry positional
metadata only (segment id / index).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

DEFAULT_ELEMENT_SEP = "*"
DEFAULT_SEGMENT_TERM = "~"
DEFAULT_COMPONENT_SEP = ":"
DEFAULT_REPETITION_SEP = "^"


class EDIParseError(ValueError):
    """Raised on malformed EDI. Carries only non-PHI positional metadata."""

    def __init__(self, message: str, *, segment_id: str | None = None, index: int | None = None):
        self.segment_id = segment_id
        self.index = index
        super().__init__(message)


@dataclass(frozen=True)
class Delimiters:
    element: str = DEFAULT_ELEMENT_SEP
    segment: str = DEFAULT_SEGMENT_TERM
    component: str = DEFAULT_COMPONENT_SEP
    repetition: str = DEFAULT_REPETITION_SEP


@dataclass
class Segment:
    """A generic X12 segment: an id and its positional elements (1-indexed in X12)."""

    id: str
    elements: list[str]
    delimiters: Delimiters

    def get(self, position: int, default: str = "") -> str:
        """Return element at 1-based X12 position (e.g. CLP02 -> get(2))."""
        idx = position - 1
        if 0 <= idx < len(self.elements):
            return self.elements[idx]
        return default

    def components(self, position: int) -> list[str]:
        """Split a composite element on the component separator."""
        return self.get(position).split(self.delimiters.component)


def detect_delimiters(raw: str) -> Delimiters:
    """Detect delimiters from a well-formed ISA segment, else use defaults.

    A standard ISA is fixed-width: element separator at index 3, repetition
    separator at index 82, component separator at index 104, segment terminator
    at index 105.
    """
    stripped = raw.lstrip("\r\n\t ")
    if stripped.startswith("ISA") and len(stripped) >= 106:
        element = stripped[3]
        repetition = stripped[82]
        component = stripped[104]
        segment = stripped[105]
        if not element.isalnum() and not segment.isalnum():
            return Delimiters(
                element=element,
                segment=segment,
                component=component if not component.isalnum() else DEFAULT_COMPONENT_SEP,
                repetition=repetition if not repetition.isalnum() else DEFAULT_REPETITION_SEP,
            )
    return Delimiters()


def tokenize(raw: str, delimiters: Delimiters | None = None) -> list[Segment]:
    """Split raw EDI into `Segment`s.

    Tolerant of newlines/whitespace inserted between segments (common payer
    quirk). Empty segments are skipped.
    """
    if not raw or not raw.strip():
        raise EDIParseError("Empty EDI payload")
    delims = delimiters or detect_delimiters(raw)

    segments: list[Segment] = []
    for chunk in raw.split(delims.segment):
        seg_text = chunk.strip("\r\n\t ")
        if not seg_text:
            continue
        elements = seg_text.split(delims.element)
        seg_id = elements[0].strip()
        if not seg_id:
            continue
        segments.append(Segment(id=seg_id, elements=elements[1:], delimiters=delims))
    if not segments:
        raise EDIParseError("No segments found in payload")
    return segments


def to_decimal(value: str | None) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal("0")
