"""CARC/RARC code mappings and denial categorization.

Ported from Healtcare-RCM-Denial-Recovery-Agent@4129fdd (backend/src/edi/carc_rarc.py).

CARC = Claim Adjustment Reason Codes; RARC = Remittance Advice Remark Codes
(maintained by the X12 code committees). This module is the version-controlled
source of truth for the deterministic Triage step. The base set is representative
and covers all eight denial categories.
"""

from __future__ import annotations

from enum import StrEnum


class DenialCategory(StrEnum):
    CLERICAL = "clerical"
    COVERAGE = "coverage"
    MEDICAL_NECESSITY = "medical_necessity"
    PRIOR_AUTH = "prior_auth"
    TIMELY_FILING = "timely_filing"
    DUPLICATE = "duplicate"
    COB = "cob"
    PATIENT_RESPONSIBILITY = "patient_responsibility"
    OTHER = "other"


class AppealStrategy(StrEnum):
    AUTO_CORRECT = "auto_correct"
    MEDICAL_NECESSITY_APPEAL = "medical_necessity_appeal"
    PRIOR_AUTH_APPEAL = "prior_auth_appeal"
    COB_RESUBMIT = "cob_resubmit"
    TIMELY_FILING_APPEAL = "timely_filing_appeal"
    DUPLICATE_REVIEW = "duplicate_review"
    NONE = "none"


# Each entry: code -> {description, category, appeal_strategy}
CARC_MAPPINGS: dict[str, dict[str, str]] = {
    "1": {"description": "Deductible amount", "category": DenialCategory.PATIENT_RESPONSIBILITY, "appeal_strategy": AppealStrategy.NONE},
    "2": {"description": "Coinsurance amount", "category": DenialCategory.PATIENT_RESPONSIBILITY, "appeal_strategy": AppealStrategy.NONE},
    "3": {"description": "Co-payment amount", "category": DenialCategory.PATIENT_RESPONSIBILITY, "appeal_strategy": AppealStrategy.NONE},
    "4": {"description": "The procedure code is inconsistent with the modifier used", "category": DenialCategory.CLERICAL, "appeal_strategy": AppealStrategy.AUTO_CORRECT},
    "11": {"description": "The diagnosis is inconsistent with the procedure", "category": DenialCategory.CLERICAL, "appeal_strategy": AppealStrategy.AUTO_CORRECT},
    "16": {"description": "Claim/service lacks information or has submission/billing error(s)", "category": DenialCategory.CLERICAL, "appeal_strategy": AppealStrategy.AUTO_CORRECT},
    "18": {"description": "Exact duplicate claim/service", "category": DenialCategory.DUPLICATE, "appeal_strategy": AppealStrategy.DUPLICATE_REVIEW},
    "22": {"description": "This care may be covered by another payer per coordination of benefits", "category": DenialCategory.COB, "appeal_strategy": AppealStrategy.COB_RESUBMIT},
    "23": {"description": "Impact of prior payer(s) adjudication including payments/adjustments", "category": DenialCategory.COB, "appeal_strategy": AppealStrategy.COB_RESUBMIT},
    "29": {"description": "The time limit for filing has expired", "category": DenialCategory.TIMELY_FILING, "appeal_strategy": AppealStrategy.TIMELY_FILING_APPEAL},
    "50": {"description": "Non-covered services because this is not deemed a medical necessity", "category": DenialCategory.MEDICAL_NECESSITY, "appeal_strategy": AppealStrategy.MEDICAL_NECESSITY_APPEAL},
    "55": {"description": "Procedure/treatment is deemed experimental/investigational", "category": DenialCategory.MEDICAL_NECESSITY, "appeal_strategy": AppealStrategy.MEDICAL_NECESSITY_APPEAL},
    "96": {"description": "Non-covered charge(s)", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
    "97": {"description": "Benefit for this service is included in another service already adjudicated", "category": DenialCategory.CLERICAL, "appeal_strategy": AppealStrategy.AUTO_CORRECT},
    "109": {"description": "Claim/service not covered by this payer/contractor", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
    "119": {"description": "Benefit maximum for this time period/occurrence has been reached", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
    "146": {"description": "Diagnosis was invalid for the date(s) of service reported", "category": DenialCategory.CLERICAL, "appeal_strategy": AppealStrategy.AUTO_CORRECT},
    "147": {"description": "Provider contracted/negotiated rate expired or not on file", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
    "151": {"description": "Payer deems the information submitted does not support this many services", "category": DenialCategory.MEDICAL_NECESSITY, "appeal_strategy": AppealStrategy.MEDICAL_NECESSITY_APPEAL},
    "167": {"description": "This (these) diagnosis(es) is (are) not covered", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
    "197": {"description": "Precertification/authorization/notification/pre-treatment absent", "category": DenialCategory.PRIOR_AUTH, "appeal_strategy": AppealStrategy.PRIOR_AUTH_APPEAL},
    "198": {"description": "Precertification/authorization exceeded", "category": DenialCategory.PRIOR_AUTH, "appeal_strategy": AppealStrategy.PRIOR_AUTH_APPEAL},
    "204": {"description": "This service/equipment/drug is not covered under the patient's benefit plan", "category": DenialCategory.COVERAGE, "appeal_strategy": AppealStrategy.NONE},
}

RARC_MAPPINGS: dict[str, dict[str, str]] = {
    "N395": {"description": "Service not covered by this plan"},
    "N386": {"description": "This decision was based on a National Coverage Determination (NCD)"},
    "N115": {"description": "This decision was based on a Local Coverage Determination (LCD)"},
    "M76": {"description": "Missing/incomplete/invalid diagnosis or condition"},
    "M51": {"description": "Missing/incomplete/invalid procedure code(s)"},
    "N130": {"description": "Consult plan benefit documents for information about restrictions"},
    "MA04": {"description": "Secondary payment cannot be considered without primary EOB"},
    "N479": {"description": "Missing Explanation of Benefits (Coordination of Benefits or Medicare Secondary Payer)"},
    "N211": {"description": "You may not appeal this decision"},
}

# When several CARCs are present, the most appeal-actionable category wins over
# pure patient-responsibility ones.
_CATEGORY_PRIORITY: list[DenialCategory] = [
    DenialCategory.MEDICAL_NECESSITY,
    DenialCategory.PRIOR_AUTH,
    DenialCategory.TIMELY_FILING,
    DenialCategory.COB,
    DenialCategory.DUPLICATE,
    DenialCategory.CLERICAL,
    DenialCategory.COVERAGE,
    DenialCategory.PATIENT_RESPONSIBILITY,
    DenialCategory.OTHER,
]


def get_description(carc_code: str) -> str:
    entry = CARC_MAPPINGS.get(carc_code)
    return entry["description"] if entry else f"Unknown CARC code {carc_code}"


def get_category(carc_codes: list[str]) -> DenialCategory:
    """Resolve a single denial category from one or more CARC codes.

    Unknown codes contribute OTHER. The highest-priority category present wins, so a
    medical-necessity denial combined with a patient-responsibility adjustment is
    still routed for appeal.
    """
    found: set[DenialCategory] = set()
    for code in carc_codes:
        entry = CARC_MAPPINGS.get(code)
        found.add(DenialCategory(entry["category"]) if entry else DenialCategory.OTHER)
    for category in _CATEGORY_PRIORITY:
        if category in found:
            return category
    return DenialCategory.OTHER


def get_appeal_strategy(carc_codes: list[str]) -> AppealStrategy:
    category = get_category(carc_codes)
    for code in carc_codes:
        entry = CARC_MAPPINGS.get(code)
        if entry and DenialCategory(entry["category"]) == category:
            return AppealStrategy(entry["appeal_strategy"])
    return AppealStrategy.NONE
