// Pure helpers for plateau walk-forward studies (Mission 8 spec §7–8); no React, no fetch.
import { formatSeconds } from './components/OptimizePopover';
import type { StudyPlan } from './contracts';
import { priceLabel } from './experiments';
import { DASH, money, num, pct } from './format';
import { STUDY_RULE_LABELS, STUDY_RULES, type StudyCurvePoint, type StudyReport, type StudyRule, type StudyRuleReport } from './results';

const n = (value: number) => value.toLocaleString('en-US');

/** "3 symbols · 48 windows · 12,096 runs · ≈ 2 min 0 s (measured on this host)". */
/** The selected study, only while it is one of the open experiment's studies: a study chosen
 *  under another experiment (or by a deep link) never shows under this one. */
export function visibleStudy(selectedId: string | null, items: Array<{ id: string }> | null): string | null {
  if (!selectedId || !items) return null;
  return items.some((item) => item.id === selectedId) ? selectedId : null;
}

export function planLine(plan: StudyPlan): string {
  const symbols = plan.symbols.length;
  const windows = plan.symbols.reduce((sum, s) => sum + s.windows, 0);
  const sampled = plan.symbols.find((s) => s.mode === 'sampled');
  const parts = [`${symbols} symbol${symbols === 1 ? '' : 's'}`, `${n(windows)} windows`, `${n(plan.total_runs)} runs`];
  if (sampled) parts.push(`sampled ${n(sampled.cells_per_window)} of ${n(plan.valid_cells)} cells per window`);
  parts.push(`≈ ${formatSeconds(plan.estimate_seconds)} (${priceLabel(plan)})`);
  return parts.join(' · ');
}

export interface RuleRow {
  rule: StudyRule;
  label: string;
  absent?: string;
  cells: Record<'net_pnl' | 'net_return' | 'cagr' | 'max_drawdown' | 'mar' | 'trades' | 'exposure', string>;
  hash?: string;
}

const EMPTY: RuleRow['cells'] = { net_pnl: DASH, net_return: DASH, cagr: DASH, max_drawdown: DASH, mar: DASH, trades: DASH, exposure: DASH };

/** The three rules side by side for one symbol: "—" for an absent value, the reason when the
 *  frozen centre is absent. */
export function ruleRows(report: StudyReport, symbol: string): RuleRow[] {
  const entry = report.symbols[symbol];
  return STUDY_RULES.map((rule) => {
    const record = entry?.rules[rule];
    if (!record || 'absent' in record) return { rule, label: STUDY_RULE_LABELS[rule], absent: record ? record.absent : 'not run', cells: EMPTY };
    const m = (record as StudyRuleReport).metrics;
    return {
      rule,
      label: STUDY_RULE_LABELS[rule],
      hash: (record as StudyRuleReport).result_hash,
      cells: {
        net_pnl: money(m.net_pnl),
        net_return: pct(m.net_return),
        cagr: pct(m.cagr),
        max_drawdown: pct(m.max_drawdown),
        mar: num(m.mar, 2),
        trades: m.trade_count === null || m.trade_count === undefined ? DASH : String(m.trade_count),
        exposure: pct(m.exposure),
      },
    };
  });
}

/** SVG paths for each rule's stitched equity in a width × height box: one time domain and one
 *  equity range across every curve, the first and last points kept. */
export function equityPaths(
  curves: Partial<Record<StudyRule, StudyCurvePoint[]>>,
  width: number,
  height: number,
): { paths: Partial<Record<StudyRule, string>>; domain: [number, number]; range: [number, number] } {
  const all = Object.values(curves).flatMap((points) => points ?? []);
  if (all.length === 0) return { paths: {}, domain: [0, 0], range: [0, 0] };
  const times = all.map((p) => Date.parse(p.timestamp));
  const values = all.map((p) => p.equity);
  const domain: [number, number] = [Math.min(...times), Math.max(...times)];
  const range: [number, number] = [Math.min(...values), Math.max(...values)];
  const x = (t: number) => (domain[1] === domain[0] ? width / 2 : ((t - domain[0]) / (domain[1] - domain[0])) * width);
  const y = (v: number) => (range[1] === range[0] ? height / 2 : height - ((v - range[0]) / (range[1] - range[0])) * height);
  const paths: Partial<Record<StudyRule, string>> = {};
  for (const [rule, points] of Object.entries(curves) as Array<[StudyRule, StudyCurvePoint[] | undefined]>) {
    if (!points || points.length === 0) continue;
    paths[rule] = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(Date.parse(p.timestamp)).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ');
  }
  return { paths, domain, range };
}

interface WindowSpan {
  index: number;
  oos_start: string;
  oos_end: string;
  flat: boolean;
}

function scaler(domain: [number, number], width: number) {
  return (iso: string) => {
    const t = Date.parse(iso);
    if (domain[1] === domain[0]) return 0;
    return Math.min(width, Math.max(0, ((t - domain[0]) / (domain[1] - domain[0])) * width));
  };
}

/** One shaded band per window where the plateau rule stood flat. */
export function flatShading(windows: WindowSpan[], domain: [number, number], width: number): Array<{ index: number; x0: number; x1: number }> {
  const x = scaler(domain, width);
  return windows.filter((w) => w.flat).map((w) => ({ index: w.index, x0: x(w.oos_start), x1: x(w.oos_end) }));
}

/** One boundary line at each window's first out-of-sample bar. */
export function windowMarks(windows: WindowSpan[], domain: [number, number], width: number): Array<{ index: number; x: number }> {
  const x = scaler(domain, width);
  return windows.map((w) => ({ index: w.index, x: x(w.oos_start) }));
}

/** A window's in-sample cells, best first by the objective (lower first for max drawdown), invalid
 *  cells dropped and cells without a value last (review finding: the list was always descending). */
export function bestCells<T extends Record<string, unknown>>(rows: T[], objective: string, limit: number): T[] {
  const key = `combined.${objective}`;
  const lowerIsBetter = objective === 'max_drawdown';
  const value = (row: T): number | null => {
    const v = row[key];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };
  return rows
    .filter((row) => row.valid === true)
    .sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x === null || y === null || x === y) {
        if (x === null && y !== null) return 1;
        if (y === null && x !== null) return -1;
        return Number(a.cell) - Number(b.cell);
      }
      return lowerIsBetter ? x - y : y - x;
    })
    .slice(0, limit);
}

