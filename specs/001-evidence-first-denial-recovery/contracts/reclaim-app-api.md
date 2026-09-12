# Contract: Reclaim App API (consumed by the dashboard)

Served at `http://127.0.0.1:8000/api`. JSON unless noted. All responses include
`"synthetic": true` at the top level. The acting persona is sent as `X-Demo-Persona`
(no passwords; see spec Assumptions). Errors use RFC 9457 `application/problem+json`.

## Personas

| Persona id | Roles |
|---|---|
| `billing-specialist-01` | `billing-specialist` |
| `billing-approver-01` | `billing-specialist`, `authorized-billing-user` |
| `clinician-lee` | `treating-clinician` |

## Demo control

| Method | Path | Role | Effect |
|---|---|---|---|
| POST | `/demo/simulate-remit` | any | Places the synthetic 835 in the clearinghouse inbox. `202 {"file":"era-2026-09-12.835"}` |
| POST | `/demo/reset` | any | Recreates DB, restores inbox/archive seeds, clears mock payer state. `204` |
| GET/PUT | `/demo/settings` | any | `{demoDate, missingEvidenceMode, letterMode, activePersona, llmAvailable}` |
| PUT | `/demo/faults` | any | Proxies to the mock payer fault switch (retry-path demo) |

## Cases

| Method | Path | Returns |
|---|---|---|
| GET | `/cases` | worklist: `[{id, state, hospitalClaimId, payer, deniedAmountCents, denialCode, appealDeadline, daysToDeadline, evidenceCompleteness:{satisfied,total}|null}]` |
| GET | `/cases/{id}` | case header + `stateReason` + `letterSource` |
| GET | `/cases/{id}/identity` | `{mapping:{remit:{…}, claim:{…}, map:{…}}, checks:[{field, value835, value837, valueMap, result}]}` |
| GET | `/cases/{id}/evidence` | `[{reference, resourceType, clinicalDate, source, title, excerptable}]` |
| GET | `/cases/{id}/evidence/{itemId}/text` | `text/plain` note body (synthetic) |
| GET | `/cases/{id}/decision` | PayerDecision + letter link |
| GET | `/cases/{id}/matrix` | `{policy:{id, version, effectiveStart, effectiveEnd, sourceUrl, retrievedAt}, satisfied, total, requirements:[{id, text, status, ruleTrace, citations:[{id, reference, clinicalDate, exact, prefix, suffix, start, end}]}]}` |
| GET | `/cases/{id}/tasks` | EvidenceTask list |
| GET | `/cases/{id}/packet` | latest packet: `{version, status, letterSource, fallbackReason, fields, letterMarkdown, attachments, requiredRole, contentSha256}` |
| GET | `/cases/{id}/packet/{version}.pdf` | `application/pdf`, SYNTHETIC watermark |
| POST | `/cases/{id}/packet/{version}/approve` | role `authorized-billing-user`; body `{contentSha256}` must match; `409` if stale, `403` if role missing |
| POST | `/cases/{id}/packet/{version}/reject` | same role; body `{contentSha256, reason}` |
| POST | `/cases/{id}/retry` | re-runs the failed stage for `gather_failed` / `submit_failed` |
| GET | `/cases/{id}/submission` | Submission + latest payer status |
| GET | `/cases/{id}/timeline` | CaseEvent list |

## Tasks

| Method | Path | Role | Effect |
|---|---|---|---|
| GET | `/tasks?assigneeRole=treating-clinician` | any | open tasks |
| POST | `/tasks/{id}/resolve` | `treating-clinician` | Demo: restores the withheld record in the mock EHR and records `resolutionReference`; case returns to `gathering` |

## Transparency

| Method | Path | Returns |
|---|---|---|
| GET | `/data-sources` | `[{asset, kind, origin, licence, synthetic, mock}]` generated from `fixtures/DATA_SOURCES.md` |
| GET | `/health` | `{status, db, poller, llmAvailable, sftp}` |

## Live progress: `GET /api/events` (Server-Sent Events)

`text/event-stream`, keep-alive pings every 15 s. Event types:

| `event:` | `data:` |
|---|---|
| `case.created` | `{caseId, hospitalClaimId, deniedAmountCents}` |
| `case.state` | `{caseId, from, to, reason, actor, at}` |
| `stage.progress` | `{caseId, stage, step, detail}`; e.g. `{"stage":"gather","step":"GET Condition?patient=patient-0042","detail":"1 match"}` |
| `matrix.requirement` | `{caseId, requirementId, status}`; emitted one by one so the UI can turn rows green |
| `packet.ready` | `{caseId, version, letterSource}` |
| `submission.received` | `{caseId, appealId, receivedAt}` |

Events carry identifiers already shown on screen and never clinical text.
