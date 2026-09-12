"""Reversible PHI tokenization before LLM calls, and post-generation scrubbing.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/services/phi_tokenizer.py).
The Redis + Vault Transit token store became an in-process `TokenVault`: the demo runs
in one process and every value it sees is synthetic. Token format (`[[PHI:<id>]]`) and
HMAC determinism are unchanged, so a value appearing twice tokenizes consistently.
"""

from __future__ import annotations

import hmac
import re
from hashlib import sha256

from reclaim.phi import detector, guard

TOKEN_RE = re.compile(r"\[\[PHI:([0-9a-f]{16})\]\]")


class TokenVault:
    def __init__(self, secret: bytes, *, use_ner: bool = False) -> None:
        if not secret:
            raise ValueError("TokenVault needs a non-empty secret")
        self._secret = secret
        self._use_ner = use_ner
        self._values: dict[str, str] = {}

    def _token_id(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("utf-8"), sha256).hexdigest()[:16]

    def tokenize(self, text: str) -> str:
        """Replace detected PHI in `text` with reversible `[[PHI:id]]` tokens."""
        if not text:
            return text
        spans = guard.find_spans(text)
        if self._use_ner:
            spans.extend(s for s in detector.ner_spans(text) if s not in spans)
            spans.sort(key=lambda s: s[1])

        parts: list[str] = []
        cursor = 0
        for _label, start, end, value in spans:
            if start < cursor:
                continue  # overlap guard
            token_id = self._token_id(value)
            self._values[token_id] = value
            parts.append(text[cursor:start])
            parts.append(f"[[PHI:{token_id}]]")
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)

    def detokenize(self, text: str) -> str:
        """Replace `[[PHI:id]]` tokens with their original values; unknown tokens are left as-is."""
        if not text:
            return text
        return TOKEN_RE.sub(lambda m: self._values.get(m.group(1), m.group(0)), text)


def scrub_generated_text(text: str) -> str:
    """Post-generation scrubber: never trust model output to be PHI-free."""
    return guard.redact_text(text or "")


def has_leaked_phi(text: str) -> bool:
    return guard.contains_phi(text or "")
