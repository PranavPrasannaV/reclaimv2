"""X12 5010 segment writer and synthetic 837P builder.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/edi/generator.py),
generalised from a frequency-code-7 replacement generator into reusable segment
builders plus an original-claim 837P builder, so demo fixtures are produced by code
and round-trip through the same tokenizer the pipeline uses.

Every interchange defaults to ISA15 = "T" (test data): all claims built here are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from reclaim.edi.x12 import (
    DEFAULT_COMPONENT_SEP,
    DEFAULT_ELEMENT_SEP,
    DEFAULT_REPETITION_SEP,
    DEFAULT_SEGMENT_TERM,
)

IMPL_837P = "005010X222A1"
IMPL_835 = "005010X221A1"
FREQUENCY_ORIGINAL = "1"
FREQUENCY_REPLACEMENT = "7"


def _text(value: object) -> str:
    return "" if value is None else str(value)


def seg(segment_id: str, *elements: object) -> str:
    """Join a segment, trimming trailing empty elements as X12 requires."""
    values = [_text(e) for e in elements]
    while values and values[-1] == "":
        values.pop()
    return DEFAULT_ELEMENT_SEP.join([segment_id, *values])


def composite(*parts: object) -> str:
    values = [_text(p) for p in parts]
    while values and values[-1] == "":
        values.pop()
    return DEFAULT_COMPONENT_SEP.join(values)


def money(amount: Decimal) -> str:
    """X12 R-type amount: at most two decimals, no trailing zeros ("4800", "12.5")."""
    text = format(amount.quantize(Decimal("0.01")), "f")
    return text.rstrip("0").rstrip(".") or "0"


def quantity(value: Decimal) -> str:
    return format(value.normalize(), "f")


def x12_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def transaction_set(
    code: str, implementation_ref: str | None, body: list[str], control_number: str = "0001"
) -> list[str]:
    """Wrap body segments in ST/SE; SE01 counts ST through SE inclusive.

    ST03 is required in the 837 and Not Used in the 835, so pass None for an 835.
    """
    return [
        seg("ST", code, control_number, implementation_ref),
        *body,
        seg("SE", len(body) + 2, control_number),
    ]


@dataclass(frozen=True)
class Envelope:
    sender_id: str
    receiver_id: str
    interchange_control_number: int
    created_at: datetime
    functional_id_code: str  # GS01: HC = 837 claim, HP = 835 remittance
    implementation_ref: str
    usage_indicator: str = "T"  # ISA15: T = test data


def interchange(envelope: Envelope, transaction: list[str], group_control_number: int = 1) -> str:
    """Wrap one transaction set in ISA/GS ... GE/IEA. ISA is fixed-width (106 chars with terminator)."""
    when = envelope.created_at
    icn = f"{envelope.interchange_control_number:09d}"
    isa = DEFAULT_ELEMENT_SEP.join([
        "ISA", "00", " " * 10, "00", " " * 10,
        "ZZ", f"{envelope.sender_id:<15}"[:15],
        "ZZ", f"{envelope.receiver_id:<15}"[:15],
        when.strftime("%y%m%d"), when.strftime("%H%M"),
        DEFAULT_REPETITION_SEP, "00501", icn, "0", envelope.usage_indicator, DEFAULT_COMPONENT_SEP,
    ])
    segments = [
        isa,
        seg("GS", envelope.functional_id_code, envelope.sender_id, envelope.receiver_id,
            when.strftime("%Y%m%d"), when.strftime("%H%M"), group_control_number, "X",
            envelope.implementation_ref),
        *transaction,
        seg("GE", 1, group_control_number),
        seg("IEA", 1, icn),
    ]
    return DEFAULT_SEGMENT_TERM.join(segments) + DEFAULT_SEGMENT_TERM


@dataclass(frozen=True)
class Address:
    line1: str
    city: str
    state: str
    postal_code: str


@dataclass(frozen=True)
class BillingProvider:
    name: str
    npi: str
    tax_id: str
    address: Address


@dataclass(frozen=True)
class Practitioner:
    last_name: str
    first_name: str
    npi: str


@dataclass(frozen=True)
class Subscriber:
    last_name: str
    first_name: str
    member_id: str
    birth_date: date
    gender: str  # DMG03: F / M / U
    address: Address


@dataclass(frozen=True)
class ServiceLineSpec:
    procedure_code: str
    charge: Decimal
    service_date: date
    units: Decimal = Decimal("1")
    modifiers: tuple[str, ...] = ()
    diagnosis_pointers: tuple[int, ...] = (1,)
    line_control_number: str = ""  # REF*6R; the 835 echoes it to match lines


@dataclass(frozen=True)
class ClaimSpec:
    claim_id: str  # CLM01; the 835 echoes it in CLP01 (keep to 17 chars; payers may truncate)
    payer_name: str
    payer_id: str
    subscriber: Subscriber
    billing_provider: BillingProvider
    diagnosis_codes: tuple[str, ...]  # ICD-10-CM; principal first
    service_lines: tuple[ServiceLineSpec, ...]
    rendering_provider: Practitioner | None = None  # 2310B; send only when it differs from billing
    referring_provider: Practitioner | None = None  # 2310A NM1*DN
    place_of_service: str = "11"
    frequency_code: str = FREQUENCY_ORIGINAL
    claim_filing_indicator: str = "12"  # SBR09: 12 = PPO
    group_number: str = ""  # SBR03
    prior_authorization_number: str = ""  # REF*G1
    medical_record_number: str = ""  # REF*EA
    original_payer_claim_number: str = ""  # REF*F8, required for replacements
    submitter_name: str = "RECLAIM DEMO"
    submitter_id: str = "RECLAIMDEMO"
    submitter_phone: str = "5555550100"

    @property
    def total_charge(self) -> Decimal:
        return sum((line.charge for line in self.service_lines), Decimal("0"))


def build_837p_body(claim: ClaimSpec, created_at: datetime) -> list[str]:
    if claim.frequency_code == FREQUENCY_REPLACEMENT and not claim.original_payer_claim_number:
        raise ValueError("a replacement claim needs original_payer_claim_number for REF*F8")
    sub = claim.subscriber
    bp = claim.billing_provider
    body = [
        seg("BHT", "0019", "00", claim.claim_id, x12_date(created_at), created_at.strftime("%H%M"), "CH"),
        seg("NM1", "41", "2", claim.submitter_name, "", "", "", "", "46", claim.submitter_id),
        seg("PER", "IC", claim.submitter_name, "TE", claim.submitter_phone),
        seg("NM1", "40", "2", claim.payer_name, "", "", "", "", "46", claim.payer_id),
        seg("HL", "1", "", "20", "1"),
        seg("NM1", "85", "2", bp.name, "", "", "", "", "XX", bp.npi),
        seg("N3", bp.address.line1),
        seg("N4", bp.address.city, bp.address.state, bp.address.postal_code),
        seg("REF", "EI", bp.tax_id),
        seg("HL", "2", "1", "22", "0"),
        seg("SBR", "P", "18", claim.group_number, "", "", "", "", "", claim.claim_filing_indicator),
        seg("NM1", "IL", "1", sub.last_name, sub.first_name, "", "", "", "MI", sub.member_id),
        seg("N3", sub.address.line1),
        seg("N4", sub.address.city, sub.address.state, sub.address.postal_code),
        seg("DMG", "D8", x12_date(sub.birth_date), sub.gender),
        seg("NM1", "PR", "2", claim.payer_name, "", "", "", "", "PI", claim.payer_id),
        seg("CLM", claim.claim_id, money(claim.total_charge), "", "",
            composite(claim.place_of_service, "B", claim.frequency_code), "Y", "A", "Y", "Y"),
    ]
    # Loop 2300 REF order per the TR3: G1, F8, ..., EA.
    if claim.prior_authorization_number:
        body.append(seg("REF", "G1", claim.prior_authorization_number))
    if claim.original_payer_claim_number:
        body.append(seg("REF", "F8", claim.original_payer_claim_number))
    if claim.medical_record_number:
        body.append(seg("REF", "EA", claim.medical_record_number))
    if claim.diagnosis_codes:
        body.append(seg("HI", *(
            composite("ABK" if i == 0 else "ABF", code.replace(".", ""))
            for i, code in enumerate(claim.diagnosis_codes[:12])
        )))
    for qualifier, practitioner in (("DN", claim.referring_provider), ("82", claim.rendering_provider)):
        if practitioner is not None:
            body.append(seg("NM1", qualifier, "1", practitioner.last_name, practitioner.first_name,
                            "", "", "", "XX", practitioner.npi))
    for number, line in enumerate(claim.service_lines, start=1):
        body.extend([
            seg("LX", number),
            seg("SV1", composite("HC", line.procedure_code, *line.modifiers), money(line.charge),
                "UN", quantity(line.units), "", "", composite(*line.diagnosis_pointers)),
            seg("DTP", "472", "D8", x12_date(line.service_date)),
        ])
        if line.line_control_number:
            body.append(seg("REF", "6R", line.line_control_number))
    return body


def build_837p(
    claim: ClaimSpec,
    *,
    receiver_id: str,
    interchange_control_number: int,
    created_at: datetime,
) -> str:
    """Build a complete 837P interchange for one synthetic claim."""
    envelope = Envelope(
        sender_id=claim.submitter_id,
        receiver_id=receiver_id,
        interchange_control_number=interchange_control_number,
        created_at=created_at,
        functional_id_code="HC",
        implementation_ref=IMPL_837P,
    )
    return interchange(envelope, transaction_set("837", IMPL_837P, build_837p_body(claim, created_at)))
