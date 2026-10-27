import { describe, expect, it } from 'vitest';
import { OVERSCAN, PAGE_LIMIT, ROW_HEIGHT, pageFor, windowRows } from './trialWindow';

describe('constants', () => {
  it('uses 22 px rows, 10 rows of overscan and pages of at most 500', () => {
    expect(ROW_HEIGHT).toBe(22);
    expect(OVERSCAN).toBe(10);
    expect(PAGE_LIMIT).toBe(500);
  });
});

describe('windowRows', () => {
  it('at the top renders the visible rows plus the overscan below them', () => {
    const w = windowRows({ total: 10_000, scrollTop: 0, viewportHeight: 440 });
    expect(w.start).toBe(0);
    expect(w.end).toBe(30); // 20 visible + 10 overscan
    expect(w.padTop).toBe(0);
    expect(w.padBottom).toBe((10_000 - 30) * 22);
  });

  it('at the bottom ends exactly on the last row and reaches back by the visible rows plus the overscan', () => {
    const w = windowRows({ total: 10_000, scrollTop: 10_000 * 22 - 440, viewportHeight: 440 });
    expect(w.end).toBe(10_000);
    expect(w.start).toBe(10_000 - 30);
    expect(w.padTop).toBe((10_000 - 30) * 22);
    expect(w.padBottom).toBe(0);
  });

  it('in the middle renders the overscan above and below the visible rows', () => {
    const w = windowRows({ total: 10_000, scrollTop: 500 * 22, viewportHeight: 440 });
    expect(w.start).toBe(490);
    expect(w.end).toBe(530);
    expect(w.padTop).toBe(490 * 22);
    expect(w.padBottom).toBe((10_000 - 530) * 22);
  });

  it('counts a partly visible last row as visible', () => {
    // 450 px is 20 full rows and a 10 px sliver of the 21st
    const w = windowRows({ total: 10_000, scrollTop: 0, viewportHeight: 450, overscan: 0 });
    expect(w.end - w.start).toBe(21);
  });

  it('honours a custom row height and overscan', () => {
    const w = windowRows({ total: 1_000, scrollTop: 400, viewportHeight: 100, rowHeight: 20, overscan: 2 });
    // first = 20, visible = 5
    expect(w.start).toBe(18);
    expect(w.end).toBe(27);
    expect(w.padTop).toBe(18 * 20);
    expect(w.padBottom).toBe((1_000 - 27) * 20);
  });

  it('shows every row with no pad when the list is shorter than the viewport', () => {
    const w = windowRows({ total: 5, scrollTop: 0, viewportHeight: 440 });
    expect(w).toEqual({ start: 0, end: 5, padTop: 0, padBottom: 0 });
  });

  it('returns the empty window for no rows', () => {
    expect(windowRows({ total: 0, scrollTop: 0, viewportHeight: 440 })).toEqual({
      start: 0,
      end: 0,
      padTop: 0,
      padBottom: 0,
    });
    expect(windowRows({ total: 0, scrollTop: 9_999, viewportHeight: 440 })).toEqual({
      start: 0,
      end: 0,
      padTop: 0,
      padBottom: 0,
    });
  });

  it('clamps an overscrolled scrollTop to the last row', () => {
    const w = windowRows({ total: 100, scrollTop: 1_000_000, viewportHeight: 440 });
    expect(w.end).toBe(100);
    expect(w.start).toBe(100 - 1 - OVERSCAN);
    expect(w.padTop + (w.end - w.start) * 22 + w.padBottom).toBe(100 * 22);
  });

  it('clamps a negative scrollTop to the top', () => {
    const w = windowRows({ total: 100, scrollTop: -300, viewportHeight: 440 });
    expect(w.start).toBe(0);
    expect(w.end).toBe(30);
  });

  it('still renders a row when the viewport has not been measured yet', () => {
    const w = windowRows({ total: 100, scrollTop: 0, viewportHeight: 0, overscan: 0 });
    expect(w.end - w.start).toBe(1);
  });

  it('keeps pad + rendered rows equal to the full list height, with a bounded window, for 50 seeded random inputs', () => {
    // A small linear-congruential generator keeps the draws reproducible without a dependency.
    let seed = 20261027;
    const next = (max: number): number => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed % max;
    };
    for (let i = 0; i < 50; i++) {
      const total = 1 + next(1_000_000);
      const rowHeight = 10 + next(40);
      const overscan = next(25);
      const viewportHeight = 1 + next(2_000);
      const scrollTop = next(total * rowHeight + 5_000) - 500; // includes negative and overscrolled
      const w = windowRows({ total, scrollTop, viewportHeight, rowHeight, overscan });
      const visible = Math.ceil(viewportHeight / rowHeight);
      const label = JSON.stringify({ total, scrollTop, viewportHeight, rowHeight, overscan, w });

      expect(w.padTop + (w.end - w.start) * rowHeight + w.padBottom, label).toBe(total * rowHeight);
      expect(w.end - w.start, label).toBeLessThanOrEqual(visible + 2 * overscan);
      expect(w.end - w.start, label).toBeGreaterThanOrEqual(1);
      expect(w.start, label).toBeGreaterThanOrEqual(0);
      expect(w.end, label).toBeLessThanOrEqual(total);
    }
  });
});

describe('pageFor', () => {
  it('asks the server for the rows the window renders', () => {
    const w = windowRows({ total: 10_000, scrollTop: 500 * 22, viewportHeight: 440 });
    expect(pageFor(w)).toEqual({ offset: 490, limit: 40 });
  });

  it('caps the limit at 500 rows however tall the window is', () => {
    const w = windowRows({ total: 10_000, scrollTop: 0, viewportHeight: 13_000 });
    expect(w.end - w.start).toBeGreaterThan(PAGE_LIMIT);
    expect(pageFor(w)).toEqual({ offset: 0, limit: 500 });
  });

  it('takes a smaller limit when asked', () => {
    const w = windowRows({ total: 10_000, scrollTop: 0, viewportHeight: 440 });
    expect(pageFor(w, 25)).toEqual({ offset: 0, limit: 25 });
  });

  it('asks for nothing when there are no rows', () => {
    expect(pageFor(windowRows({ total: 0, scrollTop: 0, viewportHeight: 440 }))).toEqual({ offset: 0, limit: 0 });
  });

  it('asks for at least one row for every non-empty window', () => {
    for (const total of [1, 7, 10_000]) {
      for (const scrollTop of [0, 22 * 3, 22 * 9_999]) {
        const { limit } = pageFor(windowRows({ total, scrollTop, viewportHeight: 440 }));
        expect(limit).toBeGreaterThanOrEqual(1);
      }
    }
  });
});
