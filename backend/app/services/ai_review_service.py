"""Stateless AI review audit workflow (application/service layer, not an API endpoint).

Wires an injected orchestrator (`app.services.review_orchestrator.ReviewOrchestrator`,
or any test double structurally satisfying
`app.services.review_workflow.ReviewOrchestratorProtocol`) to the single
`ai.review` audit row documented for `POST /api/ai/review`
(API_CONTRACTS.md, "POST /api/ai/review"):

    document_text -> orchestrator.review(document_text) -> ReviewOrchestrationResult
    -> audit_runs insert (entity_type=None, entity_id=None) -> ReviewOrchestrationResult

The orchestrator is called at most once and is never constructed here: this module
never imports `OpenAIReviewClient`, never talks to OpenAI, and never re-implements
QC or the fallback factory. `LLMClientError` is already handled inside the
orchestrator (safe fallback `FinalReview`); it can never reach this module.

Unlike `app.services.review_workflow.ReviewWorkflow`, this service never creates or
reads a `Document` or `Review` row (API_CONTRACTS.md, "POST /api/ai/review", "Creates
domain record: **no** `documents` or `reviews` row. **Yes** — creates `audit_runs`
row.").

Audit status for this action follows the documented per-outcome table for
`ai.review` (API_CONTRACTS.md, "POST /api/ai/review"), which — unlike
`document.review` — audits a safe LLM fallback as a technical `status="error"`
with a non-empty sanitized summary, not `status="needs_review"`:

    final_review.needs_review is False, used_fallback is False -> success,   error=None
    final_review.needs_review is True,  used_fallback is False -> needs_review, error=None
    used_fallback is True                                      -> error,     non-empty sanitized error

The sanitized error message only ever names the safe, closed `LLMErrorCategory`
value — never the original exception, its message, a traceback, or a provider
payload.

Recovery boundary (mirrors `ReviewWorkflow`'s own error-audit pattern): the
orchestrator call, audit-snapshot construction, and the ordinary `ai.review` audit
insert/flush/commit are all covered by one `try`/`except Exception`. On any
ordinary exception — never `KeyboardInterrupt`/`SystemExit`/`GeneratorExit`, which
are `BaseException` subclasses and are never caught here — the (possibly partially
flushed) transaction is rolled back first, then a *separate*, best-effort recovery
transaction records exactly one `AuditRun(action="ai.review", status="error")` with
a fixed, non-secret Russian message (never `str(exc)`, a traceback, the document
text, the title, or a provider payload). If that recovery write itself fails, it is
rolled back and swallowed so it never replaces the original exception, which is
always re-raised unchanged via a bare `raise`. Either way the session is left with
no open transaction and remains usable for a subsequent query.

Out of scope here: HTTP endpoints, HTTP status mapping, `Document`/`Review`
persistence, retries, a second LLM call, background tasks — see backend/README.md.
"""

import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.enums import AuditStatus
from app.llm.prompts import PROMPT_VERSION, REVIEW_SCHEMA_VERSION
from app.services.audit_service import AuditService
from app.services.review_orchestrator import ReviewOrchestrationResult
from app.services.review_workflow import ReviewOrchestratorProtocol

_AUDIT_ACTION = "ai.review"

_FALLBACK_AUDIT_ERROR_MESSAGE_TEMPLATE = (
    "Проверка ИИ вернула безопасный резервный результат (категория ошибки LLM: {category})."
)

_UNEXPECTED_ERROR_AUDIT_MESSAGE = (
    "Не удалось выполнить проверку текста из-за непредвиденной ошибки приложения."
)


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


class AIReviewService:
    """Application-layer service: run orchestration once, write the `ai.review` audit row.

    Not responsible for HTTP, `Document`/`Review` persistence, retries, or building
    the orchestrator/LLM client — all of those are injected or out of scope. Never
    closes the injected `session` and never opens a second one.
    """

    def __init__(
        self,
        *,
        session: Session,
        orchestrator: ReviewOrchestratorProtocol,
        model_name: Optional[str] = None,
    ) -> None:
        self._session = session
        self._orchestrator = orchestrator
        self._model_name = model_name

    def review(self, *, title: Optional[str], text: str) -> ReviewOrchestrationResult:
        start = time.perf_counter()

        try:
            result = self._orchestrator.review(text)

            if result.used_fallback:
                status = AuditStatus.error
                error = _FALLBACK_AUDIT_ERROR_MESSAGE_TEMPLATE.format(
                    category=result.llm_error_category.value
                )
            elif result.final_review.needs_review:
                status = AuditStatus.needs_review
                error = None
            else:
                status = AuditStatus.success
                error = None

            AuditService(self._session).record(
                action=_AUDIT_ACTION,
                entity_type=None,
                entity_id=None,
                input_json=self._input_json(title=title, text=text),
                output_json={
                    "used_fallback": result.used_fallback,
                    "llm_error_category": (
                        result.llm_error_category.value
                        if result.llm_error_category is not None
                        else None
                    ),
                    "needs_review": result.final_review.needs_review,
                    "review_reason_codes": [
                        code.value for code in result.final_review.review_reason_codes
                    ],
                },
                status=status.value,
                error=error,
                duration_ms=_elapsed_ms(start),
            )
            self._session.commit()
        except Exception:
            self._write_error_audit(title=title, text=text, start=start)
            raise

        return result

    def _input_json(self, *, title: Optional[str], text: str) -> Dict[str, Any]:
        return {
            "title_length": len(title) if title is not None else None,
            "text_length": len(text),
            "prompt_version": PROMPT_VERSION,
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "model": self._model_name,
        }

    def _write_error_audit(self, *, title: Optional[str], text: str, start: float) -> None:
        """Best-effort error audit for an unexpected `ai.review` failure.

        Rolls back any incomplete main transaction first, then records a separate
        `status="error"` audit row with a fixed, non-secret message. Never
        re-raises: if this secondary write itself fails, it must not replace or
        hide the original exception the caller is about to re-raise.
        """
        self._session.rollback()
        try:
            AuditService(self._session).record(
                action=_AUDIT_ACTION,
                entity_type=None,
                entity_id=None,
                input_json=self._input_json(title=title, text=text),
                output_json=None,
                status=AuditStatus.error.value,
                error=_UNEXPECTED_ERROR_AUDIT_MESSAGE,
                duration_ms=_elapsed_ms(start),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
