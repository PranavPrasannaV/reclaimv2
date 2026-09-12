# Feature Specification: Evidence-First Denial Recovery Agent

**Feature Branch**: `001-evidence-first-denial-recovery`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: the team's idea document, "an evidence-first denial recovery
agent". Hospitals lose money on denied claims because staff must notice the denial, find the
original claim and encounter, read scattered records to judge whether the insurer was wrong,
and write an appeal before the deadline. The product automates the investigation, not just
the letter. All patient data, claims, policies and payer responses are synthetic, and the demo
says so.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A denial arrives and becomes a verified case (Priority: P1)

A billing specialist sees a new $4,800 denial appear on their worklist without uploading
anything. The system picked up a remittance file from the clearinghouse inbox, found the denied
claim, retrieved the original claim, and confirmed that the claim, member, service date, payer,
provider and procedure all agree, before it touched any patient chart.

**Why this priority**: Everything downstream depends on working the right patient's chart. A
wrong-patient match is the one failure that cannot be allowed.

**Independent Test**: Press "Simulate incoming remit". A case appears with the hospital claim
id, payer claim id, member id, denial code and amount, plus a visible 835 → 837 → encounter
mapping with every identity check passed. Repeat with a fixture whose member id differs: the
case shows `needs-review` and no EHR request is made.

**Acceptance Scenarios**:

1. **Given** the synthetic 835 `era-2026-09-12.835` is placed in the mock clearinghouse
   outbound inbox, **When** the ingestion poller runs, **Then** one case `case-100028` is
   created with hospital claim `HSP-CLM-100028`, payer claim `PAYER-CLM-99281`, payer Northstar
   Health, member `MEMBER-448820`, denial `CO-50` (medical necessity) and denied amount $4,800.
2. **Given** a new case, **When** the system fetches `/claim-archive/837/HSP-CLM-100028.837`,
   **Then** it extracts claim id, member id, procedure, diagnosis, date of service, provider NPI,
   units and billed amount, and the claim map resolves it to patient `patient-0042`, MRN
   `MRN-0042` and encounter `encounter-20260810-42`.
3. **Given** all identity checks agree, **When** resolution completes, **Then** the case moves
   to `resolved` and shows each check with the values compared.
4. **Given** any identity check conflicts, **When** resolution runs, **Then** the case moves to
   `needs-review`, the conflicting fields are shown side by side, and no chart data is requested.
5. **Given** the same 835 file is delivered twice, **When** the poller runs again, **Then** no
   duplicate case is created.

---

### User Story 2 - Evidence is gathered and tested against the payer's own policy (Priority: P1)

For a resolved case, the specialist sees only the chart records relevant to this denial (order,
notes, imaging report, coverage), each with its source and date. They also see the payer's
decision details (reason text, appeal deadline, allowed channels, denial letter) and a
requirement-by-requirement matrix against the payer policy that was in effect on the date of
service.

**Why this priority**: This is the product's differentiator: an investigation result, not a
letter. The climax of the demo is the matrix turning green: "3/3 policy criteria satisfied".

**Independent Test**: For a resolved case, run evidence gathering against the mock EHR, mock payer
and policy store. The matrix shows R1-R3 satisfied, each citing specific records with dates and
excerpts, and the case shows deadline October 19 and expected recovery $4,800.

**Acceptance Scenarios**:

1. **Given** a resolved case, **When** evidence gathering runs, **Then** the system reads the
   encounter and patient and searches Coverage, Condition, ServiceRequest, Procedure,
   DiagnosticReport, Observation, DocumentReference (and linked Binary) for that patient only.
   Every retrieved item is listed with resource reference, date and source.
2. **Given** a resolved case, **When** the payer decision is fetched, **Then** the case records
   reason text, appeal deadline `2026-10-19`, allowed submission channels, and the denial letter
   document.
3. **Given** policy `NST-IMG-2026-04` is effective on the date of service for Northstar Health,
   Commercial PPO and the billed procedure, **When** the policy is selected, **Then** the case
   records the policy id, version, effective dates, source URL and retrieval date.
4. **Given** evidence and policy, **When** the matrix is built, **Then** each requirement is
   `satisfied`, `missing` or `conflicting`, each satisfied requirement cites at least one
   retrieved record with date and verbatim excerpt, and the summary reads "Evidence completeness:
   3/3 policy criteria satisfied".
5. **Given** no policy matches payer + plan + procedure + date of service, **When** selection runs,
   **Then** the case moves to `needs-review` with reason "no applicable policy" and no appeal is
   drafted.

---

### User Story 3 - A cited appeal packet is approved by a human and submitted (Priority: P1)

The specialist opens an appeal packet marked "Ready for review" with the deadline and expected
recovery. Each policy requirement is linked to the chart evidence that satisfies it. An authorized
billing approver approves it, the system submits it through the payer adapter, and the case shows
the payer's confirmation id and starts tracking.

**Why this priority**: Closes the loop from denial to a filed appeal with a confirmation number,
the result judges and users can hold.

**Independent Test**: Approve a ready packet. The mock payer returns `NST-APL-80126`, status
`received`, and the case moves to `submitted` with expected resolution in 14 days. Re-submitting
the same packet version returns the same confirmation without creating a second appeal.

**Acceptance Scenarios**:

1. **Given** a complete matrix, **When** the packet is generated, **Then** it contains both claim
   ids, patient/member identifiers, procedure, diagnosis, provider, service date, amount, stated
   denial reason, policy id and version, requirement-by-requirement citations, the requested action
   (reconsider and reprocess payment), the attachment list and the required approver role.
2. **Given** the packet letter, **When** it is checked, **Then** every factual statement cites a
   record in the case's evidence set, and every amount, date and identifier matches the structured
   case data exactly.
3. **Given** a packet in `ready-for-review`, **When** a user without the approver role tries to
   submit, **Then** submission is refused.
4. **Given** an approver approves packet version 1, **When** submission runs, **Then** the payer
   adapter receives a request with `Idempotency-Key: appeal-case-100028-v1`, and the case records
   appeal id, status, received time and expected resolution days.
5. **Given** the payer adapter is unavailable, **When** submission runs, **Then** the case stays
   `approved` with a visible retry state, and never shows "submitted".

---

### User Story 4 - Missing evidence produces one targeted question (Priority: P2)

With "missing evidence mode" on (the prior-treatment note hidden), the same denial stops at "needs
one item". Instead of a letter, the system drafts a single clinician request naming the exact
policy requirement and what would satisfy it.

**Why this priority**: Shows that the system refuses unsupported appeals and isolates the gap. It is
the second half of the core claim.

**Independent Test**: Toggle missing-evidence mode and replay the case. The matrix shows R2
`missing`, no appeal letter exists, and exactly one `clinical-evidence-request` task is assigned to
the treating clinician.

**Acceptance Scenarios**:

1. **Given** the conservative-treatment note is withheld, **When** the matrix is built, **Then** R2
   is `missing`, R1 and R3 stay `satisfied`, and the summary reads 2/3.
2. **Given** any requirement is `missing`, **When** the pipeline continues, **Then** no appeal
   letter is generated and the case moves to `needs-evidence`.
3. **Given** requirement R2 is missing, **When** the task is created, **Then** exactly one task
   exists, with type `clinical-evidence-request`, assignee role `treating-clinician`, the case id,
   and a question that names the policy requirement text.
4. **Given** the clinician's note is then provided, **When** evidence gathering re-runs, **Then** the
   matrix returns to 3/3 and the packet can be generated.

---

### User Story 5 - The demo is honest and replayable (Priority: P3)

A judge or evaluator can see what is synthetic, where each fixture came from, which parts are mock
contracts rather than real APIs, and whether the letter came from the model or the offline template.
The presenter can reset and replay the whole flow.

**Why this priority**: Declaring what is synthetic builds trust, and a demo that can be reset cannot
get stuck halfway.

**Independent Test**: Open the data-sources view: every fixture lists origin and licence, and the
payer adapter is labelled as a mock contract. Reset and replay: the flow completes again with
identical results.

**Acceptance Scenarios**:

1. **Given** any screen or exported document, **When** it is displayed, **Then** it carries a
   SYNTHETIC DATA marker.
2. **Given** no network and no LLM key, **When** the full flow runs, **Then** it completes, and the
   packet shows that the deterministic template was used.
3. **Given** a completed demo, **When** the presenter resets, **Then** inboxes, cases, tasks and
   submissions return to the initial state.

---

### Edge Cases

- An 835 contains paid claims alongside the denial: only denied claims become cases.
- An 835 contains a denial that is not medical necessity (for example CO-16): the case is created and
  classified, but marked "out of scope for this demo" rather than routed to the evidence pipeline.
- The 837 is missing from the archive: the case moves to `needs-review`, reason "original claim not
  found".
- The claim map has no entry, or two entries, for the claim id: `needs-review`.
- Date of service in the 835 service line differs from the 837 `DTP*472`: `needs-review`.
- Policy exists but its effective dates do not cover the date of service: "no applicable policy".
- The appeal deadline has already passed on the demo date: the case is shown as expired and
  submission is blocked.
- A DocumentReference points to a non-text attachment (PDF scan): listed as evidence, but not
  excerptable. It cannot satisfy a requirement on its own unless a text excerpt exists.
- The LLM output cites a record that is not in the evidence set, or changes a number: the output is
  rejected and the deterministic template is used, with the reason recorded.
- The same Idempotency-Key is sent with a different packet body: the payer adapter rejects it, and the
  case surfaces the conflict.
- The EHR returns an error mid-gathering: the case records a retryable failure and does not build a
  partial matrix that claims completeness.

## Requirements *(mandatory)*

### Functional Requirements

**Ingestion and identity**

- **FR-001**: System MUST poll a mock clearinghouse inbox (`/outbound/835/`) for new 835 files and
  ingest each file exactly once.
- **FR-002**: System MUST provide a "Simulate incoming remit" control that places the synthetic 835 in
  that inbox; the main demo flow MUST NOT require a manual upload.
- **FR-003**: System MUST parse X12 5010 835 files and create one case per denied claim with hospital
  claim id (CLP01), payer claim id (CLP07), payer, member id, patient name, group + reason code (claim-
  or line-level CAS), remark codes, the payer policy id when sent (`REF*0K`), denial category and denied
  amount. Denial is detected from adjudication (paid amount and CAS), not from CLP02 alone.
- **FR-004**: System MUST retrieve the original 837P from the mock claim archive by hospital claim id and
  extract claim id, member id, procedure code, diagnosis codes, date of service, billing and rendering
  NPI, units and billed amount.
- **FR-005**: System MUST resolve claim id → patient id, MRN and encounter id from the claim map.
- **FR-006**: System MUST cross-check claim id, member id, date of service, payer, provider and procedure
  across 835, 837 and claim map, and MUST move the case to `needs-review` without any EHR access on any
  conflict.
- **FR-007**: System MUST NOT match a patient by name.

**Evidence, payer decision and policy**

- **FR-008**: System MUST read clinical evidence only from a FHIR R4 API, using the resource types
  Encounter, Patient, Coverage, Condition, ServiceRequest, Procedure, DiagnosticReport, Observation,
  DocumentReference, Binary and MedicationRequest, scoped to the resolved patient.
- **FR-009**: System MUST record, for each evidence item, resource reference, version, clinically relevant
  date and source system.
- **FR-010**: System MUST fetch the payer decision (reason text, appeal deadline, allowed channels, letter
  document) through a payer adapter interface.
- **FR-011**: System MUST store payer policies as versioned records (policy id, payer, plan type, procedure,
  effective start/end, requirements with accepted evidence types, source URL, retrieval date) and select one
  by payer + plan + procedure + date of service. When the 835 names a policy (`REF*0K`), the selected policy
  id MUST equal it, else the case moves to `needs-review`.
- **FR-012**: System MUST build the evidence matrix deterministically before any prose is generated. Each
  requirement MUST have status `satisfied` / `missing` / `conflicting` and citations with resource
  reference, date and verbatim excerpt with character offsets into the source text.
- **FR-013**: When any requirement is `missing`, system MUST NOT generate an appeal letter and MUST create
  exactly one `clinical-evidence-request` task per missing requirement, naming the requirement.

**Appeal packet and submission**

- **FR-014**: System MUST generate an appeal packet containing the fields in User Story 3, scenario 1.
- **FR-015**: Amounts, dates, identifiers, policy id/version and citations in the packet MUST come from
  structured case data, not from model output.
- **FR-016**: Model-written prose MUST cite only records in the case's evidence set. Output that fails
  this check MUST be rejected in favour of the deterministic template, and the reason recorded.
- **FR-017**: System MUST tokenize identifiers in any text sent to the language model and scrub model
  output before display.
- **FR-018**: System MUST show the packet as "Ready for review" with evidence completeness, appeal deadline
  and expected recovery, and MUST NOT describe it as filed before payer confirmation.
- **FR-019**: System MUST require a user holding the `authorized-billing-user` role to approve a specific
  packet version before submission.
- **FR-020**: System MUST submit through the payer adapter with an Idempotency-Key derived from case id and
  packet version, and record appeal id, status, received time and expected resolution days.
- **FR-021**: System MUST track submitted appeals and show their status on the case.

**Demo integrity**

- **FR-022**: System MUST display a SYNTHETIC DATA marker on every screen and generated document.
- **FR-023**: System MUST provide a data-sources view listing each fixture with origin and licence, and
  label every mock contract as a mock.
- **FR-024**: System MUST provide a missing-evidence mode that withholds the conservative-treatment note.
- **FR-025**: System MUST run the whole flow without network access or an LLM key, and show which letter
  path ran.
- **FR-026**: System MUST provide a reset that restores the initial demo state.
- **FR-027**: System MUST keep an append-only event log of every case state transition with actor and
  timestamp, and show it as a case timeline.
- **FR-028**: System MUST show pipeline progress live as each stage completes.

**Mock systems (documented contracts)**

- **FR-029**: A mock EHR MUST serve valid FHIR R4 resources and searchset Bundles for the synthetic patient.
- **FR-030**: A mock Northstar Health payer MUST expose the decision, document and appeal-submission
  endpoints described in the idea document, with idempotent appeal creation.

### Key Entities

- **Remittance File**: One ingested 835; file name, content hash, interchange control number, received
  time, processing status.
- **Case**: One denied claim under recovery; ids, payer, member, denial code and category, denied amount,
  state, timestamps.
- **Original Claim**: Parsed 837P claim; claim id, member id, procedures, diagnoses, service date, provider
  NPIs, units, billed amount.
- **Claim Map Entry**: Hospital claim id → patient id, MRN, encounter id.
- **Identity Check**: One compared field with the values from each source and pass/fail.
- **Evidence Item**: A retrieved FHIR resource (and text, if any) with reference, version, date, source.
- **Payer Decision**: Reason code and text, appeal deadline, channels, letter document reference.
- **Payer Policy**: Versioned policy snapshot with requirements and accepted evidence types.
- **Evidence Matrix**: Per-requirement status and citations for one case and one policy version.
- **Evidence Task**: Targeted request for a missing requirement; type, assignee role, question, status.
- **Appeal Packet**: Versioned packet content, letter source (model or template), attachments, approval.
- **Submission**: Idempotency key, payer appeal id, status, received time, expected resolution.
- **Case Event**: Append-only state transition with actor and time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From pressing "Simulate incoming remit" to "Ready for review" takes under 60 seconds on a
  typical laptop with the template letter path, and under 90 seconds with the model path.
- **SC-002**: 100% of identity-conflict fixtures (member id, date of service, provider, procedure, payer,
  missing claim map) end in `needs-review` with zero EHR requests, verified by a test that counts requests.
- **SC-003**: 100% of factual statements in a generated appeal cite a record in the case's evidence set, and
  100% of amounts, dates and identifiers match structured case data, verified automatically on every packet.
- **SC-004**: Missing-evidence mode produces exactly one evidence task and zero appeal letters.
- **SC-005**: Delivering the same 835 file twice creates exactly one case; submitting the same packet version
  twice creates exactly one payer appeal.
- **SC-006**: The complete flow succeeds with networking disabled and no LLM key.
- **SC-007**: Every synthetic 835/837 fixture passes structural X12 validation and every FHIR fixture passes
  R4 validation in CI.
- **SC-008**: A presenter can run reset → full flow → missing-evidence replay three times in a row without a
  restart.

## Assumptions

- Scope is one payer (Northstar Health, fake), one plan type (Commercial PPO), one denial type (CARC 50
  medical necessity) and one appeal type (reconsideration). Corrected-claim refiling is out of scope.
- The demo date is fixed at 2026-09-12 for deadline math, so replays are deterministic.
- Authentication is a demo persona switcher (billing specialist, authorized billing approver, treating
  clinician) with no passwords. Production SSO/SMART user auth is out of scope.
- Production integrations (real SFTP, SMART backend-services credentials, per-payer adapters, a policy
  library crawler) are represented by adapter interfaces and documented, not implemented.
- The synthetic claim carries a prior authorization number (`REF*G1`), so a medical-necessity denial
  (CARC 50) rather than a missing-authorization denial (CARC 197) is the plausible payer outcome.
- The idea document's draft 835/837 samples are corrected per research.md §1 (CLP02 = 1, CLP05 = 0,
  CLP06 = 12, CAS at line level, required envelope and loops). The case facts (ids, member, amount,
  dates) are unchanged.
- The treating clinician's task response is simulated in the demo (a control that "provides" the withheld note).
- Real public code sets (CPT/HCPCS, ICD-10-CM, CARC/RARC) may be used for realism with fully fake patients;
  the choice and licensing are settled in research.
