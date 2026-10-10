import { TIMEFRAMES, useDispatch, useWorkspace, type Timeframe } from '../state/workspace';

const SYMBOLS = ['QQQ', 'SPY', 'ITOT'];

export function TopBar() {
  const { selection, running } = useWorkspace();
  const dispatch = useDispatch();
  const set = (patch: Partial<typeof selection>) => dispatch({ type: 'SET_SELECTION', selection: patch });

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" />
        AEGIS
      </div>
      <div className="search">Search assets, indicators, strategies, or type a command… <span style={{ marginLeft: 'auto' }}>Ctrl K</span></div>
      <div className="top-controls">
        <select className="control" value={selection.symbol} onChange={(e) => set({ symbol: e.target.value })} aria-label="Symbol">
          {SYMBOLS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select className="control" value={selection.timeframe} onChange={(e) => set({ timeframe: e.target.value as Timeframe })} aria-label="Timeframe">
          {TIMEFRAMES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <input className="control date" type="date" value={selection.start} onChange={(e) => set({ start: e.target.value })} aria-label="Start date" />
        <span className="muted">→</span>
        <input className="control date" type="date" value={selection.end} onChange={(e) => set({ end: e.target.value })} aria-label="End date" />
        <button className="btn btn-primary" disabled title="Backtest service not connected yet">
          ▶ Run Backtest{running ? '…' : ''}
        </button>
        <button className="btn btn-green" disabled title="Optimizer not connected yet">
          ⚙ Optimize
        </button>
      </div>
    </header>
  );
}
