import { useEffect, useState, type ReactNode } from 'react';
import { api, errorMessage } from '../api/client';
import { DASH, shortHash, timeLabel } from '../format';
import type { LibraryEntry, RunEnvelope } from '../results';
import { unsavedEdits, useDispatch, useWorkspace } from '../state/workspace';
import { EquityView } from './EquityTab';
import { LibraryChart } from './LibraryChart';
import { SummaryView } from './SummaryTab';
import { TradesView } from './TradesTab';

type Tab = 'summary' | 'trades' | 'equity';
const TABS: Array<[Tab, string]> = [
  ['summary', 'Summary'],
  ['trades', 'Trades'],
  ['equity', 'Equity Curve'],
];

/** A saved backtest, read-only (spec §5.1): its header, chart and results come from the run; the
 *  workspace changes only when the operator presses Load. */
export function LibraryBacktestView({ entry, actions }: { entry: LibraryEntry; actions?: ReactNode }) {
  const state = useWorkspace();
  const dispatch = useDispatch();
  const [run, setRun] = useState<RunEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('summary');

  useEffect(() => {
    let cancelled = false;
    setRun(null);
    setError(null);
    api
      .run(entry.id)
      .then((r) => !cancelled && setRun(r))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [entry.id]);

  const load = () => {
    if (!run) return;
    if (unsavedEdits(state) && !window.confirm('Load this run into the workspace? Unsaved strategy edits will be replaced.')) return;
    dispatch({ type: 'LOAD_RUN', run });
    dispatch({ type: 'SET_PAGE', page: 'charts' });
  };

  if (error) return <div className="error">{error}</div>;
  if (!run) return <div className="empty-state">Loading the saved run…</div>;
  const d = run.data;
  return (
    <div className="library-backtest">
      <div className="library-view-head">
        <div>
          <div className="panel-title">
            <span>
              {entry.starred ? '★ ' : ''}
              {entry.label || entry.name}
            </span>
          </div>
          <div className="small muted">
            {d.symbol ?? DASH} · {d.timeframe ?? DASH} · {d.start ?? DASH} → {d.end ?? DASH} · strategy {run.strategy.name ?? DASH} ({shortHash(run.strategy_hash)}) · result {shortHash(run.result_hash)} · saved {timeLabel(run.created_at)} · engine {run.engine ?? DASH}
            {d.source === 'raw_archive' ? ' · raw archive, not research-eligible' : ' · supplied bars'}
          </div>
        </div>
        <div className="library-actions">
          {actions}
          <button type="button" className="btn btn-primary" id="library-load" onClick={load} title="Replace the workspace's strategy, selection and results with this run">
            Load into workspace
          </button>
        </div>
      </div>
      <LibraryChart run={run} />
      <div className="library-results">
        <div className="result-tabs">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" id={`library-tab-${id}`} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </div>
        {tab === 'summary' && <SummaryView run={run} />}
        {tab === 'trades' && <TradesView run={run} />}
        {tab === 'equity' && <EquityView run={run} />}
      </div>
    </div>
  );
}
