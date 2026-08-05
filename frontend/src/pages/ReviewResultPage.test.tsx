import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { ReviewResultPage } from "./ReviewResultPage";
import { explainReasonCode } from "../utils/reasonCodes";
import type { FinalReview, ReviewResponse } from "../types/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function flushMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function renderReviewPage(reviewId = "review-1") {
  return render(
    <MemoryRouter initialEntries={[`/reviews/${reviewId}`]}>
      <Routes>
        <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function NavigateButton({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(to)}>
      Перейти на {to}
    </button>
  );
}

const BASE_FINAL_REVIEW: Omit<FinalReview, "needs_review" | "review_reason_codes"> = {
  summary: "Резюме проверки для теста.",
  risks: [],
  missing_requirements: [],
  contradictions: [],
  questions_to_client: [],
  acceptance_criteria: [],
  confidence: "low",
  document_readiness: "not_ready",
};

function buildReview(overrides: {
  id?: string;
  needs_review: boolean;
  reason_codes: string[];
}): ReviewResponse {
  const id = overrides.id ?? "review-1";
  return {
    id,
    created_at: "2026-08-04T18:30:00Z",
    document_id: "doc-1",
    review_json: {
      ...BASE_FINAL_REVIEW,
      needs_review: overrides.needs_review,
      review_reason_codes: overrides.reason_codes,
    },
    confidence: "low",
    readiness: "not_ready",
    needs_review: overrides.needs_review,
    reason_codes: overrides.reason_codes,
    error: null,
  };
}

describe("ReviewResultPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отображает блок «Требуется ручная проверка» и коды причин при needs_review=true", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        buildReview({
          needs_review: true,
          reason_codes: ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
        }),
      ),
    );

    renderReviewPage();

    expect(await screen.findByText("Требуется ручная проверка")).toBeInTheDocument();
    expect(screen.getByText("LOW_CONFIDENCE")).toBeInTheDocument();
    expect(screen.getByText("MISSING_ACCEPTANCE_CRITERIA")).toBeInTheDocument();
    expect(screen.getByText(explainReasonCode("LOW_CONFIDENCE")!)).toBeInTheDocument();
    expect(screen.getByText(explainReasonCode("MISSING_ACCEPTANCE_CRITERIA")!)).toBeInTheDocument();
  });

  it("корректно отображает спокойный статус при needs_review=false", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(buildReview({ needs_review: false, reason_codes: [] })),
    );

    renderReviewPage();

    expect(await screen.findByText("Ручная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByText("Требуется ручная проверка")).not.toBeInTheDocument();
  });

  it("показывает русскоязычную ошибку API при сбое загрузки проверки", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500),
    );

    renderReviewPage();

    expect(await screen.findByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText(/не удалось загрузить проверку/i)).toBeInTheDocument();
  });

  it("показывает понятное сообщение, если проверка не найдена (404)", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "Проверка не найдена" }, 404),
    );

    renderReviewPage("missing-review");

    expect(await screen.findByRole("heading", { name: /проверка не найдена/i })).toBeInTheDocument();
  });

  it("не ломается при пустых массивах и показывает нейтральные формулировки", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(buildReview({ needs_review: false, reason_codes: [] })),
    );

    renderReviewPage();

    expect(await screen.findByText("Резюме проверки для теста.")).toBeInTheDocument();
    expect(screen.getByText("В результате проверки риски не указаны.")).toBeInTheDocument();
    expect(
      screen.getByText("В результате проверки недостающие требования не указаны."),
    ).toBeInTheDocument();
    expect(screen.getByText("В результате проверки противоречия не указаны.")).toBeInTheDocument();
    expect(screen.getByText("В результате проверки уточняющие вопросы не указаны.")).toBeInTheDocument();
    expect(screen.getByText("В результате проверки критерии приёмки не указаны.")).toBeInTheDocument();
    expect(screen.queryByText(/не обнаружены/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/не сформированы/i)).not.toBeInTheDocument();
  });

  it("безопасно отображает неизвестный reason code без падения интерфейса", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(buildReview({ needs_review: true, reason_codes: ["FUTURE_UNKNOWN_CODE"] })),
    );

    renderReviewPage();

    expect(await screen.findByText("FUTURE_UNKNOWN_CODE")).toBeInTheDocument();
    expect(screen.getByText("Неизвестный технический код причины.")).toBeInTheDocument();
  });

  it("при safe fallback (needs_review=true, пустые массивы) не утверждает «не обнаружено»", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(buildReview({ needs_review: true, reason_codes: ["MODEL_ERROR"] })),
    );

    renderReviewPage();

    expect(await screen.findByText("Требуется ручная проверка")).toBeInTheDocument();
    expect(screen.getByText("MODEL_ERROR")).toBeInTheDocument();
    expect(screen.getByText("В результате проверки риски не указаны.")).toBeInTheDocument();
    expect(screen.queryByText(/не обнаружены/i)).not.toBeInTheDocument();
  });

  it("для 422 с type=uuid_parsing показывает русское сообщение без английского msg", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        {
          detail: [
            {
              loc: ["path", "review_id"],
              msg: "Input should be a valid UUID, invalid character: expected an optional prefix",
              type: "uuid_parsing",
            },
          ],
        },
        422,
      ),
    );

    renderReviewPage("not-a-valid-uuid");

    expect(await screen.findByText("Некорректный идентификатор проверки.")).toBeInTheDocument();
    expect(screen.queryByText(/valid UUID/i)).not.toBeInTheDocument();
  });

  it("показывает контролируемую ошибку при пустом теле успешного ответа", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(new Response("", { status: 200 }));

    renderReviewPage();

    expect(
      await screen.findByText(
        "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
      ),
    ).toBeInTheDocument();
  });

  it("показывает контролируемую ошибку при non-JSON успешном ответе", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response("<html>oops</html>", { status: 200, headers: { "Content-Type": "text/html" } }),
    );

    renderReviewPage();

    expect(
      await screen.findByText(
        "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
      ),
    ).toBeInTheDocument();
  });

  it("показывает контролируемую ошибку при null или структурно неверном JSON", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(null, 200));

    renderReviewPage();

    expect(
      await screen.findByText(
        "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
      ),
    ).toBeInTheDocument();
  });

  it("не показывает устаревший ответ при смене reviewId (race condition)", async () => {
    const deferredReview1 = createDeferred<Response>();
    const deferredReview2 = createDeferred<Response>();

    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/reviews/review-1")) return deferredReview1.promise;
      if (url.endsWith("/reviews/review-2")) return deferredReview2.promise;
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText(/загружаем результат проверки/i);

    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    // The newer request (review-2) resolves first.
    deferredReview2.resolve(
      jsonResponse(buildReview({ id: "review-2", needs_review: false, reason_codes: [] })),
    );
    await screen.findByText("review-2");

    // The superseded request (review-1) resolves late; it must be ignored.
    deferredReview1.resolve(
      jsonResponse(buildReview({ id: "review-1", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] })),
    );
    await flushMicrotasks();

    expect(screen.getByText("review-2")).toBeInTheDocument();
    expect(screen.queryByText("review-1")).not.toBeInTheDocument();
    expect(screen.getByText("Ручная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByText("Требуется ручная проверка")).not.toBeInTheDocument();
  });

  it("не показывает error banner для устаревшего запроса, который поздно завершается ошибкой", async () => {
    const deferredReview1 = createDeferred<Response>();
    const deferredReview2 = createDeferred<Response>();

    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/reviews/review-1")) return deferredReview1.promise;
      if (url.endsWith("/reviews/review-2")) return deferredReview2.promise;
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText(/загружаем результат проверки/i);
    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    deferredReview2.resolve(
      jsonResponse(buildReview({ id: "review-2", needs_review: false, reason_codes: [] })),
    );
    await screen.findByText("review-2");

    // The superseded review-1 request finishes late — with a real error this
    // time, not a stale success. It must still be ignored.
    deferredReview1.reject(new Error("boom: stale network failure"));
    await flushMicrotasks();

    expect(screen.getByText("review-2")).toBeInTheDocument();
    expect(screen.getByText("Ручная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/не удалось загрузить проверку/i)).not.toBeInTheDocument();
  });

  it("cleanup при unmount реально отменяет запрос (signal.aborted) и игнорирует поздний ответ", async () => {
    const deferred = createDeferred<Response>();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockReturnValueOnce(deferred.promise);

    const { unmount, container } = renderReviewPage();
    await screen.findByText(/загружаем результат проверки/i);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const capturedSignal = (init as RequestInit).signal as AbortSignal;
    expect(capturedSignal.aborted).toBe(false);

    unmount();

    // Cleanup calls `controller.abort()` synchronously — observable
    // independent of whether the deferred promise ever settles.
    expect(capturedSignal.aborted).toBe(true);

    const htmlAfterUnmount = container.innerHTML;

    // Both a late success and a late failure must be no-ops post-unmount:
    // no navigation, no error banner, no DOM update:
    deferred.resolve(jsonResponse(buildReview({ needs_review: false, reason_codes: [] })));
    await flushMicrotasks();

    expect(container.innerHTML).toBe(htmlAfterUnmount);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("под React.StrictMode не показывает ошибку и корректно завершает загрузку", async () => {
    // A fresh Response per call: StrictMode's dev-only double effect invocation
    // means fetch may run twice, and a Response body can only be read once.
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(() =>
      Promise.resolve(jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))),
    );

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/reviews/review-1"]}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    expect(await screen.findByText("Ручная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
