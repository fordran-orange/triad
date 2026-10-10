import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { METRICS, METRIC_LABELS, TERMINAL_JOB_STATES, type Metric, type OptimizePlan, type WalkForwardPlan } from '../results';
import { SIDES, SIDE_KEY, useDispatch, useWorkspace, type Side } from '../state/workspace';
import { defaultWindowBars, longestLength } from './WalkForwardTab';

export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

type Mode = 'grid' | 'walkforward';

/** Side, objective and the pre-run plan before a start; grid optimization or walk-forward. */
export function OptimizePopover({ onClose }: { onClose: () => void }) {
  const { strategy, selection, settings, optimization, walkforward, loadedBars } = useWorkspace();
  const dispatch = useDispatch();
  const [mode, setMode] = useState<Mode>('grid');
  const [side, setSide] = useState<Side>('long');
  const [objective, setObjective] = useState<Metric>('net_pnl');
  const [plan, setPlan] = useState<OptimizePlan | null>(null);
  const [wfPlan, setWfPlan] = useState<WalkForwardPlan | null>(null);
  const [windows, setWindows] = useState(() => defaultWindowBars(loadedBars?.count ?? null, longestLength(strategy?.[SIDE_KEY['long']])));
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const busy = SIDES.some(
    (s) => (optimization[s] && !TERMINAL_JOB_STATES.has(optimization[s]!.status)) || (walkforward[s] && !TERMINAL_JOB_STATES.has(walkforward[s]!.status)),
  );
  const longest = longestLength(strategy?.[SIDE_KEY[side]]);

  // Propose window lengths from the loaded bars until the operator edits them.
  useEffect(() => {
    if (!touched) setWindows(defaultWindowBars(loadedBars?.count ?? null, longest));
  }, [loadedBars?.count, longest, touched]);

  useEffect(() => {
    if (!strategy) return;
    let cancelled = false;
    setPlan(null);
    setWfPlan(null);
    setError(null);
    const body = { strategy, side, data: selection, settings, objective };
    const request =
      mode === 'grid'
        ? api.optimizePlan(body).then((p) => !cancelled && setPlan(p))
        : api.walkforwardPlan({ ...body, in_sample_bars: windows.inSample, out_of_sample_bars: windows.outOfSample }).then((p) => !cancelled && setWfPlan(p));
    request.catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [strategy, side, selection, settings, objective, mode, windows]);

  const start = async () => {
    if (!strategy) return;
    setStarting(true);
    setError(null);
    try {
      const body = { strategy, side, data: selection, settings, objective };
      if (mode === 'grid') {
        const started = await api.optimize(body);
        dispatch({ type: 'JOB_UPDATED', side, job: await api.job(started.job_id) });
        dispatch({ type: 'SELECT_CONFIG', side, params: null });
        dispatch({ type: 'SET_RESULTS_TAB', tab: 'optimization' });
      } else {
        const started = await api.walkforward({ ...body, in_sample_bars: windows.inSample, out_of_sample_bars: windows.outOfSample });
        dispatch({ type: 'WALKFORWARD_UPDATED', side, job: await api.walkforwardJob(started.job_id) });
        dispatch({ type: 'SET_RESULTS_TAB', tab: 'walkforward' });
      }
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const setBars = (key: 'inSample' | 'outOfSample', raw: string) => {
    const value = Math.round(Number(raw));
    if (!Number.isFinite(value) || value < 1) return;
    setTouched(true);
    setWindows((w) => ({ ...w, [key]: value }));
  };

  const ready = mode === 'grid' ? plan !== null : wfPlan !== null;

  return (
    <div className="popover" role="dialog" aria-label="Optimize">
      <div className="row">
        <label>Mode</label>
        <div className="pills">
          <button id="grid-mode" type="button" className={'pill btn' + (mode === 'grid' ? ' on' : '')} onClick={() => setMode('grid')} aria-pressed={mode === 'grid'}>
            Grid
          </button>
          <button id="walkforward-mode" type="button" className={'pill btn' + (mode === 'walkforward' ? ' on' : '')} onClick={() => setMode('walkforward')} aria-pressed={mode === 'walkforward'}>
            Walk-forward
          </button>
        </div>
      </div>
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
      {mode === 'walkforward' && (
        <>
          <div className="row">
            <label htmlFor="in-sample-bars">In-sample bars</label>
            <input id="in-sample-bars" type="number" min={35} step={1} value={windows.inSample} onChange={(e) => setBars('inSample', e.target.value)} />
          </div>
          <div className="row">
            <label htmlFor="out-of-sample-bars">Out-of-sample bars</label>
            <input id="out-of-sample-bars" type="number" min={20} step={1} value={windows.outOfSample} onChange={(e) => setBars('outOfSample', e.target.value)} />
          </div>
        </>
      )}
      <div className="plan" id={mode === 'grid' ? 'optimize-plan' : 'walkforward-plan'}>
        {mode === 'grid' && plan && (
          <>
            {plan.total_cells} valid cells · {plan.skipped_cells} skipped (fast ≥ slow) · {plan.bars.toLocaleString()} bars · ≈ {formatSeconds(plan.estimated_seconds)} estimated
          </>
        )}
        {mode === 'walkforward' && wfPlan && (
          <>
            {wfPlan.windows} windows · {wfPlan.cells_per_window} cells each · {wfPlan.total_units} units · {wfPlan.unused_tail_bars} unused tail bars · {wfPlan.bars.toLocaleString()} bars · ≈{' '}
            {formatSeconds(wfPlan.estimated_seconds)} estimated
          </>
        )}
        {!ready && (error ? <span className="error">{error}</span> : 'Planning…')}
      </div>
      <div className="small muted">
        {ready
          ? `Priced at the last observed cell cost on this host (${(mode === 'grid' ? plan : wfPlan)!.ms_per_bar} ms per bar); the running job refines it.`
          : 'The estimate uses the cell cost last observed on this host.'}
      </div>
      {busy && <div className="notice warn">A job is already running; wait for it or cancel it in its tab.</div>}
      <div className="actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
        <button
          id={mode === 'grid' ? 'start-optimization' : 'start-walkforward'}
          type="button"
          className="btn btn-green"
          disabled={!ready || busy || starting}
          onClick={start}
        >
          {starting ? 'Starting…' : mode === 'grid' ? `Start ${side.toUpperCase()} optimization` : `Start ${side.toUpperCase()} walk-forward`}
        </button>
      </div>
    </div>
  );
}
