import { Fragment } from 'react';
import { DASH, money, num, pct } from '../format';
import type { Breakdown, Metrics, ResultSide } from '../results';
import { useWorkspace } from '../state/workspace';

const SIDES: Array<[ResultSide, string]> = [
  ['long', 'Long'],
  ['short', 'Short'],
  ['combined', 'Combined'],
];

const ROWS: Array<[keyof Metrics, string, (v: number | null | undefined) => string]> = [
  ['net_pnl', 'Net P&L', money],
  ['net_return', 'Net return', pct],
  ['cagr', 'CAGR', pct],
  ['max_drawdown', 'Max drawdown', pct],
  ['mar', 'MAR', (v) => num(v, 2)],
  ['win_rate', 'Win rate', pct],
  ['expectancy', 'Expectancy', money],
  ['profit_factor', 'Profit factor', (v) => num(v, 2)],
  ['trade_count', 'Trades', (v) => num(v, 0)],
  ['exposure', 'Exposure', pct],
];

export interface BreakdownRow {
  tag: string;
  long?: Breakdown;
  short?: Breakdown;
  combined?: Breakdown;
}

/** One row per temporal tag any side produced: ALL first, then the tags in sorted order. */
export function breakdownRows(temporal: Record<ResultSide, Record<string, Breakdown>>): BreakdownRow[] {
  const tags = new Set<string>();
  for (const side of SIDES) for (const tag of Object.keys(temporal[side[0]] ?? {})) tags.add(tag);
  const ordered = [...tags].filter((t) => t !== 'ALL').sort();
  if (tags.has('ALL')) ordered.unshift('ALL');
  return ordered.map((tag) => ({
    tag,
    long: temporal.long?.[tag],
    short: temporal.short?.[tag],
    combined: temporal.combined?.[tag],
  }));
}

export function SummaryTab() {
  const { lastRun } = useWorkspace();
  const result = lastRun?.result ?? null;
  const rows = result ? breakdownRows(result.temporal) : [];
  return (
    <div className="result-body single">
      <div className="results-table">
        {!result && <div className="empty-state">No backtest run yet — press Run Backtest in the top bar.</div>}
        <table id="summary-metrics">
          <thead>
            <tr>
              <th>Metric</th>
              {SIDES.map(([side, label]) => (
                <th key={side}>
                  {label}
                  {result && side !== 'combined' && !result[side].enabled && <span className="muted"> (disabled)</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([key, label, format]) => (
              <tr key={key}>
                <td>{label}</td>
                {SIDES.map(([side]) => {
                  const m = result?.[side].metrics;
                  return <td key={side}>{m ? format(m[key]) : DASH}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {result && (
          <>
            <div className="section-label" style={{ marginTop: 14 }}>
              Temporal breakdown <span className="muted">(ANALYZE tags on trades; a trade counts under every tag it carries)</span>
            </div>
            <table id="temporal-breakdown" className="breakdown small">
              <thead>
                <tr>
                  <th />
                  {SIDES.map(([side, label]) => (
                    <th key={side} className="group" colSpan={4}>
                      {label}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th>Tag</th>
                  {SIDES.map(([side]) => (
                    <Fragment key={side}>
                      <th>Trades</th>
                      <th>Net P&L</th>
                      <th>Win rate</th>
                      <th>Expectancy</th>
                    </Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={13} className="muted">
                      No trades, so no breakdown.
                    </td>
                  </tr>
                )}
                {rows.map((row) => (
                  <tr key={row.tag}>
                    <td className="mono">{row.tag}</td>
                    {SIDES.map(([side]) => {
                      const b = row[side];
                      return (
                        <Fragment key={side}>
                          <td>{b ? num(b.trades, 0) : DASH}</td>
                          <td className={b ? (b.net_pnl >= 0 ? 'green' : 'red') : ''}>{b ? money(b.net_pnl) : DASH}</td>
                          <td>{b ? pct(b.win_rate) : DASH}</td>
                          <td>{b ? money(b.expectancy) : DASH}</td>
                        </Fragment>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
