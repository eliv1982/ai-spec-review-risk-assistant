from typing import Iterable, List

from app.enums import ReviewConfidence, ReviewReadiness, ReviewReasonCode
from app.schemas.review import FinalReview, ModelReviewDraft
from app.utils.text import is_too_vague

_CATALOGUE_ORDER: tuple[ReviewReasonCode, ...] = tuple(ReviewReasonCode)

_TECHNICAL_ROOT_REASON_CODES = frozenset(
    {
        ReviewReasonCode.MODEL_ERROR,
        ReviewReasonCode.INVALID_JSON,
        ReviewReasonCode.SCHEMA_MISMATCH,
    }
)

_FALLBACK_SUMMARY = (
    "Автоматическая проверка не может быть выполнена надёжно. Требуется ручная проверка."
)
_FALLBACK_QUESTION = (
    "Можете ли вы предоставить более полный и конкретный документ с требованиями?"
)


def _order_reason_codes(codes: Iterable[ReviewReasonCode]) -> List[ReviewReasonCode]:
    """Deduplicate and sort reason codes into the fixed catalogue order."""
    unique = set(codes)
    return [code for code in _CATALOGUE_ORDER if code in unique]


def build_final_review(*, original_text: str, draft: ModelReviewDraft) -> FinalReview:
    """Deterministic QC over a successfully validated ModelReviewDraft (REVIEW_SCHEMA.md,
    "Backend construction from a validated ModelReviewDraft").

    Reads `original_text` and `draft` without mutating either, and returns a new
    validated FinalReview. Reason codes are reconstructed exclusively from
    verified backend conditions; the model does not supply any reason code.
    """
    vague = is_too_vague(original_text)

    fired: set[ReviewReasonCode] = set()
    if draft.confidence == ReviewConfidence.low:
        fired.add(ReviewReasonCode.LOW_CONFIDENCE)
    if vague:
        fired.add(ReviewReasonCode.TOO_VAGUE_INPUT)
    if len(draft.contradictions) > 0:
        fired.add(ReviewReasonCode.CONTRADICTORY_INPUT)
    if len(draft.acceptance_criteria) == 0:
        fired.add(ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA)
    if vague and len(draft.questions_to_client) < 3:
        fired.add(ReviewReasonCode.INSUFFICIENT_QUESTIONS)

    reason_codes = _order_reason_codes(fired)
    final_needs_review = draft.model_needs_review or len(reason_codes) > 0

    return FinalReview(
        summary=draft.summary,
        risks=list(draft.risks),
        missing_requirements=list(draft.missing_requirements),
        contradictions=list(draft.contradictions),
        questions_to_client=list(draft.questions_to_client),
        acceptance_criteria=list(draft.acceptance_criteria),
        confidence=draft.confidence,
        document_readiness=draft.document_readiness,
        needs_review=final_needs_review,
        review_reason_codes=reason_codes,
    )


def build_fallback_review(*, original_text: str, root_reason_code: ReviewReasonCode) -> FinalReview:
    """Safe FinalReview fallback for a technical failure (REVIEW_SCHEMA.md,
    "Failure-only reason codes and safe fallback").

    `root_reason_code` must be one of the failure-provenance codes (MODEL_ERROR,
    INVALID_JSON, SCHEMA_MISMATCH); content-derived codes are rejected as root
    provenance since they only apply to a successfully validated draft.
    TOO_VAGUE_INPUT is appended only when the original input independently
    fails the exact vagueness thresholds; no other content-derived code is
    ever inferred from these synthetic fallback fields.
    """
    if root_reason_code not in _TECHNICAL_ROOT_REASON_CODES:
        raise ValueError(
            "root_reason_code must be one of MODEL_ERROR, INVALID_JSON, SCHEMA_MISMATCH; "
            f"got {root_reason_code!r}"
        )

    fired = {root_reason_code}
    if is_too_vague(original_text):
        fired.add(ReviewReasonCode.TOO_VAGUE_INPUT)

    return FinalReview(
        summary=_FALLBACK_SUMMARY,
        risks=[],
        missing_requirements=[],
        contradictions=[],
        questions_to_client=[_FALLBACK_QUESTION],
        acceptance_criteria=[],
        confidence=ReviewConfidence.low,
        document_readiness=ReviewReadiness.not_ready,
        needs_review=True,
        review_reason_codes=_order_reason_codes(fired),
    )
