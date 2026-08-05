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

const SEVERITY_LABELS: Record<string, string> = {
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
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
  reviewed: "Проверен",
  review_failed: "Проверка не выполнена",
};

const AUDIT_STATUS_LABELS: Record<string, string> = {
  success: "Успешно",
  needs_review: "Требуется ручная проверка",
  error: "Техническая ошибка",
};

/** `audit_runs.entity_type` (docs/DATA_MODEL.md, "Entity mapping"): the only
 * two values the backend ever writes are `document` and `review`. */
const ENTITY_TYPE_LABELS: Record<string, string> = {
  document: "Документ",
  review: "Проверка",
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

/** CSS badge modifier class for an `AuditStatus` value — falls back to the
 * neutral badge for a future/unrecognized status rather than guessing a color. */
export function auditStatusBadgeClass(status: string): string {
  if (status === "success") return "badge-success";
  if (status === "needs_review") return "badge-warning";
  if (status === "error") return "badge-danger";
  return "badge-neutral";
}
