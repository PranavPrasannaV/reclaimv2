# Contract: Mock Hospital EHR (FHIR R4, SMART backend services shape)

**MOCK.** Serves hand-authored synthetic resources for one fake patient. Mounted in-process at
`/mock/ehr/fhir/R4`; the demo narrative calls it `https://mock-hospital.example/fhir/R4`.
Consumed only through `reclaim.fhir.client.FhirClient`.

## Discovery and auth

| Method | Path | Behaviour |
|---|---|---|
| GET | `/.well-known/smart-configuration` | `token_endpoint`, `grant_types_supported: ["client_credentials"]`, `token_endpoint_auth_methods_supported: ["private_key_jwt"]`, `token_endpoint_auth_signing_alg_values_supported: ["RS384","ES384"]`, `capabilities: ["client-confidential-asymmetric","permission-v2"]`, `code_challenge_methods_supported: ["S256"]`, `scopes_supported` |
| POST | `/mock/ehr/oauth2/token` | `application/x-www-form-urlencoded`: `grant_type=client_credentials`, `scope`, `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer`, `client_assertion` (ES384 JWT: `iss`=`sub`=client_id, `aud`=token URL, `exp` ≤ 5 min, unique `jti`). Verifies against `fixtures/ehr/jwks.json`. Returns `{"access_token","token_type":"bearer","expires_in":300,"scope"}`. |

Every FHIR call requires `Authorization: Bearer <token>`; missing or expired → `401` with an
OperationOutcome. `Accept: application/fhir+json` is required for JSON.

## Reads

| Method | Path | Notes |
|---|---|---|
| GET | `/Patient/{id}` | |
| GET | `/Encounter/{id}` | |
| GET | `/Binary/{id}` | JSON Binary for `application/fhir+json`; raw bytes with the Binary `contentType` otherwise |
| GET | `/{type}/{id}/_history/{vid}` | version read; every fixture has `meta.versionId` |

Unknown id → `404` + OperationOutcome.

## Searches (return `Bundle.type = searchset`)

| Resource | Supported params |
|---|---|
| Coverage | `patient`, `beneficiary`, `status` |
| Condition | `patient`, `code`, `clinical-status`, `encounter` |
| ServiceRequest | `patient`, `code`, `authored`, `encounter` |
| Procedure | `patient`, `code`, `date` |
| DiagnosticReport | `patient`, `code`, `date`, `category` |
| Observation | `patient`, `code`, `date`, `category` |
| DocumentReference | `patient`, `type`, `category`, `date`, `period`, `encounter` |
| MedicationRequest | `patient`, `authoredon`, `status` |

Rules:

- `patient` accepts `patient-0042` and `Patient/patient-0042`.
- Unsupported params are ignored and reported in an `OperationOutcome` entry with `search.mode = outcome`.
- `_count` (default 50) pages with `link[relation=next]`; `link[relation=self]` always present; `total` present.
- `entry.fullUrl` is absolute and unique; `entry.search.mode` is `match`.
- Date params support `eq`, `lt`, `le`, `gt`, `ge` prefixes on day precision.

## Missing-evidence mode

When `DemoSettings.missing_evidence_mode` is on, resources listed in `fixtures/fhir/withheld.json`
(the conservative-treatment `DocumentReference`, its `Binary`, and the physical-therapy `Procedure`
and `MedicationRequest`) are excluded from reads (404) and searches, exactly as if the chart
lacked them.

## Fixture inventory (all synthetic, hand-authored)

| Id | Type | Shows |
|---|---|---|
| `patient-0042` | Patient | Jordan Rivera (fake), birthDate, gender, `identifier` MR = `MRN-0042` |
| `cov-0042` | Coverage | payor Northstar Health (fake), plan class Commercial PPO, `subscriberId` = `MEMBER-448820`, `beneficiary` = patient |
| `encounter-20260810-42` | Encounter | `AMB`, period 2026-08-10 09:00–09:45Z, participant rendering practitioner, serviceProvider `mock-hospital` |
| `condition-100` | Condition | ICD-10-CM lumbar radiculopathy, onset before DOS |
| `order-901` | ServiceRequest | MRI lumbar spine w/o contrast, `reasonReference` → condition-100, clinical rationale in `note` |
| `proc-pt-001` | Procedure | physical therapy course, `performedPeriod` ≥ 6 weeks before DOS |
| `medrx-nsaid-001` | MedicationRequest | NSAID course before DOS |
| `dr-xray-001` | DiagnosticReport | prior lumbar X-ray, conclusion text |
| `obs-slr-001` | Observation | positive straight-leg raise exam finding |
| `treatment-note-022` + `Binary/treatment-note-022` | DocumentReference + Binary | 2026-07-14 note documenting conservative treatment |
| `note-progress-031` + `Binary/note-progress-031` | DocumentReference + Binary | 2026-08-10 progress note with diagnosis and clinician rationale |

DocumentReference and Binary share an id so a reviewer can follow the link by eye.

Every DocumentReference carries `content.attachment.size` and `hash` (base64 SHA-1) matching its
Binary; CI asserts they agree.
