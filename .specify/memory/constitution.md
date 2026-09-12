# Reclaim Constitution

## Core Principles

### I. Synthetic Data Only, Disclosed Everywhere (NON-NEGOTIABLE)

Every patient, claim, policy, payer and payer response in this project is fake and
authored from scratch. No real records, and no "de-identified" real records either.
Every surface that shows data (dashboard, appeal packet, denial letter, exported file)
carries a visible SYNTHETIC marker. X12 interchanges set `ISA15 = T`. The demo script
states this out loud.

### II. Real Standards Where Standards Exist

Use the real format wherever one exists: X12 5010 835 and 837P, FHIR R4 with real
field names and valid search Bundles, X12 CARC/RARC codes. Invent a contract only where
no universal standard exists (the payer adapter). An invented contract is labelled as a
mock, documented with a schema, and never described as a real payer API.

### III. Evidence Before Prose

The system builds a structured evidence matrix before any text is written. Each policy
requirement gets a status (satisfied / missing / conflicting) and citations to retrieved
records (resource reference, version, date, excerpt with character offsets). The language
model writes prose only over a sealed evidence set and may cite only records in it.
Money, dates, deadlines, identifiers and citations are inserted by code, not generated.
A requirement without evidence blocks the appeal and produces one targeted task. The
system never drafts an unsupported claim.

### IV. Identity Hard Stop

Never match by patient name. Before any chart access, cross-check claim control number,
member id, date of service, payer, billing/rendering provider and procedure between the
835, the 837 and the claim map. Any conflict moves the case to `needs-review` and the
EHR is not queried for that case.

### V. Nothing Leaves Without a Human

No appeal is submitted until a named approver with the approver role acts on the exact
packet version shown. Submission is idempotent (one Idempotency-Key per packet version).
Every state transition is written to an append-only event log with actor and timestamp.
The UI never says "filed" before the payer adapter confirms receipt.

### VI. Deterministic Core, Demo Cannot Fail

Parsing, matching, deadline math, policy selection and the evidence matrix are plain,
unit-tested code the model never touches. The full flow runs offline with no API key: the
letter falls back to a deterministic template, and a visible flag says which path ran.
One command starts everything.

### VII. Simplicity

One process, one port, no external infrastructure for the demo. Each outside system
(clearinghouse, EHR, payer, policy library) sits behind an adapter interface, so a
production integration replaces one class, not the pipeline. No speculative features:
corrected-claim refiling and non-medical-necessity denials are out of scope until the
main flow ships.

## Data Handling

- PHI hygiene applies even though data is synthetic: logs and error messages never carry
  clinical text or identifiers; text sent to the LLM is tokenized first and model output is
  scrubbed before display.
- Every fixture records its origin and licence in a data-sources table.
- Payer policies are stored as versioned snapshots (policy id, version, effective dates,
  source URL, retrieval date) and selected by payer + plan + procedure + date of service.

## Development Workflow

- Tests are written before implementation for the deterministic core (parsers, identity
  check, deadline math, matrix, idempotency).
- Fixtures are validated in CI: X12 structural checks (envelope, SE counts, required loops)
  and FHIR R4 resource validation.
- A task is marked done only with evidence (a passing test, a command output, a
  screenshot). Work blocked on something outside the repo is labelled with the exact blocker.
- UI work follows the `design-stack` workflow: a committed design system before any UI code.

## Governance

This constitution overrides other practices in the repo. Amendments update this file, bump
the version (MAJOR: principle removed or redefined; MINOR: principle or section added; PATCH:
wording), and note the change in the plan that required it. Plans must pass the
Constitution Check before research and again after design; any violation must be justified
in the plan's Complexity Tracking table.

**Version**: 1.0.0 | **Ratified**: 2026-09-12 | **Last Amended**: 2026-09-12
