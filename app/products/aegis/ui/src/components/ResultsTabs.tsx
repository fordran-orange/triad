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

export function ResultsTabs() {
  const { resultsTab: tab } = useWorkspace();
  const dispatch = useDispatch();
  return (
    <section className="results">
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
      </div>
      {tab === 'summary' && <SummaryTab />}
      {tab === 'trades' && <TradesTab />}
      {tab === 'optimization' && <OptimizationTab />}
      {tab === 'walkforward' && <WalkForwardTab />}
      {tab === 'equity' && <EquityTab />}
    </section>
  );
}
