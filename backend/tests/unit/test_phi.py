"""PHI guard, detector and tokenizer tests."""

from __future__ import annotations

import pytest

from reclaim.phi import detector, guard
from reclaim.phi.tokenizer import TokenVault, has_leaked_phi, scrub_generated_text


def test_redact_structured_phi():
    text = "SSN 123-45-6789, phone (555) 123-4567, email a@b.com, NPI 1234567890"
    out = guard.redact_text(text)
    assert "123-45-6789" not in out
    assert "555" not in out
    assert "a@b.com" not in out
    assert "1234567890" not in out
    assert guard.REDACTED in out


def test_contains_phi():
    assert guard.contains_phi("dob 1980-01-01")
    assert not guard.contains_phi("no identifiers here, just words")


def test_find_spans_non_overlapping():
    spans = guard.find_spans("SSN 123-45-6789 and SSN 987-65-4321")
    assert len(spans) == 2
    assert all(label == "ssn" for label, *_ in spans)


def test_redact_nested_structure():
    data = {"note": "SSN 123-45-6789", "items": ["phone 555-123-4567", {"x": "ok"}]}
    out = guard.redact(data)
    assert "123-45-6789" not in out["note"]
    assert "555-123-4567" not in out["items"][0]
    assert out["items"][1]["x"] == "ok"


def test_tokenize_detokenize_round_trip():
    vault = TokenVault(b"test-secret")
    text = "Patient MRN-0042 seen for low back pain, SSN 123-45-6789"
    tokenized = vault.tokenize(text)
    assert "MRN-0042" not in tokenized
    assert "123-45-6789" not in tokenized
    assert tokenized.count("[[PHI:") == 2
    assert vault.detokenize(tokenized) == text


def test_tokenize_is_deterministic_per_secret():
    assert TokenVault(b"a").tokenize("SSN 123-45-6789") == TokenVault(b"a").tokenize("SSN 123-45-6789")
    assert TokenVault(b"a").tokenize("SSN 123-45-6789") != TokenVault(b"b").tokenize("SSN 123-45-6789")


def test_unknown_token_left_untouched():
    assert TokenVault(b"a").detokenize("[[PHI:0123456789abcdef]]") == "[[PHI:0123456789abcdef]]"


def test_empty_secret_rejected():
    with pytest.raises(ValueError):
        TokenVault(b"")


def test_scrub_generated_text():
    leaked = "Approved; SSN 123-45-6789"
    assert "123-45-6789" not in scrub_generated_text(leaked)
    assert has_leaked_phi(leaked)
    assert not has_leaked_phi(scrub_generated_text(leaked))


def test_detector_degrades_to_regex_without_ner(monkeypatch):
    monkeypatch.setattr(detector, "_nlp_loaded", True)
    monkeypatch.setattr(detector, "_nlp", None)
    spans = detector.detect("Call 555-123-4567 about MRN-0042")
    assert [s.label for s in spans] == ["phone", "mrn"]
    assert all(s.source == "regex" and s.confidence == detector.STRUCTURED_CONFIDENCE for s in spans)
