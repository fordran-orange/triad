import { useState } from 'react';
import { DASH, money, num, timeLabel } from '../format';
import type { ResultSide, Trade } from '../results';
import { useWorkspace, type RunRecord } from '../state/workspace';
import { StaleNotice } from './RunContext';

const FILTERS: Array<[ResultSide, string]> = [
  ['combined', 'All'],
  ['long', 'Long'],
  ['short', 'Short'],
];

export function TradesTab() {
  const { lastRun } = useWorkspace();
  return <TradesView run={lastRun} stale />;
}

/** One run's view; the Library feeds it a saved run without touching the workspace (Mission 9). */
export function TradesView({ run: lastRun, stale = false }: { run: RunRecord | null; stale?: boolean }) {
  const [filter, setFilter] = useState<ResultSide>('combined');
  const result = lastRun?.result;
  const trades: Trade[] = result ? result[filter].trades : [];
  return (
    <div className="result-body single">
      <div className="results-table">
        {stale && <StaleNotice />}
        {result && (
          <div className="legend">
            {FILTERS.map(([side, label]) => (
              <button key={side} type="button" className={'chip' + (filter === side ? ' active' : '')} onClick={() => setFilter(side)}>
                {label} ({result[side].trades.length})
              </button>
            ))}
          </div>
        )}
        {trades.length === 0 && <div className="empty-state">{result ? 'No trades on this side for the last run.' : 'No trades — no backtest has been run.'}</div>}
        {trades.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Side</th>
                <th>Signal</th>
                <th>Entry</th>
                <th>Entry px</th>
                <th>Exit</th>
                <th>Exit px</th>
                <th>Qty</th>
                <th>Net P&L</th>
                <th>Return</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={`${t.side}-${t.entry_time}-${t.exit_time}`}>
                  <td className={t.side === 'LONG' ? 'green' : 'red'}>{t.side}</td>
                  <td>{timeLabel(t.signal_time)}</td>
                  <td>{timeLabel(t.entry_time)}</td>
                  <td>{num(t.entry_price)}</td>
                  <td>{timeLabel(t.exit_time)}</td>
                  <td>{num(t.exit_price)}</td>
                  <td>{num(t.quantity, 0)}</td>
                  <td className={t.net_pnl >= 0 ? 'green' : 'red'}>{money(t.net_pnl)}</td>
                  <td>{(t.return * 100).toFixed(2)}%</td>
                  <td className="small">{t.temporal_tags.join(' ') || DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
