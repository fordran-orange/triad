// The Lab heatmap's decisions, nothing React and nothing drawn: what each square of a matrix answer shows (its tone
// from the dock's `Heatmap.cells()`, reused and never re-implemented, its n, the hatch of an untested square, the
// low-n and confounded flags), the basis and the live-region summary, where the keyboard cursor may stand, what a
// selection resolves to, and the grid's geometry on the canvas. LabHeatmap only draws what this returns.
import { cells, profitKind } from '../components/Heatmap';
import { compactMoney } from '../layout';
import { PERCENT_OBJECTIVES, type LabMatrix, type LabSnapshot, type LabSquareStats, type Objective } from '../results';
import { panelLabel } from './labQuery';
import type { LabAction, LabMode, SquareSelection } from './labStore';

export type Tone = ReturnType<typeof cells>[number][number]['tone'];

export interface HeatSquare {
  r: number;
  c: number;
  /** The square's value; null when untested or when the metric is undefined over it (never coloured). */
  value: number | null;
  /** The trials on the square: an exact square's trial and its duplicates, an aggregate square's n. */
  n: number;
  tone: Tone;
  /** No trial tested it: drawn hatched, never filled. */
  untested: boolean;
  /** An aggregate square under AGG_MIN_N trials: drawn dim and labelled `low n`. */
  lowN: boolean;
  /** The flagged paths from `stats[r][c].confounded` (empty when not flagged). */
  confounded: string[];
  /** An exact square's lowest trial (null untested, and always null in aggregate mode). */
  trialId: string | null;
}

/** A value as the Lab prints a parameter value: no binary noise (0.30000000000000004 reads 0.3). */
export function valueText(v: number): string {
  return String(Number(v.toPrecision(12)));
}

const count = (n: number) => n.toLocaleString('en-US');

/** A matrix answer as the heatmap draws it. Untested squares are hatched and their values never used; a
 *  null-valued tested square has no colour; an all-null matrix gives the empty text, never a NaN scale. */
export function heatModel(
  matrix: LabMatrix,
  metric: string,
  mode: LabMode,
  lowerIsBetter: boolean,
): { squares: HeatSquare[][]; basis: string; legend: string; empty: string | null; summary: string } {
  const counts = (r: number, c: number) => matrix.counts[r]?.[c] ?? 0;
  // A value on an untested square is never shown, so it never enters the tones either.
  const shown = matrix.rows.map((_, r) => matrix.cols.map((_, c) => (counts(r, c) > 0 ? (matrix.values[r]?.[c] ?? null) : null)));
  const grid = cells(matrix.rows, matrix.cols, shown, lowerIsBetter, profitKind(metric));
  let tested = 0;
  let best: { r: number; c: number; v: number } | null = null;
  const squares = grid.map((row, r) =>
    row.map((cell, c): HeatSquare => {
      const n = counts(r, c);
      const value = cell.value !== null && Number.isFinite(cell.value) ? cell.value : null;
      if (n > 0) tested += 1;
      if (value !== null && (best === null || (lowerIsBetter ? value < best.v : value > best.v))) best = { r, c, v: value };
      const stats = mode === 'aggregate' && n > 0 ? (matrix.stats?.[r]?.[c] ?? null) : null;
      return {
        r,
        c,
        value,
        n,
        tone: value === null ? 'empty' : cell.tone,
        untested: n === 0,
        lowN: stats?.low_n ?? false,
        confounded: stats ? [...stats.confounded] : [],
        trialId: mode === 'exact' && n > 0 ? (matrix.trial_ids?.[r]?.[c] ?? null) : null,
      };
    }),
  );
  const total = matrix.rows.length * matrix.cols.length;
  const size = `heatmap ${matrix.rows.length} × ${matrix.cols.length}`;
  const found = best as { r: number; c: number; v: number } | null;
  let summary: string;
  let empty: string | null = null;
  if (tested === 0) {
    summary = `0 of ${count(total)} squares tested`;
    empty = 'no square in view is tested: every square is untested';
  } else if (found === null) {
    summary = `${size}, ${count(tested)} of ${count(total)} squares tested, none with a ${metric} value`;
    empty = `no tested square has a ${metric} value: it is undefined for every trial in view`;
  } else {
    summary = `${size}, best at ${matrix.rows_path} = ${valueText(matrix.rows[found.r])} / ${matrix.cols_path} = ${valueText(matrix.cols[found.c])}`;
  }
  return { squares, basis: matrix.basis, legend: matrix.legend, empty, summary };
}

/** `#lab-heatmap-basis` for an answered matrix: the server's basis and legend verbatim, and its own snapshot while
 *  provisional. */
export function heatBasis(answer: Pick<LabMatrix, 'basis' | 'legend'> & { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string }): string {
  return `${answer.basis} · ${answer.legend}${panelLabel(answer)}`;
}

/** Where the keyboard cursor may stand on a matrix: its row and column values and its two axis paths ([rows,
 *  columns]). Typed structurally, so the Lab's `LabMatrix` and the optimizer's `AxisMatrix` both fit. Null without a
 *  matrix or without a square. */
export type CursorDims = { rows: number[]; cols: number[]; axes: [string, string] };

export function cursorDims(matrix: { rows: number[]; cols: number[]; rows_path: string; cols_path: string } | null): CursorDims | null {
  if (matrix === null || matrix.rows.length === 0 || matrix.cols.length === 0) return null;
  return { rows: matrix.rows, cols: matrix.cols, axes: [matrix.rows_path, matrix.cols_path] };
}

const clamp = (value: number, size: number) => Math.min(Math.max(value, 0), Math.max(size - 1, 0));

/** The one selection a click and Enter both dispatch: the square at (r, c) (kept inside the grid), its axes and its
 *  two values ([row value, column value]), the filter that defines it. */
export function selectSquareAction(dims: CursorDims, r: number, c: number): Extract<LabAction, { type: 'SELECT_SQUARE' }> {
  const y = clamp(r, dims.rows.length);
  const x = clamp(c, dims.cols.length);
  return { type: 'SELECT_SQUARE', x, y, axes: dims.axes, values: [dims.rows[y], dims.cols[x]] };
}

/** The square at (r, c): its exact trial (null untested or aggregate), whether any trial tested it, its values. */
export function squareAt(matrix: LabMatrix, r: number, c: number): { trialId: string | null; tested: boolean; values: [number, number] } {
  return { trialId: matrix.trial_ids?.[r]?.[c] ?? null, tested: (matrix.counts[r]?.[c] ?? 0) > 0, values: [matrix.rows[r], matrix.cols[c]] };
}

/** The selected square on this matrix, found by its axes and values; null when it belongs to another pair or its
 *  values are off these axes. */
export function locateSquare(matrix: { rows: number[]; cols: number[]; rows_path: string; cols_path: string }, square: SquareSelection): { r: number; c: number } | null {
  if (square.axes[0] !== matrix.rows_path || square.axes[1] !== matrix.cols_path) return null;
  const r = matrix.rows.indexOf(square.values[0]);
  const c = matrix.cols.indexOf(square.values[1]);
  return r < 0 || c < 0 ? null : { r, c };
}

/** What a selected square resolves to: an exact square's trial (the selection moves to it), an untested square
 *  (the panel's one line), or an aggregate square's distribution (never a configuration). */
export type SquareView = { kind: 'trial'; trialId: string } | { kind: 'untested' } | { kind: 'aggregate'; stats: LabSquareStats };

export function squareView(matrix: LabMatrix, mode: LabMode, r: number, c: number): SquareView {
  if (mode === 'aggregate') {
    const stats = matrix.stats?.[r]?.[c] ?? null;
    return stats === null || stats.n === 0 ? { kind: 'untested' } : { kind: 'aggregate', stats };
  }
  const at = squareAt(matrix, r, c);
  return at.tested && at.trialId !== null ? { kind: 'trial', trialId: at.trialId } : { kind: 'untested' };
}

/** The exact square whose trial is `trialId` (the selected trial's square), or null. */
export function trialSquare(matrix: LabMatrix, trialId: string): { r: number; c: number } | null {
  const ids = matrix.trial_ids ?? [];
  for (let r = 0; r < ids.length; r++) {
    const c = ids[r].indexOf(trialId);
    if (c >= 0) return { r, c };
  }
  return null;
}

/** The plot's margins: room for the row values and the y title on the left, the column values and the x title
 *  below. */
export const HEAT_MARGIN = { left: 76, top: 6, right: 8, bottom: 38 };
/** A square never grows past this: a 2 × 3 matrix keeps squares, not banners. */
export const HEAT_MAX_CELL = { w: 96, h: 48 };

/** Where the grid sits on a width × height canvas and how big a square is. A canvas too small for the margins has
 *  no square (size 0), never a negative or NaN one. */
export function heatLayout(width: number, height: number, rows: number, cols: number): { x0: number; y0: number; cellW: number; cellH: number } {
  const plotW = Math.max(0, width - HEAT_MARGIN.left - HEAT_MARGIN.right);
  const plotH = Math.max(0, height - HEAT_MARGIN.top - HEAT_MARGIN.bottom);
  const cellW = cols > 0 && plotH > 0 ? Math.min(plotW / cols, HEAT_MAX_CELL.w) : 0;
  const cellH = rows > 0 && plotW > 0 ? Math.min(plotH / rows, HEAT_MAX_CELL.h) : 0;
  return { x0: HEAT_MARGIN.left, y0: HEAT_MARGIN.top, cellW, cellH };
}

/** A square's value in the room a square has: money compact ($47.2k), a share as a percentage, a count whole. */
export function squareLabel(metric: string, v: number): string {
  if (metric === 'net_pnl' || metric === 'expectancy') return compactMoney(v);
  if (PERCENT_OBJECTIVES.has(metric as Objective)) return `${(v * 100).toFixed(1)}%`;
  if (metric === 'trade_count') return String(Math.round(v));
  return v.toFixed(2);
}

// A metric as the panels name it lives with the other metric rules (pure, no component): re-exported for the heatmap.
export { metricName } from './metricRules';
