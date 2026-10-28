import { describe, expect, it } from 'vitest';
import { cells, profitKind } from '../components/Heatmap';
import type { AxisMatrix, LabMatrix, LabSnapshot, LabSquareStats } from '../results';
import { cursorDims, heatBasis, heatLayout, heatModel, locateSquare, selectSquareAction, squareAt, squareView, trialSquare } from './labHeatmapModel';
import { answered } from './labQuery';

const ROWS = 'long_side.indicators.ema.length';
const COLS = 'long_side.indicators.sma.length';

/** An exact slice as `matrix_view` sends it: a square with a value is tested by one trial, the others untested. */
function exact(rows: number[], cols: number[], values: Array<Array<number | null>>, over: Partial<LabMatrix> = {}): LabMatrix {
  const counts = values.map((row) => row.map((v) => (v === null ? 0 : 1)));
  return {
    rows_path: ROWS,
    cols_path: COLS,
    rows,
    cols,
    values,
    counts,
    basis: 'Tested (exact)',
    legend: 'empty = untested',
    trial_ids: values.map((row, r) => row.map((v, c) => (v === null ? null : `exp:e1#${r * cols.length + c}`))),
    duplicates: counts.map((row) => row.map(() => 0)),
    ...over,
  };
}

function stats(n: number, over: Partial<LabSquareStats> = {}): LabSquareStats {
  return { n, p25: 1, p75: 3, min: 0, max: 4, low_n: n < 8, confounded: [], histogram: { edges: [0, 2, 4], counts: [n - 1, 1], nulls: 0 }, ...over };
}

/** An aggregated projection: each square's n and statistics, an untested square's null. */
function aggregate(rows: number[], cols: number[], values: Array<Array<number | null>>, grid: Array<Array<LabSquareStats | null>>): LabMatrix {
  return {
    rows_path: ROWS,
    cols_path: COLS,
    rows,
    cols,
    values,
    counts: grid.map((row) => row.map((s) => s?.n ?? 0)),
    basis: 'Aggregated from tested (n = 40)',
    legend: 'Aggregated n ≥ 8 / n < 8 low',
    stats: grid,
  };
}

/** Every number anywhere inside a value. */
function numbersIn(value: unknown): number[] {
  if (typeof value === 'number') return [value];
  if (Array.isArray(value)) return value.flatMap(numbersIn);
  if (value !== null && typeof value === 'object') return Object.values(value).flatMap(numbersIn);
  return [];
}

const tones = (model: ReturnType<typeof heatModel>) => model.squares.map((row) => row.map((s) => s.tone));

describe('labHeatmap', () => {
  it('empty: an all-null matrix gives the empty text, every square untested, no NaN', () => {
    const none = Array.from({ length: 3 }, () => [null, null, null, null]);
    for (const [model, basis] of [
      [heatModel(exact([5, 6, 7], [20, 25, 30, 35], none), 'net_pnl', 'exact', false), 'Tested (exact)'],
      [heatModel(aggregate([5, 6, 7], [20, 25, 30, 35], none, none), 'max_drawdown', 'aggregate', true), 'Aggregated from tested (n = 40)'],
    ] as const) {
      expect(typeof model.empty).toBe('string');
      expect(model.empty).not.toBe('');
      expect(model.squares.flat()).toHaveLength(12);
      expect(model.squares.flat().every((s) => s.untested && s.n === 0 && s.value === null && s.tone === 'empty' && s.trialId === null)).toBe(true);
      expect(model.summary).toBe('0 of 12 squares tested');
      expect(model.basis).toBe(basis);
      expect(numbersIn(model).some((v) => !Number.isFinite(v))).toBe(false);
    }
    const bare = heatModel(exact([], [20, 25], []), 'net_pnl', 'exact', false);
    expect(bare.squares).toEqual([]);
    expect(bare.summary).toBe('0 of 0 squares tested');
    expect(bare.empty).not.toBeNull();
  });

  it('a tested square without a value is never coloured and never untested', () => {
    const m = aggregate([5], [20, 25], [[null, 7]], [[stats(3), stats(9)]]);
    const model = heatModel(m, 'mar', 'aggregate', false);
    expect(model.squares[0][0]).toMatchObject({ value: null, tone: 'empty', untested: false, n: 3 });
    expect(model.empty).toBeNull();
    // Every tested square undefined: tested, yet nothing to colour, and the empty text says so.
    const undefinedEverywhere = heatModel(aggregate([5], [20], [[null]], [[stats(4)]]), 'mar', 'aggregate', false);
    expect(undefinedEverywhere.squares[0][0]).toMatchObject({ tone: 'empty', untested: false });
    expect(undefinedEverywhere.empty).not.toBeNull();
    expect(undefinedEverywhere.summary).toBe('heatmap 1 × 1, 1 of 1 squares tested, none with a mar value');
  });

  it('one axis: a 1 × 5 matrix renders five squares and cursorDims gives one row value, five column values and the axes', () => {
    const m = exact([9], [20, 25, 30, 35, 40], [[10, -5, null, 3, 0]]);
    const model = heatModel(m, 'net_pnl', 'exact', false);
    expect(model.squares).toHaveLength(1);
    expect(model.squares[0]).toHaveLength(5);
    expect(model.squares[0].map((s) => [s.r, s.c])).toEqual([
      [0, 0],
      [0, 1],
      [0, 2],
      [0, 3],
      [0, 4],
    ]);
    expect(model.summary).toBe(`heatmap 1 × 5, best at ${ROWS} = 9 / ${COLS} = 20`);
    expect(cursorDims(m)).toEqual({ rows: [9], cols: [20, 25, 30, 35, 40], axes: [ROWS, COLS] });
    expect(cursorDims(exact([1, 2, 3, 4, 5], [7], [[1], [2], [3], [4], [5]]))).toEqual({ rows: [1, 2, 3, 4, 5], cols: [7], axes: [ROWS, COLS] });
    expect(cursorDims(null)).toBeNull();
    expect(cursorDims(exact([], [20], []))).toBeNull(); // no square to stand on
    // The structural type admits the optimizer's AxisMatrix too.
    const job: AxisMatrix = { rows_path: 'indicators.ema.length', cols_path: 'indicators.sma.length', rows: [5, 6], cols: [20], counts: [[1], [1]], metrics: {}, cells: [] };
    expect(cursorDims(job)).toEqual({ rows: [5, 6], cols: [20], axes: ['indicators.ema.length', 'indicators.sma.length'] });
  });

  it('a click and the keyboard select through one action: the square, its axes and its two values', () => {
    const dims = cursorDims(exact([9, 10], [20, 25, 30], [[1, 2, 3], [4, 5, 6]]));
    if (dims === null) throw new Error('a 2 × 3 matrix has dims');
    expect(selectSquareAction(dims, 1, 2)).toEqual({ type: 'SELECT_SQUARE', x: 2, y: 1, axes: [ROWS, COLS], values: [10, 30] });
    // A cursor outside the grid (the matrix shrank under it) selects the nearest square.
    expect(selectSquareAction(dims, 7, -3)).toEqual({ type: 'SELECT_SQUARE', x: 0, y: 1, axes: [ROWS, COLS], values: [10, 20] });
  });

  it('losses-red scale: every losing square is a loss, break-even is neutral, and the tones are Heatmap.cells()', () => {
    const values = [
      [-50, -10, 0],
      [5, 20, 100],
    ];
    const pnl = heatModel(exact([5, 6], [20, 25, 30], values), 'net_pnl', 'exact', false);
    expect(tones(pnl)).toEqual([
      ['loss', 'loss', 'mid'],
      ['gain', 'gain', 'hot'],
    ]);
    expect(pnl.squares.flat().filter((s) => s.value !== null && s.value < 0).every((s) => s.tone === 'loss')).toBe(true);
    expect(pnl.squares.flat().filter((s) => s.value === 0).map((s) => s.tone)).toEqual(['mid']);
    expect(tones(pnl)).toEqual(cells([5, 6], [20, 25, 30], values, false, profitKind('net_pnl')).map((row) => row.map((c) => c.tone)));
    // Lower is better for the drawdown: the ranks invert.
    const dd = exact([5], [20, 25, 30], [[0.1, 0.2, 0.3]]);
    expect(tones(heatModel(dd, 'max_drawdown', 'exact', true))).toEqual([['hot', 'mid', 'cool']]);
    expect(tones(heatModel(dd, 'max_drawdown', 'exact', false))).toEqual([['cool', 'mid', 'hot']]);
    expect(tones(heatModel(dd, 'max_drawdown', 'exact', true))).toEqual(cells([5], [20, 25, 30], [[0.1, 0.2, 0.3]], true, profitKind('max_drawdown')).map((row) => row.map((c) => c.tone)));
    expect(heatModel(dd, 'max_drawdown', 'exact', true).summary).toBe(`heatmap 1 × 3, best at ${ROWS} = 5 / ${COLS} = 20`);
    // An aggregate of losses is red too.
    const agg = heatModel(aggregate([5], [20, 25], [[-3, 2]], [[stats(9), stats(9)]]), 'net_pnl', 'aggregate', false);
    expect(tones(agg)).toEqual([['loss', 'hot']]);
  });

  it('low n and confounded flags are carried, confounded as the path list', () => {
    const flagged = ['long_side.stop_loss_pct', 'short_side.indicators.rsi.length'];
    const grid = [
      [stats(3), stats(12, { confounded: flagged })],
      [null, stats(8)],
    ];
    const model = heatModel(
      aggregate([5, 6], [20, 25], [
        [-2, 4],
        [null, 1],
      ], grid),
      'net_pnl',
      'aggregate',
      false,
    );
    expect(model.squares[0][0]).toMatchObject({ n: 3, lowN: true, confounded: [], untested: false, trialId: null, tone: 'loss' });
    expect(model.squares[0][1]).toMatchObject({ n: 12, lowN: false, confounded: flagged });
    expect(model.squares[1][0]).toMatchObject({ n: 0, untested: true, tone: 'empty', value: null, lowN: false, confounded: [] });
    expect(model.squares[1][1]).toMatchObject({ n: 8, lowN: false });
    expect(model.basis).toBe('Aggregated from tested (n = 40)');
    expect(model.legend).toBe('Aggregated n ≥ 8 / n < 8 low');
  });

  it('squareAt: an exact tested square gives its trialId, an untested one tested false and no trialId, both with the axis values', () => {
    const m = exact([5, 6], [20, 25], [
      [1, 2],
      [null, 4],
    ]);
    expect(squareAt(m, 0, 1)).toEqual({ trialId: 'exp:e1#1', tested: true, values: [5, 25] });
    expect(squareAt(m, 1, 0)).toEqual({ trialId: null, tested: false, values: [6, 20] });
    const agg = aggregate([5], [20], [[3]], [[stats(9)]]);
    expect(squareAt(agg, 0, 0)).toEqual({ trialId: null, tested: true, values: [5, 20] });
  });

  it('a selected square is found by its axes and values; its view is a trial, untested or a distribution', () => {
    const m = exact([5, 6], [20, 25], [
      [1, 2],
      [null, 4],
    ]);
    expect(locateSquare(m, { x: 1, y: 0, axes: [ROWS, COLS], values: [5, 25] })).toEqual({ r: 0, c: 1 });
    expect(locateSquare(m, { x: 1, y: 0, axes: [COLS, ROWS], values: [5, 25] })).toBeNull(); // another pair
    expect(locateSquare(m, { x: 1, y: 0, axes: [ROWS, COLS], values: [5, 26] })).toBeNull(); // off the axis
    expect(squareView(m, 'exact', 0, 1)).toEqual({ kind: 'trial', trialId: 'exp:e1#1' });
    expect(squareView(m, 'exact', 1, 0)).toEqual({ kind: 'untested' });
    const s = stats(9);
    const agg = aggregate([5], [20, 25], [[3, null]], [[s, null]]);
    expect(squareView(agg, 'aggregate', 0, 0)).toEqual({ kind: 'aggregate', stats: s });
    expect(squareView(agg, 'aggregate', 0, 1)).toEqual({ kind: 'untested' });
    expect(trialSquare(m, 'exp:e1#3')).toEqual({ r: 1, c: 1 });
    expect(trialSquare(m, 'exp:e1#99')).toBeNull();
    expect(trialSquare(agg, 'exp:e1#0')).toBeNull();
  });

  it('the basis line carries only answered text: the answer verbatim, else the last answer of this source, never a loading literal', () => {
    type Shown = { source: string; envelope: LabMatrix & { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string } };
    const settled = { ...exact([5], [20], [[1]]), provisional: false, snapshot: null, receivedAt: '2026-10-28T12:00:00Z' };
    const first: Shown = { source: 'exp:e1', envelope: settled };
    expect(heatBasis(settled)).toBe('Tested (exact) · empty = untested');
    const running = { ...aggregate([5], [20], [[3]], [[stats(9)]]), provisional: true, snapshot: { generation: 3, chunk_watermark: 7 }, receivedAt: '2026-10-28T12:00:05Z' };
    expect(heatBasis(running)).toBe('Aggregated from tested (n = 40) · Aggregated n ≥ 8 / n < 8 low · PROVISIONAL · snapshot 12:00:05 · gen 3');
    // While the next answer is asked there is no current one: the line keeps the last answer this source gave.
    expect(answered(null, first, 'exp:e1')).toBe(first);
    const next: Shown = { source: 'exp:e1', envelope: running };
    expect(answered(next, first, 'exp:e1')).toBe(next);
    // Another source's last answer is never shown; before any answer the line is empty.
    expect(answered(null, first, 'exp:e2')).toBeNull();
    expect(answered<Shown>(null, null, 'exp:e1')).toBeNull();
    for (const shown of [answered(null, first, 'exp:e1'), answered<Shown>(null, null, 'exp:e1')]) {
      expect(shown === null ? '' : heatBasis(shown.envelope)).not.toMatch(/loading|updating/i);
    }
  });

  it('heatLayout keeps the grid inside the canvas, caps a square, and an empty grid has no NaN', () => {
    const big = heatLayout(600, 300, 10, 20);
    expect(big.x0 + 20 * big.cellW).toBeLessThanOrEqual(600);
    expect(big.y0 + 10 * big.cellH).toBeLessThanOrEqual(300);
    expect(big.cellW).toBeGreaterThan(0);
    const small = heatLayout(1200, 900, 2, 3);
    expect(small.cellW).toBeLessThanOrEqual(96);
    expect(small.cellH).toBeLessThanOrEqual(48);
    for (const layout of [heatLayout(600, 300, 0, 0), heatLayout(10, 10, 3, 3)]) {
      expect(numbersIn(layout).every(Number.isFinite)).toBe(true);
      expect(layout.cellW).toBe(0);
    }
  });
});
