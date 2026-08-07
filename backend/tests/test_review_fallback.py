import pytest

from app.enums import ReviewReasonCode
from app.schemas.review import FinalReview
from app.services.review_qc import build_fallback_review
from app.utils.text import normalize_text

NON_VAGUE_TEXT = (
    "The system shall allow an authenticated administrator to configure "
    "notification delivery preferences, including channel selection, retry "
    "policy, and retention period, and every configuration change must be "
    "recorded in an audit log entry that is visible to operators within the "
    "administration panel for later review and compliance reporting purposes."
)

VAGUE_TEXT = "Too short."

TECHNICAL_ROOT_CODES = [
    ReviewReasonCode.MODEL_ERROR,
    ReviewReasonCode.INVALID_JSON,
    ReviewReasonCode.SCHEMA_MISMATCH,
]

APPROVED_FALLBACK_SUMMARY = (
    "Автоматическая проверка не может быть выполнена надёжно. Требуется ручная проверка."
)
APPROVED_FALLBACK_QUESTIONS = [
    "Можете ли вы предоставить более полный и конкретный документ с требованиями?"
]


def test_fixture_text_constants_have_expected_properties():
    normalized_non_vague = normalize_text(NON_VAGUE_TEXT)
    assert len(normalized_non_vague) >= 200
    assert len(normalized_non_vague.split(" ")) >= 30

    normalized_vague = normalize_text(VAGUE_TEXT)
    assert len(normalized_vague) < 200
    assert len(normalized_vague.split(" ")) < 30


# ---------------------------------------------------------------------------
# Each technical root code, with non-vague input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("root_code", TECHNICAL_ROOT_CODES)
def test_root_code_with_non_vague_input(root_code):
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=root_code)
    assert final.needs_review is True
    assert final.review_reason_codes == [root_code]
    assert final.confidence == "low"
    assert final.document_readiness == "not_ready"


@pytest.mark.parametrize("root_code", TECHNICAL_ROOT_CODES)
def test_root_code_with_vague_input_appends_too_vague(root_code):
    final = build_fallback_review(original_text=VAGUE_TEXT, root_reason_code=root_code)
    assert ReviewReasonCode.TOO_VAGUE_INPUT in final.review_reason_codes
    assert root_code in final.review_reason_codes
    assert len(final.review_reason_codes) == 2


# ---------------------------------------------------------------------------
# Catalogue ordering (TOO_VAGUE_INPUT is index 2; all technical codes are
# later in the catalogue, so TOO_VAGUE_INPUT must always come first)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("root_code", TECHNICAL_ROOT_CODES)
def test_vague_plus_root_code_ordering(root_code):
    final = build_fallback_review(original_text=VAGUE_TEXT, root_reason_code=root_code)
    assert final.review_reason_codes == [ReviewReasonCode.TOO_VAGUE_INPUT, root_code]


# ---------------------------------------------------------------------------
# No fabricated findings
# ---------------------------------------------------------------------------


def test_no_fabricated_findings():
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert final.risks == []
    assert final.missing_requirements == []
    assert final.contradictions == []
    assert final.acceptance_criteria == []


def test_exactly_one_safe_question():
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert len(final.questions_to_client) == 1


# ---------------------------------------------------------------------------
# Russian safe summary and question
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("root_code", TECHNICAL_ROOT_CODES)
def test_summary_and_question_match_approved_russian_text(root_code):
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=root_code)
    assert final.summary == APPROVED_FALLBACK_SUMMARY
    assert final.questions_to_client == APPROVED_FALLBACK_QUESTIONS


def test_summary_and_question_identical_across_root_codes():
    # The safe fallback text itself does not depend on which technical failure occurred.
    results = [
        build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=code) for code in TECHNICAL_ROOT_CODES
    ]
    summaries = {r.summary for r in results}
    questions = {tuple(r.questions_to_client) for r in results}
    assert len(summaries) == 1
    assert len(questions) == 1


# ---------------------------------------------------------------------------
# Rejection of content reason codes as root provenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_code",
    [
        ReviewReasonCode.LOW_CONFIDENCE,
        ReviewReasonCode.TOO_VAGUE_INPUT,
        ReviewReasonCode.CONTRADICTORY_INPUT,
        ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA,
        ReviewReasonCode.INSUFFICIENT_QUESTIONS,
    ],
)
def test_rejects_content_derived_code_as_root_provenance(content_code):
    with pytest.raises(ValueError):
        build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=content_code)


# ---------------------------------------------------------------------------
# Synthetic fallback fields do not trigger content-derived codes
# ---------------------------------------------------------------------------


def test_low_confidence_from_synthetic_fields_is_not_added():
    # The fallback always sets confidence="low", but LOW_CONFIDENCE must not
    # be added merely because of that synthetic field.
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert ReviewReasonCode.LOW_CONFIDENCE not in final.review_reason_codes


def test_missing_acceptance_criteria_from_synthetic_fields_is_not_added():
    # The fallback always sets acceptance_criteria=[], but
    # MISSING_ACCEPTANCE_CRITERIA must not be added merely because of that.
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.INVALID_JSON)
    assert ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA not in final.review_reason_codes


def test_insufficient_questions_from_synthetic_fields_is_not_added():
    # The fallback always has exactly one question, but INSUFFICIENT_QUESTIONS
    # must not be added merely because of that, even with vague input.
    final = build_fallback_review(original_text=VAGUE_TEXT, root_reason_code=ReviewReasonCode.SCHEMA_MISMATCH)
    assert ReviewReasonCode.INSUFFICIENT_QUESTIONS not in final.review_reason_codes


def test_contradictory_input_from_synthetic_fields_is_not_added():
    # The fallback always sets contradictions=[], so CONTRADICTORY_INPUT can
    # never fire from it (documented for completeness alongside the other
    # synthetic-field guards above).
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert ReviewReasonCode.CONTRADICTORY_INPUT not in final.review_reason_codes


def test_fallback_only_ever_contains_root_code_and_optional_too_vague():
    for root_code in TECHNICAL_ROOT_CODES:
        for text in (NON_VAGUE_TEXT, VAGUE_TEXT):
            final = build_fallback_review(original_text=text, root_reason_code=root_code)
            allowed = {root_code, ReviewReasonCode.TOO_VAGUE_INPUT}
            assert set(final.review_reason_codes) <= allowed


# ---------------------------------------------------------------------------
# Returns a valid, natively serializable FinalReview
# ---------------------------------------------------------------------------


def test_returns_final_review_instance():
    final = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert isinstance(final, FinalReview)


def test_fallback_reason_codes_have_no_duplicates():
    final = build_fallback_review(original_text=VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR)
    assert len(final.review_reason_codes) == len(set(final.review_reason_codes))
