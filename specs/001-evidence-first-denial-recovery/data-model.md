# Data Model: Evidence-First Denial Recovery Agent

All tables live in one SQLite database (SQLModel, WAL mode) at
`%LOCALAPPDATA%\reclaim\reclaim.db` (never inside OneDrive; see research.md §5).
Money is stored as integer cents. Timestamps are UTC ISO-8601. Every row describes
synthetic data.

Fixture inputs (835, 837, claim map, FHIR resources, payer decisions, policies) are files
under `backend/fixtures/`. They are read by the adapters, never edited by the pipeline.

---

## Case state machine

```text
                 ┌──────────────► out_of_scope        (denial is not CARC 50 / medical necessity)
new ──► resolving ┼──► needs_review                  (identity conflict, missing 837, claim-map miss)
                 └──► resolved ──► gathering ──┬──► evidence_complete ──► drafting ──► ready_for_review
                                   ▲           ├──► needs_evidence ─┐                    │      │
                                   │           ├──► needs_review    │ (task resolved)     │      └──► rejected ──► drafting (new packet version)
                                   │           └──► gather_failed ──┤                     ▼
                                   └───────────────────────────────┘               approved ──► submitting ──┬──► submitted ──► (tracking)
                                                                                                         └──► submit_failed ──► submitting
any non-terminal state ──► expired   (demo date is past the appeal deadline; submission blocked)
```

| From | To | Guard (deterministic) | Actor |
|---|---|---|---|
| `new` | `resolving` | 837 fetch started | system (Registrar) |
| `resolving` | `resolved` | every IdentityCheck passes and exactly one ClaimMapEntry | system |
| `resolving` | `needs_review` | any IdentityCheck fails, 837 missing, 0 or >1 map entries | system |
| `new` | `out_of_scope` | denial category ≠ `medical_necessity` | system |
| `resolved` | `gathering` | always | system (Chart Abstractor) |
| `gathering` | `needs_review` | no PayerPolicy matches payer + plan + procedure + DOS | system |
| `gathering` | `gather_failed` | EHR or payer adapter error | system |
| `gathering` | `evidence_complete` | matrix `satisfied_count == total` | system (Auditor) |
| `gathering` | `needs_evidence` | any requirement `missing`; one EvidenceTask per missing requirement | system |
| `needs_evidence` | `gathering` | all tasks for the case resolved | treating-clinician |
| `evidence_complete` | `drafting` | always | system (Appeals Writer) |
| `drafting` | `ready_for_review` | packet passes LetterCheck (model or template) | system |
| `ready_for_review` | `approved` | persona has `authorized-billing-user`; approves the current packet version | billing approver |
| `ready_for_review` | `rejected` | same role; reason required | billing approver |
| `approved` | `submitting` | deadline not passed | system (Courier) |
| `submitting` | `submitted` | payer adapter returned `received` | system |
| `submitting` | `submit_failed` | adapter unavailable or 5xx; retryable | system |
| * | `expired` | `demo_date > appeal_deadline` | system |

Transitions use compare-and-set (`UPDATE case SET state=:to, version=version+1 WHERE id=:id AND state=:from AND version=:v`)
and always insert a `CaseEvent` in the same transaction.

---

## Entities

### RemittanceFile

One 835 file taken from the clearinghouse inbox.

| Field | Type | Rules |
|---|---|---|
| id | int PK | |
| source | enum `local`, `sftp` | which InboxSource delivered it |
| file_name | str | original name, e.g. `era-2026-09-12.835` |
| sha256 | str | **UNIQUE**; exact-duplicate guard |
| sender_id | str | ISA06, trimmed |
| interchange_control_number | str | ISA13 |
| trace_number | str | TRN02 (check/EFT trace) |
| status | enum `ingested`, `duplicate`, `suspected_duplicate`, `rejected` | `suspected_duplicate` when (sender_id, ISA13) was seen with a different hash |
| structural_errors | JSON list | from `x12_validate`; non-empty ⇒ `rejected` |
| claims_found / denials_found | int | |
| received_at | datetime | |

UNIQUE (sender_id, interchange_control_number, sha256).

### Case

| Field | Type | Rules |
|---|---|---|
| id | str PK | `case-` + numeric tail of CLP01 (`HSP-CLM-100028` → `case-100028`) |
| hospital_claim_id | str | CLP01, **UNIQUE** |
| payer_claim_id | str | CLP07 |
| payer_name / payer_id | str | N1*PR |
| member_id | str | `ClaimPayment.member_id` (NM1*IL, else NM1*QC with MI) |
| patient_display_name | str | NM1*QC; display only, never used to match (FR-007) |
| group_code / reason_code | str | first CO adjustment at claim or line level (the corrected 835 puts it under `SVC`); `denial_code` = `CO-50` |
| remark_codes | JSON list | LQ*HE RARCs, e.g. `N661`, `N130` |
| remit_policy_id | str null | line `REF*0K`; if present the selected PayerPolicy id must match (`policy.remit_mismatch`) |
| denial_category | enum | from `carc_rarc.get_category` |
| denied_amount_cents | int | sum of CO-group CAS amounts across the claim and its denied lines |
| remittance_file_id | FK RemittanceFile | |
| patient_id / mrn / encounter_id | str null | set only in `resolved` |
| date_of_service | date null | from 837 `DTP*472` after identity passes |
| appeal_deadline | date null | from PayerDecision |
| expected_recovery_cents | int null | = denied_amount_cents for a full CO-50 denial (deterministic) |
| state | enum (above) | |
| state_reason | str null | machine code, e.g. `identity.member_id_mismatch`, `policy.none_effective` |
| version | int | optimistic lock |
| created_at / updated_at | datetime | |

### OriginalClaim

Parsed 837P for a case. One per case.

| Field | Type | Rules |
|---|---|---|
| case_id | FK Case, UNIQUE | |
| archive_path | str | `/claim-archive/837/{claim_id}.837` |
| sha256 | str | of the 837 bytes |
| claim_id | str | CLM01 |
| member_id | str | NM1*IL NM109 |
| payer_id | str | NM1*PR NM109 |
| billing_npi / rendering_npi | str | NM1*85 / NM1*82; both Luhn-valid (NPI check digit) |
| medical_record_number | str null | REF*EA (optional in the TR3; the claim map stays the source of truth) |
| prior_authorization_number | str null | REF*G1 |
| group_number | str | SBR03 |
| frequency_code | str | CLM05-3; must be `1` for this feature |
| total_charge_cents | int | CLM02 |
| diagnosis_codes | JSON list[str] | HI, principal first |
| service_lines | JSON list | `{line, procedure_code, modifiers, charge_cents, units, service_date, diagnosis_pointers, line_control_number}`; `line_control_number` (REF*6R) matches the 835 service line |

### ClaimMapEntry

Loaded from `fixtures/claim-map.json` (stands in for the hospital billing system).

| Field | Type | Rules |
|---|---|---|
| hospital_claim_id | str | |
| patient_id | str | FHIR `Patient.id` |
| mrn | str | must equal `Patient.identifier[type=MR].value` and 837 `REF*EA` when present |
| encounter_id | str | FHIR `Encounter.id` |
| date_of_service | date | |

Lookup must return exactly one row; zero or many ⇒ `needs_review`.

### IdentityCheck

One row per compared field per resolution attempt.

| Field | Type | Rules |
|---|---|---|
| case_id | FK | |
| attempt | int | increments on re-resolution |
| field | enum `claim_id`, `member_id`, `date_of_service`, `payer`, `billing_provider`, `procedure`, `mrn` | |
| value_835 / value_837 / value_map | str null | raw values as compared |
| result | enum `pass`, `fail`, `not_applicable` | `not_applicable` only when the 835 legitimately lacks the element (e.g. no SVC loop ⇒ procedure checked 837 vs map policy procedure) |

Comparison rules: exact string match after trimming; dates compared as `date`; payer compared by
payer id, not name. Names are never compared.

### EvidenceItem

A FHIR resource retrieved for the case (and its text, when textual).

| Field | Type | Rules |
|---|---|---|
| id | int PK | |
| case_id | FK | |
| resource_type | str | one of the FR-008 types |
| resource_id / version_id | str | `meta.versionId` required on every fixture |
| reference | str | versioned: `DocumentReference/treatment-note-022/_history/1` |
| content_reference | str null | `Binary/treatment-note-022/_history/1` |
| clinical_date | date null | per type: Condition.onset/recordedDate, ServiceRequest.authoredOn, Procedure.performed, DiagnosticReport.effective, Observation.effective, DocumentReference.context.period.start or date, MedicationRequest.authoredOn |
| last_updated | datetime | `meta.lastUpdated` |
| source_system | str | `mock-hospital FHIR R4` |
| content_type | str null | |
| text | str null | decoded text for `text/*`; PDFs are listed but not excerptable |
| text_sha1_b64 | str null | must equal `attachment.hash` when present |
| codes | JSON list | `{system, code}` extracted for rule matching (ICD-10-CM, LOINC, RxNorm, etc.) |

The **evidence set** for a matrix is the sorted list of `reference`s; its SHA-256 is stored on the
matrix and packet (sealing, Constitution III).

### PayerDecision

| Field | Type | Rules |
|---|---|---|
| case_id | FK, UNIQUE | |
| payer_claim_id / claim_id | str | must equal Case values, else `needs_review` |
| decision | enum `denied`, `paid`, `partial` | only `denied` continues |
| reason_code / reason_text | str | reason_code must equal Case.denial_code |
| appeal_deadline | date | |
| allowed_submission_channels | JSON list | contains `portal` for API submission |
| letter_document_id / letter_sha256 | str | |

### PayerPolicy

Versioned snapshot loaded from `fixtures/policies/*.json`.

| Field | Type | Rules |
|---|---|---|
| policy_id + version | str + int | composite PK |
| payer_id / plan_type | str | |
| states | JSON list | empty = all states |
| procedure_codes | JSON list | |
| effective_start / effective_end | date / date null | |
| requirements | JSON list of Requirement | ≥1 |
| source_url | str | `https://example.org/mock-policy/...` (clearly fake) |
| retrieved_at | date | |
| snapshot_sha256 | str | of the JSON file bytes |

**Requirement** (embedded):

```json
{
  "id": "R2",
  "text": "Documented trial of conservative treatment",
  "evidenceTypes": ["DocumentReference", "MedicationRequest", "Procedure"],
  "rule": {
    "anyOf": [
      {"resourceType": "Procedure", "codeIn": "conservative-therapy", "performedBefore": "dateOfService", "minDurationDays": 42},
      {"resourceType": "MedicationRequest", "authoredBefore": "dateOfService", "minDurationDays": 42},
      {"resourceType": "DocumentReference", "textMatches": "conservative-therapy-phrases", "dateBefore": "dateOfService"}
    ]
  }
}
```

Rules reference named value sets and phrase lists shipped with the policy file. The matrix
evaluator is a pure function of (policy version, evidence set, date of service). No model call.

Selection: `payer_id == case.payer_id AND plan_type == coverage.plan AND procedure ∈ procedure_codes
AND effective_start ≤ DOS AND (effective_end IS NULL OR DOS ≤ effective_end)`; exactly one match,
else `needs_review` with `policy.none_effective` or `policy.ambiguous`.

### EvidenceMatrix, RequirementResult, Citation

| EvidenceMatrix | Type | Rules |
|---|---|---|
| id | int PK | |
| case_id | FK | |
| policy_id / policy_version | str / int | |
| evidence_set_sha256 | str | |
| satisfied_count / total | int | |
| complete | bool | `satisfied_count == total` |
| built_at | datetime | |

| RequirementResult | Type | Rules |
|---|---|---|
| matrix_id + requirement_id | PK | |
| status | enum `satisfied`, `missing`, `conflicting` | `conflicting` when a matching item is contradicted (e.g. therapy dated after DOS) |
| rule_trace | JSON | which `anyOf` branch matched, for the on-screen reasoning panel |

| Citation | Type | Rules |
|---|---|---|
| id | str | `C1`, `C2`… stable within a matrix |
| requirement_result | FK | a satisfied requirement has ≥1 |
| evidence_item_id | FK | must belong to the same case and evidence set |
| reference | str | versioned reference |
| clinical_date | date | |
| start / end | int | code-point offsets into EvidenceItem.text (0-based, end exclusive) |
| exact / prefix / suffix | str | W3C TextQuoteSelector; `text[start:end] == exact` is asserted on write |

Structured-only evidence (e.g. a Condition with no text) cites the resource with
`exact` = a rendered, deterministic summary (`"Condition M54.16 Radiculopathy, lumbar region, onset 2026-06-01"`)
and `start`/`end` null.

### EvidenceTask

| Field | Type | Rules |
|---|---|---|
| id | str | `task-{case}-{requirement}` (UNIQUE ⇒ exactly one per missing requirement) |
| case_id / requirement_id | FK / str | |
| task_type | enum `clinical-evidence-request` | |
| assignee_role | enum `treating-clinician` | |
| question | str | template: "The policy {policy_id} requires {requirement.text}. Please identify the relevant note or provide a factual attestation." |
| status | enum `open`, `resolved`, `cancelled` | |
| resolution_reference | str null | reference of the record the clinician pointed to |

### AppealPacket

| Field | Type | Rules |
|---|---|---|
| id | int PK | |
| case_id + version | UNIQUE | version increments on re-draft |
| matrix_id | FK | matrix must be `complete` |
| evidence_set_sha256 | str | copied from matrix; packet is invalid if it differs |
| letter_source | enum `model`, `template` | shown on screen (FR-025) |
| fallback_reason | str null | e.g. `llm.no_api_key`, `llm.uncited_claim`, `llm.digit_in_prose` |
| letter_markdown | str | placeholders already filled by code |
| fields | JSON | FR-014 structured fields; the single source for every amount/date/id |
| attachments | JSON list | evidence references + `policy-snapshot-{policy_id}` + denial letter id |
| pdf_sha256 | str | reportlab output, SYNTHETIC watermark |
| required_role | str | `authorized-billing-user` |
| status | enum `ready_for_review`, `approved`, `rejected`, `superseded` | |
| content_sha256 | str | over `fields` + `letter_markdown` + `attachments` |

### Approval

| Field | Type | Rules |
|---|---|---|
| packet_id | FK | |
| user_id / role | str | role must be `authorized-billing-user` |
| decision | enum `approved`, `rejected` | |
| packet_content_sha256 | str | must equal packet's current hash (approves exactly what was shown) |
| reason | str null | required for `rejected` |
| at | datetime | |

### Submission

| Field | Type | Rules |
|---|---|---|
| id | int PK | |
| packet_id | FK, UNIQUE | |
| idempotency_key | str UNIQUE | `appeal-{case_id}-v{packet.version}` |
| request_sha256 | str | canonical JSON of the request body |
| state | enum `in_flight`, `received`, `failed_retryable`, `conflict` | |
| payer_appeal_id | str null | e.g. `NST-APL-80126` |
| payer_status | enum FHIR Task status subset: `requested`, `received`, `in-progress`, `completed`, `rejected` | |
| received_at | datetime null | |
| expected_resolution_days | int null | |
| attempts | int | |
| last_error | str null | PHI-free code |

### CaseEvent (append-only)

| Field | Type | Rules |
|---|---|---|
| id | int autoincrement PK | |
| case_id | FK | |
| from_state / to_state | str | |
| actor | str | `system:registrar`, `persona:billing-approver-01`, … |
| detail | JSON | PHI-free (passed through `phi.guard.assert_phi_free`) |
| at | datetime | |

No UPDATE or DELETE statements exist for this table outside `demo reset`, which drops and recreates
the database.

### DemoSettings (singleton)

| Field | Type | Rules |
|---|---|---|
| demo_date | date | fixed `2026-09-12` |
| missing_evidence_mode | bool | when true, the mock EHR withholds the resources listed in `fixtures/fhir/withheld.json` |
| letter_mode | enum `auto`, `template` | `auto` uses the model when a key is present |
| active_persona | str | `billing-specialist-01`, `billing-approver-01`, `clinician-lee` |

---

## Mock-side state (lives in the same process, separate tables, prefixed `mock_`)

| Table | Purpose |
|---|---|
| `mock_idempotency` | key, body SHA-256, state (`in_flight`/`done`), stored status + response, created_at (24 h TTL) |
| `mock_appeal` | appeal id sequence, payer claim id, status progression for tracking |

These model the fake payer's own storage and are reset with the demo.
