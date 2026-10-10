import { useState } from 'react';
import { EquityTab } from './EquityTab';
import { OptimizationTab } from './OptimizationTab';
import { SummaryTab } from './SummaryTab';
import { TradesTab } from './TradesTab';

type Tab = 'summary' | 'trades' | 'optimization' | 'equity';

const TABS: Array<{ id: Tab | 'walkforward' | 'logs'; label: string; disabled?: boolean }> = [
  { id: 'summary', label: 'Backtest Summary' },
  { id: 'trades', label: 'Trades' },
  { id: 'optimization', label: 'Optimization' },
  { id: 'equity', label: 'Equity Curve' },
  { id: 'walkforward', label: 'Walk-Forward', disabled: true },
  { id: 'logs', label: 'Logs', disabled: true },
];

export function ResultsTabs() {
  const [tab, setTab] = useState<Tab>('summary');
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
            onClick={() => !t.disabled && setTab(t.id as Tab)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'summary' && <SummaryTab />}
      {tab === 'trades' && <TradesTab />}
      {tab === 'optimization' && <OptimizationTab />}
      {tab === 'equity' && <EquityTab />}
    </section>
  );
}
