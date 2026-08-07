import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createDocument } from "../api/documents";
import { runDocumentReview } from "../api/reviews";
import { ApiError, isAbortError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingIndicator } from "../components/LoadingIndicator";

function messageFromError(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function CreateDocumentPage() {
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stageMessage, setStageMessage] = useState<string | null>(null);
  const [creationError, setCreationError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  // Guards against updating state (or navigating) from a create/review
  // request that resolves after this page has already been unmounted —
  // e.g. the user navigated away while the request was still in flight.
  const isMountedRef = useRef(true);
  const activeControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      activeControllerRef.current?.abort();
    };
  }, []);

  const isFormValid = title.trim().length > 0 && text.trim().length > 0;

  async function startReview(id: string) {
    setReviewError(null);
    setStageMessage("Запускаем проверку документа…");
    const controller = new AbortController();
    activeControllerRef.current = controller;
    try {
      const review = await runDocumentReview(id, controller.signal);
      if (!isMountedRef.current) return;
      navigate(`/reviews/${review.id}`);
    } catch (err) {
      if (!isMountedRef.current || isAbortError(err)) return;
      setReviewError(messageFromError(err, "Не удалось запустить проверку документа."));
      setBusy(false);
      setStageMessage(null);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    if (documentId) {
      // Document already created: only retry the review, never re-create it.
      setBusy(true);
      await startReview(documentId);
      return;
    }

    const trimmedTitle = title.trim();
    const trimmedText = text.trim();
    if (!trimmedTitle || !trimmedText) return;

    setBusy(true);
    setCreationError(null);
    setReviewError(null);
    setStageMessage("Создаём документ…");
    const controller = new AbortController();
    activeControllerRef.current = controller;
    try {
      const document = await createDocument({ title: trimmedTitle, text: trimmedText }, controller.signal);
      if (!isMountedRef.current) return;
      setDocumentId(document.id);
      await startReview(document.id);
    } catch (err) {
      if (!isMountedRef.current || isAbortError(err)) return;
      setCreationError(messageFromError(err, "Не удалось создать документ."));
      setBusy(false);
      setStageMessage(null);
    }
  }

  function handleReset() {
    setTitle("");
    setText("");
    setDocumentId(null);
    setBusy(false);
    setStageMessage(null);
    setCreationError(null);
    setReviewError(null);
  }

  const documentLocked = documentId !== null;

  return (
    <main className="page">
      <div className="container">
        <h1>ИИ-рецензент требований и технических заданий</h1>
        <p className="lead">
          Добавьте техническое задание, проектные или бизнес-требования. Ассистент выявит
          пробелы, противоречия и риски, а также сформирует уточняющие вопросы.
        </p>

        <form className="card form" onSubmit={handleSubmit} noValidate>
          <div className="form-field">
            <label htmlFor="title">
              Название документа <span className="required">*</span>
            </label>
            <input
              id="title"
              name="title"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              aria-required="true"
              disabled={documentLocked || busy}
              placeholder="Например: Требования к модулю уведомлений"
            />
          </div>

          <div className="form-field">
            <label htmlFor="text">
              Текст документа <span className="required">*</span>
            </label>
            <textarea
              id="text"
              name="text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              required
              aria-required="true"
              disabled={documentLocked || busy}
              rows={12}
              placeholder="Вставьте техническое задание, требования, описание функции или задачи на автоматизацию…"
            />
          </div>

          {creationError && <ErrorBanner title="Ошибка создания документа" message={creationError} />}

          {documentId && (
            <div className="banner banner-info" role="status">
              <strong className="banner-title">Документ создан</strong>
              <p className="banner-text">
                Идентификатор документа: <code>{documentId}</code>
              </p>
            </div>
          )}

          {reviewError && <ErrorBanner title="Ошибка запуска проверки" message={reviewError} />}

          {busy && stageMessage && <LoadingIndicator message={stageMessage} />}

          <div className="form-actions">
            <button type="submit" className="button button-primary" disabled={busy || (!documentLocked && !isFormValid)}>
              {documentLocked
                ? "Повторить запуск проверки"
                : busy
                  ? "Выполняется…"
                  : "Сохранить документ и запустить проверку"}
            </button>

            {documentLocked && (
              <button type="button" className="button button-secondary" onClick={handleReset} disabled={busy}>
                Проверить другой документ
              </button>
            )}
          </div>
        </form>
      </div>
    </main>
  );
}
