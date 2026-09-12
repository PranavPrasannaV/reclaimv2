# Contract: Appeal Letter Generation ("Evidence Lock")

Internal interface between the sealed evidence matrix and the letter text. It exists so that the
model can write prose while never becoming the source of a fact.

```python
class LetterWriter(Protocol):
    async def write(self, packet_input: PacketInput) -> LetterDraft: ...

@dataclass(frozen=True)
class PacketInput:
    fields: PacketFields                 # every amount, date, id, policy id/version (from DB)
    requirements: list[RequirementView]  # id, text, status == satisfied
    documents: list[EvidenceDocument]    # the sealed evidence set, one per citation source
    evidence_set_sha256: str

@dataclass(frozen=True)
class LetterDraft:
    source: Literal["model", "template"]
    markdown: str                        # placeholders filled
    citations: list[LetterCitation]      # sentence index -> Citation ids
    fallback_reason: str | None
```

Implementations: `ClaudeLetterWriter` (model) and `TemplateLetterWriter` (deterministic).
`CheckedLetterWriter` wraps the model writer, runs the checks below, and falls back to the template
on any failure, recording `fallback_reason`.

## Model call (ClaudeLetterWriter)

- SDK: official `anthropic` Python SDK. Model `claude-opus-5`, adaptive thinking (default),
  server-side refusal fallback enabled (`fallbacks: "default"`), `stop_reason` checked for `refusal`
  before reading content.
- Input: one `document` content block per EvidenceDocument with `citations: {enabled: true}` (all
  documents, as the API requires). Plain-text source for note excerpts; custom content blocks for
  structured resources (rendered deterministic summaries). Plus a policy document containing the
  requirement texts, and a denial document with the payer's reason text.
- Document `title` = the versioned FHIR reference (for example
  `DocumentReference/treatment-note-022/_history/1`), so every returned citation maps to exactly
  one evidence item.
- Text sent is first passed through `phi.tokenizer.TokenVault.tokenize`; the model sees
  `[[PHI:…]]` tokens for MRNs and similar.
- `output_config.format` is NOT used (incompatible with citations). Any machine fields come from
  `PacketFields`, never from this call.
- The prompt instructs the model to use only these placeholders for facts, and to write no digits:

| Placeholder | Filled from |
|---|---|
| `{{HOSPITAL_CLAIM_ID}}`, `{{PAYER_CLAIM_ID}}` | Case |
| `{{MEMBER_ID}}`, `{{PATIENT_NAME}}` | Case / OriginalClaim |
| `{{SERVICE_DATE}}`, `{{PROCEDURE}}`, `{{DIAGNOSIS}}`, `{{PROVIDER}}` | OriginalClaim |
| `{{DENIED_AMOUNT}}`, `{{DENIAL_CODE}}`, `{{DENIAL_REASON}}` | Case / PayerDecision |
| `{{POLICY_ID}}`, `{{POLICY_VERSION}}`, `{{REQ:R1}}` … | PayerPolicy |
| `{{APPEAL_DEADLINE}}` | PayerDecision |

## Checks, in order (all deterministic; any failure → template)

| # | Check | Failure code |
|---|---|---|
| 1 | Response not a refusal; not truncated (`stop_reason` ∈ {`end_turn`}) | `llm.refusal`, `llm.truncated` |
| 2 | Every citation's `document_title` is in the sealed evidence set | `llm.cited_unknown_record` |
| 3 | Every `cited_text` is an exact substring of that document's text | `llm.cited_text_mismatch` |
| 4 | Every satisfied requirement is cited at least once | `llm.requirement_uncited` |
| 5 | Every sentence that mentions a clinical fact carries ≥1 citation (sentences made only of placeholders and fixed boilerplate are exempt) | `llm.uncited_claim` |
| 6 | No digits in model prose outside placeholders, and no unknown placeholders | `llm.digit_in_prose`, `llm.unknown_placeholder` |
| 7 | After detokenizing and filling placeholders, `phi.tokenizer.has_leaked_phi` on the *model-written spans only* is false | `llm.phi_leak` |
| 8 | Filled amounts/dates/ids equal `PacketFields` byte-for-byte (re-parsed from the output) | `llm.field_mismatch` |

No key, no network, or a timeout (30 s) → `llm.unavailable` / `llm.no_api_key`, straight to template.

## Template (TemplateLetterWriter)

Fixed Markdown with the same placeholders, one paragraph per requirement quoting the citation's
`exact` text with its reference and date. Output is byte-identical for identical inputs (tested with
a golden file).

## Rendering

`pdf.letter.render(packet)` builds the PDF with reportlab Platypus: letterhead "Mock Hospital
(synthetic)", a diagonal `SYNTHETIC` watermark on every page, a citations table (requirement → reference
→ date → excerpt), and an attachment list. The PDF bytes' SHA-256 is stored on the packet.
