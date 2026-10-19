import { describe, expect, it } from 'vitest';
import { RESULTS_DEFAULT, RESULTS_MIN, clampResultsHeight, compactMoney, heatTemplate, loadResultsHeight, saveResultsHeight } from './layout';

describe('results panel height (operator, 2026-10-19)', () => {
  it('clamps to the minimum and to 80% of the window', () => {
    expect(clampResultsHeight(40, 1000)).toBe(RESULTS_MIN);
    expect(clampResultsHeight(500, 1000)).toBe(500);
    expect(clampResultsHeight(950, 1000)).toBe(800);
    expect(clampResultsHeight(Number.NaN, 1000)).toBe(RESULTS_DEFAULT);
    expect(clampResultsHeight(300, 150)).toBe(RESULTS_MIN); // a tiny window never goes below the minimum
  });

  it('remembers a height per viewer and survives storage that throws', () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(loadResultsHeight(storage, 1000)).toBe(RESULTS_DEFAULT);
    saveResultsHeight(storage, 420);
    expect(loadResultsHeight(storage, 1000)).toBe(420);
    expect(loadResultsHeight(storage, 400)).toBe(320); // re-clamped to a smaller window
    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    expect(loadResultsHeight(broken, 1000)).toBe(RESULTS_DEFAULT);
    expect(() => saveResultsHeight(broken, 420)).not.toThrow();
    expect(loadResultsHeight(null, 1000)).toBe(RESULTS_DEFAULT);
  });
});

describe('the matrix fits itself', () => {
  it('gives every column a minimum width that holds a compact value and lets cells grow', () => {
    expect(heatTemplate(17)).toBe('72px repeat(17, minmax(56px, 1fr))');
    expect(heatTemplate(3, 40)).toBe('40px repeat(3, minmax(56px, 1fr))');
  });

  it('writes money compactly, keeping the sign', () => {
    expect(compactMoney(47239)).toBe('$47.2k');
    expect(compactMoney(-3425.4)).toBe('-$3.4k');
    expect(compactMoney(812)).toBe('$812');
    expect(compactMoney(-0.4)).toBe('-$0');
    expect(compactMoney(1_234_567)).toBe('$1.23M');
    expect(compactMoney(999_960)).toBe('$1.00M');
  });
});
