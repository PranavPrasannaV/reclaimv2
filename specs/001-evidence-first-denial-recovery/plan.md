# Implementation Plan: Evidence-First Denial Recovery Agent

**Branch**: `001-evidence-first-denial-recovery` | **Date**: 2026-09-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-evidence-first-denial-recovery/spec.md`

## Summary

A synthetic 835 remittance lands in a mock clearinghouse inbox; Reclaim ingests it exactly once, pulls the
matching 837P, and runs an **Identity Hard Stop** (claim id, member id, DOS, payer, provider, procedure, MRN)
before touching the chart. It then gathers only the relevant FHIR R4 evidence from a mock EHR, fetches the
payer decision from a mock Northstar Health adapter, selects the versioned payer policy in effect on the date
of service, and builds a deterministic evidence matrix with code-point-anchored citations. A complete matrix
produces a cited appeal packet (Claude writes prose under an **Evidence Lock**, and code supplies every fact).
An incomplete one produces exactly one targeted clinician task. **Nothing Leaves Without a Human**: an
authorized approver approves the exact packet version, and submission goes through an idempotent payer
adapter that returns `NST-APL-80126`. One Python process, one port, offline-capable, all data synthetic.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 5 + React 19 (dashboard, prebuilt)

**Primary Dependencies**:
- runtime: FastAPI ≥ 0.135 (native SSE), uvicorn, SQLModel 0.0.42, httpx ≥ 0.27, anthropic (official SDK), reportlab 5.0.1, pyjwt[crypto]
- optional: asyncssh 2.24 (`--sftp`), spaCy (`phi-ner`)
- dev: pytest, pytest-asyncio, jsonschema, fhir.resources 8.x, pyx12 4.0.0, ruff
- frontend build only: Vite 8

**Storage**: SQLite (WAL) at `%LOCALAPPDATA%\reclaim\reclaim.db`, never in OneDrive. Fixtures are versioned files under `backend/fixtures/`.

**Testing**: pytest (unit, contract, integration, fixture validation), with an `offline` marker that blocks sockets and unsets the LLM key. Optional CI steps: HAPI FHIR validator and pyx12 `x12valid`. UI is verified in the Browser pane.

**Target Platform**: Windows 11 laptop (demo); Linux CI

**Project Type**: Web application (FastAPI backend + static SPA served by the same process)

**Performance Goals**: remit → "Ready for review" < 60 s with the template letter and < 90 s with the model letter (SC-001); matrix rows animate in as evaluated

**Constraints**: offline with no API key; one command; one port (8000); no Docker; no real or de-identified patient data; no AMA CPT descriptors or X12 code-list text in LLM prompts

**Scale/Scope**: 1 payer, 1 plan, 1 denial type (CARC 50), 1 primary case, ~10 mutated identity-conflict fixtures, missing-evidence variant; optional 50-denial ERA to populate the worklist

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the design satisfies it | Pre-research | Post-design |
|---|---|---|---|
| I. Synthetic data only, disclosed | Hand-authored fixtures; `ISA15 = T` enforced at ingest (`P` refused); SYNTHETIC watermark on PDFs; `"synthetic": true` in every API response and payer mock schema; data-sources view (FR-022/023) | PASS | PASS |
| II. Real standards where they exist | X12 5010 835/837P generated and validated (research §1, §5); FHIR R4 with schema + invariants (§6, §7); real CPT/ICD-10-CM/LOINC/CARC/RARC code numbers (§4); payer API labelled MOCK with OpenAPI contract and disclosure (§18) | PASS | PASS |
| III. Evidence before prose | Matrix is a pure function of policy version + evidence set + DOS (data-model); citations anchored by code points (§10); Evidence Lock checks 1–8 with template fallback (contracts/appeal-letter-generation.md); missing requirement ⇒ task, no letter (FR-013) | PASS | PASS |
| IV. Identity hard stop | Registrar compares seven fields before any EHR call; `ClinicalSource.gather` refuses non-`resolved` cases; SC-002 counts EHR requests via transport hook | PASS | PASS |
| V. Nothing leaves without a human | Approval bound to `packet.content_sha256` and role; Idempotency-Key per packet version; append-only CaseEvent; `submitted` only after payer receipt | PASS | PASS |
| VI. Deterministic core, demo cannot fail | Parsing, identity, deadlines, policy selection, matrix, idempotency are unit-tested code; LLM optional with visible `letterSource`; ASGI transport keeps mocks offline; `reclaim demo` single command | PASS | PASS |
| VII. Simplicity | One process, SQLite, in-process mocks; adapters per external system; corrected claims and other denial types out of scope | PASS | PASS (one justified deviation below) |
| Data handling | Logs/events PHI-free via `phi.guard`; TokenVault before LLM; policies versioned and selected by payer + plan + procedure + DOS, cross-checked with 835 `REF*0K` | PASS | PASS |
| Workflow | Test-first for deterministic core; fixture validation in CI; evidence-based task completion; design-stack gate before UI code | PASS | PASS |

**Gate result: PASS.** No unjustified violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-evidence-first-denial-recovery/
├── spec.md
├── plan.md                                   # this file
├── research.md                               # Phase 0
├── data-model.md                             # Phase 1
├── quickstart.md                             # Phase 1
├── contracts/
│   ├── northstar-payer-api.openapi.yaml      # MOCK payer (decision, documents, appeals + Idempotency-Key)
│   ├── mock-ehr-fhir.md                      # FHIR R4 subset + SMART discovery/token
│   ├── clearinghouse-inbox.md                # 835 inbox + 837 archive layout and rules
│   ├── reclaim-app-api.md                    # dashboard API + SSE events
│   ├── appeal-letter-generation.md           # Evidence Lock: Claude citations + checks + template
│   └── adapters.md                           # production seams (Protocols)
└── tasks.md                                  # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml
├── PORTED.md                         # provenance of modules reused from the RCM repo
├── src/reclaim/
│   ├── app.py                        # FastAPI factory, lifespan (poller), routers, SPA catch-all
│   ├── cli.py                        # `reclaim demo [--sftp]`
│   ├── settings.py                   # DATA_DIR, demo date, feature flags
│   ├── db.py                         # engine, pragmas, session, reset
│   ├── models/                       # SQLModel tables (data-model.md)
│   ├── edi/
│   │   ├── x12.py                    # PORTED tokenizer
│   │   ├── era835.py                 # PORTED 835 parser (+NM1, DTM, REF fixes)
│   │   ├── claim837.py               # NEW 837P parser (shares x12.py)
│   │   ├── carc_rarc.py              # PORTED
│   │   ├── x12_writer.py             # PORTED/generalised writer (fixtures)
│   │   └── x12_validate.py           # NEW envelope, SE01, control numbers, balancing, NPI Luhn, ISA15
│   ├── phi/                          # PORTED guard, detector, tokenizer
│   ├── fhir/client.py                # PORTED/extended FHIR client
│   ├── adapters/                     # inbox, claim_archive, claim_map, clinical, payer, policy_store
│   ├── pipeline/
│   │   ├── orchestrator.py           # state machine, CAS transitions, events, per-case lock
│   │   ├── mailroom.py               # The Mailroom: poll → validate → parse → cases
│   │   ├── registrar.py              # The Registrar: 837 fetch, claim map, Identity Hard Stop
│   │   ├── chart_abstractor.py       # The Chart Abstractor: FHIR gather → EvidenceItems
│   │   ├── payer_liaison.py          # The Payer Liaison: decision + denial letter
│   │   ├── policy_librarian.py       # The Policy Librarian: select policy by payer+plan+procedure+DOS, REF*0K check
│   │   ├── auditor.py                # The Auditor: deterministic matrix + citations + tasks
│   │   ├── appeals_writer.py         # The Appeals Writer: packet fields, Evidence Lock, PDF
│   │   └── courier.py                # The Courier: idempotent submission + status tracking
│   ├── llm/                          # ClaudeLetterWriter, TemplateLetterWriter, checks
│   ├── pdf/letter.py                 # reportlab packet + denial letter renderer
│   ├── api/                          # cases, demo, tasks, data_sources, events (SSE)
│   └── mocks/                        # clearinghouse, ehr (FHIR + SMART), northstar (payer)
├── fixtures/                         # all synthetic; see DATA_SOURCES.md
│   ├── DATA_SOURCES.md
│   ├── clearinghouse/outbound/835/era-2026-09-12.835
│   ├── clearinghouse/claim-archive/837/HSP-CLM-100028.837
│   ├── claim-map.json
│   ├── fhir/R4/*.json, fhir/withheld.json, fhir/schema/fhir.schema.json
│   ├── ehr/jwks.json
│   ├── payer/northstar/decisions/PAYER-CLM-99281.json, appeal-response.json
│   ├── policies/NST-IMG-2026-04.v1.json
│   └── mutations/                    # identity-conflict variants for SC-002
├── scripts/build_fixtures.py         # writes 835/837 via x12_writer, Binary hashes, denial-letter PDF
└── tests/
    ├── unit/                         # 43 passing today (ported modules)
    ├── contract/                     # Northstar OpenAPI + idempotency, mock EHR search/bundle rules
    ├── integration/                  # main flow, identity hard stop, missing evidence, offline
    └── fixtures_validation/          # X12 structure, FHIR schema + invariants

frontend/
├── src/                              # worklist, case (identity, evidence, matrix, packet, timeline), data sources
└── dist/                             # committed build served by FastAPI
```

**Structure Decision**: Web application layout (backend + frontend) because the demo needs a real dashboard,
but a single runtime process: FastAPI serves the API, the three mocks and the prebuilt SPA. The pipeline
stages carry human job-title names (Mailroom, Registrar, Chart Abstractor, Payer Liaison, Policy Librarian,
Auditor, Appeals Writer, Courier). Only the Appeals Writer calls a model; the others are deterministic code,
and the UI says so.

## Build Order (input to /speckit-tasks)

1. **Fixtures and validators**: `build_fixtures.py`, `x12_validate`, FHIR schema + invariant tests, `DATA_SOURCES.md` (SC-007). Everything downstream reads these.
2. **US1 (P1)**: models/db, orchestrator, Mailroom (LocalDirInbox), `claim837.py`, Registrar + mutation fixtures (SC-002, SC-005 ingest half).
3. **US2 (P1)**: mock EHR + SMART token, mock Northstar decision/documents, policy store, Chart Abstractor, Payer Liaison, Policy Librarian, Auditor (matrix + citations).
4. **US3 (P1)**: Appeals Writer (template first, then Claude with Evidence Lock), PDF, approval, Courier + mock `POST /appeals` idempotency (SC-003, SC-005).
5. **US4 (P2)**: missing-evidence mode, EvidenceTask, clinician resolve loop (SC-004).
6. **API + SSE**, then **UI** through design-stack (design system → worklist → case → matrix animation → packet → timeline).
7. **US5 (P3)**: data-sources view, reset, offline integration test, optional `--sftp`, three-replay run (SC-006, SC-008).

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Judge who knows X12 spots a wrong segment | Fixtures generated by code, validated by our checks and pyx12 in CI; corrections documented in research §1 |
| Licensing: CPT descriptors, X12 code text, LOINC notice | No AMA descriptors; X12 descriptions UI-only, never in prompts; LOINC notice in DATA_SOURCES; legal review before public release |
| Model latency or refusal during a live demo | Template path is first-class; `letterMode=template` switch; server-side refusal fallback; 30 s timeout |
| SQLite corruption from OneDrive sync | DB in `%LOCALAPPDATA%`; reset recreates it |
| Plausibility: MRI denied for medical necessity despite prior auth | `REF*G1` on the claim; the policy requires documentation the payer said was insufficient |
| spec-kit scripts fail on this machine (python3 shim, no jq) | Documented env-var workaround in CLAUDE.md |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Second language/toolchain (TypeScript SPA via Vite) alongside Python | The demo climax (matrix rows turning green live, citation highlighting in note text, timeline) and the design-stack quality bar need a component UI | Server-rendered Jinja templates cannot deliver the live matrix/citation interactions at the required design quality; the built `dist/` is committed, so the runtime is still one Python process |
