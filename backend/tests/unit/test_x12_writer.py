"""X12 writer + 837P builder tests: everything must round-trip through the tokenizer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from reclaim.edi.x12 import detect_delimiters, tokenize
from reclaim.edi.x12_writer import (
    FREQUENCY_REPLACEMENT,
    Address,
    BillingProvider,
    ClaimSpec,
    Practitioner,
    ServiceLineSpec,
    Subscriber,
    build_837p,
    composite,
    money,
    seg,
    transaction_set,
)

CREATED_AT = datetime(2026, 8, 11, 9, 0)


def _claim(**overrides) -> ClaimSpec:
    base = dict(
        claim_id="HSP-CLM-100028",
        payer_name="NORTHSTAR HEALTH",
        payer_id="NSTR01",
        subscriber=Subscriber(
            last_name="RIVERA",
            first_name="JORDAN",
            member_id="MEMBER-448820",
            birth_date=date(1980, 1, 15),
            gender="F",
            address=Address("12 FICTIONAL LN", "SPRINGFIELD", "IL", "62704"),
        ),
        billing_provider=BillingProvider(
            name="MOCK HOSPITAL",
            npi="1234567893",
            tax_id="991234567",
            address=Address("200 SAMPLE AVE", "SPRINGFIELD", "IL", "627011234"),
        ),
        diagnosis_codes=("M54.16",),
        service_lines=(
            ServiceLineSpec("72148", Decimal("4800"), date(2026, 8, 10), line_control_number="HSP100028L1"),
        ),
        rendering_provider=Practitioner("LEE", "SAM", "1987654328"),
        referring_provider=Practitioner("PATEL", "ANIKA", "1555000011"),
        group_number="NST-GRP-7700",
        prior_authorization_number="NST-PA-55120",
        medical_record_number="MRN-0042",
    )
    base.update(overrides)
    return ClaimSpec(**base)


def _edi(claim: ClaimSpec) -> str:
    return build_837p(claim, receiver_id="NSTR01", interchange_control_number=201, created_at=CREATED_AT)


def _segments(claim: ClaimSpec):
    return tokenize(_edi(claim))


def _ref(segs, qualifier):
    return next((s for s in segs if s.id == "REF" and s.get(1) == qualifier), None)


def test_isa_is_fixed_width():
    edi = _edi(_claim())
    assert edi.index("~") == 105
    assert detect_delimiters(edi).component == ":"


def test_usage_indicator_marks_test_data_and_st03_present():
    segs = _segments(_claim())
    assert segs[0].get(15) == "T"
    assert next(s for s in segs if s.id == "ST").get(3) == "005010X222A1"


def test_clm_carries_claim_id_total_and_frequency():
    clm = next(s for s in _segments(_claim()) if s.id == "CLM")
    assert clm.get(1) == "HSP-CLM-100028"
    assert clm.get(2) == "4800"
    assert clm.components(5) == ["11", "B", "1"]


def test_sbr_is_ppo_with_group_number():
    sbr = next(s for s in _segments(_claim()) if s.id == "SBR")
    assert (sbr.get(1), sbr.get(2), sbr.get(3), sbr.get(9)) == ("P", "18", "NST-GRP-7700", "12")


def test_member_id_mrn_and_prior_auth_present_in_tr3_order():
    segs = _segments(_claim())
    nm1_il = next(s for s in segs if s.id == "NM1" and s.get(1) == "IL")
    assert (nm1_il.get(8), nm1_il.get(9)) == ("MI", "MEMBER-448820")
    assert _ref(segs, "EA").get(2) == "MRN-0042"
    assert _ref(segs, "G1").get(2) == "NST-PA-55120"
    assert _ref(segs, "F8") is None
    refs = [s.get(1) for s in segs if s.id == "REF" and s.get(1) in {"G1", "EA"}]
    assert refs == ["G1", "EA"]


def test_diagnosis_procedure_date_line_control_and_providers():
    segs = _segments(_claim())
    ids = [s.id for s in segs]
    assert next(s for s in segs if s.id == "HI").get(1) == "ABK:M5416"
    lx = ids.index("LX")
    assert ids[lx:lx + 4] == ["LX", "SV1", "DTP", "REF"]
    sv1 = segs[lx + 1]
    assert sv1.components(1) == ["HC", "72148"]
    assert (sv1.get(2), sv1.get(3), sv1.get(4), sv1.get(7)) == ("4800", "UN", "1", "1")
    assert segs[lx + 2].get(3) == "20260810"
    assert (segs[lx + 3].get(1), segs[lx + 3].get(2)) == ("6R", "HSP100028L1")
    practitioners = [(s.get(1), s.get(9)) for s in segs if s.id == "NM1" and s.get(1) in {"DN", "82"}]
    assert practitioners == [("DN", "1555000011"), ("82", "1987654328")]


def test_se_count_matches_transaction_length():
    segs = _segments(_claim())
    ids = [s.id for s in segs]
    st, se = ids.index("ST"), ids.index("SE")
    assert int(segs[se].get(1)) == se - st + 1


def test_replacement_requires_and_references_original():
    with pytest.raises(ValueError):
        _segments(_claim(frequency_code=FREQUENCY_REPLACEMENT))
    segs = _segments(_claim(frequency_code=FREQUENCY_REPLACEMENT, original_payer_claim_number="PAYER-CLM-99281"))
    assert next(s for s in segs if s.id == "CLM").components(5)[2] == "7"
    assert _ref(segs, "F8").get(2) == "PAYER-CLM-99281"


def test_835_transaction_set_omits_st03():
    st, *_ = transaction_set("835", None, [seg("BPR", "H", "0", "C", "NON")])
    assert st == "ST*835*0001"


def test_segment_helpers_trim_trailing_empties():
    assert seg("NM1", "82", "1", "LEE", "", "") == "NM1*82*1*LEE"
    assert composite("11", "B", "") == "11:B"
    assert money(Decimal("4800.00")) == "4800"
    assert money(Decimal("12.50")) == "12.5"
    assert money(Decimal("0")) == "0"
