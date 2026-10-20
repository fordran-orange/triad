import { describe, expect, it } from 'vitest';
import { curvePaths, diffText } from './compare';
import type { CompareMetricRow, ComparePoint } from './results';

const EQUITY: { a: ComparePoint[]; b: ComparePoint[] } = {
  a: [
    { t: '2024-01-01T00:00:00+00:00', pct: 0, usd: 100_000, dd: 0 },
    { t: '2024-01-03T00:00:00+00:00', pct: 0.1, usd: 110_000, dd: 0 },
  ],
  b: [
    { t: '2024-01-02T00:00:00+00:00', pct: 0, usd: 50_000, dd: 0 },
    { t: '2024-01-05T00:00:00+00:00', pct: -0.1, usd: 45_000, dd: 0.1 },
  ],
};

const row = (metric: string, diff: number | null): CompareMetricRow => ({ metric, a: 1, b: 1, diff, mark: null });

describe('compare helpers', () => {
  it('curvePaths puts both runs on one calendar domain and one value range, in either unit', () => {
    const pct = curvePaths(EQUITY, 400, 100, 'pct');
    expect(pct.domain).toEqual({ start: Date.parse('2024-01-01T00:00:00Z'), end: Date.parse('2024-01-05T00:00:00Z') });
    expect(pct.range).toEqual({ min: -0.1, max: 0.1 });
    expect(pct.a).toBe('M0.0 50.0 L200.0 0.0');
    expect(pct.b).toBe('M100.0 50.0 L400.0 100.0');

    const usd = curvePaths(EQUITY, 400, 100, 'usd');
    expect(usd.range).toEqual({ min: 45_000, max: 110_000 });
    expect(usd.a).toBe('M0.0 15.4 L200.0 0.0');
    expect(usd.b).toBe('M100.0 92.3 L400.0 100.0');
  });

  it('curvePaths draws drawdown down from zero', () => {
    const dd = curvePaths(EQUITY, 400, 100, 'dd');
    expect(dd.range).toEqual({ min: -0.1, max: 0 });
    expect(dd.a).toBe('M0.0 0.0 L200.0 0.0');
    expect(dd.b).toBe('M100.0 0.0 L400.0 100.0');
  });

  it('curvePaths of nothing draws nothing', () => {
    expect(curvePaths({ a: [], b: [] }, 400, 100, 'pct')).toEqual({ a: '', b: '', domain: null, range: null });
  });

  it('diffText signs money, percentage points, ratios and counts; a dash for nulls', () => {
    expect(diffText(row('net_pnl', 1234.5))).toBe('+$1,235');
    expect(diffText(row('expectancy', -50))).toBe('-$50');
    expect(diffText(row('net_pnl', 0))).toBe('$0');
    expect(diffText(row('win_rate', 0.05))).toBe('+5.00 pp');
    expect(diffText(row('max_drawdown', -0.0123))).toBe('-1.23 pp');
    expect(diffText(row('mar', 0.12))).toBe('+0.12');
    expect(diffText(row('profit_factor', -0.5))).toBe('-0.50');
    expect(diffText(row('trade_count', -3))).toBe('-3');
    expect(diffText(row('net_pnl', null))).toBe('—');
  });
});
