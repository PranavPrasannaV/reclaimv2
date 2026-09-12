"""FHIR client tests against an httpx MockTransport (no network)."""

from __future__ import annotations

import base64

import httpx
import pytest

from reclaim.fhir.client import (
    FhirClient,
    FhirResourceNotFound,
    FhirUnavailableError,
    SmartBackendAuth,
)

BASE = "https://mock-hospital.example/fhir/R4"
TOKEN_URL = "https://mock-hospital.example/oauth2/token"
NOTE = "Synthetic progress note: six weeks of physical therapy without improvement."


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _bundle(resources, next_url=None):
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": r, "search": {"mode": "match"}} for r in resources],
    }
    if next_url:
        bundle["link"] = [{"relation": "next", "url": next_url}]
    return bundle


class EHR:
    """Tiny routing table standing in for the mock EHR."""

    def __init__(self) -> None:
        self.token_requests: list[dict] = []
        self.issued = 0
        self.reject_next_with_401 = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            form = dict(httpx.QueryParams(request.content.decode()))
            self.token_requests.append(form)
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"tok-{self.issued}", "expires_in": 300})
        if self.reject_next_with_401:
            self.reject_next_with_401 = False
            return httpx.Response(401)
        assert request.headers["Accept"] == "application/fhir+json"
        path = request.url.path.removeprefix("/fhir/R4/")
        page = request.url.params.get("page")
        if path == "Encounter/encounter-20260810-42":
            return httpx.Response(200, json={"resourceType": "Encounter", "id": "encounter-20260810-42"})
        if path == "Encounter/wrong-type":
            return httpx.Response(200, json={"resourceType": "Patient", "id": "x"})
        if path == "Condition" and page is None:
            return httpx.Response(200, json=_bundle(
                [{"resourceType": "Condition", "id": "condition-100"}],
                next_url=f"{BASE}/Condition?patient=patient-0042&page=2",
            ))
        if path == "Condition" and page == "2":
            outcome = {"resourceType": "OperationOutcome", "issue": []}
            return httpx.Response(200, json=_bundle([{"resourceType": "Condition", "id": "condition-101"}, outcome]))
        if path == "Observation":
            return httpx.Response(200, json=_bundle([], next_url="https://elsewhere.example/Observation?page=2"))
        if path == "Binary/note-progress-031":
            data = base64.b64encode(NOTE.encode()).decode()
            return httpx.Response(200, json={"resourceType": "Binary", "contentType": "text/plain", "data": data})
        return httpx.Response(404, json={"resourceType": "OperationOutcome"})


def _client(ehr: EHR, clock: FakeClock | None = None, **auth_kwargs) -> FhirClient:
    return FhirClient(
        BASE,
        auth=SmartBackendAuth(token_url=TOKEN_URL, client_id="reclaim-demo", **auth_kwargs),
        transport=httpx.MockTransport(ehr),
        clock=clock or FakeClock(),
    )


async def test_token_reused_then_refreshed_inside_lead_window():
    ehr, clock = EHR(), FakeClock()
    async with _client(ehr, clock) as client:
        await client.get_encounter("encounter-20260810-42")
        await client.get_encounter("encounter-20260810-42")
        assert ehr.issued == 1
        clock.now += 300 - 59  # inside the 60 s lead window
        await client.get_encounter("encounter-20260810-42")
        assert ehr.issued == 2


async def test_client_assertion_sent_when_configured():
    ehr = EHR()
    async with _client(ehr, client_assertion_factory=lambda: "signed.jwt.value") as client:
        await client.get_encounter("encounter-20260810-42")
    form = ehr.token_requests[0]
    assert form["client_assertion"] == "signed.jwt.value"
    assert form["client_assertion_type"].endswith("jwt-bearer")
    assert form["scope"] == "system/*.rs"


async def test_401_refetches_token_once_and_retries():
    ehr = EHR()
    async with _client(ehr) as client:
        await client.get_encounter("encounter-20260810-42")
        ehr.reject_next_with_401 = True
        encounter = await client.get_encounter("encounter-20260810-42")
    assert encounter["id"] == "encounter-20260810-42"
    assert ehr.issued == 2


async def test_search_follows_next_links_and_drops_operation_outcomes():
    async with _client(EHR()) as client:
        conditions = await client.search_for_patient("Condition", "patient-0042")
    assert [c["id"] for c in conditions] == ["condition-100", "condition-101"]


async def test_next_link_outside_base_is_refused():
    async with _client(EHR()) as client:
        with pytest.raises(FhirUnavailableError):
            await client.search_for_patient("Observation", "patient-0042")


async def test_read_rejects_wrong_resource_type():
    async with _client(EHR()) as client:
        with pytest.raises(FhirUnavailableError):
            await client.get_encounter("wrong-type")


async def test_not_found_keeps_reference_off_the_message():
    async with _client(EHR()) as client:
        with pytest.raises(FhirResourceNotFound) as excinfo:
            await client.get_patient("patient-9999")
    assert "patient-9999" not in str(excinfo.value)
    assert excinfo.value.reference == "Patient/patient-9999"


async def test_document_text_via_binary_and_inline():
    via_binary = {"content": [{"attachment": {"contentType": "text/plain", "url": "Binary/note-progress-031"}}]}
    inline = {"content": [
        {"attachment": {"contentType": "application/pdf", "url": "Binary/scan-1"}},
        {"attachment": {"contentType": "text/plain", "data": base64.b64encode(b"inline note").decode()}},
    ]}
    async with _client(EHR()) as client:
        assert await client.document_text(via_binary) == NOTE
        assert await client.document_text(inline) == "inline note"
        with pytest.raises(FhirResourceNotFound):
            await client.document_text({"content": []})


async def test_unknown_evidence_type_rejected():
    async with _client(EHR()) as client:
        with pytest.raises(ValueError):
            await client.search_for_patient("Claim", "patient-0042")


def test_requires_some_auth():
    with pytest.raises(ValueError):
        FhirClient(BASE)
