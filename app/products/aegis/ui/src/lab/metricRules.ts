// The Lab's metric rules, pure and in one place (nothing React, nothing drawn, no component imported): where a metric stops
// losing money, whether a value loses (and so is red whatever its rank: operator, 2026-10-19), which way a metric reads,
// and how a metric's value is printed. The dock's `Heatmap` and every Lab model and panel read these, so a loss is the same
// loss on a square, a ranking, a point and a card, and "max drawdown is lower-is-better" is said once (the worker's
// `LOWER_IS_BETTER`).
import { DASH, money, num, pct } from '../format';
import { OBJECTIVE_LABELS, PERCENT_OBJECTIVES, type Objective } from '../results';
import { SHARPE, SHARPE_LABEL } from './labQuery';

/** 'sign': below 0 loses money (net P&L, return, CAGR, MAR, expectancy, the trade Sharpe); 'ratio': below 1 loses money
 *  (profit factor); null: the metric has no profit sign. The server's `BREAK_EVEN` (lab/policy.py) names the same metrics
 *  at the same values. */
export type ProfitKind = 'sign' | 'ratio' | null;

const SIGNED = new Set(['net_pnl', 'net_return', 'cagr', 'mar', 'expectancy', 'sharpe_trade']);

export function profitKind(metric: string): ProfitKind {
  if (SIGNED.has(metric)) return 'sign';
  return metric === 'profit_factor' ? 'ratio' : null;
}

/** Where a metric stops losing money: 0, or 1 for a ratio such as the profit factor; null for a metric with no profit sign
 *  (a drawdown, a count, a share). */
export function breakEven(metric: string): number | null {
  const kind = profitKind(metric);
  return kind === null ? null : kind === 'ratio' ? 1 : 0;
}

/** The tone of a value by its profit sign: below break-even is a loss (red whatever its rank), above is a gain, break-even
 *  itself and any value of a metric with no profit sign (or no value) are neither. */
export function lossTone(metric: string, value: number | null): 'loss' | 'gain' | undefined {
  const even = breakEven(metric);
  if (value === null || even === null) return undefined;
  return value < even ? 'loss' : value > even ? 'gain' : undefined;
}

/** Whether `value` of `metric` loses money (strictly below its break-even). */
export function losesMoney(metric: string, value: number | null): boolean {
  return lossTone(metric, value) === 'loss';
}

/** Whether lower is better: `max_drawdown`, and nothing else. */
export function lowerIsBetter(metric: string): boolean {
  return metric === 'max_drawdown';
}

/** The sign the worker gives a metric's values to make higher better: -1 for a lower-is-better metric, else 1. */
export function orientationOf(metric: string): 1 | -1 {
  return lowerIsBetter(metric) ? -1 : 1;
}

/** The metric of a `<scope>.<metric>` column (`combined.net_pnl` is `net_pnl`); a bare metric stays as it is. Labels use this. */
export function bareMetric(column: string): string {
  const dot = column.indexOf('.');
  return dot < 0 ? column : column.slice(dot + 1);
}

/** A metric as the panels name it: the objective's label, the trade Sharpe with its qualifiers. */
export function metricName(metric: string): string {
  if (metric === SHARPE) return SHARPE_LABEL;
  return (OBJECTIVE_LABELS as Record<string, string>)[metric] ?? metric;
}

/** An objective's value as the reports print it: money for P&L and expectancy, a percentage for the shares, two decimals
 *  for the ratios and the trade Sharpe, whole trades. */
export function objectiveText(objective: string, value: number | null): string {
  if (value === null) return DASH;
  if (PERCENT_OBJECTIVES.has(objective as Objective)) return pct(value);
  if (objective === 'net_pnl' || objective === 'expectancy') return money(value);
  if (objective === SHARPE) return num(value, 2);
  return num(value, objective === 'trade_count' ? 0 : 2);
}
