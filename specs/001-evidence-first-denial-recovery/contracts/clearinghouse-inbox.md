# Contract: Mock Clearinghouse (835 inbox + 837 claim archive)

**MOCK.** In production a hospital authorizes its existing clearinghouse to deliver 835 remittance
files by SFTP or API. Here the same layout lives on local disk by default, with an optional real
SFTP server for the "it really is SFTP" moment.

## Layout

```text
{DATA_DIR}/clearinghouse/                      # DATA_DIR = %LOCALAPPDATA%\reclaim
├── outbound/835/                              # sftp://mock-clearinghouse/outbound/835/
│   ├── era-2026-09-12.835                     # dropped by "Simulate incoming remit"
│   └── processed/{sha256[:12]}_{name}         # moved after ingestion (never overwritten)
└── claim-archive/837/                         # sftp://mock-clearinghouse/claim-archive/837/
    └── HSP-CLM-100028.837
```

Seed copies live in `backend/fixtures/clearinghouse/`; `demo reset` restores `DATA_DIR` from them.

## Interfaces (Python, `reclaim.adapters`)

```python
class InboxSource(Protocol):
    async def list_new(self) -> list[InboxFile]: ...          # name, size, mtime; excludes processed/
    async def read(self, name: str) -> bytes: ...
    async def mark_processed(self, name: str, sha256: str) -> None: ...

class ClaimArchive(Protocol):
    async def fetch_837(self, hospital_claim_id: str) -> bytes: ...   # raises ClaimNotArchived
```

Implementations: `LocalDirInbox` / `LocalDirClaimArchive` (default) and `AsyncSSHInbox` /
`AsyncSSHClaimArchive` (enabled by `RECLAIM_SFTP=1`; starts an asyncssh server on
`127.0.0.1:2222`, user `demo`, host key cached in `DATA_DIR/sftp_host_ed25519`).

## File rules

| Rule | Behaviour |
|---|---|
| Name | `*.835` in `outbound/835`; `{hospital_claim_id}.837` in `claim-archive/837`. `hospital_claim_id` must match `^[A-Z0-9-]{1,38}$` (CLM01 max length 38) before it is used in a path. |
| Poll interval | 2 s (demo), configurable; one poller task per process |
| Exactly-once | `sha256(bytes)` UNIQUE → `duplicate`; same `(ISA06, ISA13)` with different hash → `suspected_duplicate` (held for review, not silently dropped) |
| Structure | `x12_validate` must pass: ISA fixed width, `ISA15`, matching `GS`/`GE` and `ST`/`SE` control numbers, `SE01` count, `IEA01`/`GE01` counts, 835 `ST01=835` + `BPR` + `TRN` present |
| Usage indicator | `ISA15 = T` expected for all demo files; `P` is rejected with `interchange.production_data_refused` |
| Move | after the DB transaction commits; a crash before the move re-reads the file and hits the hash UNIQUE guard |

## Simulate control

`POST /api/demo/simulate-remit` copies `fixtures/clearinghouse/outbound/835/era-2026-09-12.835` into
the inbox (atomic write: temp file + `os.replace`). It never calls the ingestion code directly: the
poller must find the file, like a real feed.
