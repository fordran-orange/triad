// Pure helpers for comparing two backtests (Mission 9 spec §7); no React, no fetch.
import { DASH, money, num } from './format';
import type { CompareMetricRow, ComparePoint } from './results';

export type CurveUnit = 'pct' | 'usd' | 'dd';

export const METRIC_NAMES: Record<string, string> = {
  net_pnl: 'Net P&L',
  net_return: 'Net return',
  cagr: 'CAGR',
  max_drawdown: 'Max drawdown',
  mar: 'MAR',
  win_rate: 'Win rate',
  expectancy: 'Expectancy',
  profit_factor: 'Profit factor',
  trade_count: 'Trades',
  exposure: 'Exposure',
};

const MONEY = new Set(['net_pnl', 'expectancy']);
const PERCENT = new Set(['net_return', 'cagr', 'max_drawdown', 'win_rate', 'exposure']);

/** Drawdown is drawn below zero; return and dollars as they are. */
const valueOf = (p: ComparePoint, unit: CurveUnit) => (unit === 'dd' ? -p.dd : p[unit]);

/** Both runs' curves as SVG paths on the union of their dates and one value range, so the two
 *  lines compare by position (spec §7: one calendar axis). */
export function curvePaths(
  equity: { a: ComparePoint[]; b: ComparePoint[] },
  width: number,
  height: number,
  unit: CurveUnit,
): { a: string; b: string; domain: { start: number; end: number } | null; range: { min: number; max: number } | null } {
  const all = [...equity.a, ...equity.b];
  if (all.length === 0) return { a: '', b: '', domain: null, range: null };
  const times = all.map((p) => Date.parse(p.t));
  const values = all.map((p) => valueOf(p, unit));
  if (unit === 'dd') values.push(0);
  const domain = { start: Math.min(...times), end: Math.max(...times) };
  const range = { min: Math.min(...values), max: Math.max(...values) };
  const span = domain.end - domain.start || 1;
  const height_ = range.max - range.min || 1;
  const path = (points: ComparePoint[]) =>
    points
      .map((p, i) => {
        const x = ((Date.parse(p.t) - domain.start) / span) * width;
        const y = height - ((valueOf(p, unit) - range.min) / height_) * height;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  return { a: path(equity.a), b: path(equity.b), domain, range };
}

const signed = (text: string, value: number) => (value > 0 ? '+' + text : text);

/** B − A in the metric's own unit: dollars, percentage points, a ratio or a count. */
export function diffText(row: CompareMetricRow): string {
  const d = row.diff;
  if (d === null || d === undefined || Number.isNaN(d)) return DASH;
  if (MONEY.has(row.metric)) return signed(money(d), d);
  if (PERCENT.has(row.metric)) return signed(`${(d * 100).toFixed(2)} pp`, d);
  if (row.metric === 'trade_count') return signed(num(d, 0), d);
  return signed(num(d, 2), d);
}
