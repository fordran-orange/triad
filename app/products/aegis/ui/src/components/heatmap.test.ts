import { describe, expect, it } from 'vitest';
import { cells } from './Heatmap';

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
