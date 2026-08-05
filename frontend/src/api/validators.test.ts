import { describe, expect, it } from "vitest";
import {
  parseAuditRunResponse,
  parseDocumentResponse,
  parseFinalReview,
  parsePaginatedResponse,
  parseReviewResponse,
} from "./validators";
import {
  AUDIT_STATUS_VALUES,
  DOCUMENT_STATUS_VALUES,
  REVIEW_CONFIDENCE_VALUES,
  REVIEW_READINESS_VALUES,
  RISK_CATEGORY_VALUES,
  RISK_SEVERITY_VALUES,
} from "../types/api";

const VALID_FINAL_REVIEW = {
  summary: "Резюме.",
  risks: [],
  missing_requirements: [],
  contradictions: [],
  questions_to_client: [],
  acceptance_criteria: [],
  confidence: "low",
  document_readiness: "not_ready",
  needs_review: false,
  review_reason_codes: [],
};

describe("parseDocumentResponse", () => {
  it("принимает корректный DocumentResponse", () => {
    const value = {
      id: "doc-1",
      created_at: "2026-08-04T18:30:00Z",
      title: "Название",
      text: "Текст",
      status: "created",
    };
    expect(parseDocumentResponse(value)).toEqual(value);
  });

  it.each([[null], [undefined], ["string"], [42], [[]], [{}]])(
    "отклоняет некорректные данные верхнего уровня: %j",
    (value) => {
      expect(() => parseDocumentResponse(value)).toThrow();
    },
  );

  it("отклоняет ответ с полем неверного типа", () => {
    expect(() =>
      parseDocumentResponse({ id: 1, created_at: "x", title: "t", text: "x", status: "created" }),
    ).toThrow();
  });
});

describe("parseFinalReview", () => {
  it("принимает корректный FinalReview", () => {
    expect(parseFinalReview(VALID_FINAL_REVIEW)).toEqual(VALID_FINAL_REVIEW);
  });

  it("отклоняет FinalReview, если risks не массив", () => {
    expect(() => parseFinalReview({ ...VALID_FINAL_REVIEW, risks: "not-array" })).toThrow();
  });

  it("отклоняет contradiction, если evidence не массив строк", () => {
    expect(() =>
      parseFinalReview({
        ...VALID_FINAL_REVIEW,
        contradictions: [{ description: "d", evidence: [1, 2] }],
      }),
    ).toThrow();
  });

  it("отклоняет risk с evidence неправильного типа", () => {
    expect(() =>
      parseFinalReview({
        ...VALID_FINAL_REVIEW,
        risks: [{ severity: "low", category: "other", description: "d", evidence: 5 }],
      }),
    ).toThrow();
  });

  it("принимает risk с evidence=null", () => {
    const review = {
      ...VALID_FINAL_REVIEW,
      risks: [{ severity: "low", category: "other", description: "d", evidence: null }],
    };
    expect(parseFinalReview(review)).toEqual(review);
  });

  it("отклоняет needs_review не-boolean", () => {
    expect(() => parseFinalReview({ ...VALID_FINAL_REVIEW, needs_review: "true" })).toThrow();
  });
});

describe("parseReviewResponse", () => {
  const VALID_REVIEW = {
    id: "review-1",
    created_at: "2026-08-04T18:30:00Z",
    document_id: "doc-1",
    review_json: VALID_FINAL_REVIEW,
    confidence: "low",
    readiness: "not_ready",
    needs_review: false,
    reason_codes: [],
    error: null,
  };

  it("принимает корректный ReviewResponse", () => {
    expect(parseReviewResponse(VALID_REVIEW)).toEqual(VALID_REVIEW);
  });

  it("принимает ReviewResponse со строковым error", () => {
    const review = { ...VALID_REVIEW, error: "техническая ошибка" };
    expect(parseReviewResponse(review)).toEqual(review);
  });

  it("отклоняет review_json неправильной структуры", () => {
    expect(() => parseReviewResponse({ ...VALID_REVIEW, review_json: { bad: true } })).toThrow();
  });

  it("отклоняет reason_codes не-массив строк", () => {
    expect(() => parseReviewResponse({ ...VALID_REVIEW, reason_codes: [1, 2] })).toThrow();
  });

  it("отклоняет error неправильного типа", () => {
    expect(() => parseReviewResponse({ ...VALID_REVIEW, error: 42 })).toThrow();
  });

  it.each([[null], [undefined], ["string"], [[]]])("отклоняет данные верхнего уровня: %j", (value) => {
    expect(() => parseReviewResponse(value)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// Closed backend enum validation (backend/app/enums.py is the source of
// truth). Every field below must reject a value outside the actual backend
// enum and accept every value the backend actually declares — confirming
// the runtime validator and the backend enum stay in sync, not just that
// *some* string passes.
// ---------------------------------------------------------------------------

describe("closed enum validation", () => {
  const VALID_DOCUMENT = {
    id: "doc-1",
    created_at: "2026-08-04T18:30:00Z",
    title: "Название",
    text: "Текст",
    status: "created",
  };

  const VALID_REVIEW = {
    id: "review-1",
    created_at: "2026-08-04T18:30:00Z",
    document_id: "doc-1",
    review_json: VALID_FINAL_REVIEW,
    confidence: "low",
    readiness: "not_ready",
    needs_review: false,
    reason_codes: [],
    error: null,
  };

  describe("DocumentResponse.status", () => {
    it.each(DOCUMENT_STATUS_VALUES)("принимает допустимое значение %s", (status) => {
      expect(parseDocumentResponse({ ...VALID_DOCUMENT, status }).status).toBe(status);
    });

    it.each(["pending", "PENDING", "Created", ""])("отклоняет недопустимое значение %j", (status) => {
      expect(() => parseDocumentResponse({ ...VALID_DOCUMENT, status })).toThrow();
    });
  });

  describe("ReviewResponse.confidence / readiness", () => {
    // The cross-field invariant (ReviewResponse.confidence === review_json.confidence,
    // etc.) requires the nested review_json to be kept consistent with
    // whichever top-level value is under test here.
    it.each(REVIEW_CONFIDENCE_VALUES)("принимает допустимый confidence=%s", (confidence) => {
      const review = { ...VALID_REVIEW, confidence, review_json: { ...VALID_FINAL_REVIEW, confidence } };
      expect(parseReviewResponse(review).confidence).toBe(confidence);
    });

    it("отклоняет недопустимый confidence на верхнем уровне ReviewResponse", () => {
      expect(() => parseReviewResponse({ ...VALID_REVIEW, confidence: "certain" })).toThrow();
    });

    it.each(REVIEW_READINESS_VALUES)("принимает допустимый readiness=%s", (readiness) => {
      const review = {
        ...VALID_REVIEW,
        readiness,
        review_json: { ...VALID_FINAL_REVIEW, document_readiness: readiness },
      };
      expect(parseReviewResponse(review).readiness).toBe(readiness);
    });

    it("отклоняет недопустимый readiness на верхнем уровне ReviewResponse", () => {
      expect(() => parseReviewResponse({ ...VALID_REVIEW, readiness: "almost_ready" })).toThrow();
    });
  });

  describe("FinalReview.confidence / document_readiness", () => {
    it.each(REVIEW_CONFIDENCE_VALUES)("принимает допустимый confidence=%s", (confidence) => {
      expect(parseFinalReview({ ...VALID_FINAL_REVIEW, confidence }).confidence).toBe(confidence);
    });

    it("отклоняет недопустимый confidence во вложенном FinalReview", () => {
      expect(() => parseFinalReview({ ...VALID_FINAL_REVIEW, confidence: "certain" })).toThrow();
    });

    it.each(REVIEW_READINESS_VALUES)("принимает допустимый document_readiness=%s", (document_readiness) => {
      expect(parseFinalReview({ ...VALID_FINAL_REVIEW, document_readiness }).document_readiness).toBe(
        document_readiness,
      );
    });

    it("отклоняет недопустимый document_readiness во вложенном FinalReview", () => {
      expect(() =>
        parseFinalReview({ ...VALID_FINAL_REVIEW, document_readiness: "almost_ready" }),
      ).toThrow();
    });
  });

  describe("Risk.severity / Risk.category", () => {
    it.each(RISK_SEVERITY_VALUES)("принимает допустимый severity=%s", (severity) => {
      const review = {
        ...VALID_FINAL_REVIEW,
        risks: [{ severity, category: "other", description: "d", evidence: null }],
      };
      expect(parseFinalReview(review).risks[0].severity).toBe(severity);
    });

    it("отклоняет недопустимый severity элемента risks", () => {
      expect(() =>
        parseFinalReview({
          ...VALID_FINAL_REVIEW,
          risks: [{ severity: "critical", category: "other", description: "d", evidence: null }],
        }),
      ).toThrow();
    });

    it.each(RISK_CATEGORY_VALUES)("принимает допустимую category=%s", (category) => {
      const review = {
        ...VALID_FINAL_REVIEW,
        risks: [{ severity: "low", category, description: "d", evidence: null }],
      };
      expect(parseFinalReview(review).risks[0].category).toBe(category);
    });

    it("отклоняет недопустимую category элемента risks", () => {
      expect(() =>
        parseFinalReview({
          ...VALID_FINAL_REVIEW,
          risks: [{ severity: "low", category: "billing", description: "d", evidence: null }],
        }),
      ).toThrow();
    });
  });

  describe("MissingRequirement.category", () => {
    it.each(RISK_CATEGORY_VALUES)("принимает допустимую category=%s", (category) => {
      const review = {
        ...VALID_FINAL_REVIEW,
        missing_requirements: [{ category, description: "d" }],
      };
      expect(parseFinalReview(review).missing_requirements[0].category).toBe(category);
    });

    it("отклоняет недопустимую category элемента missing_requirements", () => {
      expect(() =>
        parseFinalReview({
          ...VALID_FINAL_REVIEW,
          missing_requirements: [{ category: "billing", description: "d" }],
        }),
      ).toThrow();
    });
  });

  it("review_reason_codes и reason_codes остаются forward-compatible (неизвестный код не отклоняется)", () => {
    const review = {
      ...VALID_REVIEW,
      reason_codes: ["FUTURE_UNKNOWN_CODE"],
      review_json: { ...VALID_FINAL_REVIEW, review_reason_codes: ["FUTURE_UNKNOWN_CODE"] },
    };
    const parsed = parseReviewResponse(review);
    expect(parsed.reason_codes).toEqual(["FUTURE_UNKNOWN_CODE"]);
    expect(parsed.review_json.review_reason_codes).toEqual(["FUTURE_UNKNOWN_CODE"]);
  });
});

describe("parseAuditRunResponse", () => {
  const VALID_AUDIT_RUN = {
    id: "audit-1",
    created_at: "2026-08-04T18:30:00Z",
    action: "document.review",
    entity_type: "review",
    entity_id: "review-1",
    input_json: { document_id: "doc-1" },
    output_json: { review_id: "review-1" },
    status: "needs_review",
    error: null,
    duration_ms: 42,
  };

  it("принимает корректный AuditRunResponse", () => {
    expect(parseAuditRunResponse(VALID_AUDIT_RUN)).toEqual(VALID_AUDIT_RUN);
  });

  it("принимает null для entity_type/entity_id/input_json/output_json/error", () => {
    const value = {
      ...VALID_AUDIT_RUN,
      entity_type: null,
      entity_id: null,
      input_json: null,
      output_json: null,
      error: null,
      status: "success",
    };
    expect(parseAuditRunResponse(value)).toEqual(value);
  });

  it("принимает status=error со строковым error", () => {
    const value = { ...VALID_AUDIT_RUN, status: "error", error: "сбой модели" };
    expect(parseAuditRunResponse(value)).toEqual(value);
  });

  it.each(AUDIT_STATUS_VALUES)("принимает допустимый status=%s", (status) => {
    // status="error" requires a non-empty error; "success"/"needs_review" require null.
    const value = { ...VALID_AUDIT_RUN, status, error: status === "error" ? "сбой" : null };
    expect(parseAuditRunResponse(value).status).toBe(status);
  });

  it("отклоняет недопустимое значение status", () => {
    expect(() => parseAuditRunResponse({ ...VALID_AUDIT_RUN, status: "pending" })).toThrow();
  });

  it("отклоняет input_json, если это массив, а не объект", () => {
    expect(() => parseAuditRunResponse({ ...VALID_AUDIT_RUN, input_json: [1, 2, 3] })).toThrow();
  });

  it("отклоняет duration_ms не-числового типа", () => {
    expect(() => parseAuditRunResponse({ ...VALID_AUDIT_RUN, duration_ms: "42" })).toThrow();
  });

  it.each([[null], [undefined], ["string"], [[]]])("отклоняет данные верхнего уровня: %j", (value) => {
    expect(() => parseAuditRunResponse(value)).toThrow();
  });
});

describe("parsePaginatedResponse", () => {
  it("валидирует items через переданный parseItem и сохраняет total/limit/offset", () => {
    const raw = {
      items: [
        { id: "doc-1", created_at: "2026-08-04T18:30:00Z", title: "t", text: "x", status: "created" },
      ],
      total: 5,
      limit: 20,
      offset: 0,
    };
    const parsed = parsePaginatedResponse(raw, parseDocumentResponse, "Test");
    expect(parsed.total).toBe(5);
    expect(parsed.limit).toBe(20);
    expect(parsed.offset).toBe(0);
    expect(parsed.items).toEqual(raw.items);
  });

  it("отклоняет envelope без items-массива", () => {
    expect(() =>
      parsePaginatedResponse({ total: 0, limit: 20, offset: 0 }, parseDocumentResponse, "Test"),
    ).toThrow();
  });

  it("отклоняет, если один из элементов items не проходит parseItem", () => {
    const raw = {
      items: [{ id: "doc-1", created_at: "x", title: "t", text: "x", status: "bogus" }],
      total: 1,
      limit: 20,
      offset: 0,
    };
    expect(() => parsePaginatedResponse(raw, parseDocumentResponse, "Test")).toThrow();
  });

  it.each(["total", "limit", "offset"])("отклоняет нечисловое значение %s", (field) => {
    const raw = { items: [], total: 0, limit: 20, offset: 0, [field]: "not-a-number" };
    expect(() => parsePaginatedResponse(raw, parseDocumentResponse, "Test")).toThrow();
  });

  it.each([[null], [undefined], ["string"], [[]]])("отклоняет данные верхнего уровня: %j", (value) => {
    expect(() => parsePaginatedResponse(value, parseDocumentResponse, "Test")).toThrow();
  });

  // -------------------------------------------------------------------------
  // Integer/range validation (docs/API_CONTRACTS.md, "Pagination"):
  // total/offset >= 0, limit >= 1, all finite integers — never negative,
  // fractional, NaN, Infinity, a string, or null.
  // -------------------------------------------------------------------------

  describe("total: диапазон и тип", () => {
    it.each([-1, 1.5, NaN, Infinity, -Infinity, "5", null])("отклоняет total=%p", (total) => {
      const raw = { items: [], total, limit: 20, offset: 0 };
      expect(() => parsePaginatedResponse(raw, parseDocumentResponse, "Test")).toThrow();
    });

    it.each([0, 1, 1000])("принимает total=%p", (total) => {
      const raw = { items: [], total, limit: 20, offset: 0 };
      expect(parsePaginatedResponse(raw, parseDocumentResponse, "Test").total).toBe(total);
    });
  });

  describe("offset: диапазон и тип", () => {
    it.each([-1, 1.5, NaN, Infinity, -Infinity, "5", null])("отклоняет offset=%p", (offset) => {
      const raw = { items: [], total: 0, limit: 20, offset };
      expect(() => parsePaginatedResponse(raw, parseDocumentResponse, "Test")).toThrow();
    });

    it.each([0, 1, 1000])("принимает offset=%p", (offset) => {
      const raw = { items: [], total: offset + 1, limit: 20, offset };
      expect(parsePaginatedResponse(raw, parseDocumentResponse, "Test").offset).toBe(offset);
    });
  });

  describe("limit: диапазон и тип", () => {
    it.each([0, -1, 1.5, NaN, Infinity, -Infinity, "5", null])("отклоняет limit=%p", (limit) => {
      const raw = { items: [], total: 0, limit, offset: 0 };
      expect(() => parsePaginatedResponse(raw, parseDocumentResponse, "Test")).toThrow();
    });

    it.each([1, 20, 100])("принимает limit=%p", (limit) => {
      const raw = { items: [], total: 0, limit, offset: 0 };
      expect(parsePaginatedResponse(raw, parseDocumentResponse, "Test").limit).toBe(limit);
    });
  });
});

describe("AuditRunResponse.duration_ms: диапазон и тип", () => {
  const VALID_AUDIT_RUN = {
    id: "audit-1",
    created_at: "2026-08-04T18:30:00Z",
    action: "document.review",
    entity_type: "review",
    entity_id: "review-1",
    input_json: null,
    output_json: null,
    status: "success",
    error: null,
    duration_ms: 42,
  };

  it.each([-1, 1.5, NaN, Infinity, -Infinity, "42"])("отклоняет duration_ms=%p", (duration_ms) => {
    expect(() => parseAuditRunResponse({ ...VALID_AUDIT_RUN, duration_ms })).toThrow();
  });

  // Not nullable per the backend schema (backend/app/schemas/audit.py::AuditRunResponse.duration_ms: int) —
  // confirmed against the actual schema, not assumed; no null-accepting branch is added.
  it("отклоняет duration_ms=null (backend не объявляет это поле nullable)", () => {
    expect(() => parseAuditRunResponse({ ...VALID_AUDIT_RUN, duration_ms: null })).toThrow();
  });

  it.each([0, 1, 999999])("принимает duration_ms=%p", (duration_ms) => {
    expect(parseAuditRunResponse({ ...VALID_AUDIT_RUN, duration_ms }).duration_ms).toBe(duration_ms);
  });
});

describe("ReviewResponse cross-field invariants", () => {
  const CONSISTENT_FINAL_REVIEW = {
    ...VALID_FINAL_REVIEW,
    needs_review: true,
    review_reason_codes: ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
  };

  const CONSISTENT_REVIEW = {
    id: "review-1",
    created_at: "2026-08-04T18:30:00Z",
    document_id: "doc-1",
    review_json: CONSISTENT_FINAL_REVIEW,
    confidence: "low",
    readiness: "not_ready",
    needs_review: true,
    reason_codes: ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
    error: null,
  };

  it("принимает полностью согласованный ReviewResponse", () => {
    expect(parseReviewResponse(CONSISTENT_REVIEW)).toEqual(CONSISTENT_REVIEW);
  });

  it("отклоняет несовпадение needs_review (верхний уровень vs review_json)", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      review_json: { ...CONSISTENT_FINAL_REVIEW, needs_review: false },
    };
    expect(() => parseReviewResponse(review)).toThrow(/needs_review/);
  });

  it("отклоняет несовпадение confidence (верхний уровень vs review_json)", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      review_json: { ...CONSISTENT_FINAL_REVIEW, confidence: "high" },
    };
    expect(() => parseReviewResponse(review)).toThrow(/confidence/);
  });

  it("отклоняет несовпадение readiness/document_readiness (верхний уровень vs review_json)", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      review_json: { ...CONSISTENT_FINAL_REVIEW, document_readiness: "ready" },
    };
    expect(() => parseReviewResponse(review)).toThrow(/readiness/);
  });

  it("отклоняет несовпадение значений reason_codes / review_reason_codes", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      reason_codes: ["LOW_CONFIDENCE", "TOO_VAGUE_INPUT"],
    };
    expect(() => parseReviewResponse(review)).toThrow(/reason_codes/);
  });

  it("отклоняет несовпадение порядка reason_codes / review_reason_codes", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      reason_codes: ["MISSING_ACCEPTANCE_CRITERIA", "LOW_CONFIDENCE"],
    };
    expect(() => parseReviewResponse(review)).toThrow(/reason_codes/);
  });

  it("отклоняет несовпадение длины reason_codes / review_reason_codes", () => {
    const review = {
      ...CONSISTENT_REVIEW,
      reason_codes: ["LOW_CONFIDENCE"],
    };
    expect(() => parseReviewResponse(review)).toThrow(/reason_codes/);
  });
});

describe("AuditRun error invariants (status/error)", () => {
  const BASE_AUDIT_RUN = {
    id: "audit-1",
    created_at: "2026-08-04T18:30:00Z",
    action: "document.review",
    entity_type: null,
    entity_id: null,
    input_json: null,
    output_json: null,
    duration_ms: 10,
  };

  it("принимает status=error с непустым error", () => {
    const value = { ...BASE_AUDIT_RUN, status: "error", error: "сбой модели" };
    expect(parseAuditRunResponse(value).error).toBe("сбой модели");
  });

  it("отклоняет status=error с error=null", () => {
    expect(() => parseAuditRunResponse({ ...BASE_AUDIT_RUN, status: "error", error: null })).toThrow();
  });

  it("отклоняет status=error с error=''", () => {
    expect(() => parseAuditRunResponse({ ...BASE_AUDIT_RUN, status: "error", error: "" })).toThrow();
  });

  it("отклоняет status=error с error='   ' (только пробелы)", () => {
    expect(() => parseAuditRunResponse({ ...BASE_AUDIT_RUN, status: "error", error: "   " })).toThrow();
  });

  it("принимает status=success с error=null", () => {
    const value = { ...BASE_AUDIT_RUN, status: "success", error: null };
    expect(parseAuditRunResponse(value).status).toBe("success");
  });

  it("отклоняет status=success с непустым error", () => {
    expect(() =>
      parseAuditRunResponse({ ...BASE_AUDIT_RUN, status: "success", error: "неожиданная ошибка" }),
    ).toThrow();
  });

  it("принимает status=needs_review с error=null", () => {
    const value = { ...BASE_AUDIT_RUN, status: "needs_review", error: null };
    expect(parseAuditRunResponse(value).status).toBe("needs_review");
  });

  it("отклоняет status=needs_review с непустым error (needs_review — не техническая ошибка)", () => {
    expect(() =>
      parseAuditRunResponse({ ...BASE_AUDIT_RUN, status: "needs_review", error: "не должно быть здесь" }),
    ).toThrow();
  });
});
