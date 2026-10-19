import { describe, expect, it } from 'vitest';
import { cells, profitKind } from './Heatmap';

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
