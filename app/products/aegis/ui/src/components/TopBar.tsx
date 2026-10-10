import { api, errorMessage } from '../api/client';
import { TIMEFRAMES, useDispatch, useWorkspace, type Timeframe } from '../state/workspace';

const SYMBOLS = ['QQQ', 'SPY', 'ITOT'];

export function TopBar({ runsOpen, onToggleRuns }: { runsOpen: boolean; onToggleRuns: () => void }) {
  const { selection, strategy, settings, running } = useWorkspace();
  const dispatch = useDispatch();
  const set = (patch: Partial<typeof selection>) => dispatch({ type: 'SET_SELECTION', selection: patch });

  const runBacktest = async () => {
    if (!strategy || running) return;
    dispatch({ type: 'RUN_STARTED' });
    try {
      const run = await api.backtest({ strategy, data: selection, settings });
      dispatch({ type: 'RUN_COMPLETED', run });
    } catch (error) {
      dispatch({ type: 'RUN_FAILED', error: errorMessage(error) });
    }
  };

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
        <button
          id="run-backtest"
          className="btn btn-primary"
          type="button"
          disabled={!strategy || running}
          title={!strategy ? 'Strategy contract not loaded' : running ? 'Backtest running' : 'Run the backtest on the pinned raw archive'}
          onClick={runBacktest}
        >
          ▶ {running ? 'Running…' : 'Run Backtest'}
        </button>
        <button className="btn btn-green" type="button" disabled title="Optimizer not connected yet">
          ⚙ Optimize
        </button>
        <button className={'btn' + (runsOpen ? ' active' : '')} type="button" onClick={onToggleRuns} title="Saved runs" aria-pressed={runsOpen}>
          ☰ Runs
        </button>
      </div>
    </header>
  );
}
