import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { METRICS, METRIC_LABELS, TERMINAL_JOB_STATES, type Metric, type OptimizePlan } from '../results';
import { SIDES, useDispatch, useWorkspace, type Side } from '../state/workspace';

export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

/** Side choice, objective and the pre-run plan (valid cells, skipped, bars, estimate) before a start. */
export function OptimizePopover({ onClose }: { onClose: () => void }) {
  const { strategy, selection, settings, optimization } = useWorkspace();
  const dispatch = useDispatch();
  const [side, setSide] = useState<Side>('long');
  const [objective, setObjective] = useState<Metric>('net_pnl');
  const [plan, setPlan] = useState<OptimizePlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = SIDES.some((s) => optimization[s] && !TERMINAL_JOB_STATES.has(optimization[s]!.status));

  useEffect(() => {
    if (!strategy) return;
    let cancelled = false;
    setPlan(null);
    setError(null);
    api
      .optimizePlan({ strategy, side, data: selection, settings, objective })
      .then((p) => !cancelled && setPlan(p))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [strategy, side, selection, settings, objective]);

  const start = async () => {
    if (!strategy) return;
    setStarting(true);
    setError(null);
    try {
      const started = await api.optimize({ strategy, side, data: selection, settings, objective });
      dispatch({ type: 'JOB_UPDATED', side, job: await api.job(started.job_id) });
      dispatch({ type: 'SELECT_CONFIG', side, params: null });
      dispatch({ type: 'SET_RESULTS_TAB', tab: 'optimization' });
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="popover" role="dialog" aria-label="Optimize">
      <div className="row">
        <label>Side</label>
        <div className="pills">
          {SIDES.map((s) => (
            <button key={s} type="button" className={'pill btn' + (side === s ? ' on' : '')} onClick={() => setSide(s)} aria-pressed={side === s}>
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="row">
        <label htmlFor="objective">Objective</label>
        <select id="objective" value={objective} onChange={(e) => setObjective(e.target.value as Metric)}>
          {METRICS.map((m) => (
            <option key={m} value={m}>
              {METRIC_LABELS[m]}
            </option>
          ))}
        </select>
      </div>
      <div className="plan" id="optimize-plan">
        {plan ? (
          <>
            {plan.total_cells} valid cells · {plan.skipped_cells} skipped (fast ≥ slow) · {plan.bars.toLocaleString()} bars · ≈ {formatSeconds(plan.estimated_seconds)} estimated
          </>
        ) : error ? (
          <span className="error">{error}</span>
        ) : (
          'Planning…'
        )}
      </div>
      <div className="small muted">
        {plan ? `Priced at the last observed cell cost on this host (${plan.ms_per_bar} ms per bar); the running job refines it.` : 'The estimate uses the cell cost last observed on this host.'}
      </div>
      {busy && <div className="notice warn">An optimization is already running; wait for it or cancel it in the Optimization tab.</div>}
      <div className="actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
        <button id="start-optimization" type="button" className="btn btn-green" disabled={!plan || busy || starting} onClick={start}>
          {starting ? 'Starting…' : `Start ${side.toUpperCase()} optimization`}
        </button>
      </div>
    </div>
  );
}
