import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { ReviewResultRoute } from "./ReviewResultPage";
import { explainReasonCode } from "../utils/reasonCodes";
import { labelReasonCode } from "../utils/labels";
import { formatDateTime } from "../utils/formatting";
import type { DocumentResponse, FinalReview, ReviewResponse } from "../types/api";

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

/** Routes a stubbed `fetch` by matching the end of the request URL against
 * `routes` keys, in insertion order. Any unmatched URL rejects loudly rather
 * than hanging, so a missing mock branch fails the test instead of timing out. */
function routedFetch(routes: Array<[string, () => Response | Promise<Response>]>) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    for (const [suffix, handler] of routes) {
      if (url.endsWith(suffix)) return Promise.resolve(handler());
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
}

function renderReviewPage(reviewId = "review-1") {
  return render(
    <MemoryRouter initialEntries={[`/reviews/${reviewId}`]}>
      <Routes>
        <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
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
  documentId?: string;
  needs_review: boolean;
  reason_codes: string[];
}): ReviewResponse {
  const id = overrides.id ?? "review-1";
  return {
    id,
    created_at: "2026-08-04T18:30:00Z",
    document_id: overrides.documentId ?? "doc-1",
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

function buildDocument(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "doc-1",
    created_at: "2026-08-04T18:00:00Z",
    title: "Название документа для теста",
    text: "Полный исходный текст документа для теста.",
    status: "reviewed",
    ...overrides,
  };
}

describe("ReviewResultPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отображает блок «Нужна экспертная проверка» и коды причин при needs_review=true", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        [
          "/reviews/review-1",
          () =>
            jsonResponse(
              buildReview({ needs_review: true, reason_codes: ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"] }),
            ),
        ],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Нужна экспертная проверка")).toBeInTheDocument();
    expect(screen.getByText(labelReasonCode("LOW_CONFIDENCE"))).toBeInTheDocument();
    expect(screen.getByText(labelReasonCode("MISSING_ACCEPTANCE_CRITERIA"))).toBeInTheDocument();
    expect(screen.getByText(explainReasonCode("LOW_CONFIDENCE")!)).toBeInTheDocument();
    expect(screen.getByText(explainReasonCode("MISSING_ACCEPTANCE_CRITERIA")!)).toBeInTheDocument();
    expect(screen.queryByText("LOW_CONFIDENCE")).not.toBeInTheDocument();
    expect(screen.queryByText("MISSING_ACCEPTANCE_CRITERIA")).not.toBeInTheDocument();
  });

  it("корректно отображает спокойный статус при needs_review=false", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByText("Нужна экспертная проверка")).not.toBeInTheDocument();
  });

  it("подключает бизнес-labels к данным ревью: Дата проверки, Статус готовности, Уверенность анализа, Краткое заключение, статус документа", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Краткое заключение")).toBeInTheDocument();
    expect(screen.getByText("Резюме проверки для теста.")).toBeInTheDocument();

    expect(screen.getByText("Дата проверки")).toBeInTheDocument();
    expect(screen.getByText(formatDateTime("2026-08-04T18:30:00Z"))).toBeInTheDocument();

    // buildReview() fixes confidence="low"/readiness="not_ready" — proves the
    // page renders the localized label, not the raw enum value.
    expect(screen.getByText("Статус готовности")).toBeInTheDocument();
    expect(screen.getByText("Не готов")).toBeInTheDocument();
    expect(screen.queryByText("not_ready")).not.toBeInTheDocument();

    expect(screen.getByText("Уверенность анализа")).toBeInTheDocument();
    expect(screen.getByText("Низкая")).toBeInTheDocument();
    expect(screen.queryByText("low")).not.toBeInTheDocument();

    // Document workflow status is a distinct field from review readiness —
    // buildDocument() defaults to status "reviewed", which must render as
    // the business-facing "Проверка завершена", never the raw enum value.
    expect(await screen.findByText("Проверка завершена")).toBeInTheDocument();
    expect(screen.getByText("Статус документа")).toBeInTheDocument();
    expect(screen.queryByText("reviewed")).not.toBeInTheDocument();
  });

  it("не переиспользует одно и то же грамматическое согласование для уровня риска и уверенности анализа", async () => {
    const review: ReviewResponse = {
      id: "review-1",
      created_at: "2026-08-04T18:30:00Z",
      document_id: "doc-1",
      review_json: {
        ...BASE_FINAL_REVIEW,
        confidence: "high",
        risks: [
          {
            severity: "high",
            category: "security",
            description: "Описание риска для теста.",
            evidence: null,
          },
        ],
        needs_review: false,
        review_reason_codes: [],
      },
      confidence: "high",
      readiness: "not_ready",
      needs_review: false,
      reason_codes: [],
      error: null,
    };

    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(review)],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    // Risk severity uses masculine adjective agreement ("Уровень риска: Высокий").
    expect(await screen.findByText(/Уровень риска:\s*Высокий/)).toBeInTheDocument();

    // Review confidence uses feminine adjective agreement ("Высокая") — a
    // distinct top-level meta field from risk severity, not the same value
    // rendered twice through one shared mapping helper.
    expect(screen.getByText("Уверенность анализа")).toBeInTheDocument();
    expect(screen.getByText("Высокая")).toBeInTheDocument();

    // Catches accidental reuse of one grammatical mapping for both fields:
    // severity must never render the feminine form, confidence must never
    // render the bare masculine form.
    expect(screen.queryByText(/Уровень риска:\s*Высокая/)).not.toBeInTheDocument();
    expect(screen.queryByText("Высокий")).not.toBeInTheDocument();
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
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Резюме проверки для теста.")).toBeInTheDocument();
    expect(screen.getByText("Риски не выявлены.")).toBeInTheDocument();
    expect(screen.getByText("Недостающие требования не выявлены.")).toBeInTheDocument();
    expect(screen.getByText("Противоречия не выявлены.")).toBeInTheDocument();
    expect(screen.getByText("Уточняющие вопросы не сформированы.")).toBeInTheDocument();
    expect(screen.getByText("Критерии приёмки не сформированы.")).toBeInTheDocument();
    expect(screen.queryByText(/не обнаружены/i)).not.toBeInTheDocument();
  });

  it("безопасно отображает неизвестный reason code без падения интерфейса", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        [
          "/reviews/review-1",
          () => jsonResponse(buildReview({ needs_review: true, reason_codes: ["FUTURE_UNKNOWN_CODE"] })),
        ],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("FUTURE_UNKNOWN_CODE")).toBeInTheDocument();
    expect(screen.getByText("Неизвестный технический код причины.")).toBeInTheDocument();
  });

  it("при safe fallback (needs_review=true, пустые массивы) не утверждает «не обнаружено»", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: true, reason_codes: ["MODEL_ERROR"] }))],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Нужна экспертная проверка")).toBeInTheDocument();
    expect(screen.getByText(labelReasonCode("MODEL_ERROR"))).toBeInTheDocument();
    expect(screen.queryByText("MODEL_ERROR")).not.toBeInTheDocument();
    expect(screen.getByText("Риски не выявлены.")).toBeInTheDocument();
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

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) return deferredReview1.promise;
        if (url.endsWith("/reviews/review-2")) return deferredReview2.promise;
        if (url.endsWith("/documents/doc-1")) return Promise.resolve(jsonResponse(buildDocument()));
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
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
    expect(screen.getByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByText("Нужна экспертная проверка")).not.toBeInTheDocument();
  });

  it("не показывает error banner для устаревшего запроса, который поздно завершается ошибкой", async () => {
    const deferredReview1 = createDeferred<Response>();
    const deferredReview2 = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) return deferredReview1.promise;
        if (url.endsWith("/reviews/review-2")) return deferredReview2.promise;
        if (url.endsWith("/documents/doc-1")) return Promise.resolve(jsonResponse(buildDocument()));
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
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
    expect(screen.getByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/не удалось загрузить проверку/i)).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------
  // Stale committed render (route-boundary + key={reviewId} regression):
  // an AbortController/`active` guard only stops a *late async result* from
  // overwriting current state — it does nothing about a component instance
  // that is still mounted with A's state at the moment the URL already
  // reads B, before A's effects have had a chance to reset anything. These
  // tests assert on the render immediately after the route change, not
  // after first awaiting B, since waiting for B lets passive effects catch
  // up and would hide the defect the fix (route-bound `key`) addresses.
  // ---------------------------------------------------------------------

  it("A → B после полностью загруженного A: контент A исчезает сразу, до завершения B", async () => {
    const deferredReview2 = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) {
          return Promise.resolve(
            jsonResponse(
              buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] }),
            ),
          );
        }
        if (url.endsWith("/documents/doc-1")) {
          return Promise.resolve(jsonResponse(buildDocument({ id: "doc-1", title: "Документ A" })));
        }
        if (url.endsWith("/reviews/review-2")) return deferredReview2.promise;
        if (url.endsWith("/documents/doc-2")) {
          return Promise.resolve(jsonResponse(buildDocument({ id: "doc-2", title: "Документ B" })));
        }
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    // A is fully committed: review id and document title both rendered.
    expect(await screen.findByText("review-1")).toBeInTheDocument();
    expect(await screen.findByText("Документ A")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    // Checked immediately — review-2's fetch (deferredReview2) has not
    // resolved yet. No committed render at this point may still show A's
    // id/title/summary; the loading state for B must already be visible.
    expect(screen.queryByText("review-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Документ A")).not.toBeInTheDocument();
    expect(screen.queryByText("Резюме проверки для теста.")).not.toBeInTheDocument();
    expect(screen.getByText(/загружаем результат проверки/i)).toBeInTheDocument();

    deferredReview2.resolve(
      jsonResponse(buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] })),
    );
    expect(await screen.findByText("review-2")).toBeInTheDocument();
    expect(await screen.findByText("Документ B")).toBeInTheDocument();
  });

  it("pending document A: поздний success документа A не появляется после перехода на B", async () => {
    const deferredDocA = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) {
          return Promise.resolve(
            jsonResponse(
              buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] }),
            ),
          );
        }
        if (url.endsWith("/documents/doc-1")) return deferredDocA.promise;
        if (url.endsWith("/reviews/review-2")) {
          return Promise.resolve(
            jsonResponse(
              buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] }),
            ),
          );
        }
        if (url.endsWith("/documents/doc-2")) {
          return Promise.resolve(jsonResponse(buildDocument({ id: "doc-2", title: "Документ B" })));
        }
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    // Review A loaded; document A's request is still pending.
    expect(await screen.findByText("review-1")).toBeInTheDocument();
    expect(screen.getByText(/загружаем исходный документ/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    expect(await screen.findByText("review-2")).toBeInTheDocument();
    expect(await screen.findByText("Документ B")).toBeInTheDocument();

    // Document A's request — pending since before the navigation, on an
    // instance that is now fully unmounted — resolves late. Its title must
    // never appear, and B's already-displayed document must stay intact.
    deferredDocA.resolve(jsonResponse(buildDocument({ id: "doc-1", title: "Документ A (устаревший)" })));
    await flushMicrotasks();

    expect(screen.queryByText("Документ A (устаревший)")).not.toBeInTheDocument();
    expect(screen.getByText("Документ B")).toBeInTheDocument();
  });

  it("pending document A: поздняя ошибка документа A не появляется после перехода на B", async () => {
    const deferredDocA = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) {
          return Promise.resolve(
            jsonResponse(
              buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] }),
            ),
          );
        }
        if (url.endsWith("/documents/doc-1")) return deferredDocA.promise;
        if (url.endsWith("/reviews/review-2")) {
          return Promise.resolve(
            jsonResponse(
              buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] }),
            ),
          );
        }
        if (url.endsWith("/documents/doc-2")) {
          return Promise.resolve(jsonResponse(buildDocument({ id: "doc-2", title: "Документ B" })));
        }
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("review-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    expect(await screen.findByText("review-2")).toBeInTheDocument();
    expect(await screen.findByText("Документ B")).toBeInTheDocument();

    // Document A's pending request now fails late, on an unmounted instance.
    deferredDocA.reject(new Error("boom: stale document A failure"));
    await flushMicrotasks();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Документ B")).toBeInTheDocument();
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
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) {
          return Promise.resolve(jsonResponse(buildReview({ needs_review: false, reason_codes: [] })));
        }
        if (url.endsWith("/documents/doc-1")) return Promise.resolve(jsonResponse(buildDocument()));
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/reviews/review-1"]}>
          <Routes>
            <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    expect(await screen.findByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------
  // Source document card (docs task: "review detail page" requirements)
  // ---------------------------------------------------------------------

  it("загружает и отображает исходный документ: title и text", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        [
          "/documents/doc-1",
          () => jsonResponse(buildDocument({ title: "Спецификация модуля X", text: "Требование 1. Требование 2." })),
        ],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Спецификация модуля X")).toBeInTheDocument();
    expect(screen.getByText("Требование 1. Требование 2.")).toBeInTheDocument();
  });

  it("отображает свёрнутый блок с исходным review_json в формате JSON", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        [
          "/reviews/review-1",
          () => jsonResponse(buildReview({ needs_review: true, reason_codes: ["LOW_CONFIDENCE"] })),
        ],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    const { container } = renderReviewPage();

    expect(await screen.findByText("Служебные данные")).toBeInTheDocument();
    expect(await screen.findByText("JSON результата")).toBeInTheDocument();
    const details = container.querySelector(".json-block-details");
    expect(details).not.toBeNull();
    expect(details?.hasAttribute("open")).toBe(false);
    const pre = container.querySelector("pre.json-block");
    expect(pre?.textContent).toContain('"summary"');
    expect(pre?.textContent).toContain("Резюме проверки для теста.");
    expect(pre?.textContent).toContain('"review_reason_codes"');
    // The raw technical code stays intact inside the JSON block, even though
    // the human-readable reason list above it shows the translated label
    // instead (see the "коды причин" test above).
    expect(pre?.textContent).toContain('"LOW_CONFIDENCE"');
  });

  it("ошибка загрузки документа не скрывает уже загруженный review", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        ["/documents/doc-1", () => jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500)],
      ]),
    );

    renderReviewPage();

    expect(await screen.findByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(screen.getByText("Резюме проверки для теста.")).toBeInTheDocument();
    expect(screen.getByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить исходный документ")).toBeInTheDocument();
  });

  it("при смене reviewId на документ с другим document_id не показывает старый document", async () => {
    const deferredDoc2 = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) {
          return Promise.resolve(
            jsonResponse(buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] })),
          );
        }
        if (url.endsWith("/reviews/review-2")) {
          return Promise.resolve(
            jsonResponse(buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] })),
          );
        }
        if (url.endsWith("/documents/doc-1")) {
          return Promise.resolve(jsonResponse(buildDocument({ id: "doc-1", title: "Документ номер один" })));
        }
        if (url.endsWith("/documents/doc-2")) return deferredDoc2.promise;
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Документ номер один")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));

    // review-2 is loaded and its document fetch (doc-2) is still pending:
    // the old document-1 title must already be gone, not lingering.
    await screen.findByText("review-2");
    expect(screen.queryByText("Документ номер один")).not.toBeInTheDocument();

    deferredDoc2.resolve(jsonResponse(buildDocument({ id: "doc-2", title: "Документ номер два" })));
    expect(await screen.findByText("Документ номер два")).toBeInTheDocument();
  });

  it("ссылки «К истории проверок» и «Проверить другой документ» ведут на точные маршруты", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch([
        ["/reviews/review-1", () => jsonResponse(buildReview({ needs_review: false, reason_codes: [] }))],
        ["/documents/doc-1", () => jsonResponse(buildDocument())],
      ]),
    );

    renderReviewPage();

    const historyLink = await screen.findByRole("link", { name: "К истории проверок" });
    expect(historyLink).toHaveAttribute("href", "/reviews");

    const newDocumentLink = screen.getByRole("link", { name: "Проверить другой документ" });
    expect(newDocumentLink).toHaveAttribute("href", "/");
  });
});

function csvResponse(body: string, headers: Record<string, string> = {}, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/csv; charset=utf-8", ...headers },
  });
}

/** Routes `GET /reviews/{reviewId}` and `GET /documents/{documentId}` through
 * fixed success responses, and `GET /reviews/{reviewId}/export` through
 * `exportHandler` — verifying method + exact pathname suffix for the export
 * route specifically (the other two reuse this file's existing `routedFetch`
 * convention, which only matches on URL suffix). */
function mockReviewPageWithExport(
  reviewId: string,
  review: ReviewResponse,
  document: DocumentResponse,
  exportHandler: (url: URL) => Response | Promise<Response>,
) {
  const exportSuffix = `/reviews/${reviewId}/export`;
  const reviewSuffix = `/reviews/${reviewId}`;
  const documentSuffix = `/documents/${document.id}`;

  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";

    if (url.endsWith(exportSuffix)) {
      if (method !== "GET") {
        return Promise.reject(new Error(`export mock: expected GET, got ${method}`));
      }
      return Promise.resolve(exportHandler(new URL(url)));
    }
    if (url.endsWith(reviewSuffix)) return Promise.resolve(jsonResponse(review));
    if (url.endsWith(documentSuffix)) return Promise.resolve(jsonResponse(document));
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
}

describe("ReviewResultPage — экспорт CSV", () => {
  let anchorClickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
    anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete (URL as unknown as { createObjectURL?: unknown }).createObjectURL;
    delete (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL;
    anchorClickSpy.mockRestore();
  });

  it("кнопка «Скачать результат CSV» появляется только после успешной загрузки проверки", async () => {
    const deferredReview = createDeferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1")) return deferredReview.promise;
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    renderReviewPage();
    await screen.findByText(/загружаем результат проверки/i);
    expect(screen.queryByRole("button", { name: "Скачать результат CSV" })).not.toBeInTheDocument();

    deferredReview.resolve(
      jsonResponse(buildReview({ needs_review: false, reason_codes: [] })),
    );
    // The document fetch fires next but the export button only depends on
    // the review having loaded, not the document.
    expect(await screen.findByRole("button", { name: "Скачать результат CSV" })).toBeInTheDocument();
  });

  it("экспорт использует точный review id из URL и запускает скачивание ровно один раз", async () => {
    const review = buildReview({ id: "review-1", needs_review: false, reason_codes: [] });
    const document = buildDocument();
    const fetchMock = mockReviewPageWithExport("review-1", review, document, () => csvResponse("header\r\n"));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderReviewPage("review-1");
    await screen.findByRole("button", { name: "Скачать результат CSV" });

    await user.click(screen.getByRole("button", { name: "Скачать результат CSV" }));
    await screen.findByRole("button", { name: "Скачать результат CSV" });

    const exportCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviews/review-1/export"));
    expect(exportCall).toBeDefined();

    // Positive assertion: the download was actually triggered exactly once —
    // not merely "the export request was sent", which would also pass if
    // downloadBlob were never called after a successful response.
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);

    // No further download after the pending promise has already settled.
    await flushMicrotasks();
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
  });

  it("кнопка отключена во время формирования CSV, текст меняется", async () => {
    const review = buildReview({ id: "review-1", needs_review: false, reason_codes: [] });
    const document = buildDocument();
    const deferredExport = createDeferred<Response>();
    vi.stubGlobal(
      "fetch",
      mockReviewPageWithExport("review-1", review, document, () => deferredExport.promise),
    );

    const user = userEvent.setup();
    renderReviewPage("review-1");
    const button = await screen.findByRole("button", { name: "Скачать результат CSV" });

    await user.click(button);
    expect(await screen.findByRole("button", { name: "Формируется CSV…" })).toBeDisabled();

    deferredExport.resolve(csvResponse("header\r\n"));
    await screen.findByRole("button", { name: "Скачать результат CSV" });
    expect(screen.getByRole("button", { name: "Скачать результат CSV" })).not.toBeDisabled();
  });

  it("ошибка экспорта отображается отдельно от ошибки загрузки страницы", async () => {
    const review = buildReview({ id: "review-1", needs_review: false, reason_codes: [] });
    const document = buildDocument();
    vi.stubGlobal(
      "fetch",
      mockReviewPageWithExport("review-1", review, document, () =>
        jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500),
      ),
    );

    const user = userEvent.setup();
    renderReviewPage("review-1");
    await screen.findByRole("button", { name: "Скачать результат CSV" });
    // The review itself loaded successfully — no page-load error banner.
    expect(screen.queryByText("Не удалось загрузить проверку")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Скачать результат CSV" }));

    expect(await screen.findByText("Не удалось сформировать CSV-файл")).toBeInTheDocument();
    expect(screen.getByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    // Still no page-load error — the two error surfaces are independent.
    expect(screen.queryByText("Не удалось загрузить проверку")).not.toBeInTheDocument();
  });

  it("двойной клик не запускает два экспорт-запроса", async () => {
    const review = buildReview({ id: "review-1", needs_review: false, reason_codes: [] });
    const document = buildDocument();
    const deferredExport = createDeferred<Response>();
    let exportCalls = 0;
    vi.stubGlobal(
      "fetch",
      mockReviewPageWithExport("review-1", review, document, () => {
        exportCalls += 1;
        return deferredExport.promise;
      }),
    );

    const user = userEvent.setup();
    renderReviewPage("review-1");
    const button = await screen.findByRole("button", { name: "Скачать результат CSV" });

    await user.click(button);
    await user.click(button); // second click while pending must be a no-op

    expect(exportCalls).toBe(1);

    deferredExport.resolve(csvResponse("header\r\n"));
    await screen.findByRole("button", { name: "Скачать результат CSV" });
  });

  it("повторный клик после ошибки экспорта работает (retry)", async () => {
    const review = buildReview({ id: "review-1", needs_review: false, reason_codes: [] });
    const document = buildDocument();
    let exportCalls = 0;
    vi.stubGlobal(
      "fetch",
      mockReviewPageWithExport("review-1", review, document, () => {
        exportCalls += 1;
        if (exportCalls === 1) return jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500);
        return csvResponse("header\r\n");
      }),
    );

    const user = userEvent.setup();
    renderReviewPage("review-1");
    await screen.findByRole("button", { name: "Скачать результат CSV" });

    await user.click(screen.getByRole("button", { name: "Скачать результат CSV" }));
    await screen.findByText("Не удалось сформировать CSV-файл");

    await user.click(screen.getByRole("button", { name: "Скачать результат CSV" }));
    await screen.findByRole("button", { name: "Скачать результат CSV" });

    expect(screen.queryByText("Не удалось сформировать CSV-файл")).not.toBeInTheDocument();
    expect(exportCalls).toBe(2);
  });

  it("переход на другую проверку во время экспорта не обновляет состояние размонтированного компонента", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const review1 = buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] });
    const review2 = buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] });
    const doc1 = buildDocument({ id: "doc-1", title: "Документ один" });
    const doc2 = buildDocument({ id: "doc-2", title: "Документ два" });
    const deferredExport = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1/export")) return deferredExport.promise;
        if (url.endsWith("/reviews/review-1")) return Promise.resolve(jsonResponse(review1));
        if (url.endsWith("/reviews/review-2")) return Promise.resolve(jsonResponse(review2));
        if (url.endsWith("/documents/doc-1")) return Promise.resolve(jsonResponse(doc1));
        if (url.endsWith("/documents/doc-2")) return Promise.resolve(jsonResponse(doc2));
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Скачать результат CSV" }));
    await screen.findByRole("button", { name: "Формируется CSV…" });

    // Navigate away while the export request for review-1 is still pending —
    // unmounts the review-1 instance of ReviewResultPage entirely.
    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));
    await screen.findByText("Документ два");

    // The stale export resolves after the component is gone: must not throw
    // or log a React "state update on unmounted component" warning, and must
    // not affect the now-mounted review-2 page.
    deferredExport.resolve(csvResponse("header\r\n"));
    await flushMicrotasks();

    expect(screen.getByText("Документ два")).toBeInTheDocument();
    expect(screen.queryByText("Не удалось сформировать CSV-файл")).not.toBeInTheDocument();
    // Explicit positive assertion that the gap Codex flagged is closed: a
    // late-resolving export for the unmounted review-1 instance must not
    // trigger a download. This is what fails if the mounted-ref guard before
    // downloadBlob() is removed.
    expect(anchorClickSpy).not.toHaveBeenCalled();
    const reactWarnings = consoleErrorSpy.mock.calls.filter(([msg]) =>
      typeof msg === "string" && msg.includes("state update"),
    );
    expect(reactWarnings).toHaveLength(0);

    consoleErrorSpy.mockRestore();
  });

  it("переход на другую проверку во время экспорта: последующий reject не запускает скачивание и не обновляет состояние размонтированного компонента", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const review1 = buildReview({ id: "review-1", documentId: "doc-1", needs_review: false, reason_codes: [] });
    const review2 = buildReview({ id: "review-2", documentId: "doc-2", needs_review: false, reason_codes: [] });
    const doc1 = buildDocument({ id: "doc-1", title: "Документ один" });
    const doc2 = buildDocument({ id: "doc-2", title: "Документ два" });
    const deferredExport = createDeferred<Response>();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/reviews/review-1/export")) return deferredExport.promise;
        if (url.endsWith("/reviews/review-1")) return Promise.resolve(jsonResponse(review1));
        if (url.endsWith("/reviews/review-2")) return Promise.resolve(jsonResponse(review2));
        if (url.endsWith("/documents/doc-1")) return Promise.resolve(jsonResponse(doc1));
        if (url.endsWith("/documents/doc-2")) return Promise.resolve(jsonResponse(doc2));
        return Promise.reject(new Error(`unexpected url: ${url}`));
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/reviews/review-1"]}>
        <NavigateButton to="/reviews/review-2" />
        <Routes>
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Скачать результат CSV" }));
    await screen.findByRole("button", { name: "Формируется CSV…" });

    // Navigate away while the export request for review-1 is still pending —
    // unmounts the review-1 instance of ReviewResultPage entirely.
    await user.click(screen.getByRole("button", { name: /перейти на \/reviews\/review-2/i }));
    await screen.findByText("Документ два");

    // The stale export rejects after the component is gone: must not throw
    // out of the test (awaited via flushMicrotasks, never an unhandled
    // rejection), must not trigger a download, must not show an export error
    // for the unmounted instance, and must not affect the now-mounted
    // review-2 page.
    deferredExport.reject(new Error("boom: late rejection after unmount"));
    await flushMicrotasks();

    expect(screen.getByText("Документ два")).toBeInTheDocument();
    expect(screen.queryByText("Не удалось сформировать CSV-файл")).not.toBeInTheDocument();
    expect(anchorClickSpy).not.toHaveBeenCalled();
    const reactWarnings = consoleErrorSpy.mock.calls.filter(([msg]) =>
      typeof msg === "string" && msg.includes("state update"),
    );
    expect(reactWarnings).toHaveLength(0);

    consoleErrorSpy.mockRestore();
  });
});
