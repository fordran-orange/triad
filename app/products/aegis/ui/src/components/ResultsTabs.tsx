import { useEffect, useRef } from 'react';
import { useDispatch, useWorkspace, type ResultsTab } from '../state/workspace';
import { EquityTab } from './EquityTab';
import { OptimizationTab } from './OptimizationTab';
import { SummaryTab } from './SummaryTab';
import { TradesTab } from './TradesTab';
import { WalkForwardTab } from './WalkForwardTab';

const TABS: Array<{ id: ResultsTab | 'logs'; label: string; disabled?: boolean }> = [
  { id: 'summary', label: 'Backtest Summary' },
  { id: 'trades', label: 'Trades' },
  { id: 'optimization', label: 'Optimization' },
  { id: 'equity', label: 'Equity Curve' },
  { id: 'walkforward', label: 'Walk-Forward' },
  { id: 'logs', label: 'Logs', disabled: true },
];

interface Props {
  height: number;
  onResize: (px: number) => void;
  onResizeEnd: (px: number) => void;
  maximized: boolean;
  onMaximize: (maximized: boolean) => void;
}

const STEP = 24; // keyboard resize step in pixels

/** The results under the chart (operator, 2026-10-19: the x/y matrix window was unreadable): a
 *  divider to drag (or ArrowUp/ArrowDown on it), Maximize to give the results the whole workspace,
 *  Esc to restore. */
export function ResultsTabs({ height, onResize, onResizeEnd, maximized, onMaximize }: Props) {
  const { resultsTab: tab } = useWorkspace();
  const dispatch = useDispatch();
  const drag = useRef<{ startY: number; startHeight: number; last: number } | null>(null);
  useEffect(() => {
    if (!maximized) return;
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onMaximize(false);
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [maximized, onMaximize]);
  return (
    <section className="results">
      {!maximized && (
        <div
          className="results-resizer"
          id="results-resizer"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize the results panel"
          aria-valuenow={height}
          tabIndex={0}
          title="Drag to resize the results; ArrowUp / ArrowDown also work"
          onPointerDown={(e) => {
            drag.current = { startY: e.clientY, startHeight: height, last: height };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (!drag.current) return;
            const next = drag.current.startHeight - (e.clientY - drag.current.startY);
            drag.current.last = next;
            onResize(next);
          }}
          onPointerUp={(e) => {
            if (!drag.current) return;
            e.currentTarget.releasePointerCapture(e.pointerId);
            onResizeEnd(drag.current.last);
            drag.current = null;
          }}
          onKeyDown={(e) => {
            if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
            e.preventDefault();
            const next = height + (e.key === 'ArrowUp' ? STEP : -STEP);
            onResize(next);
            onResizeEnd(next);
          }}
        />
      )}
      <div className="result-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={(tab === t.id ? 'active' : '') + (t.disabled ? ' disabled' : '')}
            disabled={t.disabled}
            title={t.disabled ? 'Not yet built' : undefined}
            onClick={() => !t.disabled && dispatch({ type: 'SET_RESULTS_TAB', tab: t.id as ResultsTab })}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          className="results-maximize"
          id="results-maximize"
          aria-pressed={maximized}
          title={maximized ? 'Restore the chart (Esc)' : 'Give the results the whole workspace'}
          onClick={() => onMaximize(!maximized)}
        >
          {maximized ? 'Restore ⤡' : 'Maximize ⤢'}
        </button>
      </div>
      {tab === 'summary' && <SummaryTab />}
      {tab === 'trades' && <TradesTab />}
      {tab === 'optimization' && <OptimizationTab />}
      {tab === 'walkforward' && <WalkForwardTab />}
      {tab === 'equity' && <EquityTab />}
    </section>
  );
}
