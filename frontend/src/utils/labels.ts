/** Russian labels for closed backend enums (docs/REVIEW_SCHEMA.md, backend/app/enums.py). */

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
};

const READINESS_LABELS: Record<string, string> = {
  ready: "Готов",
  needs_clarification: "Требует уточнений",
  not_ready: "Не готов",
};

/** Masculine forms ("Уровень риска: Высокий"), distinct from
 * `CONFIDENCE_LABELS`'s feminine forms ("Уверенность: Высокая") — Russian
 * adjective agreement depends on the noun each label attaches to. */
const SEVERITY_LABELS: Record<string, string> = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

const CATEGORY_LABELS: Record<string, string> = {
  scope: "Объём работ",
  functionality: "Функциональность",
  data: "Данные",
  integration: "Интеграции",
  security: "Безопасность",
  privacy: "Конфиденциальность",
  performance: "Производительность",
  reliability: "Надёжность",
  usability: "Удобство использования",
  operations: "Эксплуатация",
  acceptance: "Приёмка",
  timeline: "Сроки",
  dependency: "Зависимости",
  compliance: "Соответствие требованиям",
  other: "Прочее",
};

const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  created: "Создан",
  reviewed: "Проверка завершена",
  review_failed: "Проверка не выполнена",
};

const AUDIT_STATUS_LABELS: Record<string, string> = {
  success: "Успешно",
  needs_review: "Нужна экспертная проверка",
  error: "Техническая ошибка",
};

/** `audit_runs.entity_type` (docs/DATA_MODEL.md, "Entity mapping"): the only
 * two values the backend ever writes are `document` and `review`. */
const ENTITY_TYPE_LABELS: Record<string, string> = {
  document: "Документ",
  review: "Проверка",
};

/** `needs_review` (ReviewResponse/ReviewListItem — REVIEW_SCHEMA.md), kept
 * distinct from `DOCUMENT_STATUS_LABELS`'s workflow status: a review can be
 * "Проверка завершена" and still need expert review. */
const NEEDS_REVIEW_LABELS: Record<"true" | "false", string> = {
  true: "Нужна экспертная проверка",
  false: "Экспертная проверка не требуется",
};

/** Short, user-facing labels for the closed `ReviewReasonCode` catalogue
 * (docs/REVIEW_SCHEMA.md, "review_reason_codes") — the primary text shown in
 * place of the raw technical code; `utils/reasonCodes.ts::explainReasonCode`
 * supplies the longer supporting sentence shown underneath it. */
const REASON_CODE_LABELS: Record<string, string> = {
  LOW_CONFIDENCE: "Низкая уверенность анализа",
  TOO_VAGUE_INPUT: "Недостаточно конкретный документ",
  CONTRADICTORY_INPUT: "Обнаружены противоречия",
  MISSING_ACCEPTANCE_CRITERIA: "Не хватает критериев приёмки",
  INSUFFICIENT_QUESTIONS: "Недостаточно уточняющих вопросов",
  MODEL_ERROR: "Ошибка ИИ-модели",
  INVALID_JSON: "Ответ модели не в формате JSON",
  SCHEMA_MISMATCH: "Ответ модели не соответствует схеме",
};

/** `audit_runs.action` (docs/DATA_MODEL.md): the closed set of actions the
 * backend currently writes. */
const AUDIT_ACTION_LABELS: Record<string, string> = {
  "document.create": "Создание документа",
  "document.review": "Проверка документа",
  "ai.review": "Проверка текста без сохранения",
};

function labelOrRaw(map: Record<string, string>, value: string): string {
  return map[value] ?? value;
}

export const labelConfidence = (value: string): string => labelOrRaw(CONFIDENCE_LABELS, value);
export const labelReadiness = (value: string): string => labelOrRaw(READINESS_LABELS, value);
export const labelSeverity = (value: string): string => labelOrRaw(SEVERITY_LABELS, value);
export const labelCategory = (value: string): string => labelOrRaw(CATEGORY_LABELS, value);
export const labelDocumentStatus = (value: string): string => labelOrRaw(DOCUMENT_STATUS_LABELS, value);
export const labelAuditStatus = (value: string): string => labelOrRaw(AUDIT_STATUS_LABELS, value);
export const labelEntityType = (value: string): string => labelOrRaw(ENTITY_TYPE_LABELS, value);
export const labelNeedsReview = (value: boolean): string => NEEDS_REVIEW_LABELS[value ? "true" : "false"];
export const labelReasonCode = (code: string): string => labelOrRaw(REASON_CODE_LABELS, code);
export const labelAuditAction = (action: string): string => labelOrRaw(AUDIT_ACTION_LABELS, action);

/** CSS badge modifier class for an `AuditStatus` value — falls back to the
 * neutral badge for a future/unrecognized status rather than guessing a color. */
export function auditStatusBadgeClass(status: string): string {
  if (status === "success") return "badge-success";
  if (status === "needs_review") return "badge-warning";
  if (status === "error") return "badge-danger";
  return "badge-neutral";
}
