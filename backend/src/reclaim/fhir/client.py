"""FHIR R4 client for the evidence pull, shaped like a SMART backend-services app.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/services/ehr_client.py).
Kept: proactive token refresh `refresh_lead_seconds` before expiry and a single reactive
re-fetch + retry on 401. Changed: the Redis token cache is in-process, the transport is
injectable (in-process mock EHR, tests), and reads cover the resource types the evidence
matrix needs. Error messages never contain resource ids or clinical content.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

FHIR_JSON = "application/fhir+json"
JWT_BEARER_ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

PATIENT_SCOPED_TYPES = frozenset({
    "Coverage",
    "Condition",
    "ServiceRequest",
    "Procedure",
    "DiagnosticReport",
    "Observation",
    "DocumentReference",
    "MedicationRequest",
})


class FhirUnavailableError(RuntimeError):
    """The EHR could not be reached, authenticated, or returned an unusable response."""


class FhirResourceNotFound(LookupError):
    """The requested resource does not exist. `reference` is kept off the message on purpose."""

    def __init__(self, reference: str):
        self.reference = reference
        super().__init__("FHIR resource not found")


@dataclass(frozen=True)
class SmartBackendAuth:
    token_url: str
    client_id: str
    scope: str = "system/*.rs"
    # Returns a signed JWT for private_key_jwt client authentication. None only for mock EHRs.
    client_assertion_factory: Callable[[], str] | None = None


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float


class FhirClient:
    def __init__(
        self,
        base_url: str,
        *,
        auth: SmartBackendAuth | None = None,
        static_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        refresh_lead_seconds: int = 60,
        timeout: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if auth is None and static_token is None:
            raise ValueError("FhirClient needs SMART auth or a static token")
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._static_token = static_token
        self._lead = refresh_lead_seconds
        self._clock = clock
        self._token: _CachedToken | None = None
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def __aenter__(self) -> FhirClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- OAuth2 token management ------------------------------------------
    async def _fetch_token(self) -> str:
        if self._auth is None:
            return self._static_token  # type: ignore[return-value]
        data = {
            "grant_type": "client_credentials",
            "scope": self._auth.scope,
            "client_id": self._auth.client_id,
        }
        if self._auth.client_assertion_factory is not None:
            data["client_assertion_type"] = JWT_BEARER_ASSERTION
            data["client_assertion"] = self._auth.client_assertion_factory()
        try:
            resp = await self._http.post(self._auth.token_url, data=data)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise FhirUnavailableError(f"token fetch failed: {type(exc).__name__}") from exc
        expires_in = int(payload.get("expires_in", 300))
        self._token = _CachedToken(payload["access_token"], self._clock() + expires_in)
        return self._token.access_token

    async def _bearer(self) -> str:
        if self._token is not None and self._clock() < self._token.expires_at - self._lead:
            return self._token.access_token
        return await self._fetch_token()

    # --- HTTP ---------------------------------------------------------------
    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
        else:
            url = f"{self._base_url}/{path_or_url.lstrip('/')}"
        if not url.startswith(f"{self._base_url}/"):
            raise FhirUnavailableError("refusing to follow a URL outside the configured FHIR base")
        return url

    async def _get(self, path_or_url: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        url = self._url(path_or_url)
        headers = {"Authorization": f"Bearer {await self._bearer()}", "Accept": FHIR_JSON}
        try:
            resp = await self._http.get(url, headers=headers, params=params)
            if resp.status_code == 401:
                self._token = None
                headers["Authorization"] = f"Bearer {await self._fetch_token()}"
                resp = await self._http.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise FhirUnavailableError(f"FHIR request failed: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise FhirResourceNotFound(path_or_url)
        if resp.is_error:
            raise FhirUnavailableError(f"FHIR request failed: HTTP {resp.status_code}")
        return resp.json()

    # --- FHIR reads --------------------------------------------------------
    async def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        resource = await self._get(f"{resource_type}/{resource_id}")
        if resource.get("resourceType") != resource_type:
            raise FhirUnavailableError(f"expected {resource_type}, got {resource.get('resourceType')}")
        return resource

    async def search(self, resource_type: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """Run a search and follow `next` links; returns matched resources only."""
        resources: list[dict[str, Any]] = []
        bundle = await self._get(resource_type, params=params)
        while True:
            if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "searchset":
                raise FhirUnavailableError("expected a searchset Bundle")
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                # OperationOutcome entries (search.mode = outcome) are diagnostics, not matches.
                if resource.get("resourceType") == resource_type:
                    resources.append(resource)
            next_url = next(
                (link.get("url") for link in bundle.get("link", []) if link.get("relation") == "next"),
                None,
            )
            if not next_url:
                return resources
            bundle = await self._get(next_url)

    async def get_encounter(self, encounter_id: str) -> dict[str, Any]:
        return await self.read("Encounter", encounter_id)

    async def get_patient(self, patient_id: str) -> dict[str, Any]:
        return await self.read("Patient", patient_id)

    async def search_for_patient(
        self, resource_type: str, patient_id: str, extra: Mapping[str, str] | None = None
    ) -> list[dict[str, Any]]:
        if resource_type not in PATIENT_SCOPED_TYPES:
            raise ValueError(f"{resource_type} is not a patient-scoped evidence type")
        return await self.search(resource_type, {"patient": patient_id, **(extra or {})})

    async def document_text(self, document_reference: Mapping[str, Any]) -> str:
        """Return the first text attachment of a DocumentReference, inline or via Binary."""
        for content in document_reference.get("content", []):
            attachment = content.get("attachment", {})
            content_type = attachment.get("contentType", "")
            if content_type and not content_type.startswith("text/"):
                continue
            if attachment.get("data"):
                return _decode(attachment["data"])
            if attachment.get("url"):
                binary = await self._get(attachment["url"])
                if binary.get("resourceType") != "Binary":
                    raise FhirUnavailableError("attachment url did not resolve to a Binary")
                if not binary.get("contentType", "text/").startswith("text/"):
                    continue
                return _decode(binary.get("data", ""))
        raise FhirResourceNotFound("DocumentReference.content")


def _decode(data: str) -> str:
    return base64.b64decode(data).decode("utf-8")
