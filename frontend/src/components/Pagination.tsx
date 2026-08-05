interface PaginationProps {
  limit: number;
  offset: number;
  itemCount: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  disabled?: boolean;
}

/** Backend-driven pager: `total`, `limit`, and `offset` all come from the
 * server (docs/API_CONTRACTS.md, "Pagination"). Never infers a total or a
 * "has more" state from the current page's item count alone. */
export function Pagination({ limit, offset, itemCount, total, onPrev, onNext, disabled }: PaginationProps) {
  const from = itemCount === 0 ? 0 : offset + 1;
  const to = offset + itemCount;
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <nav className="pagination" aria-label="Постраничная навигация">
      <button
        type="button"
        className="button button-secondary"
        onClick={onPrev}
        disabled={disabled || !hasPrev}
      >
        Назад
      </button>
      <span className="pagination-status" role="status" aria-live="polite">
        {total === 0 ? "Нет записей" : `Показаны ${from}–${to} из ${total}`}
      </span>
      <button
        type="button"
        className="button button-secondary"
        onClick={onNext}
        disabled={disabled || !hasNext}
      >
        Далее
      </button>
    </nav>
  );
}
