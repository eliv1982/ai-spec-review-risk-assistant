import { describe, expect, it } from "vitest";
import { parseDocumentResponse, parseFinalReview, parseReviewResponse } from "./validators";
import {
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
    it.each(REVIEW_CONFIDENCE_VALUES)("принимает допустимый confidence=%s", (confidence) => {
      expect(parseReviewResponse({ ...VALID_REVIEW, confidence }).confidence).toBe(confidence);
    });

    it("отклоняет недопустимый confidence на верхнем уровне ReviewResponse", () => {
      expect(() => parseReviewResponse({ ...VALID_REVIEW, confidence: "certain" })).toThrow();
    });

    it.each(REVIEW_READINESS_VALUES)("принимает допустимый readiness=%s", (readiness) => {
      expect(parseReviewResponse({ ...VALID_REVIEW, readiness }).readiness).toBe(readiness);
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
