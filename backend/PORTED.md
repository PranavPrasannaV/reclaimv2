# Modules ported from the RCM repo

Source: `Healtcare-RCM-Denial-Recovery-Agent` at commit `4129fdd`. Everything else in
that repo (Mongo, Postgres, Redis, Vault, Celery, LangGraph, JWT/MFA, SLA timers,
837 frequency-7 refiling flow) was deliberately left behind.

| Source | Destination | What changed on port |
|---|---|---|
| `backend/src/edi/parser.py` | `src/reclaim/edi/x12.py`, `src/reclaim/edi/era835.py` | Tokenizer split into `x12.py` so the 837 parser can share it. Loop 2100 now reads `NM1*QC` / `NM1*IL` (patient name, member id) and claim-level `DTM*232/233`; `N1*PR` keeps the payer id. Fixed a crash: `REF` after an `SVC` raised `AttributeError` because `ServiceLine` had no `references` field. |
| `backend/src/edi/carc_rarc.py` | `src/reclaim/edi/carc_rarc.py` | Unchanged mappings; Mongo seeding note removed. |
| `backend/tests/edi_fixtures/*.edi`, `denial_dataset.json` | `tests/fixtures/edi/` | Copied as-is (50-denial ERA, pipe-delimited ERA, 1,200-record classification dataset). |
| `backend/src/edi/generator.py` | `src/reclaim/edi/x12_writer.py` | Generalised from a frequency-code-7 replacement generator into segment builders plus an original-claim (`CLM05-3 = 1`) 837P builder. Adds the loops the X12 review called for: `SBR03` group number, `SBR09 = 12` (PPO), `REF*G1` prior auth, `REF*EA` medical record number (TR3 REF order), referring (`NM1*DN`) and rendering (`NM1*82`) providers, line `REF*6R`. `ST03` is optional so the same helper can write an 835. Trailing empty elements are trimmed; `ISA15` defaults to `T` because every fixture is synthetic. No longer depends on the Mongo `OriginalClaim` model. |
| `backend/src/services/phi_guard.py` | `src/reclaim/phi/guard.py` | Unchanged. |
| `backend/src/services/phi_detector.py` | `src/reclaim/phi/detector.py` | Settings object replaced by module constants; structlog replaced by stdlib logging. spaCy stays optional. |
| `backend/src/services/phi_tokenizer.py` | `src/reclaim/phi/tokenizer.py` | Redis + Vault Transit token store replaced by an in-process `TokenVault`; NER layer is opt-in so tests are deterministic. |
| `backend/src/services/ehr_client.py` | `src/reclaim/fhir/client.py` | Kept proactive token refresh and the single 401 retry. Redis token cache replaced by an in-process one; transport is injectable (mock EHR, tests). Reads widened from 4 resource types to the 10 the evidence matrix needs, with searchset paging, `DocumentReference` → `Binary` text retrieval, and a refusal to follow URLs outside the configured FHIR base. Token request accepts a SMART backend-services client assertion. |

Known carry-over to resolve in implementation: `guard.py` redacts every ISO date and
every 10-digit number (service dates, NPIs). That is correct for LLM input but means
dates and NPIs must be injected by code after scrubbing, never left in model prose.
