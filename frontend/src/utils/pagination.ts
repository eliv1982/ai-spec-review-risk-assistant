/**
 * Detects an out-of-range page and computes the nearest valid `offset` to
 * fall back to (docs task: "out-of-range pagination" fix). Triggers only
 * when the *current* page came back empty while the backend's own `total`
 * says there should be data somewhere before it — never for a genuinely
 * empty result set (`total === 0` with `offset` already `0`), and never for
 * a page that legitimately has no rows because it's simply the caller's
 * first request (`offset === 0`).
 *
 * Returns `null` when no correction is needed, or the corrected `offset`
 * otherwise. The corrected value is always strictly less than the current
 * `offset` (proof: when `offset >= total > 0`, `floor((total-1)/pageSize)
 * *pageSize <= total-1 < total <= offset`; when `total === 0` the corrected
 * value is `0 < offset`), so repeatedly applying this function converges to
 * a stable page in a single step and can never loop.
 */
export function computeCorrectedOffset(params: {
  itemCount: number;
  offset: number;
  total: number;
  pageSize: number;
}): number | null {
  const { itemCount, offset, total, pageSize } = params;

  if (itemCount !== 0) return null;
  if (offset <= 0) return null;
  if (offset < total) return null;

  const corrected = total === 0 ? 0 : Math.floor((total - 1) / pageSize) * pageSize;
  return corrected !== offset ? corrected : null;
}
