# Research: Evidence-First Denial Recovery Agent

Phase 0 output for `plan.md`. Three parallel research passes (X12, FHIR/SMART, infrastructure and
standards) on 2026-09-12, plus the ported-module review. Each item: **Decision / Rationale /
Alternatives**. Anything not confirmed against a primary source is marked **UNVERIFIED** and must
not be stated flat in the pitch.

No `NEEDS CLARIFICATION` items remain in the Technical Context.

---

## 1. X12 fixture correctness (corrections to the idea document's samples)

**Decision:** Generate both fixtures with `reclaim.edi.x12_writer` and correct the draft samples:

| Draft | Corrected | Why |
|---|---|---|
| `CLP02 = 4` | `1` (processed as primary) | Code 4 is for an unrecognized patient whose claim was not forwarded; a found patient paid $0 is still 1 ([X12 RFI 1423](https://x12.org/resources/requests-for-interpretation/rfi-1423-835-clp02-claim-status-code-4)) |
| `CLP05 = 4800` | `0` | CLP05 is the sum of PR adjustments; a CO-50 denial has none ([RFI 2548](https://x12.org/resources/requests-for-interpretation/rfi-2548-clp05-has-different-value-sum-pr-cas-segments)) |
| `CLP06 = MC` | `12` (PPO) | MC is Medicaid; plan is Commercial PPO. `CI` is valid only in 837 `SBR09` (835 code list taken from a parser's TR3 mapping, not the guide itself) |
| `CAS` at claim level, no `SVC` | `SVC*HC:72148*4800*0` → `DTM*472` → `CAS*CO*50*4800` → `REF*6R` → `REF*0K` → `LQ*HE*N661` → `LQ*HE*N130` | Professional claims require loop 2110 ([RFI 1950](https://x12.org/resources/requests-for-interpretation/rfi-1950-svc-835-required-always)); CARC 50's usage note points to the policy REF in 2110 |
| `DTM*232*20260820` | omitted | Contradicted DOS 2026-08-10; claim dates are optional when every line has a date ([RFI 2055](https://x12.org/resources/requests-for-interpretation/rfi-2055-835-dtm)) |
| `ST*835*0001` without envelope, `SE*8` | full `ISA/GS/ST/BPR/TRN/N1*PR(N3,N4,PER*BL)/N1*PE/LX/…/SE/GE/IEA`, `SE01` computed | Required 835 header; `ST03` is Not Used in the 835; `BPR*H*0*C*NON…` with `BPR16` date is valid for a zero payment |
| 837 without `LX`, billing/subscriber/payer loops | `BHT`, `1000A/B`, `2000A NM1*85/N3/N4/REF*EI`, `2000B SBR/NM1*IL/N3/N4/DMG/NM1*PR`, `CLM`, `REF`, `HI`, `2310A/B`, `LX/SV1/DTP*472/REF*6R` | Minimum 005010X222A1 structure; `ST03 = 005010X222A1` required |
| `HI*ABK:DEMO-DX-01` | `HI*ABK:M5416` | ICD-10-CM without the decimal point |

`CLM*HSP-CLM-100028*4800***11:B:1*Y*A*Y*I` was already valid. Balancing to enforce in the validator:
`CLP03 − Σ CAS = CLP04` and `SVC02 − Σ line CAS = SVC03`
([RFI 2601](https://x12.org/resources/requests-for-interpretation/rfi-2601-claim-line-balancing-relationship-charged-allowed)).
Keep `CLM01` ≤ 17 characters because some payers truncate ([RFI 2091](https://x12.org/resources/requests-for-interpretation/rfi-2091-patient-control-number)).
Send `NM1*82` only when the rendering provider differs from the billing provider ([RFI 1531](https://x12.org/resources/requests-for-interpretation/rfi-1531-rendering-providers-837p)).

**Rationale:** Constitution II. The audience includes people who read X12; a wrong status code is the
kind of error that loses credibility for everything else.

**Alternatives:** Keep the hand-typed drafts: rejected, they fail basic TR3 rules. Status verified by the
tests `test_corrected_835_line_level_denial` and `test_x12_writer.py`; full TR3 validation is §5.

## 2. Linking 835 → 837 → patient

**Decision:** Match on `CLP01 = CLM01`, lines on `REF*6R`, and treat the claim map as the source of truth
for MRN and encounter. Put `REF*EA` in the 837 to show where an MRN can travel, but never depend on the
payer echoing it. Cross-check the 835 line `REF*0K` policy id against the selected policy.

**Rationale:** `CLP01` must equal the submitted `CLM01` (for replacements, the original's
[RFI 1945](https://x12.org/resources/requests-for-interpretation/rfi-1945-replacement-claim-clp01));
`CLP07` is the payer's number, sent back in `REF*F8` only on frequency 7/8; `REF*6R` is echoed for line
matching ([RFI 1917](https://x12.org/resources/requests-for-interpretation/rfi-1917-line-item-control-number-835)).
`REF*EA` is optional in 837P 2300 and payer echo in the 835 is **UNVERIFIED**.

**Alternatives:** Match by member id + DOS: rejected, a patient can have several claims per day. Match by
name: forbidden (Constitution IV).

## 3. NPIs

**Decision:** Use `1234567893` (billing, Mock Hospital), `1987654328` (rendering, Dr. Sam Lee, fake),
`1555000011` (referring, Dr. Anika Patel, fake). Validate NPIs with the Luhn check plus the `80840`
constant (24) in `x12_validate` and in identity checks.

**Rationale:** The draft `1234567890` fails its check digit. The check was run locally; the CMS
check-digit document was not re-fetched in this pass.

## 4. Code sets, clinical realism and licensing

**Decision:**

- Procedure: bare CPT number `72148` in X12 and FHIR, **no AMA descriptor text anywhere in the repo**;
  the UI shows our own plain-English label "MRI, lumbar spine (synthetic label)".
- Diagnosis: ICD-10-CM `M54.16` only (not together with `M51.16`, which M54.1's Excludes1 note forbids).
- FHIR `ServiceRequest.code`: LOINC `30679-5` plus the CPT number. LOINC attribution notice goes in
  `fixtures/DATA_SOURCES.md` (LOINC licence terms **UNVERIFIED** in this pass; check before publishing).
- Remark codes `N661`, `N130`; do not use Medicare-only `N115`/`N386`.
- Fake policy `NST-IMG-2026-04` models the widely published pattern: lumbar MRI without red flags is
  appropriate after ~6 weeks of conservative management (ACR Appropriateness Criteria, Low Back Pain,
  Variant 3; Cigna/eviCore Spine Imaging guideline effective 2026-02-03; Carelon spine imaging). The
  policy file cites none of them as its source; `sourceUrl` is `https://example.org/mock-policy/...`.
- The 837 includes prior authorization `REF*G1`, because commercial payers commonly require prior auth
  for outpatient MRI and a real claim without it would more likely be denied CARC 197 than CARC 50.
- **X12 IP:** CARC/RARC lists are copyrighted by X12; short citations are generally fair use, but X12's IP
  terms prohibit entering X12 standards/IP into AI tools ([x12.org/products/ip-use](https://x12.org/products/ip-use)).
  Therefore code descriptions are shown in the UI only and **never** included in LLM prompts; the prompt
  gets the payer's own `reasonText`. The ported `carc_rarc.py` descriptions are a licensing risk to review
  before any public release (legal conclusion **UNVERIFIED**).

**Rationale:** "Use real standards wherever they exist" (Constitution II) with fully fake patients, while
staying inside licence terms we can verify.

**Alternatives:** Fake codes (`DEMO-PROC-01`): rejected, real standards are the credibility point. AMA CPT
licence: unnecessary if descriptors are absent.

## 5. X12 parsing and validation libraries

**Decision:** Keep the ported hand-written tokenizer for parsing. Add `pyx12` 4.0.0 (BSD, active, has
X221A1 and X222A1 maps, produces a 999) as a **dev-only** validation step in CI, plus our own
`x12_validate` for the envelope, `SE01`, control numbers, balancing and NPI checks at ingest time.

**Rationale:** Parsing needs are small and already tested (43 tests). pyx12 gives an independent,
third-party "passes TR3" claim for SC-007 without putting a heavy dependency in the runtime path.

**Alternatives:** LinuxForHealth x12 (stale since 2022), TigerShark (2021), badX12 (no validation),
Databricks x12 parser (non-OSI licence), edi-835-parser (835 only).

## 6. FHIR R4 fixtures

**Decision:** Hand-author 12–15 resources, shaped to the **mandatory** elements of US Core 6.1 without
claiming conformance. Every resource has `meta.versionId` and `meta.lastUpdated`. DocumentReference and
its Binary share an id; `content.attachment` carries `contentType`, `url`, `size` and base64 SHA-1 `hash`
that CI recomputes. `context.encounter` is a list. Include MedicationRequest (missing from the idea doc's
FHIR list but named by policy R2) and a Procedure for the physical-therapy course.

Search parameters implemented by the mock (all verified in the R4 search parameter registry): Coverage
`patient` (searches `beneficiary`), Condition `patient|code|clinical-status|encounter`, ServiceRequest
`patient|code|authored|encounter`, Procedure `patient|code|date`, DiagnosticReport and Observation
`patient|code|date|category`, DocumentReference `patient|type|category|date|period|encounter`,
MedicationRequest `patient|authoredon|status`. Binary has no search in R4 (read only). Bundles obey
bdl-1 (`total` only on search/history), bdl-2 (`entry.search` only in searchsets) and bdl-7 (unique
`fullUrl`).

**Rationale:** Deterministic demo text is the whole point: the appeal quotes specific note sentences with
offsets. Synthea has no lumbar radiculopathy/MRI/PT module in its listing (one conflicting search hit,
**UNVERIFIED**) and cannot produce the quoted note text.

**Alternatives:** Synthea custom module; SMART `generated-sample-data` (used only as a shape reference).

**Open detail:** the DocumentReference category code system (`us-core-documentreference-category` vs the
Argonaut clinical-notes system) returned conflicting sources; pin it when fixtures are authored.

## 7. FHIR validation in tests

**Decision:** Three layers in pytest, no Java:
1. Vendored official R4 `fhir.schema.json` (4.0.1, JSON Schema draft-06) with `jsonschema.Draft6Validator`.
2. `fhir.resources` 8.x `R4B` models as a typed second check (R4 and R4B are structurally identical for
   every resource type used here; Observation/DiagnosticReport only gained additive subject targets).
3. Hand-written invariants: bdl-1/2/7, us-core-6 (url or data), every `Binary/...` url resolves, `size` and
   `hash` match, Coverage `beneficiary` = patient, all references resolve inside the fixture set.

CI-optional: HAPI `validator_cli.jar -version 4.0.1 -tx n/a` with a cached package directory (Java
version **UNVERIFIED**).

**Rationale:** `fhir.resources` ≥ 7 has no plain R4 subpackage; the JSON schema is the only exact 4.0.1
structural check that runs offline.

**Alternatives:** `fhir.resources` 6.x (pydantic v1 clash with FastAPI, **UNVERIFIED**), `fhircraft`
(downloads packages at runtime), HAPI as the only validator (needs Java on the demo laptop).

## 8. SMART on FHIR backend services

**Decision:** The production-shaped token request is `grant_type=client_credentials`, `scope` (SMART v2,
e.g. `system/*.rs`), `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer`,
`client_assertion=<JWT>`; JWT header `alg` RS384 or ES384, `kid`, `typ: JWT`; claims `iss = sub =
client_id`, `aud` = token URL, `exp` ≤ 5 minutes, unique `jti`. The ported client now accepts a
`client_assertion_factory` (tested). The mock EHR serves `/.well-known/smart-configuration` and verifies
ES384 assertions against a local JWKS using `pyjwt[crypto]`.

**Rationale:** The RCM client posted `client_id` alone, which no backend-services server accepts. Epic's
sandbox `.well-known/smart-configuration` (checked live) advertises `client_credentials`,
`private_key_jwt`, `client-confidential-asymmetric`, `permission-v1` and `permission-v2`.

**Alternatives:** Static bearer token only: kept as a test convenience (`static_token`), not the demo path.
Epic-specific JWT/scope rules beyond the discovery document: **UNVERIFIED**.

## 9. Mock systems transport

**Decision:** Mocks (clearinghouse file store, EHR, Northstar) are FastAPI routers mounted in the same app.
The pipeline's adapters call them over real HTTP semantics through `httpx.ASGITransport` (no sockets), so
headers, status codes, auth and idempotency behave exactly as over the network. Setting
`RECLAIM_EHR_BASE_URL` / `RECLAIM_PAYER_BASE_URL` switches adapters to a real socket transport, e.g. a HAPI
container in CI.

**Rationale:** Offline and one process (Constitution VI, VII) without faking the HTTP layer the adapters
will use in production.

**Alternatives:** Separate mock processes on other ports (more to start, firewall prompts on Windows);
HAPI FHIR JPA Docker (418 MB, needs Docker; CI-only); Medplum (needs PostgreSQL + Redis).

## 10. Evidence citations

**Decision:** Each citation stores a versioned reference (`DocumentReference/treatment-note-022/_history/1`
and `Binary/treatment-note-022/_history/1`), `meta.lastUpdated`, the attachment hash, a W3C
`TextPositionSelector` (`start` inclusive, `end` exclusive, **Unicode code points** over the decoded
`text/plain`, no normalization) and a `TextQuoteSelector` (`exact`, `prefix`, `suffix`). Writes assert
`text[start:end] == exact`. The UI must slice by code points (`Array.from(text)`), not UTF-16 indices.

**Rationale:** R4 version-specific references exist for provenance; W3C Web Annotation selectors are the
standard way to anchor a quote so a reviewer can verify it.

**Alternatives:** Emit a FHIR Provenance resource for the packet as well (not needed for the demo).

## 11. Clearinghouse inbox (SFTP)

**Decision:** `InboxSource` interface; `LocalDirInbox` default; optional `AsyncSSHInbox` against an
in-process asyncssh (2.24.0, Windows CI) server bound to `127.0.0.1:2222` with a cached ed25519 host key,
enabled by `--sftp`. Exactly-once ingest: UNIQUE `sha256(bytes)`; `(ISA06, ISA13)` reuse with a different
hash is `suspected_duplicate` (senders do reuse 9-digit ISA13), plus TRN02 recorded. Move processed files to
unique names (`processed/{sha12}_{name}`), because SFTPv3 `rename` will not overwrite.

**Rationale:** A live SFTP server is a nice beat but a demo-day failure point (port in use, key churn);
the filesystem default cannot fail.

**Alternatives:** `sftpserver` (abandoned 2017), `pytest-sftpserver` (2019), `atmoz/sftp` (Docker).

## 12. Idempotency-Key

**Decision:** Mock Northstar implements: missing key on `POST /appeals` → 400; same key + same body →
replay stored status/body with `Idempotent-Replayed: true`; same key + different body → 422; same key in
flight → 409; errors as `application/problem+json` (RFC 9457); storage `(key, sha256(canonical body),
state, status, response, created_at)` with 24 h TTL; nothing stored when validation fails. Reclaim derives
the key `appeal-{case_id}-v{packet_version}`.

**Rationale:** Latest `draft-ietf-httpapi-idempotency-key-header-07` (2025-10-15) is **expired and
archived**, never an RFC, so we say "modelled on an expired IETF draft", with Stripe's documented storage
behaviour as the practical reference. Section numbers came through a summarizer; spot-check before a slide.

**Alternatives:** No idempotency: rejected (SC-005, double-filing is a real harm).

## 13. Denial letter and appeal PDF

**Decision:** `reportlab` 5.0.1 (BSD, pure wheel + Pillow). Platypus for layout; `onPage` callback draws a
rotated `SYNTHETIC` watermark with `setFillAlpha(0.12)`.

**Alternatives:** fpdf2 (LGPL-3.0, viable); WeasyPrint (needs Pango/MSYS2 on Windows, rejected); HTML only
(kept as in-app preview).

## 14. Background work and live progress

**Decision:** One `asyncio` poller task created in FastAPI `lifespan` and cancelled on shutdown; pipeline
stages run as awaited coroutines per case with a per-case lock. Live progress via FastAPI's native SSE
(`fastapi.sse.EventSourceResponse`, FastAPI ≥ 0.135; release date partly **UNVERIFIED**) with one
`asyncio.Queue` per subscriber and 15 s keep-alive.

**Alternatives:** APScheduler 4 (alpha), arq (needs Redis), Celery (the RCM repo's choice, needs Redis),
WebSockets (bidirectional not needed), `sse-starlette` (only if pinned below FastAPI 0.135).

## 15. Storage

**Decision:** SQLite via SQLModel 0.0.42 with synchronous sessions in a threadpool; database at
`%LOCALAPPDATA%\reclaim\reclaim.db`; `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.
UNIQUE constraints implement exactly-once ingest, one task per requirement, and one submission per packet.
State changes use compare-and-set. JSON sidecars written via temp file + `os.replace`.

**Rationale:** The repo lives in OneDrive; sync tools copying a live SQLite file or moving its `-wal` corrupts
it ([sqlite.org/howtocorrupt](https://www.sqlite.org/howtocorrupt.html)). WAL does not work on network
filesystems.

**Alternatives:** JSON files (no unique constraints or atomic multi-row updates); aiosqlite (thread per
connection, no gain); Postgres (external infra).

## 16. Appeal letter generation with Claude

**Decision:** Official `anthropic` Python SDK, model `claude-opus-5`, adaptive thinking (default on this
model), server-side refusal fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`),
check `stop_reason` for `refusal` before reading content. Use the **Citations** feature: one `document`
block per sealed evidence item (plain text for notes, custom content for structured resources), titled
with the versioned FHIR reference; the model writes fact placeholders and no digits; code runs the eight
checks in `contracts/appeal-letter-generation.md` and falls back to a deterministic template on any failure.
Do not use `output_config.format` on this call (it is incompatible with citations and returns 400).
Identifiers are tokenized with the ported `TokenVault` before sending; model output is scrubbed.

**Rationale:** Citations give machine-checkable `cited_text` per claim, which enforces "may cite only
retrieved records" structurally rather than by prompt (Constitution III). The template path keeps the demo
alive offline (Constitution VI).

**Alternatives:** Structured outputs with a JSON citation schema (loses API-verified `cited_text`); tool use
returning sentences + reference ids (possible, but duplicates what Citations provides); no LLM (template
only) — kept as the fallback, but loses the "Creative use of AI" story at events that score it.

## 17. Frontend

**Decision:** Vite + React SPA in `frontend/`, built `dist/` committed and served by FastAPI on the same port
with API routers first, `/assets` mount, then a catch-all returning `index.html` (Starlette `StaticFiles(html=True)`
does not fall back for client routes). UI code is gated by the `design-stack` workflow: design system first.

**Rationale:** One command, no Node on the demo laptop. Next.js static export gives up server features and
needs `generateStaticParams` for dynamic routes.

**Alternatives:** Next.js 16 (heavier, two processes in dev); server-rendered Jinja (fails the design bar
for the matrix animation and live timeline).

## 18. Payer appeal reality (for honest disclosure)

**Decision:** Disclose on the data-sources page and in the pitch: "No HIPAA-adopted or HL7 standard exists
for electronic claim appeals. Real submission is via payer portal, fax/mail, vendor tools, or esMD for
Medicare. Northstar's API is a mock whose payload borrows Da Vinci CDex `$submit-attachment` field names
and FHIR Task status codes."

**Rationale:**
- CMS-0053-F (final, 91 FR 14350, published 2026-03-24) adopts X12 275 / 277 RFAI attachment standards and
  states they do not apply to attachments exchanged as part of a separate claims appeal. The compliance date
  was reported inconsistently by the research pass (2028-05-26 is the corrected figure): **UNVERIFIED — check
  before quoting**.
- CMS-0057-F covers prior authorization (APIs by 2027-01-01), not claim appeals.
- Da Vinci CDex STU 2.1 `$submit-attachment` parameters (TrackingId, AttachTo, PayerId, MemberId,
  ServiceDate, Attachment) verified; using `AttachTo=claim` for an appeal stretches its intent, and we say so.
- Medicare FFS redetermination: 120 days to file, 60-day MAC decision.

**Alternatives:** Pretend a universal payer API exists: forbidden (Constitution II).

## 19. Ported-module findings

**Decision:** Keep the five ported modules (see `backend/PORTED.md`), with these fixes already made and tested:
`REF` after `SVC` crashed the RCM parser (`ServiceLine` had no `references`); the 835 parser ignored `NM1*QC`
/ `NM1*IL`, so member id was lost; the EHR client sent no client assertion; the writer lacked required 837
loops. Known carry-over: `phi.guard` redacts every ISO date and 10-digit number, so dates and NPIs are
injected after scrubbing (the placeholder design in §16 does exactly this).

**Rationale:** Evidence that reuse beat rewrite: 43 tests pass on the ported code, including the two
regressions above.
