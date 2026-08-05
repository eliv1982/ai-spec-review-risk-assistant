import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getReview } from "../api/reviews";
import { ApiError, isAbortError } from "../api/client";
import type { ReviewResponse } from "../types/api";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingIndicator } from "../components/LoadingIndicator";
import { ReasonCodeBadge } from "../components/ReasonCodeBadge";
import { labelCategory, labelConfidence, labelReadiness, labelSeverity } from "../utils/labels";

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "loaded"; review: ReviewResponse };

export function ReviewResultPage() {
  const { reviewId } = useParams<{ reviewId: string }>();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

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

  function handleRetry() {
    setReloadToken((token) => token + 1);
  }

  if (!reviewId) {
    return (
      <main className="page">
        <div className="container">
          <ErrorBanner title="Некорректная ссылка" message="Не указан идентификатор проверки." />
          <p>
            <Link to="/">Вернуться к созданию документа</Link>
          </p>
        </div>
      </main>
    );
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
              <Link to="/">Вернуться к созданию документа</Link>
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

        <div className="form-actions">
          <Link to="/" className="button button-primary">
            Создать новый документ
          </Link>
        </div>
      </div>
    </main>
  );
}
