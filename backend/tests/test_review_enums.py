from app.enums import ReviewConfidence, ReviewReadiness, ReviewReasonCode, RiskCategory, RiskSeverity

EXPECTED_SEVERITY = ["low", "medium", "high"]

EXPECTED_CATEGORY = [
    "scope",
    "functionality",
    "data",
    "integration",
    "security",
    "privacy",
    "performance",
    "reliability",
    "usability",
    "operations",
    "acceptance",
    "timeline",
    "dependency",
    "compliance",
    "other",
]

EXPECTED_CONFIDENCE = ["high", "medium", "low"]

EXPECTED_READINESS = ["ready", "needs_clarification", "not_ready"]

EXPECTED_REASON_CODE_CATALOGUE_ORDER = [
    "LOW_CONFIDENCE",
    "TOO_VAGUE_INPUT",
    "CONTRADICTORY_INPUT",
    "MISSING_ACCEPTANCE_CRITERIA",
    "INSUFFICIENT_QUESTIONS",
    "INVALID_JSON",
    "SCHEMA_MISMATCH",
    "MODEL_ERROR",
]


def test_risk_severity_values():
    assert [member.value for member in RiskSeverity] == EXPECTED_SEVERITY


def test_risk_category_values():
    assert [member.value for member in RiskCategory] == EXPECTED_CATEGORY


def test_risk_category_has_exactly_fifteen_members():
    assert len(list(RiskCategory)) == 15


def test_review_confidence_values_unchanged():
    assert [member.value for member in ReviewConfidence] == EXPECTED_CONFIDENCE


def test_review_readiness_values_unchanged():
    assert [member.value for member in ReviewReadiness] == EXPECTED_READINESS


def test_review_reason_code_catalogue_order():
    assert [member.value for member in ReviewReasonCode] == EXPECTED_REASON_CODE_CATALOGUE_ORDER


def test_review_reason_code_has_exactly_eight_members():
    assert len(list(ReviewReasonCode)) == 8


def test_risk_severity_rejects_unknown_value():
    try:
        RiskSeverity("critical")
        assert False, "expected ValueError for unknown RiskSeverity value"
    except ValueError:
        pass


def test_risk_category_rejects_unknown_value():
    try:
        RiskCategory("legal")
        assert False, "expected ValueError for unknown RiskCategory value"
    except ValueError:
        pass


def test_review_reason_code_rejects_unknown_value():
    try:
        ReviewReasonCode("UNKNOWN_CODE")
        assert False, "expected ValueError for unknown ReviewReasonCode value"
    except ValueError:
        pass
