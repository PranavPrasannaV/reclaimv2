# Contract: Adapter Interfaces (production seams)

Each outside system is one Protocol. The demo wires mocks; production replaces one class per system.
All adapters raise typed, PHI-free errors and are async.

| Protocol | Demo implementation | Production replacement (not built) |
|---|---|---|
| `InboxSource` | `LocalDirInbox`, `AsyncSSHInbox` | clearinghouse SFTP or ERA API (Availity, Change/Optum, Waystar) |
| `ClaimArchive` | `LocalDirClaimArchive` | clearinghouse claim archive, or RCM/billing API `GET /rcm/v1/claims/{id}` |
| `ClaimMap` | `JsonClaimMap` (`fixtures/claim-map.json`) | hospital billing system / data warehouse lookup |
| `ClinicalSource` | `FhirClinicalSource` over `FhirClient` + in-process mock EHR | same class, pointed at Epic/Oracle Health FHIR R4 with SMART backend-services credentials |
| `PayerAdapter` | `NorthstarHttpAdapter` → mock Northstar API | one adapter per payer: API, clearinghouse document retrieval, or an authorized portal connection |
| `PolicyStore` | `VersionedJsonPolicyStore` (`fixtures/policies/`) | curated snapshots of CMS MCD / commercial policy libraries, same schema |
| `LetterWriter` | `CheckedLetterWriter(ClaudeLetterWriter, TemplateLetterWriter)` | same |

```python
class ClaimMap(Protocol):
    async def lookup(self, hospital_claim_id: str) -> list[ClaimMapEntry]: ...   # caller requires len == 1

class ClinicalSource(Protocol):
    async def encounter(self, encounter_id: str) -> dict: ...
    async def patient(self, patient_id: str) -> dict: ...
    async def gather(self, patient_id: str, types: Sequence[str], date_of_service: date) -> list[EvidenceItem]: ...

class PayerAdapter(Protocol):
    payer_id: str
    async def decision(self, payer_claim_id: str) -> PayerDecision: ...
    async def document(self, document_id: str) -> Document: ...
    async def submit_appeal(self, request: AppealRequest, idempotency_key: str) -> AppealReceipt: ...
    async def appeal_status(self, appeal_id: str) -> AppealStatus: ...

class PolicyStore(Protocol):
    async def select(self, payer_id: str, plan_type: str, procedure_code: str, date_of_service: date) -> PayerPolicy: ...
    # raises NoEffectivePolicy / AmbiguousPolicy
```

`ClinicalSource.gather` refuses to run unless the caller passes a case in state `resolved`
(Identity Hard Stop enforced at the seam as well as in the orchestrator; SC-002 counts EHR requests
through an httpx event hook).
