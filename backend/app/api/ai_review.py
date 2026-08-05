from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ai_review_service
from app.schemas.review import AIReviewRequest, AIReviewResponse
from app.services.ai_review_service import AIReviewService

router = APIRouter()


@router.post(
    "/review",
    response_model=AIReviewResponse,
    status_code=200,
    summary="Демонстрационная проверка текста ИИ без сохранения",
    description=(
        "Проверяет переданный текст без создания Document/Review — сохраняется только "
        "AuditRun (action=ai.review). Безопасный резервный результат (safe fallback) "
        "по-прежнему возвращается как HTTP 200, но в audit фиксируется как техническая "
        "ошибка (status=error) согласно API_CONTRACTS.md."
    ),
)
def review_text(
    payload: AIReviewRequest,
    service: AIReviewService = Depends(get_ai_review_service),
) -> AIReviewResponse:
    try:
        result = service.review(title=payload.title, text=payload.text)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Не удалось выполнить проверку текста.")

    return AIReviewResponse.from_final_review(result.final_review)
