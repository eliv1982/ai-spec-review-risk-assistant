"""FastAPI dependency factories wiring the LLM client, orchestrator, and
review services to a request-scoped `Session` (`app.database.get_db`).

Constructing `OpenAIReviewClient()` here never eagerly creates the real
`OpenAI` SDK client or touches `OPENAI_API_KEY`: the SDK client is built
lazily inside `OpenAIReviewClient.review()`, only when actually called
(`app/llm/client.py`). A missing/empty `OPENAI_API_KEY` therefore never
breaks application import, `/health`, or any route that never reaches the
LLM (for example a 404 for a missing document, or a 422 validation error).

Each factory below is a plain function usable as a FastAPI `Depends(...)`
target and is individually overridable via `app.dependency_overrides` in
offline tests (no real OpenAI client, no network).
"""

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.llm.client import OpenAIReviewClient
from app.services.ai_review_service import AIReviewService
from app.services.review_orchestrator import ReviewOrchestrator
from app.services.review_workflow import ReviewWorkflow


def get_review_client() -> OpenAIReviewClient:
    return OpenAIReviewClient()


def get_configured_model_name() -> Optional[str]:
    """The configured OpenAI model name for audit snapshots, read from the
    already-cached `Settings` (`app.config.get_settings`) — never a private
    field of an `OpenAI` SDK client and never a second client construction.
    Blank/unset (matching `OpenAIReviewClient`'s own "not configured" check)
    is normalized to `None` rather than an empty string.
    """
    model = get_settings().openai_model.strip()
    return model or None


def get_review_orchestrator(
    client: OpenAIReviewClient = Depends(get_review_client),
) -> ReviewOrchestrator:
    return ReviewOrchestrator(llm_client=client)


def get_review_workflow(
    db: Session = Depends(get_db),
    orchestrator: ReviewOrchestrator = Depends(get_review_orchestrator),
) -> ReviewWorkflow:
    return ReviewWorkflow(session=db, orchestrator=orchestrator)


def get_ai_review_service(
    db: Session = Depends(get_db),
    orchestrator: ReviewOrchestrator = Depends(get_review_orchestrator),
    model_name: Optional[str] = Depends(get_configured_model_name),
) -> AIReviewService:
    return AIReviewService(session=db, orchestrator=orchestrator, model_name=model_name)
