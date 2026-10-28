import { describe, expect, it } from 'vitest';
import { badge, cells, profitKind, testedCounts } from './Heatmap';

describe('heatmap mapping', () => {
  it('matrix maps to cells with fast rows and slow columns', () => {
    const grid = cells([5, 6], [8, 9, 10], [
      [1, 4, null],
      [null, -2, 3],
    ]);
    expect(grid).toHaveLength(2);
    expect(grid[0]).toHaveLength(3);
    expect(grid[0][0]).toMatchObject({ fast: 5, slow: 8, value: 1 });
    expect(grid[1][1]).toMatchObject({ fast: 6, slow: 9, value: -2, tone: 'cool' });
    expect(grid[0][1]).toMatchObject({ fast: 5, slow: 9, value: 4, tone: 'hot' });
  });

  it('null cells render as skipped', () => {
    const grid = cells([5, 6], [8, 9], [
      [null, 2],
      [null, null],
    ]);
    expect(grid[0][0]).toMatchObject({ value: null, tone: 'empty' });
    expect(grid[1].every((c) => c.value === null && c.tone === 'empty')).toBe(true);
    expect(cells([5], [8], null)[0][0]).toMatchObject({ value: null, tone: 'empty' });
  });
});


describe('heatmap orientation', () => {
  it('flips the tones when lower is better', () => {
    const grid = cells([5], [8, 9, 10], [[1, 5, 9]], true);
    expect(grid[0].map((c) => c.tone)).toEqual(['hot', 'mid', 'cool']);
    expect(cells([5], [8, 9, 10], [[1, 5, 9]])[0].map((c) => c.tone)).toEqual(['cool', 'mid', 'hot']);
  });
});

describe('losing money is red, always (operator, 2026-10-19)', () => {
  it('a negative profit value is a loss whatever its rank', () => {
    expect(cells([5], [8, 9, 10, 11], [[-50, -10, -1, 20]], false, 'sign')[0].map((c) => c.tone)).toEqual(['loss', 'loss', 'loss', 'hot']);
  });

  it('when every cell loses, none is green', () => {
    expect(cells([5], [8, 9, 10], [[-30, -20, -10]], false, 'sign')[0].map((c) => c.tone)).toEqual(['loss', 'loss', 'loss']);
  });

  it('gains rank among themselves and zero is neutral', () => {
    expect(cells([5], [8, 9, 10, 11], [[0, 10, 50, 100]], false, 'sign')[0].map((c) => c.tone)).toEqual(['mid', 'gain', 'gain', 'hot']);
  });

  it('a profit factor below 1 loses money', () => {
    expect(cells([5], [8, 9, 10, 11], [[0.5, 0.99, 1.2, 2.0]], false, 'ratio')[0].map((c) => c.tone)).toEqual(['loss', 'loss', 'gain', 'hot']);
  });

  it('profitKind names the metrics whose sign is money', () => {
    expect(['net_pnl', 'net_return', 'cagr', 'mar', 'expectancy'].map(profitKind)).toEqual(['sign', 'sign', 'sign', 'sign', 'sign']);
    expect(profitKind('profit_factor')).toBe('ratio');
    expect(['max_drawdown', 'trade_count', 'win_rate', 'exposure'].map(profitKind)).toEqual([null, null, null, null]);
  });
});

describe('the dock overlays (Task 10): n badges and hatched untested squares', () => {
  it('cells() keeps its tone rules: the overlays never change a tone', () => {
    const matrix = [
      [-5, 0, 10],
      [null, 40, 100],
    ];
    const grid = cells([5, 6], [8, 9, 10], matrix, false, 'sign');
    expect(grid.map((r) => r.map((c) => c.tone))).toEqual([
      ['loss', 'mid', 'gain'],
      ['empty', 'gain', 'hot'],
    ]);
    const counts = [
      [1, 1, 1],
      [0, 1, 1],
    ];
    expect(grid.map((r, i) => r.map((c, j) => badge(counts, i, j, c.tone)).map((b) => b.hatched))).toEqual([
      [false, false, false],
      [true, false, false],
    ]);
    expect(cells([5, 6], [8, 9, 10], matrix, false, 'sign')).toEqual(grid);
  });

  it('badge formats n and marks an empty square hatched only when counts is given', () => {
    expect(badge(undefined, 0, 0, 'empty')).toEqual({ n: null, text: null, hatched: false });
    expect(badge(null, 1, 1, 'hot')).toEqual({ n: null, text: null, hatched: false });
    const counts = [
      [0, 3],
      [1200, 2_500_000],
    ];
    expect(badge(counts, 0, 0, 'empty')).toEqual({ n: 0, text: null, hatched: true });
    expect(badge(counts, 0, 1, 'hot')).toEqual({ n: 3, text: '3', hatched: false });
    expect(badge(counts, 1, 0, 'gain')).toEqual({ n: 1200, text: '1.2k', hatched: false });
    expect(badge(counts, 1, 1, 'loss')).toEqual({ n: 2_500_000, text: '2.5M', hatched: false });
    // Tested with no value (every trial there null-valued): counted, never hatched, never coloured.
    expect(badge(counts, 0, 1, 'empty')).toEqual({ n: 3, text: '3', hatched: false });
    // A square outside the counts is untested.
    expect(badge(counts, 5, 5, 'empty')).toEqual({ n: 0, text: null, hatched: true });
  });
});

describe('the dock counts tested squares from trade_count (defined for every evaluated cell)', () => {
  // A grid above CELLS_SENT: the status lists only the best 1,000 cells, but its matrices cover every evaluated
  // cell. MAR is undefined below a year (Review Focus 3): a tested square without a MAR value is tested, not untested.
  const matrices = {
    net_pnl: { long: [[-5, 3], [null, 12]] },
    mar: { long: [[null, null], [null, null]] },
    max_drawdown: { long: [[0.1, 0.2], [null, 0.3]] },
    trade_count: { long: [[0, 14], [null, 40]] },
  };

  it('testedCounts is 1 where trade_count is defined (zero trades included) and 0 where no trial ran', () => {
    expect(testedCounts(matrices, 'long')).toEqual([
      [1, 1],
      [0, 1],
    ]);
  });

  it('a null-valued metric over an evaluated square: n 1, not hatched; an untested square: n 0, hatched', () => {
    const counts = testedCounts(matrices, 'long');
    const grid = cells([5, 6], [20, 25], matrices.mar.long, false, 'sign');
    expect(grid[0][0].tone).toBe('empty'); // MAR undefined: no colour
    expect(badge(counts, 0, 0, grid[0][0].tone)).toEqual({ n: 1, text: '1', hatched: false });
    expect(badge(counts, 1, 0, grid[1][0].tone)).toEqual({ n: 0, text: null, hatched: true });
  });

  it('is null when the status carries no trade_count matrix for the side (no badges, no hatch: never a guess)', () => {
    expect(testedCounts({}, 'long')).toBeNull();
    expect(testedCounts(matrices, 'short')).toBeNull();
    expect(testedCounts(undefined, 'long')).toBeNull();
  });
});
