"""X12 5010 835 (ERA) parser.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/edi/parser.py).

  * `parse_era()` walks the segment stream, groups CLP claim-payment loops with
    their SVC/CAS/NM1/DTM/AMT/REF/LQ children, and produces `ClaimPayment`s.
  * `classify_denial()` maps a claim's CARC codes to a denial category via the
    version-controlled mappings in carc_rarc.py.

PHI note: this module never logs raw segment content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from reclaim.edi.carc_rarc import DenialCategory, get_appeal_strategy, get_category
from reclaim.edi.x12 import Delimiters, Segment, to_decimal, tokenize

# 835 CLP02 claim status code that denotes a denied claim.
CLP_STATUS_DENIED = "4"


@dataclass
class CASAdjustment:
    """One CAS triplet: group code + reason (CARC) + amount + quantity."""

    group_code: str
    reason_code: str
    amount: Decimal
    quantity: Decimal


def parse_cas(segment: Segment) -> list[CASAdjustment]:
    """Parse a CAS segment into its repeating (reason, amount, qty) triplets.

    CAS01 = group code; then up to 6 triplets in CAS02..CAS19.
    """
    group = segment.get(1)
    adjustments: list[CASAdjustment] = []
    pos = 2
    while True:
        reason = segment.get(pos)
        if not reason:
            break
        adjustments.append(
            CASAdjustment(
                group_code=group,
                reason_code=reason,
                amount=to_decimal(segment.get(pos + 1)),
                quantity=to_decimal(segment.get(pos + 2)),
            )
        )
        pos += 3
        if pos > 19:
            break
    return adjustments


@dataclass
class ServiceLine:
    """A service-level payment (SVC loop) with its adjustments and remark codes."""

    line_number: int
    procedure_code: str
    modifiers: list[str] = field(default_factory=list)
    charge_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    units: Decimal = Decimal("0")
    adjustments: list[CASAdjustment] = field(default_factory=list)
    rarc_codes: list[str] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)  # REF qualifier -> value
    service_date: str | None = None

    @property
    def carc_codes(self) -> list[str]:
        return [a.reason_code for a in self.adjustments]

    @property
    def denial_amount(self) -> Decimal:
        return sum((a.amount for a in self.adjustments), Decimal("0"))

    @property
    def is_denied(self) -> bool:
        return self.paid_amount == 0 and bool(self.adjustments)


def _dedupe(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    return [c for c in codes if not (c in seen or seen.add(c))]


@dataclass
class ClaimPayment:
    """A CLP claim-payment loop (2100) and everything nested under it."""

    claim_control_number: str        # CLP01 — echoes the provider's CLM01
    status_code: str                 # CLP02
    total_charge: Decimal            # CLP03
    paid_amount: Decimal             # CLP04
    patient_responsibility: Decimal  # CLP05
    claim_filing_indicator: str      # CLP06
    payer_claim_control_number: str  # CLP07
    facility_type_code: str = ""     # CLP08
    frequency_code: str = ""         # CLP09
    patient_last_name: str = ""      # NM1*QC NM103
    patient_first_name: str = ""     # NM1*QC NM104
    patient_member_id: str = ""      # NM1*QC NM109 when NM108 = MI
    subscriber_member_id: str = ""   # NM1*IL NM109 when NM108 = MI
    statement_period_start: str = "" # DTM*232
    statement_period_end: str = ""   # DTM*233
    claim_adjustments: list[CASAdjustment] = field(default_factory=list)
    service_lines: list[ServiceLine] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)  # REF qualifier -> value
    rarc_codes: list[str] = field(default_factory=list)

    @property
    def member_id(self) -> str:
        """The subscriber's id when the 835 reports one (patient is a dependant), else the patient's."""
        return self.subscriber_member_id or self.patient_member_id

    @property
    def claim_level_carc_codes(self) -> list[str]:
        return [a.reason_code for a in self.claim_adjustments]

    @property
    def all_carc_codes(self) -> list[str]:
        codes = list(self.claim_level_carc_codes)
        for line in self.service_lines:
            codes.extend(line.carc_codes)
        return _dedupe(codes)

    @property
    def all_rarc_codes(self) -> list[str]:
        codes = list(self.rarc_codes)
        for line in self.service_lines:
            codes.extend(line.rarc_codes)
        return _dedupe(codes)

    @property
    def group_codes(self) -> list[str]:
        codes = [a.group_code for a in self.claim_adjustments if a.group_code]
        for line in self.service_lines:
            codes.extend(a.group_code for a in line.adjustments if a.group_code)
        return _dedupe(codes)

    @property
    def denied_service_lines(self) -> list[ServiceLine]:
        return [line for line in self.service_lines if line.is_denied]

    @property
    def is_denied(self) -> bool:
        """Denied if CLP02 says so, or it paid nothing despite adjustments,
        or it has any denied service line (partial denial)."""
        if self.status_code == CLP_STATUS_DENIED:
            return True
        if self.paid_amount == 0 and self.claim_adjustments:
            return True
        return any(line.is_denied for line in self.service_lines)


@dataclass
class ParsedERA:
    """Top-level result of parsing one 835 file."""

    sender_id: str
    receiver_id: str
    interchange_control_number: str
    total_paid: Decimal
    payer_name: str
    claims: list[ClaimPayment] = field(default_factory=list)
    payer_identifier: str = ""  # N1*PR N104

    @property
    def denied_claims(self) -> list[ClaimPayment]:
        return [c for c in self.claims if c.is_denied]


def _parse_svc(segment: Segment) -> ServiceLine:
    """SVC01 = composite procedure (qualifier:code:mod1:mod2...); SVC02 charge;
    SVC03 paid; SVC05 units."""
    composite = segment.components(1)
    procedure_code = composite[1] if len(composite) > 1 else (composite[0] if composite else "")
    modifiers = [m for m in composite[2:] if m]
    return ServiceLine(
        line_number=0,  # assigned by caller in loop order
        procedure_code=procedure_code,
        modifiers=modifiers,
        charge_amount=to_decimal(segment.get(2)),
        paid_amount=to_decimal(segment.get(3)),
        units=to_decimal(segment.get(5)) or Decimal("1"),
    )


def parse_era(raw: str, delimiters: Delimiters | None = None) -> ParsedERA:
    """Parse a raw 835 ERA payload into a structured `ParsedERA`."""
    segments = tokenize(raw, delimiters)

    sender_id = ""
    receiver_id = ""
    icn = ""
    total_paid = Decimal("0")
    payer_name = ""
    payer_identifier = ""
    claims: list[ClaimPayment] = []

    current: ClaimPayment | None = None
    current_line: ServiceLine | None = None
    line_counter = 0

    for seg in segments:
        sid = seg.id

        if sid == "ISA":
            sender_id = seg.get(6).strip()
            receiver_id = seg.get(8).strip()
            icn = seg.get(13).strip()

        elif sid == "BPR":
            total_paid = to_decimal(seg.get(2))

        elif sid == "N1":
            # Only capture the payer (PR), never patient PHI.
            if seg.get(1) == "PR":
                payer_name = seg.get(2)
                payer_identifier = seg.get(4)

        elif sid == "CLP":
            if current is not None:
                if current_line is not None:
                    current.service_lines.append(current_line)
                    current_line = None
                claims.append(current)
            line_counter = 0
            current = ClaimPayment(
                claim_control_number=seg.get(1),
                status_code=seg.get(2),
                total_charge=to_decimal(seg.get(3)),
                paid_amount=to_decimal(seg.get(4)),
                patient_responsibility=to_decimal(seg.get(5)),
                claim_filing_indicator=seg.get(6),
                payer_claim_control_number=seg.get(7),
                facility_type_code=seg.get(8),
                frequency_code=seg.get(9),
            )

        elif sid == "SVC" and current is not None:
            if current_line is not None:
                current.service_lines.append(current_line)
            line_counter += 1
            current_line = _parse_svc(seg)
            current_line.line_number = line_counter

        elif sid == "CAS" and current is not None:
            adjustments = parse_cas(seg)
            if current_line is not None:
                current_line.adjustments.extend(adjustments)
            else:
                current.claim_adjustments.extend(adjustments)

        elif sid == "NM1" and current is not None and current_line is None:
            entity = seg.get(1)
            has_member_id = seg.get(8) == "MI"
            if entity == "QC":
                current.patient_last_name = seg.get(3)
                current.patient_first_name = seg.get(4)
                if has_member_id:
                    current.patient_member_id = seg.get(9)
            elif entity == "IL" and has_member_id:
                current.subscriber_member_id = seg.get(9)

        elif sid == "DTM" and current is not None:
            qualifier, value = seg.get(1), seg.get(2)
            if current_line is not None:
                if qualifier in {"472", "150", "151"}:
                    current_line.service_date = value
            elif qualifier == "232":
                current.statement_period_start = value
            elif qualifier == "233":
                current.statement_period_end = value

        elif sid == "LQ" and current is not None:
            # LQ*HE*<RARC> -> remark code. Applies to current line if open, else claim.
            if seg.get(1) in {"HE", "RX"}:
                code = seg.get(2)
                if code:
                    if current_line is not None:
                        current_line.rarc_codes.append(code)
                    else:
                        current.rarc_codes.append(code)

        elif sid in {"MIA", "MOA"} and current is not None:
            # Inpatient/Outpatient adjudication remark codes are RARCs at claim level.
            for pos in range(1, len(seg.elements) + 1):
                val = seg.get(pos)
                if val.startswith(("N", "M", "MA")) and not val.replace(".", "").isdigit():
                    current.rarc_codes.append(val)

        elif sid == "REF" and current is not None:
            if seg.get(1):
                target = current_line if current_line is not None else current
                target.references[seg.get(1)] = seg.get(2)

    if current is not None:
        if current_line is not None:
            current.service_lines.append(current_line)
        claims.append(current)

    return ParsedERA(
        sender_id=sender_id,
        receiver_id=receiver_id,
        interchange_control_number=icn,
        total_paid=total_paid,
        payer_name=payer_name,
        claims=claims,
        payer_identifier=payer_identifier,
    )


@dataclass
class Classification:
    category: DenialCategory
    appeal_strategy: str
    carc_codes: list[str]
    rarc_codes: list[str]


def classify_denial(claim: ClaimPayment) -> Classification:
    """Map a denied claim's CARC/RARC codes to a denial category (deterministic)."""
    carc = claim.all_carc_codes
    return Classification(
        category=get_category(carc),
        appeal_strategy=str(get_appeal_strategy(carc)),
        carc_codes=carc,
        rarc_codes=claim.all_rarc_codes,
    )
