import { useWorkspace } from '../state/workspace';

const TABS = ['QQQ', 'SPY', 'ITOT'];

export function ChartPanel() {
  const { selection, strategy } = useWorkspace();
  const ema = strategy?.long_side ? indicatorLengths(strategy) : null;

  return (
    <div className="chart-panel">
      <div className="tabs">
        {TABS.map((symbol) => (
          <button key={symbol} className={'tab' + (symbol === selection.symbol ? ' active' : '')} type="button">
            {symbol}
          </button>
        ))}
        <button className="tab" type="button" disabled title="Not yet built">
          ＋
        </button>
      </div>
      <div className="chart">
        <div className="chart-header">
          <div className="instrument">
            {selection.symbol} · {selection.timeframe} <span className="badge raw">RAW ARCHIVE · NOT RESEARCH-ELIGIBLE</span>
          </div>
          <div className="ohlc">O — &nbsp; H — &nbsp; L — &nbsp; C — <span className="muted">not connected</span></div>
          <div className="legend">
            <b className="accent">EMA {ema?.ema ?? '—'}</b>
            <b className="green">SMA {ema?.sma ?? '—'}</b>
            <span>Volume</span>
          </div>
        </div>
        <div className="chart-mount" id="chart-mount" />
        <div className="chart-empty">No bars loaded — data service not connected yet</div>
      </div>
    </div>
  );
}

/** Reads the EMA/SMA lengths from either shape of the contract (side-owned after Task 3). */
function indicatorLengths(strategy: unknown): { ema: number | null; sma: number | null } {
  const s = strategy as { indicators?: Array<{ kind: string; length: number }>; long_side?: { indicators?: Array<{ kind: string; length: number }> } };
  const list = s.long_side?.indicators ?? s.indicators ?? [];
  const find = (kind: string) => list.find((i) => i.kind.toUpperCase() === kind)?.length ?? null;
  return { ema: find('EMA'), sma: find('SMA') };
}
