import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getReview } from "../api/reviews";
import { getDocument } from "../api/documents";
import { ApiError, isAbortError } from "../api/client";
import type { DocumentResponse, ReviewResponse } from "../types/api";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingIndicator } from "../components/LoadingIndicator";
import { ReasonCodeBadge } from "../components/ReasonCodeBadge";
import { JsonBlock } from "../components/JsonBlock";
import {
  labelCategory,
  labelConfidence,
  labelDocumentStatus,
  labelReadiness,
  labelSeverity,
} from "../utils/labels";

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "loaded"; review: ReviewResponse };

type DocumentLoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "loaded"; document: DocumentResponse };

interface ReviewResultPageProps {
  /** Required — always supplied by `ReviewResultRoute`, which already
   * resolved and validated it from the URL. `ReviewResultPage` never reads
   * `useParams` itself: it is mounted with `key={reviewId}` by its caller,
   * so a route change from one review to another unmounts this instance and
   * mounts a brand new one with fresh state, instead of reusing one instance
   * across ids. That is what rules out a "committed render" where the URL
   * already points at review B but the DOM still shows review/document A —
   * an `active`/`AbortController` guard alone only stops a *late async
   * result* from B being overwritten by A, not an already-rendered stale
   * commit made from A's still-mounted state before its effects re-run. */
  reviewId: string;
}

export function ReviewResultPage({ reviewId }: ReviewResultPageProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  const [documentState, setDocumentState] = useState<DocumentLoadState>({ status: "idle" });
  const [documentReloadToken, setDocumentReloadToken] = useState(0);

  useEffect(() => {
    if (!reviewId) return;

    // `active` guards against a superseded request's response overwriting
    // the current state — necessary even with AbortController, since a mock
    // or other transport that ignores the abort signal would otherwise still
    // resolve and race the newer request. It also makes cleanup a no-op for
    // an unmounted component and for React Strict Mode's extra dev-mode
    // mount/cleanup/mount cycle.
    let active = true;
    const controller = new AbortController();

    setState({ status: "loading" });
    getReview(reviewId, controller.signal)
      .then((review) => {
        if (!active) return;
        setState({ status: "loaded", review });
      })
      .catch((err) => {
        if (!active) return;
        if (isAbortError(err)) return;
        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError({ kind: "network", message: "Не удалось загрузить результат проверки." });
        setState({ status: "error", error: apiError });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [reviewId, reloadToken]);

  // Only known once the review has loaded — the document is fetched by the
  // review's own `document_id`, never derived from the route param. Runs as
  // a second, independent step (not in parallel with the review fetch) so a
  // slow/failed document load can never delay or hide an already-successful
  // review render.
  const documentId = state.status === "loaded" ? state.review.document_id : null;

  useEffect(() => {
    if (!documentId) return;

    let active = true;
    const controller = new AbortController();

    setDocumentState({ status: "loading" });
    getDocument(documentId, controller.signal)
      .then((document) => {
        if (!active) return;
        setDocumentState({ status: "loaded", document });
      })
      .catch((err) => {
        if (!active) return;
        if (isAbortError(err)) return;
        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError({ kind: "network", message: "Не удалось загрузить исходный документ." });
        setDocumentState({ status: "error", error: apiError });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [documentId, documentReloadToken]);

  function handleRetry() {
    setReloadToken((token) => token + 1);
  }

  function handleDocumentRetry() {
    setDocumentReloadToken((token) => token + 1);
  }

  if (state.status === "loading") {
    return (
      <main className="page">
        <div className="container">
          <LoadingIndicator message="Загружаем результат проверки…" />
        </div>
      </main>
    );
  }

  if (state.status === "error") {
    if (state.error.status === 404) {
      return (
        <main className="page">
          <div className="container">
            <h1>Проверка не найдена</h1>
            <p className="lead">
              Проверка с идентификатором <code>{reviewId}</code> не найдена. Возможно, ссылка
              устарела или содержит опечатку.
            </p>
            <p>
              <Link to="/">Вернуться к созданию документа</Link> ·{" "}
              <Link to="/reviews">К списку проверок</Link>
            </p>
          </div>
        </main>
      );
    }

    return (
      <main className="page">
        <div className="container">
          <ErrorBanner title="Не удалось загрузить проверку" message={state.error.message} />
          <div className="form-actions">
            <button type="button" className="button button-secondary" onClick={handleRetry}>
              Повторить попытку
            </button>
            <Link to="/reviews" className="button button-secondary">
              К списку проверок
            </Link>
            <Link to="/" className="button button-secondary">
              Вернуться к созданию документа
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const { review } = state;
  const finalReview = review.review_json;

  return (
    <main className="page">
      <div className="container">
        <h1>Результат проверки</h1>

        <section className="card">
          <dl className="meta-grid">
            <div>
              <dt>Идентификатор проверки</dt>
              <dd>
                <code>{review.id}</code>
              </dd>
            </div>
            <div>
              <dt>Идентификатор документа</dt>
              <dd>
                <code>{review.document_id}</code>
              </dd>
            </div>
            <div>
              <dt>Создано</dt>
              <dd>{review.created_at}</dd>
            </div>
            <div>
              <dt>Готовность документа</dt>
              <dd>{labelReadiness(review.readiness)}</dd>
            </div>
            <div>
              <dt>Уверенность оценки</dt>
              <dd>{labelConfidence(review.confidence)}</dd>
            </div>
          </dl>
        </section>

        <section className="card">
          <h2>Исходный документ</h2>
          {(documentState.status === "idle" || documentState.status === "loading") && (
            <LoadingIndicator message="Загружаем исходный документ…" />
          )}
          {documentState.status === "error" && (
            <>
              <ErrorBanner
                title="Не удалось загрузить исходный документ"
                message={documentState.error.message}
              />
              <div className="form-actions">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={handleDocumentRetry}
                >
                  Повторить попытку
                </button>
              </div>
            </>
          )}
          {documentState.status === "loaded" && (
            <>
              <dl className="meta-grid">
                <div>
                  <dt>Название документа</dt>
                  <dd>{documentState.document.title}</dd>
                </div>
                <div>
                  <dt>Создан</dt>
                  <dd>{documentState.document.created_at}</dd>
                </div>
                <div>
                  <dt>Статус документа</dt>
                  <dd>{labelDocumentStatus(documentState.document.status)}</dd>
                </div>
              </dl>
              <h3>Текст документа</h3>
              <p className="long-text">{documentState.document.text}</p>
            </>
          )}
        </section>

        {review.needs_review ? (
          <div className="banner banner-warning" role="alert">
            <strong className="banner-title">Требуется ручная проверка</strong>
            <p className="banner-text">
              Автоматическая проверка не может дать окончательное заключение по этому документу.
              Рекомендуем, чтобы специалист проверил его вручную перед дальнейшей работой.
            </p>
          </div>
        ) : (
          <div className="banner banner-success" role="status">
            <strong className="banner-title">Ручная проверка не требуется</strong>
            <p className="banner-text">
              Автоматическая проверка не выявила оснований для обязательного ручного рассмотрения.
              Это не гарантирует полное отсутствие ошибок — при необходимости документ можно
              дополнительно проверить вручную.
            </p>
          </div>
        )}

        {review.reason_codes.length > 0 && (
          <section className="card">
            <h2>Причины, повлиявшие на решение</h2>
            <ul className="reason-code-list">
              {review.reason_codes.map((code) => (
                <ReasonCodeBadge key={code} code={code} />
              ))}
            </ul>
          </section>
        )}

        <section className="card">
          <h2>Резюме</h2>
          <p className="long-text">{finalReview.summary}</p>
        </section>

        <section className="card">
          <h2>Риски</h2>
          {finalReview.risks.length === 0 ? (
            <p className="empty-state">В результате проверки риски не указаны.</p>
          ) : (
            <ul className="item-list">
              {finalReview.risks.map((risk, index) => (
                <li key={index} className="item-card">
                  <div className="item-card-header">
                    <span className={`badge badge-severity-${risk.severity}`}>
                      Серьёзность: {labelSeverity(risk.severity)}
                    </span>
                    <span className="badge badge-neutral">{labelCategory(risk.category)}</span>
                  </div>
                  <p className="long-text">{risk.description}</p>
                  {risk.evidence && (
                    <p className="evidence">
                      <span className="evidence-label">Цитата из документа:</span> «{risk.evidence}»
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Недостающие требования</h2>
          {finalReview.missing_requirements.length === 0 ? (
            <p className="empty-state">В результате проверки недостающие требования не указаны.</p>
          ) : (
            <ul className="item-list">
              {finalReview.missing_requirements.map((item, index) => (
                <li key={index} className="item-card">
                  <div className="item-card-header">
                    <span className="badge badge-neutral">{labelCategory(item.category)}</span>
                  </div>
                  <p className="long-text">{item.description}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Противоречия</h2>
          {finalReview.contradictions.length === 0 ? (
            <p className="empty-state">В результате проверки противоречия не указаны.</p>
          ) : (
            <ul className="item-list">
              {finalReview.contradictions.map((item, index) => (
                <li key={index} className="item-card">
                  <p className="long-text">{item.description}</p>
                  {item.evidence.length > 0 && (
                    <ul className="evidence-list">
                      {item.evidence.map((excerpt, excerptIndex) => (
                        <li key={excerptIndex} className="evidence">
                          «{excerpt}»
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Вопросы для уточнения</h2>
          {finalReview.questions_to_client.length === 0 ? (
            <p className="empty-state">В результате проверки уточняющие вопросы не указаны.</p>
          ) : (
            <ul className="item-list-simple">
              {finalReview.questions_to_client.map((question, index) => (
                <li key={index} className="long-text">
                  {question}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Критерии приёмки</h2>
          {finalReview.acceptance_criteria.length === 0 ? (
            <p className="empty-state">В результате проверки критерии приёмки не указаны.</p>
          ) : (
            <ul className="item-list-simple">
              {finalReview.acceptance_criteria.map((criterion, index) => (
                <li key={index} className="long-text">
                  {criterion}
                </li>
              ))}
            </ul>
          )}
        </section>

        {review.error && (
          <section className="card">
            <h2>Техническое примечание</h2>
            <p className="long-text">{review.error}</p>
          </section>
        )}

        <section className="card">
          <h2>Технические данные проверки</h2>
          <p className="lead">
            Полный сохранённый объект <code>review_json</code> в техническом JSON-формате — для
            диагностики и сверки с тем, что показано выше.
          </p>
          <JsonBlock title="review_json (JSON)" value={review.review_json} />
        </section>

        <div className="form-actions">
          <Link to="/reviews" className="button button-secondary">
            К списку проверок
          </Link>
          <Link to="/" className="button button-primary">
            Создать новый документ
          </Link>
        </div>
      </div>
    </main>
  );
}

/**
 * Route entry point for `/reviews/:reviewId`. Resolves and validates the URL
 * param, then mounts `ReviewResultPage` with `key={reviewId}` — the `key`
 * change forces React to unmount the previous review's component instance
 * (synchronously, in the same commit) and mount a fresh one for the new id,
 * rather than reusing one instance whose state effects haven't caught up
 * yet. That is what guarantees no committed render can ever show review or
 * document content for the old id once the URL has changed.
 */
export function ReviewResultRoute() {
  const { reviewId } = useParams<{ reviewId: string }>();

  if (!reviewId) {
    return (
      <main className="page">
        <div className="container">
          <ErrorBanner title="Некорректная ссылка" message="Не указан идентификатор проверки." />
          <p>
            <Link to="/">Вернуться к созданию документа</Link> · <Link to="/reviews">К списку проверок</Link>
          </p>
        </div>
      </main>
    );
  }

  return <ReviewResultPage key={reviewId} reviewId={reviewId} />;
}
