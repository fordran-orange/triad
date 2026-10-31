import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { Parameter, StrategySpec, Surface } from '../contracts';
import type { LabMatrix, LabParameter, LabSquareStats } from '../results';
import { candidateCard, categoryA, categoryB, interactions, labCounts, pair, PATHS } from './analyticsFixtures';
import { families } from './catalog';
import {
  breadcrumbPlan,
  breadcrumbSteps,
  candidateSquare,
  candidateStates,
  cellFilter,
  cellTitle,
  countLabel,
  drillCheck,
  isPicked,
  neighbourhoodTitle,
  rangeText,
  refreshedPick,
  familyTree,
  groupAxis,
  neighbourhoodModel,
  pickOf,
  pickFilter,
  TRELLIS_MAX_SIDE,
  TRELLIS_MIN_N,
  trellisModel,
  trellisPairs,
  trellisStat,
} from './familiesModel';
import { DrillCheck, FamiliesPage } from './FamiliesPage';
import type { LabFilter } from './labStore';
import { CrumbSteps } from './ScopeBreadcrumb';
import { TrellisGrid } from './Trellis';
import type { LabQueryData } from './useLabQuery';

const NONE: LabFilter = { ranges: {}, values: {}, scope: 'combined', pass: [], status: [] };
const ROWS_PATH = 'long_side.indicators.ema.length';
const COLS_PATH = 'long_side.stop_loss_pct';
const OTHER_PATH = 'long_side.indicators.sma.length';

function stats(n: number, nulls: number, over: Partial<LabSquareStats> = {}): LabSquareStats {
  return { n, p25: 1, p75: 3, min: 0, max: 5, low_n: n < 8, confounded: [], histogram: { edges: [], counts: [], nulls }, ...over };
}

type Square = { n: number; value?: number | null; nulls?: number; p25?: number | null; p75?: number | null };

/** An aggregate matrix as the worker sends it: `at(r, c)` is the square's n, its stat value and the trials in it with no value. */
function aggregate(rows: number[], cols: number[], at: (r: number, c: number) => Square): LabMatrix {
  const squares = rows.map((_, r) => cols.map((_, c) => at(r, c)));
  return {
    rows_path: ROWS_PATH,
    cols_path: COLS_PATH,
    rows,
    cols,
    values: squares.map((row) => row.map((s) => (s.n > 0 ? (s.value ?? null) : null))),
    counts: squares.map((row) => row.map((s) => s.n)),
    basis: 'Aggregated from tested (n = 0)',
    legend: 'Aggregated n ≥ 8 / n < 8 low',
    stats: squares.map((row) => row.map((s) => (s.n > 0 ? stats(s.n, s.nulls ?? 0, { p25: s.p25 === undefined ? 1 : s.p25, p75: s.p75 === undefined ? 3 : s.p75 }) : null))),
  };
}

const range = (from: number, to: number, step = 1) => Array.from({ length: Math.round((to - from) / step) + 1 }, (_, i) => Number((from + i * step).toFixed(6)));

describe('the axes of a trellis square', () => {
  it('keeps a lattice of up to 16 values as it is, one square per value', () => {
    expect(TRELLIS_MAX_SIDE).toBe(16);
    const groups = groupAxis(range(5, 60, 5)); // 12 values
    expect(groups).toHaveLength(12);
    expect(groups.every((g) => g.from === g.to && g.lo === g.hi)).toBe(true);
    expect(groupAxis(range(1, 16))).toHaveLength(16);
  });

  it('merges neighbours past 16 into at most 16 contiguous groups that cover the lattice once, in order', () => {
    const values = range(1, 10, 0.5); // 19 values: the stop-loss axis of the benchmark
    const groups = groupAxis(values);
    expect(groups).toHaveLength(10);
    expect(groups[0]).toEqual({ from: 0, to: 1, lo: 1, hi: 1.5 });
    expect(groups[9]).toEqual({ from: 18, to: 18, lo: 10, hi: 10 });
    for (const length of [17, 19, 33, 100, 199, 200]) {
      const g = groupAxis(range(1, length));
      expect(g.length).toBeLessThanOrEqual(16);
      expect(g[0].from).toBe(0);
      expect(g[g.length - 1].to).toBe(length - 1);
      for (let i = 1; i < g.length; i++) expect(g[i].from).toBe(g[i - 1].to + 1);
    }
    expect(groupAxis([])).toEqual([]);
  });

  it('asks for the median, and for the mean only where merging will need a statistic that can be pooled', () => {
    expect(trellisStat(12, 14)).toBe('median');
    expect(trellisStat(16, 16)).toBe('median');
    expect(trellisStat(19, 12)).toBe('mean');
    expect(trellisStat(12, 17)).toBe('mean');
    expect(trellisStat(null, 12)).toBe('median'); // a count not known: the pooled value is withheld rather than guessed
  });
});

describe('a trellis pair\'s squares', () => {
  const rows = range(5, 60, 5);
  const cols = range(1, 8);

  it('shows each square of a lattice up to 16 × 16 as the server sent it: its n and its median', () => {
    const m = trellisModel(aggregate(rows, cols, (r, c) => ({ n: 40 + r, value: r * 10 + c })), 'median', 'net_pnl');
    expect(m.merged).toBe(false);
    expect(m.rows).toHaveLength(12);
    expect(m.cols).toHaveLength(8);
    expect(m.cells[3][2]).toMatchObject({ r: 3, c: 2, n: 43, value: 32, state: 'ok' });
    expect(m.total).toBe(rows.reduce((sum, _, r) => sum + (40 + r) * cols.length, 0));
  });

  it('hatches a tested square under 30 trials and leaves it out of the scale: it carries no tone and sets no colour', () => {
    expect(TRELLIS_MIN_N).toBe(30);
    // The best value sits in a thin square (n 10). Were it in the scale, 100 would not be the top third of the gains.
    const m = trellisModel(aggregate([1, 2], [1, 2], (r, c) => ({ n: [[40, 10], [40, 35]][r][c], value: [[100, 5000], [-30, 50]][r][c] })), 'median', 'net_pnl');
    expect(m.cells[0][1]).toMatchObject({ n: 10, state: 'thin', tone: 'empty' });
    expect(m.cells[0][1].value).toBe(5000); // kept for the hover, never drawn
    expect(m.cells[0][0].tone).toBe('hot');
    expect(m.cells[1][1].tone).toBe('gain');
    expect(m.thin).toBe(1);
    expect(m.included).toBe(3);
    expect(trellisModel(aggregate([1], [1], () => ({ n: 29, value: 1 })), 'median', 'net_pnl').cells[0][0].state).toBe('thin');
    expect(trellisModel(aggregate([1], [1], () => ({ n: 30, value: 1 })), 'median', 'net_pnl').cells[0][0].state).toBe('ok');
  });

  it('paints a losing square red whatever its rank: a P&L-signed value below zero is never green or best', () => {
    const m = trellisModel(aggregate([1, 2], [1, 2], (r, c) => ({ n: 50, value: [[-5, -1], [-9, -3]][r][c] })), 'median', 'net_pnl');
    expect(m.cells.flat().every((cell) => cell.tone === 'loss')).toBe(true);
    // A drawdown has no profit sign: the lowest is the best, and nothing is a loss.
    const dd = trellisModel(aggregate([1, 2], [1, 2], (r, c) => ({ n: 50, value: [[0.05, 0.3], [0.5, 0.2]][r][c] })), 'median', 'max_drawdown');
    expect(dd.cells[0][0].tone).toBe('hot');
    expect(dd.cells.flat().some((cell) => cell.tone === 'loss')).toBe(false);
  });

  it('leaves an untested square hatched with no value, and a tested square with no defined metric without a tone', () => {
    const m = trellisModel(aggregate([1, 2], [1, 2], (r, c) => (r === 0 && c === 0 ? { n: 0 } : r === 0 ? { n: 50, value: null, nulls: 50 } : { n: 50, value: 3 })), 'median', 'mar');
    expect(m.cells[0][0]).toMatchObject({ n: 0, value: null, state: 'untested', tone: 'empty' });
    expect(m.cells[0][1]).toMatchObject({ n: 50, value: null, state: 'undefined', tone: 'empty' });
    expect(m.tested).toBe(3);
  });

  it('merges a lattice past 16 into groups whose n sums, so the trials are all still counted', () => {
    const wide = range(1, 10, 0.5); // 19
    const counts = (r: number, c: number) => 5 + ((r * 7 + c * 3) % 9);
    const m = trellisModel(aggregate(wide, cols, (r, c) => ({ n: counts(r, c), value: r + c })), 'mean', 'net_pnl');
    expect(m.merged).toBe(true);
    expect(m.rows).toHaveLength(10);
    expect(m.cols).toHaveLength(8);
    expect(m.cells[0][0].n).toBe(counts(0, 0) + counts(1, 0));
    expect(m.cells[9][0].n).toBe(counts(18, 0)); // the last group holds one value
    const sum = wide.reduce((t, _, r) => t + cols.reduce((u, __, c) => u + counts(r, c), 0), 0);
    expect(m.total).toBe(sum);
    expect(m.cells.flat().reduce((t, cell) => t + cell.n, 0)).toBe(sum);
  });

  it('pools a merged mean exactly, weighting each square by its trials with a value; a median cannot be pooled and is withheld', () => {
    const wide = range(1, 17); // 17 values: rows 0 and 1 merge
    const at = (r: number): Square => (r === 0 ? { n: 40, value: 10 } : r === 1 ? { n: 60, value: 20, nulls: 10 } : { n: 50, value: 1 });
    const mean = trellisModel(aggregate(wide, [1], at), 'mean', 'net_pnl');
    expect(mean.cells[0][0].n).toBe(100);
    expect(mean.cells[0][0].value).toBeCloseTo((10 * 40 + 20 * 50) / 90, 10); // 60 trials, 10 of them without a value
    const median = trellisModel(aggregate(wide, [1], at), 'median', 'net_pnl');
    expect(median.cells[0][0].n).toBe(100);
    expect(median.cells[0][0].value).toBeNull();
    expect(median.cells[0][0].state).toBe('undefined');
    expect(median.valueNote).toBe('squares merged past 16 per axis carry no value: a median cannot be built from the medians of its parts');
    expect(mean.valueNote).toBe('squares merged past 16 per axis show the mean of their parts, pooled exactly (a median of the whole cannot be built from its parts)');
    expect(trellisModel(aggregate(range(1, 10), [1], () => ({ n: 40, value: 1 })), 'median', 'net_pnl').valueNote).toBeNull();
  });

  it('a group of untested squares stays untested: nothing is filled from the squares beside it', () => {
    const wide = range(1, 17);
    const m = trellisModel(aggregate(wide, [1], (r) => (r < 2 ? { n: 0 } : { n: 50, value: 4 })), 'mean', 'net_pnl');
    expect(m.cells[0][0]).toMatchObject({ n: 0, value: null, state: 'untested' });
    expect(m.cells[1][0].state).toBe('ok');
  });

  it('names the pair\'s size and basis for the panel', () => {
    const m = trellisModel(aggregate(rows, cols, () => ({ n: 40, value: 1 })), 'median', 'net_pnl');
    expect(m.summary).toBe('12 × 8 squares · 96 tested · 96 with n ≥ 30 · 0 hatched');
    const merged = trellisModel(aggregate(range(1, 17), [1, 2], () => ({ n: 40, value: 1 })), 'mean', 'net_pnl');
    expect(merged.summary).toBe('9 × 2 squares (merged from 17 × 2 values) · 18 tested · 18 with n ≥ 30 · 0 hatched');
  });
});

/** The worker's side of the count, for the test: a trial passes a filter when each range holds it (ends included) and each fixed value equals it. */
function passes(params: Record<string, number>, f: LabFilter): boolean {
  return (
    Object.entries(f.ranges).every(([path, [a, b]]) => params[path] >= Math.min(a, b) && params[path] <= Math.max(a, b)) && Object.entries(f.values).every(([path, v]) => params[path] === v)
  );
}

describe('the drill-down keeps the count', () => {
  // 19 stop-loss values × 12 EMA lengths × 5 SMA lengths, a few copies of each in a pattern: the trials of a source.
  const stops = range(1, 10, 0.5);
  const emas = range(5, 60, 5);
  const smas = range(20, 60, 10);
  const trials: Array<Record<string, number>> = [];
  stops.forEach((stop, i) => emas.forEach((ema, j) => smas.forEach((sma, k) => {
    for (let copy = 0; copy < (i * 7 + j * 3 + k * 5) % 6; copy++) trials.push({ [COLS_PATH]: stop, [ROWS_PATH]: ema, [OTHER_PATH]: sma });
  })));

  /** The matrix the worker would send for `filter`: the trials that pass it, counted on the lattice. */
  function matrixOf(filter: LabFilter, rowVals: number[], colVals: number[]): LabMatrix {
    const kept = trials.filter((t) => passes(t, filter));
    return aggregate(rowVals, colVals, (r, c) => ({ n: kept.filter((t) => t[ROWS_PATH] === rowVals[r] && t[COLS_PATH] === colVals[c]).length, value: r + c }));
  }

  const filters: Array<[string, LabFilter]> = [
    ['no filter', NONE],
    ['a range on a third parameter', { ...NONE, ranges: { [OTHER_PATH]: [30, 50] } }],
    ['a brush across an axis', { ...NONE, ranges: { [COLS_PATH]: [2.5, 8], [ROWS_PATH]: [15, 45] } }],
    ['a fixed value on a third parameter', { ...NONE, values: { [OTHER_PATH]: 40 } }],
  ];
  for (const [name, filter] of filters) {
    it(`a square's n is the page total for the filter plus that square: unmerged lattice, ${name}`, () => {
      const m = trellisModel(matrixOf(filter, emas, range(1, 5, 0.5)), 'median', 'net_pnl'); // 12 × 9: nothing merges
      expect(m.merged).toBe(false);
      let checked = 0;
      for (const row of m.cells)
        for (const cell of row) {
          const f = cellFilter(filter, [ROWS_PATH, COLS_PATH], [cell.rows.lo, cell.rows.hi], [cell.cols.lo, cell.cols.hi]);
          const total = f === null ? 0 : trials.filter((t) => passes(t, f)).length;
          expect(total).toBe(cell.n); // a square with no filter holds no trial
          if (cell.n > 0) expect(f).not.toBeNull();
          checked += cell.n > 0 ? 1 : 0;
        }
      expect(checked).toBeGreaterThan(10);
    });

    it(`a merged square's n is the page total for the filter plus its two ranges: 19 stop-loss values in 10 groups, ${name}`, () => {
      const m = trellisModel(matrixOf(filter, emas, stops), 'mean', 'net_pnl');
      expect(m.merged).toBe(true);
      expect(m.cols).toHaveLength(10);
      let checked = 0;
      for (const row of m.cells)
        for (const cell of row) {
          const f = cellFilter(filter, [ROWS_PATH, COLS_PATH], [cell.rows.lo, cell.rows.hi], [cell.cols.lo, cell.cols.hi]);
          const total = f === null ? 0 : trials.filter((t) => passes(t, f)).length;
          expect(total).toBe(cell.n); // a square with no filter holds no trial
          if (cell.n > 0) expect(f).not.toBeNull();
          checked += cell.n > 0 ? 1 : 0;
        }
      expect(checked).toBeGreaterThan(10);
    });
  }

  it('fixes a single lattice value and ranges a merged group, keeps every other filter, and never edits the filter it was given', () => {
    const base: LabFilter = { ranges: { [OTHER_PATH]: [30, 50], [COLS_PATH]: [2, 6] }, values: { 'long_side.take_profit_pct': 1 }, scope: 'long', pass: ['IS'], status: ['ok'] };
    const frozen = JSON.stringify(base);
    const one = cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 15], [3, 3])!;
    expect(one.values).toEqual({ 'long_side.take_profit_pct': 1, [ROWS_PATH]: 15, [COLS_PATH]: 3 }); // one lattice value: fixed, the way a heatmap square is
    expect(one.ranges).toEqual(base.ranges); // the brush stays: it filtered the matrix too
    expect(one.scope).toBe('long');
    expect(one.pass).toEqual(['IS']);
    expect(one.status).toEqual(['ok']);
    // A merged group is a range, cut to the filter's own range on that axis (never a reversed one: the worker would reorder it).
    const cut = cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 20], [1.5, 3])!;
    expect(cut.ranges[ROWS_PATH]).toEqual([15, 20]);
    expect(cut.ranges[COLS_PATH]).toEqual([2, 3]);
    expect(cut.ranges[OTHER_PATH]).toEqual([30, 50]);
    expect(cut.values[ROWS_PATH]).toBeUndefined();
    for (const [lo, hi] of Object.values(cut.ranges)) expect(lo).toBeLessThanOrEqual(hi);
    expect(JSON.stringify(base)).toBe(frozen);
  });

  it('has no filter for a group wholly outside the filter range on its axis: it cannot be written, and the square holds no trial', () => {
    const base: LabFilter = { ...NONE, ranges: { [COLS_PATH]: [2.5, 8] } };
    expect(cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 20], [1, 1.5])).toBeNull();
    expect(cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 20], [8.5, 10])).toBeNull();
    expect(cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 20], [2, 2.5])!.ranges[COLS_PATH]).toEqual([2.5, 2.5]); // it touches: one value
    expect(cellFilter(base, [ROWS_PATH, COLS_PATH], [15, 20], [2, 2.5])).not.toBeNull();
  });

  it('a pick is the square\'s defining filter, with the n the matrix gave it', () => {
    const m = trellisModel(matrixOf(NONE, emas, stops), 'mean', 'net_pnl');
    const cell = m.cells[2][3];
    const pick = pickOf(1, m, cell);
    expect(pick).toEqual({ pair: 1, axes: [ROWS_PATH, COLS_PATH], rows: [cell.rows.lo, cell.rows.hi], cols: [cell.cols.lo, cell.cols.hi], n: cell.n });
    expect(pickFilter({ ...NONE, ranges: { [OTHER_PATH]: [30, 50] } }, pick)).toEqual(cellFilter({ ...NONE, ranges: { [OTHER_PATH]: [30, 50] } }, pick.axes, pick.rows, pick.cols));
  });

  it('compares the square\'s n with the page total and says so when they differ', () => {
    expect(drillCheck(120, 120)).toMatchObject({ match: true, text: 'the square\'s n and the table\'s total agree' });
    expect(drillCheck(120, 118)).toMatchObject({ match: false });
    expect(drillCheck(120, 118).text).toBe('the square says 120 and the table 118: they were read at different moments, or one of them is wrong');
    expect(drillCheck(120, null)).toEqual({ match: null, text: 'reading the table\'s total…' });
  });
});

describe('the pairs of the trellis', () => {
  it('are the resolved pairs in the order the worker sent them, the first k, with the larger Δ as their priority', () => {
    const view = interactions(); // pairs: (0,1) (0,2) (1,2)* (0,3)* (1,3) (2,3); * = unresolved
    const t = trellisPairs(view, 3);
    expect(t.pairs.map((p) => p.index)).toEqual([[0, 1], [0, 2], [1, 3]]);
    expect(t.pairs[0].axes).toEqual([PATHS[0], PATHS[1]]);
    expect(t.pairs[0].label).toBe('ema.length × sma.length');
    expect(t.pairs[0].priority).toBe('Δ 10.0%');
    expect(t.resolved).toBe(4);
    expect(t.line).toBe('top 3 of 4 resolved pairs by the larger Δ · 6 pairs in all, 2 unresolved and not shown');
    expect(trellisPairs(view, 10).pairs).toHaveLength(4);
  });

  it('are never guessed: nothing before the first stage, and an unresolved pair is not drawn however large its J', () => {
    expect(trellisPairs(null, 6)).toMatchObject({ pairs: [], line: '' });
    expect(trellisPairs(interactions({ computed: null, pairs: [], total_pairs: 0, unresolved_pairs: 0, constants: null }), 6)).toMatchObject({ pairs: [], line: '' });
    const only = interactions({ pairs: [pair(0, 1, { unresolved: true, coverage: 0.2 })], total_pairs: 1, unresolved_pairs: 1 });
    expect(trellisPairs(only, 6).pairs).toEqual([]);
    expect(trellisPairs(only, 6).line).toBe('no resolved pair yet · 1 pair in all, 1 unresolved and not shown');
  });

});

describe('the scope breadcrumb', () => {
  it('asks the worker only for the counts it does not already have', () => {
    expect(breadcrumbPlan(NONE)).toEqual({ filtered: null, brushed: null });
    const brush: LabFilter = { ...NONE, ranges: { p: [1, 2] } };
    expect(breadcrumbPlan(brush)).toEqual({ filtered: null, brushed: brush }); // only a brush: nothing between completed and brushed
    const slice: LabFilter = { ...NONE, values: { p: 3 } };
    expect(breadcrumbPlan(slice)).toEqual({ filtered: slice, brushed: null }); // only a slice: the brush adds nothing
    const both: LabFilter = { ...NONE, scope: 'long', values: { p: 3 }, ranges: { q: [1, 2] } };
    expect(breadcrumbPlan(both)).toEqual({ filtered: { ...both, ranges: {} }, brushed: both });
  });

  it('reads completed and valid unique from the summary, filtered without the brush, brushed with it', () => {
    const both: LabFilter = { ...NONE, scope: 'long', values: { p: 3 }, ranges: { q: [1, 2] } };
    const steps = breadcrumbSteps(labCounts(), labCounts({ filtered: 6_000 }), labCounts({ filtered: 1_500 }), breadcrumbPlan(both));
    expect(steps.map((s) => [s.key, s.label, s.n, s.unit])).toEqual([
      ['completed', 'completed', 12_000, 'trials'],
      ['unique', 'valid unique', 11_800, 'configurations'],
      ['filtered', 'filtered', 6_000, 'trials'],
      ['brushed', 'brushed', 1_500, 'trials'],
    ]);
    expect(steps[2].note).toBe('p = 3 · direction: long only');
    expect(steps[3].note).toBe('q ∈ [1, 2]');
  });

  it('with no filter or no brush, the step is the one before it and says so; a count not yet answered is unknown, not zero', () => {
    const steps = breadcrumbSteps(labCounts(), null, null, breadcrumbPlan(NONE));
    expect(steps.map((s) => s.n)).toEqual([12_000, 11_800, 12_000, 12_000]);
    expect(steps[2].note).toBe('no filter');
    expect(steps[3].note).toBe('no brush');
    const waiting = breadcrumbSteps(labCounts(), null, null, breadcrumbPlan({ ...NONE, ranges: { q: [1, 2] } }));
    expect(waiting.map((s) => s.n)).toEqual([12_000, 11_800, 12_000, null]);
    expect(breadcrumbSteps(null, null, null, breadcrumbPlan(NONE)).map((s) => s.n)).toEqual([null, null, null, null]);
  });
});

describe('the robust neighbourhood map', () => {
  /** 3 × 3: IQR = 1 + r + c; (0, 0) is untested and (2, 2) has n 5 (low n). */
  const grid = aggregate([1, 2, 3], [10, 20, 30], (r, c) => (r === 0 && c === 0 ? { n: 0 } : { n: r === 2 && c === 2 ? 5 : 40, value: r * 3 + c, p25: 0, p75: 1 + r + c }));

  it('rings a square whose IQR is above the 75th percentile of the IQRs; an untested or low-n square has no ring', () => {
    const m = neighbourhoodModel(grid, 'net_pnl');
    // IQRs of the 7 tested squares with n >= 8: 2 2 3 3 3 4 4; their 75th percentile (linear) is 3.5.
    expect(m.p75Iqr).toBe(3.5);
    expect(m.squares.flat().filter((s) => s.ring).map((s) => [s.r, s.c])).toEqual([[1, 2], [2, 1]]);
    expect(m.rings).toBe(2);
    expect(m.squares[2][2]).toMatchObject({ n: 5, lowN: true, ring: false, iqr: 5 }); // IQR 5 is the largest, yet it is not ringed
    expect(m.squares[0][0]).toMatchObject({ n: 0, untested: true, value: null, ring: false, iqr: null });
  });

  it('hatches an untested square and never fills it: its value stays null and its tone empty', () => {
    const m = neighbourhoodModel(grid, 'net_pnl');
    expect(m.squares[0][0].tone).toBe('empty');
    expect(m.squares.flat().filter((s) => s.untested)).toHaveLength(1);
    expect(m.squares[1][1].n).toBe(40);
  });

  it('has no ring where every IQR is alike, and none where a square has no quartiles', () => {
    const flat = neighbourhoodModel(aggregate([1, 2], [1, 2], () => ({ n: 40, value: 1, p25: 0, p75: 2 })), 'net_pnl');
    expect(flat.rings).toBe(0);
    const none = neighbourhoodModel(aggregate([1, 2], [1, 2], () => ({ n: 40, value: 1, p25: null, p75: null })), 'net_pnl');
    expect(none.p75Iqr).toBeNull();
    expect(none.rings).toBe(0);
    expect(none.squares[0][0].iqr).toBeNull();
  });

  it('titles a square with its median, n and spread, and says why it is ringed', () => {
    const m = neighbourhoodModel(grid, 'net_pnl');
    expect(neighbourhoodTitle(m, m.squares[0][0], 'net_pnl')).toBe('L ema.length = 1 / L stop_loss_pct = 10 · untested: no trial');
    expect(neighbourhoodTitle(m, m.squares[1][2], 'net_pnl')).toBe('L ema.length = 2 / L stop_loss_pct = 30 · median $5 · n 40 · IQR $4, ringed: above the 75th percentile of the IQRs');
    expect(neighbourhoodTitle(m, m.squares[2][2], 'net_pnl')).toBe('L ema.length = 3 / L stop_loss_pct = 30 · median $8 · n 5 · low n · IQR $5');
  });

  it('finds the selected candidate\'s square by its two parameter values, and none for a value off the lattice', () => {
    expect(candidateSquare(grid, { [ROWS_PATH]: 2, [COLS_PATH]: 30 })).toEqual({ r: 1, c: 2 });
    expect(candidateSquare(grid, { [ROWS_PATH]: 2 })).toBeNull();
    expect(candidateSquare(grid, { [ROWS_PATH]: 2.5, [COLS_PATH]: 30 })).toBeNull();
    expect(candidateSquare(grid, { [ROWS_PATH]: 2, [COLS_PATH]: null })).toBeNull();
  });

  it('prints the candidate\'s A and B states from the card, with the coverage or the n that decided each', () => {
    const states = candidateStates(candidateCard());
    expect(states).toEqual([
      { name: 'A', state: 'tested', text: 'A · tested · stable local · n 7 (needs 7) · coverage 0.87 (needs 0.5)' },
      { name: 'B', state: 'unknown', text: 'B · unknown · too few sampled trials in the region (n 12 of 30) · n 12 (needs 30)' },
    ]);
    const unresolved = candidateStates(candidateCard({ categories: { ...candidateCard().categories, A: categoryA({ resolved: false, classification: null, reason: 'untested surroundings (n 3 of 7)' }), B: categoryB({ resolved: true, classification: 'stable region', reason: null }) } }));
    expect(unresolved[0]).toMatchObject({ name: 'A', state: 'unknown' });
    expect(unresolved[0].text).toBe('A · unknown · untested surroundings (n 3 of 7) · n 7 (needs 7) · coverage 0.87 (needs 0.5)');
    expect(unresolved[1]).toMatchObject({ name: 'B', state: 'tested' });
    expect(unresolved[1].text).toBe('B · tested · stable region · n 12 (needs 30)');
  });

});

describe('the family tree', () => {
  const surface: Surface = {
    parameters: [
      ['short_side.indicators.ema.length', 5, 20, 1],
      ['long_side.indicators.ema.length', 5, 20, 1],
      ['long_side.indicators.ema.params.smooth', 1, 3, 1],
      ['long_side.stop_loss_pct', 1, 5, 0.5],
    ].map(([path, start, stop, step]): Parameter => ({ path: path as string, start: start as number, stop: stop as number, step: step as number })),
  };
  const spec = { id: 's', name: 'S', description: '', long_side: { direction: 'long', indicators: [{ id: 'ema', kind: 'ema', length: 9 }] }, short_side: { direction: 'short', indicators: [{ id: 'ema', kind: 'ema', length: 9 }] } } as unknown as StrategySpec;
  /** A parameter of `length` values with a trial at each of the `at` positions. */
  const param = (path: string, length: number, at: number[] = []): LabParameter => ({ path, side: 'long', family: 'ema', type: 'int', start: 0, stop: length, step: 1, n_values: length, values: null, tested_per_value: Array.from({ length }, (_, i) => (at.includes(i) ? 3 : 0)), bucketed: false });

  it('groups by side and then indicator id, the long side first, with the counts of each family', () => {
    const tree = familyTree(families(surface, spec), [
      param('long_side.indicators.ema.length', 16, [0, 2, 3]),
      param('long_side.indicators.ema.params.smooth', 3, [0, 1]),
      param('long_side.stop_loss_pct', 9, [0, 1, 2, 3, 4, 5, 6, 7, 8]),
      param('short_side.indicators.ema.length', 16),
    ]);
    expect(tree.map((f) => [f.key, f.side, f.id])).toEqual([['long:ema', 'long', 'ema'], ['long:levels', 'long', 'levels'], ['short:ema', 'short', 'ema']]);
    expect(tree[0]).toMatchObject({ parameters: 2, values: 16 + 3, tested: 3 + 2 });
    expect(tree[0].entries.map((e) => [e.field, e.tested, e.of])).toEqual([['length', 3, 16], ['params.smooth', 2, 3]]);
    expect(tree[0].text).toBe('2 parameters · 5 of 19 values tested');
    expect(tree[2].text).toBe('1 parameter · 0 of 16 values tested');
  });

  it('knows nothing it was not told: no summary, or a path the summary lacks, leaves the tested count unknown, never zero', () => {
    const tree = familyTree(families(surface, spec), null);
    expect(tree[0].entries.every((e) => e.tested === null)).toBe(true);
    expect(tree[0].tested).toBeNull();
    expect(tree[0].text).toBe('2 parameters · 19 values');
    const partial = familyTree(families(surface, spec), [param('long_side.indicators.ema.length', 16, [0, 2, 3])]);
    expect(partial[0].entries.map((e) => e.tested)).toEqual([3, null]);
    expect(partial[0].tested).toBeNull();
  });
});

describe('what a square prints', () => {
  it('abbreviates a count to fit a square', () => {
    expect([0, 7, 999, 1000, 1200, 12_000, 999_999, 2_500_000].map(countLabel)).toEqual(['0', '7', '999', '1k', '1.2k', '12k', '1M', '2.5M']);
  });

  it('names a value or a merged group', () => {
    expect(rangeText([15, 15])).toBe('15');
    expect(rangeText([1, 1.5])).toBe('1–1.5');
    expect(rangeText([0.30000000000000004, 0.30000000000000004])).toBe('0.3');
  });

  it('titles a square with where it is and what it holds, or why it holds nothing', () => {
    const m = trellisModel(aggregate([1, 2], [1, 2], (r, c) => ({ n: [[0, 10], [40, 40]][r][c], value: [[0, 5000], [-30, null as unknown as number]][r][c] })), 'median', 'net_pnl');
    expect(cellTitle(m, m.cells[0][0], 'net_pnl')).toBe('L ema.length = 1 / L stop_loss_pct = 1 · untested: no trial');
    expect(cellTitle(m, m.cells[0][1], 'net_pnl')).toBe('L ema.length = 1 / L stop_loss_pct = 2 · n 10: under 30, hatched and left out of the scale (median $5,000, not drawn)');
    expect(cellTitle(m, m.cells[1][0], 'net_pnl')).toBe('L ema.length = 2 / L stop_loss_pct = 1 · median -$30 · n 40');
    expect(cellTitle(m, m.cells[1][1], 'net_pnl')).toBe('L ema.length = 2 / L stop_loss_pct = 2 · n 40 · no net_pnl value');
  });
});

describe('the picked square', () => {
  const m = trellisModel(aggregate(range(1, 17), [1, 2], () => ({ n: 40, value: 1 })), 'mean', 'net_pnl');
  const pick = pickOf(0, m, m.cells[2][1]);

  it('is the square with the same pair and the same ranges, and no other', () => {
    expect(isPicked(pick, m, m.cells[2][1])).toBe(true);
    expect(isPicked(pick, m, m.cells[2][0])).toBe(false);
    expect(isPicked(pick, m, m.cells[3][1])).toBe(false);
    expect(isPicked(null, m, m.cells[2][1])).toBe(false);
    const other = trellisModel({ ...aggregate(range(1, 17), [1, 2], () => ({ n: 40, value: 1 })), cols_path: 'long_side.take_profit_pct' }, 'mean', 'net_pnl');
    expect(isPicked(pick, other, other.cells[2][1])).toBe(false); // another pair
  });

  it('takes the n the square has now, and is the same object when it has not moved', () => {
    expect(refreshedPick(pick, m)).toBe(pick);
    const grown = trellisModel(aggregate(range(1, 17), [1, 2], (r) => ({ n: r === 4 || r === 5 ? 55 : 40, value: 1 })), 'mean', 'net_pnl');
    expect(refreshedPick(pick, grown)).toEqual({ ...pick, n: 110 });
    const gone = trellisModel(aggregate([1, 2], [1, 2], () => ({ n: 40, value: 1 })), 'mean', 'net_pnl');
    expect(refreshedPick(pick, gone)).toBe(pick); // the lattice changed under it: nothing to read
  });
});

// --- the markup the walk reads (Ruling P3: `lab-families-<part>`) --------------------------------------------------------

/** One attribute of the element with `id` in static markup; undefined when the id or the attribute is absent. */
function attribute(markup: string, id: string, name: string): string | undefined {
  const tag = new RegExp(`<[a-z]+ [^>]*id="${id}"[^>]*>`).exec(markup)?.[0];
  return tag === undefined ? undefined : new RegExp(` ${name}="([^"]*)"`).exec(tag)?.[1];
}

describe('the trellis markup', () => {
  const model = trellisModel(aggregate([1, 2], [1, 2, 3], (r, c) => ({ n: [[0, 10, 45], [1200, 29, 30]][r][c], value: [[0, 5000, 100], [-30, 7, 50]][r][c] })), 'median', 'net_pnl');
  const html = renderToStaticMarkup(createElement(TrellisGrid, { model, index: 2, label: 'ema.length × stop_loss_pct', pick: pickOf(2, model, model.cells[1][0]), metric: 'net_pnl', onPick: () => undefined }));

  it('gives every square an id with its pair and place, and its exact n as data-n', () => {
    expect([[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2]].map(([r, c]) => attribute(html, `lab-families-cell-2-${r}-${c}`, 'data-n'))).toEqual(['0', '10', '45', '1200', '29', '30']);
    expect(attribute(html, 'lab-families-cell-2-1-0', 'data-rows')).toBe('2,2');
    expect(html).toContain('>1.2k<'); // the square prints a compact n
  });

  it('marks each square\'s state: untested, thin at 29, drawn at 30, and the picked one', () => {
    expect(['0-0', '0-1', '1-0', '1-1', '1-2'].map((at) => attribute(html, `lab-families-cell-2-${at}`, 'data-state'))).toEqual(['untested', 'thin', 'ok', 'thin', 'ok']);
    expect(attribute(html, 'lab-families-cell-2-1-0', 'aria-pressed')).toBe('true');
    expect(attribute(html, 'lab-families-cell-2-0-2', 'aria-pressed')).toBe('false');
    expect(attribute(html, 'lab-families-cell-2-1-0', 'class')).toContain('selected');
    // An untested square is hatched and cannot be picked; a thin one is hatched by its state and can.
    expect(attribute(html, 'lab-families-cell-2-0-0', 'class')).toContain('hatched');
    expect(attribute(html, 'lab-families-cell-2-0-0', 'aria-disabled')).toBe('true');
    expect(attribute(html, 'lab-families-cell-2-0-1', 'aria-disabled')).toBe('false');
    expect(attribute(html, 'lab-families-cell-2-1-0', 'class')).toContain('loss'); // 1200 trials at -30: red
  });
});

describe('the drill-down markup', () => {
  it('prints the square\'s n and the table\'s total as exact attributes, and whether they match', () => {
    const agree = renderToStaticMarkup(createElement(DrillCheck, { squareN: 1200, total: 1200 }));
    expect(attribute(agree, 'lab-families-drill-n', 'data-n')).toBe('1200');
    expect(attribute(agree, 'lab-families-drill-total', 'data-total')).toBe('1200');
    expect(attribute(agree, 'lab-families-drill-check', 'data-match')).toBe('true');
    expect(agree).toContain('1,200');
    const differ = renderToStaticMarkup(createElement(DrillCheck, { squareN: 1200, total: 1199 }));
    expect(attribute(differ, 'lab-families-drill-check', 'data-match')).toBe('false');
    const waiting = renderToStaticMarkup(createElement(DrillCheck, { squareN: 1200, total: null }));
    expect(attribute(waiting, 'lab-families-drill-total', 'data-total')).toBe('');
    expect(attribute(waiting, 'lab-families-drill-check', 'data-match')).toBe('');
  });
});

describe('the breadcrumb markup', () => {
  it('gives each step its exact count, empty while it is not known', () => {
    const html = renderToStaticMarkup(createElement(CrumbSteps, { steps: breadcrumbSteps(labCounts(), null, null, breadcrumbPlan({ ...NONE, ranges: { q: [1, 2] } })) }));
    expect(['completed', 'unique', 'filtered', 'brushed'].map((key) => attribute(html, `lab-families-crumb-${key}`, 'data-n'))).toEqual(['12000', '11800', '12000', '']);
  });
});

describe('the page, first render', () => {
  const surface: Surface = {
    parameters: [['long_side.indicators.ema.length', 5, 20, 1], ['long_side.indicators.sma.length', 20, 100, 5], ['long_side.stop_loss_pct', 1, 5, 0.5]].map(
      ([path, start, stop, step]): Parameter => ({ path: path as string, start: start as number, stop: stop as number, step: step as number }),
    ),
  };
  const document = { id: 'e1', name: 'E', status: 'done', objective: 'net_pnl', surface, spec: { id: 's', name: 'S', description: '', long_side: { direction: 'long', indicators: [{ id: 'ema', kind: 'ema', length: 9 }] }, short_side: null } };
  // The fields of the Lab's data the page reads before any answer: nothing is asked in a static render (effects do not run).
  const data = (loaded: unknown) =>
    ({
      loaded,
      loading: false,
      query: () => Promise.resolve(null),
      tick: 0,
      summary: null,
      summaryError: null,
      knownRows: {},
      importanceDone: 0,
      noteTask: () => undefined,
      watchTask: () => undefined,
    }) as unknown as LabQueryData;
  const props = { sort: { column: null, descending: true }, onSort: () => undefined, onSelect: () => undefined, memory: { current: { key: '', top: 0 } } };

  it('draws every panel with no answer yet, the parallel mode on bundles, and asks for nothing it cannot name', () => {
    const html = renderToStaticMarkup(createElement(FamiliesPage, { data: data({ kind: 'exp', id: 'e1', document, report: null, strategyName: 'S' }), ...props }));
    for (const id of ['lab-families', 'lab-families-catalog', 'lab-families-search', 'lab-families-maximize', 'lab-families-breadcrumb', 'lab-families-trellis', 'lab-families-neighbourhood', 'lab-families-drill', 'lab-parallel-mode', 'lab-families-pinned'])
      expect(attribute(html, id, 'id'), id).toBe(id);
    expect(attribute(html, 'lab-parallel-mode', 'data-mode')).toBe('bundles');
    expect(attribute(html, 'lab-families-family-long-ema', 'data-parameters')).toBe('1');
    expect(attribute(html, 'lab-families-family-long-levels', 'data-parameters')).toBe('1');
    expect(html).toContain('pick a trellis square to see the trials in it');
    expect(html).toContain('no candidate selected');
  });

  it('with no source open says so and draws no panel', () => {
    const html = renderToStaticMarkup(createElement(FamiliesPage, { data: data(null), ...props }));
    expect(html).toContain('No source open: choose one in the context bar.');
    expect(attribute(html, 'lab-families-trellis', 'id')).toBeUndefined();
  });
});
