import { DASH, money, num, pct } from '../format';
import { useWorkspace } from '../state/workspace';

interface Metrics {
  net_pnl?: number | null;
  net_return?: number | null;
  cagr?: number | null;
  max_drawdown?: number | null;
  mar?: number | null;
  win_rate?: number | null;
  expectancy?: number | null;
  profit_factor?: number | null;
  trade_count?: number | null;
  exposure?: number | null;
}

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

/** Pulls per-side metrics out of a run envelope; absent until the backtest phase connects. */
function metricsOf(run: unknown, side: 'long' | 'short' | 'combined'): Metrics | null {
  const r = run as { result?: Record<string, { metrics?: Metrics }> } | null;
  return r?.result?.[side]?.metrics ?? null;
}

export function SummaryTab() {
  const { lastRun } = useWorkspace();
  const sides: Array<['long' | 'short' | 'combined', string]> = [
    ['long', 'Long'],
    ['short', 'Short'],
    ['combined', 'Combined'],
  ];
  return (
    <div className="result-body single">
      <div className="results-table">
        {!lastRun && <div className="empty-state">No backtest run yet — run one from the top bar once the backtest service is connected.</div>}
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              {sides.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([key, label, format]) => (
              <tr key={key}>
                <td>{label}</td>
                {sides.map(([side]) => {
                  const m = metricsOf(lastRun, side);
                  return <td key={side}>{m ? format(m[key]) : DASH}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
