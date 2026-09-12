"""Hybrid PHI detection: regex for structured identifiers, optional spaCy NER for free text.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/services/phi_detector.py).
The spaCy model is loaded lazily and cached; if unavailable the detector degrades to the
regex layer alone so the pipeline never hard-fails on a missing model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from reclaim.phi import guard

logger = logging.getLogger("reclaim.phi.detector")

STRUCTURED_CONFIDENCE = 0.95
NER_CONFIDENCE = 0.90

# spaCy entity labels that constitute PHI under HIPAA Safe Harbor.
_PHI_ENTITY_LABELS = {"PERSON", "GPE", "LOC", "FAC", "DATE", "NORP"}
_MODEL_CANDIDATES = ("en_core_web_trf", "en_core_web_sm")

_nlp = None
_nlp_loaded = False


@dataclass
class PHISpan:
    label: str
    start: int
    end: int
    value: str
    confidence: float
    source: str  # "regex" | "ner"


def _load_nlp():
    """Lazily load a spaCy pipeline; cache the result (including failure)."""
    global _nlp, _nlp_loaded
    if _nlp_loaded:
        return _nlp
    _nlp_loaded = True
    try:
        import spacy

        for model in _MODEL_CANDIDATES:
            try:
                _nlp = spacy.load(model, disable=["lemmatizer"])
                logger.info("phi_ner_model_loaded model=%s", model)
                return _nlp
            except Exception:  # noqa: BLE001 — try next candidate
                continue
        logger.info("phi_ner_unavailable reason=no_model")
    except Exception:  # noqa: BLE001 — spaCy not installed
        logger.info("phi_ner_unavailable reason=spacy_missing")
    _nlp = None
    return _nlp


def regex_spans(text: str) -> list[PHISpan]:
    return [
        PHISpan(label=label, start=s, end=e, value=v, confidence=STRUCTURED_CONFIDENCE, source="regex")
        for label, s, e, v in guard.find_spans(text)
    ]


def ner_spans_typed(text: str) -> list[PHISpan]:
    nlp = _load_nlp()
    if nlp is None or not text:
        return []
    try:
        doc = nlp(text)
    except Exception:  # noqa: BLE001
        return []
    return [
        PHISpan(
            label=ent.label_.lower(),
            start=ent.start_char,
            end=ent.end_char,
            value=ent.text,
            confidence=NER_CONFIDENCE,
            source="ner",
        )
        for ent in doc.ents
        if ent.label_ in _PHI_ENTITY_LABELS
    ]


def detect(text: str, min_confidence: float = 0.0) -> list[PHISpan]:
    """Return all PHI spans (regex + NER) at/above `min_confidence`, deduped."""
    spans = regex_spans(text) + ner_spans_typed(text)
    regex_ranges = [(s.start, s.end) for s in spans if s.source == "regex"]
    deduped: list[PHISpan] = []
    for sp in spans:
        if sp.confidence < min_confidence:
            continue
        # Drop NER spans that overlap a (higher-confidence) regex span.
        if sp.source == "ner" and any(rs < sp.end and sp.start < re for rs, re in regex_ranges):
            continue
        deduped.append(sp)
    return sorted(deduped, key=lambda s: s.start)


def ner_spans(text: str) -> list[tuple[str, int, int, str]]:
    """Tokenizer-facing NER spans (label, start, end, value)."""
    return [(s.label, s.start, s.end, s.value) for s in ner_spans_typed(text)]
