import pytest
from pydantic import ValidationError

from app.schemas.review import Contradiction, MissingRequirement, Risk

# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


def test_risk_valid_with_evidence():
    risk = Risk(severity="high", category="reliability", description="No retry policy.", evidence="raw excerpt")
    assert risk.severity == "high"
    assert risk.category == "reliability"
    assert risk.description == "No retry policy."
    assert risk.evidence == "raw excerpt"


def test_risk_valid_with_null_evidence():
    risk = Risk(severity="low", category="scope", description="Scope gap.", evidence=None)
    assert risk.evidence is None


def test_risk_rejects_unknown_additional_field():
    with pytest.raises(ValidationError):
        Risk(
            severity="high",
            category="reliability",
            description="No retry policy.",
            evidence=None,
            extra_field="not allowed",
        )


def test_risk_rejects_unknown_severity_enum_value():
    with pytest.raises(ValidationError):
        Risk(severity="critical", category="reliability", description="x", evidence=None)


def test_risk_rejects_unknown_category_enum_value():
    with pytest.raises(ValidationError):
        Risk(severity="high", category="legal", description="x", evidence=None)


def test_risk_rejects_missing_severity():
    with pytest.raises(ValidationError):
        Risk(category="reliability", description="x", evidence=None)


def test_risk_rejects_missing_category():
    with pytest.raises(ValidationError):
        Risk(severity="high", description="x", evidence=None)


def test_risk_rejects_missing_description():
    with pytest.raises(ValidationError):
        Risk(severity="high", category="reliability", evidence=None)


def test_risk_rejects_missing_evidence_key():
    # evidence is required (may be null, but the key itself must be present)
    with pytest.raises(ValidationError):
        Risk(severity="high", category="reliability", description="x")


def test_risk_rejects_wrong_type_for_description():
    with pytest.raises(ValidationError):
        Risk(severity="high", category="reliability", description=123, evidence=None)


def test_risk_rejects_wrong_type_for_severity():
    with pytest.raises(ValidationError):
        Risk(severity=1, category="reliability", description="x", evidence=None)


def test_risk_rejects_blank_description():
    with pytest.raises(ValidationError):
        Risk(severity="high", category="reliability", description="   ", evidence=None)


def test_risk_trims_description_whitespace():
    risk = Risk(severity="high", category="reliability", description="  padded text  ", evidence=None)
    assert risk.description == "padded text"


def test_risk_rejects_blank_evidence_string():
    with pytest.raises(ValidationError):
        Risk(severity="high", category="reliability", description="x", evidence="   ")


def test_risk_trims_evidence_whitespace():
    risk = Risk(severity="high", category="reliability", description="x", evidence="  quoted text  ")
    assert risk.evidence == "quoted text"


# ---------------------------------------------------------------------------
# MissingRequirement
# ---------------------------------------------------------------------------


def test_missing_requirement_valid():
    item = MissingRequirement(category="data", description="Retention period is unspecified.")
    assert item.category == "data"
    assert item.description == "Retention period is unspecified."


def test_missing_requirement_rejects_unknown_additional_field():
    with pytest.raises(ValidationError):
        MissingRequirement(category="data", description="x", extra_field="nope")


def test_missing_requirement_rejects_unknown_category_enum_value():
    with pytest.raises(ValidationError):
        MissingRequirement(category="legal", description="x")


def test_missing_requirement_rejects_missing_category():
    with pytest.raises(ValidationError):
        MissingRequirement(description="x")


def test_missing_requirement_rejects_missing_description():
    with pytest.raises(ValidationError):
        MissingRequirement(category="data")


def test_missing_requirement_rejects_wrong_type_for_description():
    with pytest.raises(ValidationError):
        MissingRequirement(category="data", description=["not", "a", "string"])


def test_missing_requirement_rejects_blank_description():
    with pytest.raises(ValidationError):
        MissingRequirement(category="data", description="\t\n")


def test_missing_requirement_trims_description_whitespace():
    item = MissingRequirement(category="data", description="  padded  ")
    assert item.description == "padded"


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


def test_contradiction_valid_with_evidence():
    item = Contradiction(description="Conflicting statements.", evidence=["excerpt one", "excerpt two"])
    assert item.description == "Conflicting statements."
    assert item.evidence == ["excerpt one", "excerpt two"]


def test_contradiction_allows_empty_evidence_array():
    item = Contradiction(description="Conflicting statements.", evidence=[])
    assert item.evidence == []


def test_contradiction_rejects_unknown_additional_field():
    with pytest.raises(ValidationError):
        Contradiction(description="x", evidence=[], extra_field="nope")


def test_contradiction_rejects_missing_description():
    with pytest.raises(ValidationError):
        Contradiction(evidence=[])


def test_contradiction_rejects_missing_evidence_key():
    with pytest.raises(ValidationError):
        Contradiction(description="x")


def test_contradiction_rejects_wrong_type_for_evidence():
    with pytest.raises(ValidationError):
        Contradiction(description="x", evidence="not a list")


def test_contradiction_rejects_blank_description():
    with pytest.raises(ValidationError):
        Contradiction(description="   ", evidence=[])


def test_contradiction_trims_description_whitespace():
    item = Contradiction(description="  padded  ", evidence=[])
    assert item.description == "padded"


def test_contradiction_rejects_blank_evidence_string():
    with pytest.raises(ValidationError):
        Contradiction(description="x", evidence=["valid", "   "])


def test_contradiction_trims_each_evidence_string():
    item = Contradiction(description="x", evidence=["  a  ", "b"])
    assert item.evidence == ["a", "b"]


def test_contradiction_rejects_null_item_in_evidence_array():
    with pytest.raises(ValidationError):
        Contradiction(description="x", evidence=[None])
