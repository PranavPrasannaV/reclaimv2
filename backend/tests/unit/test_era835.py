"""835 parser + CARC classification tests (ported suite plus identity fields)."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from reclaim.edi import era835
from reclaim.edi.carc_rarc import DenialCategory, get_category
from reclaim.edi.x12 import EDIParseError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "edi"

# The draft sample from the idea doc, verbatim (no envelope; SE01 is not validated here).
IDEA_DOC_SAMPLE = (
    "ST*835*0001~"
    "CLP*HSP-CLM-100028*4*4800*0*4800*MC*PAYER-CLM-99281*11*1~"
    "CAS*CO*50*4800~"
    "NM1*QC*1*RIVERA*JORDAN****MI*MEMBER-448820~"
    "DTM*232*20260820~"
    "SE*8*0001~"
)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_50_denials_all_parsed():
    era = era835.parse_era(_read("sample_era_50_denials.edi"))
    assert len(era.claims) == 50
    assert len(era.denied_claims) == 50
    assert era.payer_name == "SAMPLE HEALTH PLAN"
    assert era.sender_id == "CLEARINGHOUSE"


def test_category_distribution():
    era = era835.parse_era(_read("sample_era_50_denials.edi"))
    dist = Counter(era835.classify_denial(c).category for c in era.denied_claims)
    assert dist[DenialCategory.MEDICAL_NECESSITY] == 12
    assert dist[DenialCategory.CLERICAL] == 10
    assert dist[DenialCategory.PRIOR_AUTH] == 8
    assert dist[DenialCategory.COVERAGE] == 8
    assert sum(dist.values()) == 50


def test_nonstandard_delimiters_detected():
    era = era835.parse_era(_read("nonstandard_delimiters.edi"))
    assert len(era.denied_claims) == 1
    assert era835.classify_denial(era.denied_claims[0]).category == DenialCategory.MEDICAL_NECESSITY


def test_empty_payload_raises():
    with pytest.raises(EDIParseError):
        era835.parse_era("")
    with pytest.raises(EDIParseError):
        era835.parse_era("   \n  ")


def test_combined_carc_medical_necessity_wins():
    assert get_category(["50", "1", "2"]) == DenialCategory.MEDICAL_NECESSITY
    assert get_category(["1", "2"]) == DenialCategory.PATIENT_RESPONSIBILITY


def test_unknown_carc_is_other():
    assert get_category(["ZZZ"]) == DenialCategory.OTHER


def test_classification_accuracy_dataset():
    dataset = json.loads(_read("denial_dataset.json"))
    correct = sum(1 for r in dataset if get_category(r["carc_codes"]).value == r["expected_category"])
    assert correct / len(dataset) >= 0.95


def test_partial_denial_isolates_denied_lines():
    edi = (
        "ISA*00*          *00*          *ZZ*CH             *ZZ*PROV           "
        "*260115*1200*^*00501*000000010*0*P*:~"
        "ST*835*0001~"
        "CLP*MIXED1*1*500*200*0*MC*PCN1*11~"
        "SVC*HC:99213*200*200**1~"
        "SVC*HC:99214*300*0**1~"
        "CAS*CO*50*300~"
        "SE*5*0001~"
    )
    claim = era835.parse_era(edi).claims[0]
    assert claim.is_denied
    assert len(claim.denied_service_lines) == 1
    assert claim.denied_service_lines[0].procedure_code == "99214"


def test_idea_doc_sample_yields_identity_fields():
    claim = era835.parse_era(IDEA_DOC_SAMPLE).claims[0]
    assert claim.claim_control_number == "HSP-CLM-100028"
    assert claim.payer_claim_control_number == "PAYER-CLM-99281"
    assert claim.is_denied
    assert claim.total_charge == Decimal("4800")
    assert claim.group_codes == ["CO"]
    assert claim.all_carc_codes == ["50"]
    assert claim.member_id == "MEMBER-448820"
    assert (claim.patient_last_name, claim.patient_first_name) == ("RIVERA", "JORDAN")
    assert claim.statement_period_start == "20260820"
    assert (claim.facility_type_code, claim.frequency_code) == ("11", "1")
    assert era835.classify_denial(claim).category == DenialCategory.MEDICAL_NECESSITY


def test_subscriber_member_id_wins_over_patient():
    edi = (
        "ST*835*0001~"
        "CLP*C1*4*100*0*0*12*P1*11*1~"
        "CAS*CO*50*100~"
        "NM1*QC*1*RIVERA*SAM****MI*DEPENDANT-1~"
        "NM1*IL*1*RIVERA*JORDAN****MI*MEMBER-448820~"
        "SE*6*0001~"
    )
    claim = era835.parse_era(edi).claims[0]
    assert claim.patient_member_id == "DEPENDANT-1"
    assert claim.member_id == "MEMBER-448820"


def test_ref_after_service_line_does_not_raise():
    # Regression: the RCM parser raised AttributeError here (ServiceLine had no `references`).
    edi = (
        "ST*835*0001~"
        "CLP*C1*4*100*0*0*12*P1*11*1~"
        "SVC*HC:72148*100*0**1~"
        "CAS*CO*50*100~"
        "REF*6R*LINE-1~"
        "SE*6*0001~"
    )
    claim = era835.parse_era(edi).claims[0]
    assert claim.service_lines[0].references == {"6R": "LINE-1"}
    assert claim.references == {}


# Corrected per the X12 review (research.md §1): CLP02=1, CLP05=0, CLP06=12, CAS under SVC,
# REF*0K policy id and N661/N130 remarks. SE01 counts ST..SE.
CORRECTED_835 = (
    "ISA*00*          *00*          *ZZ*NSTR01         *ZZ*MOCKHOSP       "
    "*260912*0600*^*00501*000000101*0*T*:~"
    "GS*HP*NSTR01*MOCKHOSP*20260912*0600*101*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*H*0*C*NON************20260912~"
    "TRN*1*NST-RA-0000101*1123456789~"
    "N1*PR*NORTHSTAR HEALTH*XV*NSTR01~"
    "N3*100 EXAMPLE PLAZA~"
    "N4*SPRINGFIELD*IL*62701~"
    "PER*BL*EDI SUPPORT*TE*5555550100~"
    "N1*PE*MOCK HOSPITAL*XX*1234567893~"
    "LX*1~"
    "CLP*HSP-CLM-100028*1*4800*0*0*12*PAYER-CLM-99281*11*1~"
    "NM1*QC*1*RIVERA*JORDAN****MI*MEMBER-448820~"
    "NM1*82*1*LEE*SAM****XX*1987654328~"
    "SVC*HC:72148*4800*0~"
    "DTM*472*20260810~"
    "CAS*CO*50*4800~"
    "REF*6R*HSP100028L1~"
    "REF*0K*NST-IMG-2026-04~"
    "LQ*HE*N661~"
    "LQ*HE*N130~"
    "SE*20*0001~"
    "GE*1*101~"
    "IEA*1*000000101~"
)


def test_corrected_835_line_level_denial():
    era = era835.parse_era(CORRECTED_835)
    assert (era.payer_name, era.payer_identifier, era.interchange_control_number) == (
        "NORTHSTAR HEALTH", "NSTR01", "000000101")
    claim = era.denied_claims[0]
    assert claim.status_code == "1"
    assert claim.patient_responsibility == Decimal("0")
    assert claim.claim_adjustments == []
    line = claim.denied_service_lines[0]
    assert (line.procedure_code, line.service_date, line.denial_amount) == ("72148", "20260810", Decimal("4800"))
    assert line.references == {"6R": "HSP100028L1", "0K": "NST-IMG-2026-04"}
    assert claim.all_rarc_codes == ["N661", "N130"]
    assert claim.group_codes == ["CO"]
    assert claim.member_id == "MEMBER-448820"
    assert era835.classify_denial(claim).category == DenialCategory.MEDICAL_NECESSITY


def test_payer_identifier_captured():
    edi = "ST*835*0001~N1*PR*NORTHSTAR HEALTH*XV*NSTR01~CLP*C1*4*100*0*0*12*P1*11*1~SE*4*0001~"
    era = era835.parse_era(edi)
    assert (era.payer_name, era.payer_identifier) == ("NORTHSTAR HEALTH", "NSTR01")
