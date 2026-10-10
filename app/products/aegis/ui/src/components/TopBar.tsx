import { useState } from 'react';
import { useRunBacktest } from '../state/run';
import { TIMEFRAMES, useDispatch, useWorkspace, type Timeframe } from '../state/workspace';
import { OptimizePopover } from './OptimizePopover';

export function TopBar({ runsOpen, onToggleRuns }: { runsOpen: boolean; onToggleRuns: () => void }) {
  const { selection, strategy, symbols, running } = useWorkspace();
  const dispatch = useDispatch();
  const runBacktest = useRunBacktest();
  const [optimizeOpen, setOptimizeOpen] = useState(false);
  const set = (patch: Partial<typeof selection>) => dispatch({ type: 'SET_SELECTION', selection: patch });
  // The menu is what /data/symbols found on disk; until it answers, only the current selection is offered.
  const names = symbols ? symbols.map((s) => s.symbol) : [selection.symbol];
  const options = names.includes(selection.symbol) ? names : [selection.symbol, ...names];

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" />
        AEGIS
      </div>
      <div className="search">Search assets, indicators, strategies, or type a command… <span style={{ marginLeft: 'auto' }}>Ctrl K</span></div>
      <div className="top-controls">
        <select
          className="control"
          value={selection.symbol}
          onChange={(e) => set({ symbol: e.target.value })}
          aria-label="Symbol"
          title={symbols === null ? 'Archive list not loaded yet' : symbols.length === 0 ? 'No raw archives found on disk' : `${symbols.length} raw archive(s) on disk`}
        >
          {options.map((s) => (
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
          onClick={() => void runBacktest()}
        >
          ▶ {running ? 'Running…' : 'Run Backtest'}
        </button>
        <div className="optimize-anchor">
          <button
            id="optimize"
            className={'btn btn-green' + (optimizeOpen ? ' active' : '')}
            type="button"
            disabled={!strategy}
            title={!strategy ? 'Strategy contract not loaded' : 'Plan and start a per-side grid optimization'}
            aria-expanded={optimizeOpen}
            onClick={() => setOptimizeOpen((v) => !v)}
          >
            ⚙ Optimize
          </button>
          {optimizeOpen && <OptimizePopover onClose={() => setOptimizeOpen(false)} />}
        </div>
        <button className={'btn' + (runsOpen ? ' active' : '')} type="button" onClick={onToggleRuns} title="Saved runs" aria-pressed={runsOpen}>
          ☰ Runs
        </button>
      </div>
    </header>
  );
}
