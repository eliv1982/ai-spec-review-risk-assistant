import pytest
from pydantic import ValidationError

from app.schemas.review import ModelReviewDraft


def _valid_draft_kwargs(**overrides):
    base = dict(
        summary="The brief leaves data retention unspecified.",
        risks=[
            {
                "severity": "high",
                "category": "reliability",
                "description": "No retry policy is defined.",
                "evidence": "Notifications are sent when events occur.",
            }
        ],
        missing_requirements=[
            {"category": "data", "description": "Retention period is unspecified."}
        ],
        contradictions=[],
        questions_to_client=["What is the retention period?"],
        acceptance_criteria=["Given X, when Y, then Z within 60 seconds."],
        confidence="medium",
        document_readiness="needs_clarification",
        model_needs_review=False,
    )
    base.update(overrides)
    return base


def test_valid_full_draft():
    draft = ModelReviewDraft(**_valid_draft_kwargs())
    assert draft.summary == "The brief leaves data retention unspecified."
    assert draft.confidence == "medium"
    assert draft.document_readiness == "needs_clarification"
    assert draft.model_needs_review is False
    assert len(draft.risks) == 1
    assert len(draft.missing_requirements) == 1
    assert draft.contradictions == []


def test_valid_draft_with_all_empty_arrays_allowed():
    draft = ModelReviewDraft(
        **_valid_draft_kwargs(
            risks=[],
            missing_requirements=[],
            contradictions=[],
            questions_to_client=[],
            acceptance_criteria=[],
        )
    )
    assert draft.risks == []
    assert draft.missing_requirements == []
    assert draft.contradictions == []
    assert draft.questions_to_client == []
    assert draft.acceptance_criteria == []


def test_summary_is_trimmed():
    draft = ModelReviewDraft(**_valid_draft_kwargs(summary="  padded summary  "))
    assert draft.summary == "padded summary"


def test_questions_are_trimmed():
    draft = ModelReviewDraft(**_valid_draft_kwargs(questions_to_client=["  padded question?  "]))
    assert draft.questions_to_client == ["padded question?"]


def test_acceptance_criteria_are_trimmed():
    draft = ModelReviewDraft(**_valid_draft_kwargs(acceptance_criteria=["  padded criterion  "]))
    assert draft.acceptance_criteria == ["padded criterion"]


def test_required_arrays_must_be_present():
    kwargs = _valid_draft_kwargs()
    del kwargs["risks"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_missing_requirements_array_must_be_present():
    kwargs = _valid_draft_kwargs()
    del kwargs["missing_requirements"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_contradictions_array_must_be_present():
    kwargs = _valid_draft_kwargs()
    del kwargs["contradictions"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_questions_to_client_array_must_be_present():
    kwargs = _valid_draft_kwargs()
    del kwargs["questions_to_client"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_acceptance_criteria_array_must_be_present():
    kwargs = _valid_draft_kwargs()
    del kwargs["acceptance_criteria"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_model_needs_review_is_required():
    kwargs = _valid_draft_kwargs()
    del kwargs["model_needs_review"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_model_needs_review_accepts_strict_true():
    draft = ModelReviewDraft(**_valid_draft_kwargs(model_needs_review=True))
    assert draft.model_needs_review is True


def test_model_needs_review_rejects_string_true():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(model_needs_review="true"))


def test_model_needs_review_rejects_integer_one():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(model_needs_review=1))


def test_model_needs_review_rejects_integer_zero():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(model_needs_review=0))


def test_model_needs_review_rejects_none():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(model_needs_review=None))


def test_rejects_needs_review_field():
    kwargs = _valid_draft_kwargs()
    kwargs["needs_review"] = True
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_rejects_review_reason_codes_field():
    kwargs = _valid_draft_kwargs()
    kwargs["review_reason_codes"] = ["LOW_CONFIDENCE"]
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_rejects_unrelated_unknown_field():
    kwargs = _valid_draft_kwargs()
    kwargs["unexpected_field"] = "nope"
    with pytest.raises(ValidationError):
        ModelReviewDraft(**kwargs)


def test_rejects_blank_summary():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(summary="   "))


def test_rejects_blank_question():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(questions_to_client=["valid question?", "   "]))


def test_rejects_blank_acceptance_criterion():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(acceptance_criteria=["valid criterion", "\t"]))


def test_rejects_invalid_nested_risk_item():
    with pytest.raises(ValidationError):
        ModelReviewDraft(
            **_valid_draft_kwargs(
                risks=[{"severity": "extreme", "category": "reliability", "description": "x", "evidence": None}]
            )
        )


def test_rejects_invalid_nested_missing_requirement_item():
    with pytest.raises(ValidationError):
        ModelReviewDraft(
            **_valid_draft_kwargs(missing_requirements=[{"category": "data", "description": "   "}])
        )


def test_rejects_invalid_nested_contradiction_item():
    with pytest.raises(ValidationError):
        ModelReviewDraft(
            **_valid_draft_kwargs(
                contradictions=[{"description": "conflict", "evidence": ["ok", ""]}]
            )
        )


def test_rejects_wrong_type_for_confidence():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(confidence="very-high"))


def test_rejects_wrong_type_for_document_readiness():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(document_readiness="almost_ready"))


def test_rejects_wrong_type_for_risks_field():
    with pytest.raises(ValidationError):
        ModelReviewDraft(**_valid_draft_kwargs(risks="not a list"))
