/**
 * Russian explanations for the backend's closed reason-code catalogue
 * (docs/REVIEW_SCHEMA.md, "review_reason_codes"). An unrecognized code
 * (future backend addition) falls back to `null` so callers can render the
 * raw technical value without breaking.
 */
const REASON_CODE_EXPLANATIONS: Record<string, string> = {
  LOW_CONFIDENCE: "Модель оценила уверенность в разборе документа как низкую.",
  TOO_VAGUE_INPUT: "Текст документа слишком короткий или расплывчатый для надёжного анализа.",
  CONTRADICTORY_INPUT: "В документе обнаружены внутренние противоречия.",
  MISSING_ACCEPTANCE_CRITERIA: "В документе не заданы критерии приёмки.",
  INSUFFICIENT_QUESTIONS: "Для расплывчатого документа сформировано недостаточно уточняющих вопросов.",
  INVALID_JSON: "Ответ модели не удалось разобрать как корректный JSON.",
  SCHEMA_MISMATCH: "Ответ модели не соответствует ожидаемой схеме данных.",
  MODEL_ERROR: "Произошла ошибка при обращении к модели ИИ.",
};

export function explainReasonCode(code: string): string | null {
  return REASON_CODE_EXPLANATIONS[code] ?? null;
}
