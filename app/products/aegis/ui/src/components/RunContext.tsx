import { shortHash } from '../format';
import { runStaleness, useWorkspace } from '../state/workspace';

/** Which run the results panels describe, and whether the workspace has moved on since (honesty rule). */
export function StaleNotice() {
  const state = useWorkspace();
  const run = state.lastRun;
  if (!run) return null;
  const stale = runStaleness(state);
  const d = run.data;
  const context = `${d.symbol ?? '?'} · ${d.timeframe ?? '?'} ${d.start ?? ''} → ${d.end ?? ''}`;
  if (!stale.any) {
    return (
      <div className="run-context muted small">
        Results of run {run.run_id.slice(0, 8)} on {context} · hash {shortHash(run.result_hash)}
      </div>
    );
  }
  const changed = [stale.selection && 'the selection', stale.strategy && 'the strategy', stale.settings && 'the settings'].filter(Boolean).join(', ');
  return (
    <div className="run-context notice warn" role="status">
      Stale: these results are from run {run.run_id.slice(0, 8)} on {context}; {changed} changed since. Run Backtest to update.
    </div>
  );
}
