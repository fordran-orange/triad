// Row windowing for the trial table: pure math, nothing React. The table renders only the rows near the
// scroll position and stands in for the rest with two spacers, so a million-trial list costs the same as a short one.

/** Height of one trial row, px. */
export const ROW_HEIGHT = 22;
/** Extra rows rendered above and below the visible ones, so a fast scroll never shows blank space. */
export const OVERSCAN = 10;
/** The most trials one server page request asks for. */
export const PAGE_LIMIT = 500;
/** The most rows one window renders, whatever the viewport (plan §9.6a's DOM-row ceiling). */
export const MAX_RENDERED_ROWS = 1_500;

/** Rows [start, end) are rendered; padTop and padBottom are the spacer heights in px that stand in for the rest. */
export interface RowWindow {
  start: number;
  end: number;
  padTop: number;
  padBottom: number;
}

/** The rows to render for a scroll position: the visible ones plus the overscan on each side, never more than
 *  MAX_RENDERED_ROWS (the visible rows come first, then the overscan), with the spacers summing to the list height.
 *  A bad measurement never breaks it: a row height that is not a positive, finite number and a NaN overscan take the
 *  defaults, a negative overscan is none, a NaN scroll position or viewport height reads as 0 and a non-finite
 *  total as an empty list. */
export function windowRows(input: {
  total: number;
  scrollTop: number;
  viewportHeight: number;
  rowHeight?: number;
  overscan?: number;
}): RowWindow {
  const total = Number.isFinite(input.total) ? input.total : 0;
  const rowHeight = input.rowHeight !== undefined && input.rowHeight > 0 && Number.isFinite(input.rowHeight) ? input.rowHeight : ROW_HEIGHT;
  const overscan = input.overscan === undefined || Number.isNaN(input.overscan) ? OVERSCAN : Math.max(0, input.overscan);
  const scrollTop = Number.isNaN(input.scrollTop) ? 0 : input.scrollTop;
  const viewportHeight = Number.isNaN(input.viewportHeight) ? 0 : input.viewportHeight;
  if (total <= 0) return { start: 0, end: 0, padTop: 0, padBottom: 0 };
  // A partly visible row counts as visible. An unmeasured (zero-height) viewport still asks for one row, so a
  // non-empty list never produces an empty window and the page request that follows never asks for nothing.
  const visible = Math.min(Math.max(1, Math.ceil(viewportHeight / rowHeight)), MAX_RENDERED_ROWS);
  // What the cap leaves for the overscan, split evenly above and below.
  const extra = Math.min(overscan, Math.floor((MAX_RENDERED_ROWS - visible) / 2));
  // The scroll position can overshoot the content (elastic overscroll, a list that just shrank) or go negative;
  // pin the first visible row to a real row so the spacers still add up to the full list height.
  const first = Math.max(0, Math.min(Math.floor(scrollTop / rowHeight), total - 1));
  const start = Math.max(0, first - extra);
  const end = Math.min(total, first + visible + extra);
  return { start, end, padTop: start * rowHeight, padBottom: (total - end) * rowHeight };
}

/** The server page to request for a window: its first row and how many rows, capped at `limit`
 *  (default PAGE_LIMIT). The limit is 0 only for the empty window of an empty list. */
export function pageFor(window: RowWindow, limit: number = PAGE_LIMIT): { offset: number; limit: number } {
  return { offset: window.start, limit: Math.min(limit, window.end - window.start) };
}
