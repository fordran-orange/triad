// The results panel's size and the optimizer matrix's sizing (operator, 2026-10-19: the x/y matrix
// window was unreadable — a 16 × 17 matrix squeezed into a 300 px column of a 248 px strip).
// Pure; vitest-covered (layout.test.ts).

export const RESULTS_MIN = 160;
export const RESULTS_DEFAULT = 248;
const RESULTS_KEY = 'aegis.resultsHeight';
const MIN_CELL = 56; // wide enough for a compact value such as "-$47.2k"

interface Storage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** The panel's height in pixels: at least RESULTS_MIN, at most 80% of the window. */
export function clampResultsHeight(px: number, viewport: number): number {
  const top = Math.max(RESULTS_MIN, Math.floor(viewport * 0.8));
  const wanted = Number.isFinite(px) ? px : RESULTS_DEFAULT;
  return Math.min(Math.max(Math.round(wanted), RESULTS_MIN), top);
}

/** The height this viewer last chose, re-clamped to the current window; the default when storage is
 *  unavailable (private windows, blocked site data). */
export function loadResultsHeight(storage: Storage | null | undefined, viewport: number): number {
  let stored = Number.NaN;
  try {
    const raw = storage?.getItem(RESULTS_KEY);
    if (raw !== null && raw !== undefined) stored = Number(raw);
  } catch {
    stored = Number.NaN;
  }
  return clampResultsHeight(stored, viewport);
}

export function saveResultsHeight(storage: Storage | null | undefined, px: number): void {
  try {
    storage?.setItem(RESULTS_KEY, String(Math.round(px)));
  } catch {
    // a per-viewer convenience: the panel still works without it
  }
}

/** The matrix's columns: the row-label column, then one column per value that never shrinks below
 *  a readable cell and grows into the space it is given. */
export function heatTemplate(columns: number, labelWidth = 72): string {
  return `${labelWidth}px repeat(${columns}, minmax(${MIN_CELL}px, 1fr))`;
}

/** Money in a cell: "$47.2k", "-$3.4k", "$812", "$1.23M"; the sign is kept even when a loss
 *  rounds to zero. */
export function compactMoney(value: number): string {
  const sign = value < 0 ? '-' : '';
  const size = Math.abs(value);
  if (size >= 999_500) return `${sign}$${(size / 1_000_000).toFixed(2)}M`;
  if (size >= 999.5) return `${sign}$${(size / 1000).toFixed(1)}k`;
  return `${sign}$${Math.round(size)}`;
}
