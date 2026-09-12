# Quickstart: Evidence-First Denial Recovery Agent

Validation guide proving the feature end to end. Everything runs on one Windows 11 laptop, in one
process, on `http://127.0.0.1:8000`. **All data is synthetic.**

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/) (`uv --version`)
- Optional: `ANTHROPIC_API_KEY` (or an `ant auth login` profile) for the model letter path
- Optional: Node 22.12+ only to rebuild the dashboard; the built `frontend/dist` is committed

## Setup and run

```bash
cd backend
uv sync --extra dev
uv run reclaim demo
```

`reclaim demo` creates `%LOCALAPPDATA%\reclaim`, resets demo state, starts the poller, mounts the
mock clearinghouse, EHR and Northstar payer, and opens the dashboard. `uv run reclaim demo --sftp`
also starts the local SFTP server on `127.0.0.1:2222`.

## Automated validation

```bash
cd backend
uv run pytest                          # unit + contract + integration
uv run pytest tests/fixtures_validation # X12 structure + FHIR R4 schema + invariants (SC-007)
uv run pytest -m offline               # full flow with sockets blocked and no LLM key (SC-006)
```

Optional CI-only structural cross-check against HAPI's validator (Java):
`java -jar validator_cli.jar fixtures/fhir/R4/*.json -version 4.0.1 -tx n/a`.

## Scenario 1: Main flow (US1-US3, SC-001)

1. Dashboard → persona **billing-specialist-01** → **Simulate incoming remit**. Start a stopwatch.
2. Expect within a few seconds: case `case-100028`, Northstar Health, **CO-50**, **$4,800**.
3. Open the case → **Identity**: 835 `HSP-CLM-100028` → 837 `HSP-CLM-100028` → `patient-0042` /
   `MRN-0042` / `encounter-20260810-42`; all 7 checks `pass`.
4. **Evidence**: order, progress note, treatment note, imaging report, coverage, each with reference
   and date. **Decision**: deadline **2026-10-19**, channels portal + fax, denial letter opens (SYNTHETIC watermark).
5. **Matrix**: policy `NST-IMG-2026-04` v1; R1, R2, R3 turn green one by one; header reads
   **Evidence completeness: 3/3 policy criteria satisfied**.
6. **Packet**: "Ready for review", deadline October 19, expected recovery $4,800; stopwatch
   < 60 s (template) / < 90 s (model). Letter source badge shows `model` or `template`.
7. Try **Approve** as billing-specialist-01 → refused (403).
8. Switch persona to **billing-approver-01** → **Approve**. Expect `NST-APL-80126`, status `received`,
   expected resolution 14 days; case state `submitted`. Timeline shows every transition with actor.

## Scenario 2: Missing evidence (US4, SC-004)

1. **Reset**. Settings → **Missing evidence mode** on. Simulate incoming remit.
2. Expect matrix **2/3**, R2 `missing`; case `needs_evidence`; **no** packet exists.
3. Tasks: exactly one `clinical-evidence-request` for `treating-clinician` naming "Documented trial
   of conservative treatment".
4. Persona **clinician-lee** → resolve task. Matrix returns to 3/3, packet becomes ready.

## Scenario 3: Identity hard stop (SC-002)

```bash
uv run pytest tests/integration/test_identity_hard_stop.py -v
```

Parametrised over mutated fixtures (member id, DOS, billing NPI, procedure, payer id, missing map
entry, duplicate map entry). Each expects `needs_review` and **0** requests recorded by the EHR
transport hook.

## Scenario 4: Idempotency (SC-005)

1. Click **Simulate incoming remit** twice → still one case; second file shows `duplicate` in
   **Data → Remittance files**.
2. `uv run pytest tests/contract/test_northstar_idempotency.py -v`: same key + same body → `200`
   replay with `Idempotent-Replayed: true` and the same `appealId`; different body → `422`;
   concurrent → `409`; no key → `400`.

## Scenario 5: Honest demo (US5, SC-006, SC-008)

1. Unset `ANTHROPIC_API_KEY`, disconnect Wi-Fi, run Scenario 1: completes, letter source `template`,
   fallback reason `llm.no_api_key`.
2. **Data sources** view lists every fixture with origin and licence, and marks Northstar API,
   mock EHR and clearinghouse as MOCK.
3. Run reset → Scenario 1 → Scenario 2 three times without restarting the process.

## Scenario 6: Payer outage (US3 scenario 5)

1. Settings → **Fail next submission (503)**. Approve a ready packet.
2. Expect state `submit_failed` with a Retry button; the case never shows "submitted".
3. Retry → `submitted` with the same Idempotency-Key and one payer appeal.
