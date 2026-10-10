import { money, num, timeLabel } from '../format';
import { useWorkspace } from '../state/workspace';

interface Trade {
  side: string;
  signal_time: string;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  quantity: number;
  net_pnl: number;
  temporal_tags?: string[];
}

function tradesOf(run: unknown): Trade[] {
  const r = run as { result?: { combined?: { trades?: Trade[] } } } | null;
  return r?.result?.combined?.trades ?? [];
}

export function TradesTab() {
  const { lastRun } = useWorkspace();
  const trades = tradesOf(lastRun);
  return (
    <div className="result-body single">
      <div className="results-table">
        {trades.length === 0 && <div className="empty-state">{lastRun ? 'The last run produced no trades.' : 'No trades — no backtest has been run.'}</div>}
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
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i}>
                  <td className={t.side === 'LONG' ? 'green' : 'red'}>{t.side}</td>
                  <td>{timeLabel(t.signal_time)}</td>
                  <td>{timeLabel(t.entry_time)}</td>
                  <td>{num(t.entry_price)}</td>
                  <td>{timeLabel(t.exit_time)}</td>
                  <td>{num(t.exit_price)}</td>
                  <td>{num(t.quantity, 0)}</td>
                  <td className={t.net_pnl >= 0 ? 'green' : 'red'}>{money(t.net_pnl)}</td>
                  <td className="small">{(t.temporal_tags ?? []).join(' ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
