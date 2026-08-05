from app.enums import ReviewReasonCode
from app.schemas.review import ModelReviewDraft
from app.services.review_qc import build_final_review
from app.utils.text import normalize_text

NON_VAGUE_TEXT = (
    "The system shall allow an authenticated administrator to configure "
    "notification delivery preferences, including channel selection, retry "
    "policy, and retention period, and every configuration change must be "
    "recorded in an audit log entry that is visible to operators within the "
    "administration panel for later review and compliance reporting purposes."
)

VAGUE_TEXT = "Too short."


def test_fixture_text_constants_have_expected_properties():
    normalized_non_vague = normalize_text(NON_VAGUE_TEXT)
    assert len(normalized_non_vague) >= 200
    assert len(normalized_non_vague.split(" ")) >= 30

    normalized_vague = normalize_text(VAGUE_TEXT)
    assert len(normalized_vague) < 200
    assert len(normalized_vague.split(" ")) < 30


def _clean_draft(**overrides) -> ModelReviewDraft:
    """A baseline draft where, paired with NON_VAGUE_TEXT, no deterministic
    condition fires: confidence is not low, no contradictions, non-empty
    acceptance criteria, >= 3 questions, model_needs_review False."""
    base = dict(
        summary="Summary of the reviewed specification.",
        risks=[],
        missing_requirements=[],
        contradictions=[],
        questions_to_client=["Question one?", "Question two?", "Question three?"],
        acceptance_criteria=["Given X, when Y, then Z."],
        confidence="high",
        document_readiness="ready",
        model_needs_review=False,
    )
    base.update(overrides)
    return ModelReviewDraft(**base)


# ---------------------------------------------------------------------------
# Each rule in isolation
# ---------------------------------------------------------------------------


def test_low_confidence_rule_alone():
    draft = _clean_draft(confidence="low")
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.LOW_CONFIDENCE]


def test_vague_input_rule_alone():
    draft = _clean_draft()  # confidence high, 3 questions, keeps INSUFFICIENT_QUESTIONS from firing
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.TOO_VAGUE_INPUT]


def test_contradictory_input_rule_alone():
    draft = _clean_draft(
        contradictions=[{"description": "Conflicting statements about X.", "evidence": []}]
    )
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.CONTRADICTORY_INPUT]


def test_missing_acceptance_criteria_rule_alone():
    draft = _clean_draft(acceptance_criteria=[])
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA]


def test_insufficient_questions_rule_fires_together_with_vague_input():
    # INSUFFICIENT_QUESTIONS requires vague input as a precondition, so
    # TOO_VAGUE_INPUT necessarily fires alongside it in catalogue order.
    draft = _clean_draft(questions_to_client=["Only one question?"])
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [
        ReviewReasonCode.TOO_VAGUE_INPUT,
        ReviewReasonCode.INSUFFICIENT_QUESTIONS,
    ]


def test_insufficient_questions_rule_does_not_fire_without_vague_input():
    draft = _clean_draft(questions_to_client=["Only one question?"])
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is False
    assert final.review_reason_codes == []


def test_two_questions_with_vague_input_still_fires_insufficient_questions():
    draft = _clean_draft(questions_to_client=["Q1?", "Q2?"])
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert ReviewReasonCode.INSUFFICIENT_QUESTIONS in final.review_reason_codes


def test_three_questions_with_vague_input_does_not_fire_insufficient_questions():
    draft = _clean_draft(questions_to_client=["Q1?", "Q2?", "Q3?"])
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert ReviewReasonCode.INSUFFICIENT_QUESTIONS not in final.review_reason_codes


# ---------------------------------------------------------------------------
# Combinations
# ---------------------------------------------------------------------------


def test_multiple_codes_appear_in_catalogue_order():
    draft = _clean_draft(
        confidence="low",
        contradictions=[{"description": "Conflict.", "evidence": []}],
        acceptance_criteria=[],
        questions_to_client=["Only one question?"],
    )
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [
        ReviewReasonCode.LOW_CONFIDENCE,
        ReviewReasonCode.TOO_VAGUE_INPUT,
        ReviewReasonCode.CONTRADICTORY_INPUT,
        ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA,
        ReviewReasonCode.INSUFFICIENT_QUESTIONS,
    ]


def test_no_duplicate_codes_in_combined_result():
    draft = _clean_draft(
        confidence="low",
        contradictions=[{"description": "Conflict.", "evidence": []}],
        acceptance_criteria=[],
        questions_to_client=["Only one question?"],
    )
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    assert len(final.review_reason_codes) == len(set(final.review_reason_codes))


def test_failure_only_codes_never_appear_on_successful_path():
    draft = _clean_draft(
        confidence="low",
        contradictions=[{"description": "Conflict.", "evidence": []}],
        acceptance_criteria=[],
        questions_to_client=["Only one question?"],
    )
    final = build_final_review(original_text=VAGUE_TEXT, draft=draft)
    forbidden = {ReviewReasonCode.INVALID_JSON, ReviewReasonCode.SCHEMA_MISMATCH, ReviewReasonCode.MODEL_ERROR}
    assert forbidden.isdisjoint(final.review_reason_codes)


def test_model_flag_alone_yields_empty_reason_codes():
    """Required special case (task section 6):
    model_needs_review=true, no deterministic condition fires
    -> needs_review=true, review_reason_codes=[].
    """
    draft = _clean_draft(model_needs_review=True)
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == []


def test_deterministic_trigger_with_model_flag_false():
    draft = _clean_draft(acceptance_criteria=[], model_needs_review=False)
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA]


def test_no_model_flag_and_no_trigger_yields_needs_review_false():
    draft = _clean_draft(model_needs_review=False)
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert final.needs_review is False
    assert final.review_reason_codes == []


def test_final_needs_review_false_implies_empty_reason_codes():
    draft = _clean_draft(model_needs_review=False)
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    if final.needs_review is False:
        assert final.review_reason_codes == []


# ---------------------------------------------------------------------------
# Draft is not mutated; content is faithfully copied
# ---------------------------------------------------------------------------


def test_input_draft_is_not_mutated():
    draft = _clean_draft(
        confidence="low",
        acceptance_criteria=[],
        contradictions=[{"description": "Conflict.", "evidence": ["excerpt"]}],
    )
    snapshot_before = draft.model_dump()

    build_final_review(original_text=VAGUE_TEXT, draft=draft)

    assert draft.model_dump() == snapshot_before


def test_content_fields_are_copied_faithfully():
    draft = _clean_draft(
        summary="Exact summary text.",
        risks=[
            {
                "severity": "high",
                "category": "security",
                "description": "Auth bypass risk.",
                "evidence": "raw excerpt",
            }
        ],
        missing_requirements=[{"category": "data", "description": "No retention policy."}],
        # Non-empty, distinctive values: if build_final_review ever hard-coded
        # these to empty arrays instead of copying the draft, this test would
        # catch it (unlike the previous defaults, which were already empty
        # for contradictions and thus couldn't detect that failure mode).
        contradictions=[
            {
                "description": "Distinctive contradiction about retry behaviour.",
                "evidence": ["Distinctive contradiction excerpt."],
            }
        ],
        questions_to_client=[
            "Distinctive question one?",
            "Distinctive question two?",
            "Distinctive question three?",
        ],
        acceptance_criteria=[
            "Distinctive acceptance criterion one.",
            "Distinctive acceptance criterion two.",
        ],
    )
    snapshot_before = draft.model_dump()

    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)

    # All eight content fields are faithfully copied from the draft.
    assert final.summary == draft.summary
    assert [r.model_dump() for r in final.risks] == [r.model_dump() for r in draft.risks]
    assert [m.model_dump() for m in final.missing_requirements] == [
        m.model_dump() for m in draft.missing_requirements
    ]
    assert [c.model_dump() for c in final.contradictions] == [
        c.model_dump() for c in draft.contradictions
    ]
    assert final.questions_to_client == draft.questions_to_client
    assert final.acceptance_criteria == draft.acceptance_criteria
    assert final.confidence == draft.confidence
    assert final.document_readiness == draft.document_readiness

    # model_needs_review is a draft-only field and is never exposed on FinalReview.
    assert "model_needs_review" not in final.model_dump()

    # Backend-produced needs_review / review_reason_codes: the non-empty
    # contradictions fixture is the only condition that fires here.
    assert final.needs_review is True
    assert final.review_reason_codes == [ReviewReasonCode.CONTRADICTORY_INPUT]

    # The supplied draft is left untouched by the call.
    assert draft.model_dump() == snapshot_before


def test_returns_final_review_instance():
    from app.schemas.review import FinalReview

    draft = _clean_draft()
    final = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)
    assert isinstance(final, FinalReview)
