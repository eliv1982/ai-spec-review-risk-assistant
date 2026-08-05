import pytest
from pydantic import ValidationError

from app.schemas.review import FinalReview


def _valid_final_kwargs(**overrides):
    base = dict(
        summary="The brief leaves data retention unspecified.",
        risks=[],
        missing_requirements=[
            {"category": "data", "description": "Retention period is unspecified."}
        ],
        contradictions=[],
        questions_to_client=["What is the retention period?"],
        acceptance_criteria=[],
        confidence="low",
        document_readiness="not_ready",
        needs_review=True,
        review_reason_codes=["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
    )
    base.update(overrides)
    return base


def test_valid_final_review():
    final = FinalReview(**_valid_final_kwargs())
    assert final.needs_review is True
    assert final.review_reason_codes == ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"]
    assert final.confidence == "low"
    assert final.document_readiness == "not_ready"


def test_valid_final_review_with_no_reason_codes():
    final = FinalReview(**_valid_final_kwargs(needs_review=False, review_reason_codes=[]))
    assert final.needs_review is False
    assert final.review_reason_codes == []


def test_rejects_model_needs_review_field():
    kwargs = _valid_final_kwargs()
    kwargs["model_needs_review"] = False
    with pytest.raises(ValidationError):
        FinalReview(**kwargs)


def test_needs_review_is_required():
    kwargs = _valid_final_kwargs()
    del kwargs["needs_review"]
    with pytest.raises(ValidationError):
        FinalReview(**kwargs)


def test_needs_review_rejects_string_true():
    with pytest.raises(ValidationError):
        FinalReview(**_valid_final_kwargs(needs_review="true"))


def test_needs_review_rejects_integer_one():
    with pytest.raises(ValidationError):
        FinalReview(**_valid_final_kwargs(needs_review=1))


def test_needs_review_accepts_strict_false():
    final = FinalReview(**_valid_final_kwargs(needs_review=False, review_reason_codes=[]))
    assert final.needs_review is False


def test_review_reason_codes_rejects_unknown_code():
    with pytest.raises(ValidationError):
        FinalReview(**_valid_final_kwargs(review_reason_codes=["NOT_A_REAL_CODE"]))


def test_review_reason_codes_accepts_all_catalogue_values():
    final = FinalReview(
        **_valid_final_kwargs(
            review_reason_codes=[
                "LOW_CONFIDENCE",
                "TOO_VAGUE_INPUT",
                "CONTRADICTORY_INPUT",
                "MISSING_ACCEPTANCE_CRITERIA",
                "INSUFFICIENT_QUESTIONS",
                "INVALID_JSON",
                "SCHEMA_MISMATCH",
                "MODEL_ERROR",
            ]
        )
    )
    assert len(final.review_reason_codes) == 8


def test_review_reason_codes_is_required():
    kwargs = _valid_final_kwargs()
    del kwargs["review_reason_codes"]
    with pytest.raises(ValidationError):
        FinalReview(**kwargs)


def test_rejects_unrelated_unknown_field():
    kwargs = _valid_final_kwargs()
    kwargs["unexpected_field"] = "nope"
    with pytest.raises(ValidationError):
        FinalReview(**kwargs)


def test_rejects_blank_summary():
    with pytest.raises(ValidationError):
        FinalReview(**_valid_final_kwargs(summary="   "))


def test_rejects_invalid_nested_risk_item():
    with pytest.raises(ValidationError):
        FinalReview(
            **_valid_final_kwargs(
                risks=[{"severity": "high", "category": "reliability", "description": "", "evidence": None}]
            )
        )


def test_native_serialization_round_trip():
    final = FinalReview(**_valid_final_kwargs())
    dumped = final.model_dump(mode="json")
    assert dumped["needs_review"] is True
    assert dumped["review_reason_codes"] == ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"]
    assert dumped["confidence"] == "low"
    assert dumped["document_readiness"] == "not_ready"
    assert "model_needs_review" not in dumped

    reloaded = FinalReview.model_validate(dumped)
    assert reloaded == final


def test_native_serialization_produces_plain_json_types():
    import json

    final = FinalReview(**_valid_final_kwargs())
    dumped = final.model_dump(mode="json")
    # must be plain-JSON-serializable (no Enum objects, no Python-only types)
    json.dumps(dumped)
