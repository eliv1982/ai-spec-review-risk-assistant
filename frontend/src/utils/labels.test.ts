import { describe, expect, it } from "vitest";
import {
  auditStatusBadgeClass,
  labelAuditAction,
  labelAuditStatus,
  labelConfidence,
  labelDocumentStatus,
  labelEntityType,
  labelNeedsReview,
  labelReadiness,
  labelReasonCode,
  labelSeverity,
} from "./labels";

describe("labelSeverity", () => {
  it("uses masculine adjective forms to agree with «Уровень риска»", () => {
    expect(labelSeverity("high")).toBe("Высокий");
    expect(labelSeverity("medium")).toBe("Средний");
    expect(labelSeverity("low")).toBe("Низкий");
  });
});

describe("labelConfidence", () => {
  it("uses feminine adjective forms to agree with «Уверенность»", () => {
    expect(labelConfidence("high")).toBe("Высокая");
    expect(labelConfidence("medium")).toBe("Средняя");
    expect(labelConfidence("low")).toBe("Низкая");
  });
});

describe("labelDocumentStatus", () => {
  it("maps the reviewed workflow status to «Проверка завершена»", () => {
    expect(labelDocumentStatus("reviewed")).toBe("Проверка завершена");
  });

  it("maps the fallback-failure workflow status to «Проверка не выполнена»", () => {
    expect(labelDocumentStatus("review_failed")).toBe("Проверка не выполнена");
  });

  it("never conflates the workflow status with review readiness wording", () => {
    expect(labelDocumentStatus("reviewed")).not.toBe(labelReadiness("ready"));
  });
});

describe("labelNeedsReview", () => {
  it("labels true as needing expert review", () => {
    expect(labelNeedsReview(true)).toBe("Нужна экспертная проверка");
  });

  it("labels false as not needing expert review", () => {
    expect(labelNeedsReview(false)).toBe("Экспертная проверка не требуется");
  });
});

describe("labelReasonCode", () => {
  it("maps every documented reason code to its short Russian label", () => {
    expect(labelReasonCode("LOW_CONFIDENCE")).toBe("Низкая уверенность анализа");
    expect(labelReasonCode("TOO_VAGUE_INPUT")).toBe("Недостаточно конкретный документ");
    expect(labelReasonCode("CONTRADICTORY_INPUT")).toBe("Обнаружены противоречия");
    expect(labelReasonCode("MISSING_ACCEPTANCE_CRITERIA")).toBe("Не хватает критериев приёмки");
    expect(labelReasonCode("INSUFFICIENT_QUESTIONS")).toBe("Недостаточно уточняющих вопросов");
    expect(labelReasonCode("MODEL_ERROR")).toBe("Ошибка ИИ-модели");
  });

  it("falls back to the raw code for an unrecognized future code", () => {
    expect(labelReasonCode("FUTURE_UNKNOWN_CODE")).toBe("FUTURE_UNKNOWN_CODE");
  });
});

describe("labelAuditAction", () => {
  it("maps every documented audit action to a Russian label", () => {
    expect(labelAuditAction("document.create")).toBe("Создание документа");
    expect(labelAuditAction("document.review")).toBe("Проверка документа");
    expect(labelAuditAction("ai.review")).toBe("Проверка текста без сохранения");
  });

  it("falls back to the raw action for an unrecognized future action", () => {
    expect(labelAuditAction("future.action")).toBe("future.action");
  });
});

describe("labelEntityType", () => {
  it("maps the closed entity type set", () => {
    expect(labelEntityType("document")).toBe("Документ");
    expect(labelEntityType("review")).toBe("Проверка");
  });
});

describe("labelAuditStatus / auditStatusBadgeClass", () => {
  it("maps needs_review audit status to the shared expert-review wording", () => {
    expect(labelAuditStatus("needs_review")).toBe("Нужна экспертная проверка");
    expect(labelAuditStatus("needs_review")).toBe(labelNeedsReview(true));
  });

  it("maps success/error audit status", () => {
    expect(labelAuditStatus("success")).toBe("Успешно");
    expect(labelAuditStatus("error")).toBe("Техническая ошибка");
  });

  it("assigns a distinct badge class per status", () => {
    expect(auditStatusBadgeClass("success")).toBe("badge-success");
    expect(auditStatusBadgeClass("needs_review")).toBe("badge-warning");
    expect(auditStatusBadgeClass("error")).toBe("badge-danger");
    expect(auditStatusBadgeClass("future-status")).toBe("badge-neutral");
  });
});
