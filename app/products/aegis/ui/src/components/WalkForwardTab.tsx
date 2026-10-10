import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { StrategySide } from '../contracts';
import { DASH, money, num, pct, shortHash, timeLabel } from '../format';
import { METRIC_LABELS, TERMINAL_JOB_STATES, type EquityPoint, type WalkForwardStatus, type WindowRecord } from '../results';
import { useRunBacktest } from '../state/run';
import { applyConfigs, canonical, SIDES, SIDE_KEY, useDispatch, useWorkspace, type Side } from '../state/workspace';
import { formatSeconds } from './OptimizePopover';

const MIN_BARS = 35;
const MIN_OOS_BARS = 20;

/** The popover's proposal (spec §7): 40% / 10% of the loaded bars, never below the engine floors;
 *  250 / 63 when no bars are loaded. */
export function defaultWindowBars(bars: number | null, longest: number): { inSample: number; outOfSample: number } {
  if (bars === null) return { inSample: 250, outOfSample: 63 };
  return {
    inSample: Math.max(Math.round(0.4 * bars), MIN_BARS + longest),
    outOfSample: Math.max(Math.round(0.1 * bars), MIN_OOS_BARS),
  };
}

/** The longest indicator length a side's grid can visit: current lengths and enabled length-range stops. */
export function longestLength(side: StrategySide | undefined): number {
  if (!side) return 0;
  const lengths = (side.indicators ?? []).map((i) => i.length);
  for (const range of side.optimization ?? []) if (range.enabled !== false && range.path.endsWith('.length')) lengths.push(Math.ceil(range.stop));
  return lengths.length ? Math.max(...lengths) : 0;
}

/** Out-of-sample equity of the done windows in order, with the point index where each window starts. */
export function stitchedPoints(records: WindowRecord[]): { points: EquityPoint[]; boundaries: number[] } {
  const points: EquityPoint[] = [];
  const boundaries: number[] = [];
  for (const record of [...records].sort((a, b) => a.index - b.index)) {
    if (record.status !== 'done' || !record.oos) continue;
    boundaries.push(points.length);
    points.push(...record.oos.equity);
  }
  return { points, boundaries };
}

/** "window w of W · cell c of C · unit u of U": the cell count is within the current window. */
export function progressLabel(job: Pick<WalkForwardStatus, 'progress' | 'windows' | 'cells_per_window'>): string {
  const perWindow = job.cells_per_window + 1;
  const allDone = job.windows.done >= job.windows.total;
  const window = Math.min(job.windows.done + 1, job.windows.total);
  const cell = allDone ? job.cells_per_window : Math.max(0, Math.min(job.progress.done - job.windows.done * perWindow, job.cells_per_window));
  return `window ${window} of ${job.windows.total} · cell ${cell} of ${job.cells_per_window} · unit ${job.progress.done} of ${job.progress.total}`;
}

/** The last done window's chosen configuration, which "Apply" writes into the strategy. */
export function finalChoice(records: WindowRecord[]): Record<string, number> | null {
  const done = records.filter((r) => r.status === 'done' && r.best).sort((a, b) => a.index - b.index);
  return done.length ? done[done.length - 1].best!.params : null;
}

function describe(params: Record<string, number> | null | undefined, side: StrategySide | undefined): string {
  if (!params) return DASH;
  return Object.entries(params)
    .map(([path, value]) => {
      const id = path.split('.')[1];
      const indicator = side?.indicators?.find((i) => i.id === id);
      return `${indicator ? indicator.kind.toUpperCase() : id} ${value}`;
    })
    .join(' / ');
}

function StitchedEquity({ records }: { records: WindowRecord[] }) {
  const { points, boundaries } = stitchedPoints(records);
  if (points.length < 2) return <div className="empty-state">No out-of-sample equity yet — the first window has not completed.</div>;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 1000;
  const height = 180;
  const x = (i: number) => ((i / (points.length - 1)) * width).toFixed(1);
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)} ${(height - ((p.equity - min) / span) * height).toFixed(1)}`).join(' ');
  return (
    <>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height: 170 }} aria-label="stitched out-of-sample equity">
        {boundaries.slice(1).map((b) => (
          <line key={b} x1={x(b)} x2={x(b)} y1={0} y2={height} stroke="#f5bd51" strokeWidth={1} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        ))}
        <path d={path} fill="none" stroke="#2da7ff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="legend muted small">
        <span>{timeLabel(points[0].timestamp)}</span>
        <span>
          {boundaries.length} window{boundaries.length === 1 ? '' : 's'} · min {min.toFixed(0)} · max {max.toFixed(0)}
        </span>
        <span style={{ marginLeft: 'auto' }}>{timeLabel(points[points.length - 1].timestamp)}</span>
      </div>
    </>
  );
}

function JobView({ side, job }: { side: Side; job: WalkForwardStatus }) {
  const state = useWorkspace();
  const dispatch = useDispatch();
  const run = useRunBacktest();
  const [cancelError, setCancelError] = useState<string | null>(null);
  const live = !TERMINAL_JOB_STATES.has(job.status);
  const planned = job.strategy[SIDE_KEY[side]];
  const choice = finalChoice(job.window_records);
  const stitched = job.stitched.metrics;
  const edgeExits = job.stitched.trades.filter((t) => t.window_edge_exit).length;
  const pctDone = job.progress.total ? (100 * job.progress.done) / job.progress.total : 0;
  const d = job.data;
  const s = state.selection;
  const movedSelection = d.symbol !== s.symbol || d.timeframe !== s.timeframe || d.start !== s.start || d.end !== s.end;
  const movedStrategy = state.strategy !== null && canonical(job.strategy) !== canonical(state.strategy);

  const cancel = async () => {
    setCancelError(null);
    try {
      await api.cancelWalkforward(job.job_id);
    } catch (e) {
      setCancelError(errorMessage(e));
    }
  };
  const apply = () => {
    if (!state.strategy || !choice) return;
    const applied = applyConfigs(state.strategy, { long: side === 'long' ? choice : null, short: side === 'short' ? choice : null });
    dispatch({ type: 'SET_STRATEGY', strategy: applied });
    dispatch({ type: 'SET_LINK_SIDES', linked: false });
    dispatch({ type: 'SET_RESULTS_TAB', tab: 'summary' });
    void run(applied);
  };

  return (
    <>
      <div className="job-head">
        <span className={'badge' + (job.status === 'failed' || job.status === 'lost' ? ' error' : '')}>{job.status.toUpperCase()}</span>
        <span>
          {progressLabel(job)} · in-sample {job.in_sample_bars} / out-of-sample {job.out_of_sample_bars} bars · objective {METRIC_LABELS[job.objective]}
        </span>
        <span className="muted">
          {(job.elapsed_ms / 1000).toFixed(1)} s elapsed{live ? ` · ≈ ${formatSeconds(job.estimated_seconds)} remaining` : ''} · cache hits {job.cache_hits}
          {job.unused_tail_bars > 0 ? ` · ${job.unused_tail_bars} tail bars unused` : ''}
        </span>
        {live && (
          <button type="button" className="btn" id="cancel-walkforward" onClick={cancel}>
            Cancel
          </button>
        )}
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={job.progress.total} aria-valuenow={job.progress.done}>
        <i style={{ width: `${pctDone}%` }} />
      </div>
      {job.error && <div className="error">{job.error}</div>}
      {job.status === 'lost' && <div className="notice warn">This walk-forward was still running when the worker restarted; its completed windows are what was saved.</div>}
      {cancelError && <div className="error">{cancelError}</div>}
      {(movedSelection || movedStrategy) && (
        <div className="notice warn" role="status">
          Stale: this walk-forward ran on {d.symbol} · {d.timeframe} {d.start} → {d.end}; {[movedSelection && 'the selection', movedStrategy && 'the strategy'].filter(Boolean).join(' and ')} changed since.
        </div>
      )}
      <div className="results-table">
        <div className="panel-title">
          Stitched out-of-sample equity <span className="small">{side.toUpperCase()} · chained capital · {job.result_hash ? `hash ${shortHash(job.result_hash)}` : 'hash pending'}</span>
        </div>
        <StitchedEquity records={job.window_records} />
        <div className="legend small" id={`walkforward-stitched-${side}`}>
          <span>Net P&L <b>{money(stitched.net_pnl)}</b></span>
          <span>Return <b>{pct(stitched.net_return)}</b></span>
          <span>CAGR <b>{pct(stitched.cagr)}</b></span>
          <span>Max DD <b>{pct(stitched.max_drawdown)}</b></span>
          <span>MAR <b>{num(stitched.mar, 2)}</b></span>
          <span>Win rate <b>{pct(stitched.win_rate)}</b></span>
          <span>
            Trades <b>{num(stitched.trade_count, 0)}</b>
            {edgeExits > 0 && (
              <span className="muted" title="Closed by the engine at a window's last bar, not by the strategy's exit rule; positions do not carry into the next window">
                {' '}
                ({edgeExits} closed at a window edge)
              </span>
            )}
          </span>
          <span>Exposure <b>{pct(stitched.exposure)}</b></span>
        </div>
      </div>
      <div className="result-body">
        <div className="results-table">
          <div className="panel-title">
            Windows <span className="small">{job.windows.done} of {job.windows.total} complete · {job.cells_per_window} cells each</span>
          </div>
          <table id={`walkforward-windows-${side}`} className="small">
            <thead>
              <tr>
                <th>#</th>
                <th>In-sample</th>
                <th>Out-of-sample</th>
                <th>Chosen</th>
                <th>IS {METRIC_LABELS[job.objective]}</th>
                <th>OOS net P&L</th>
                <th>OOS max DD</th>
                <th>OOS trades</th>
                <th>Efficiency</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {job.window_records.map((r) => {
                const isValue = r.best?.metrics?.[job.objective];
                return (
                  <tr key={r.index} className={r.status === 'pending' ? 'muted' : ''}>
                    <td>{r.index + 1}</td>
                    <td>
                      {timeLabel(r.is_start)} → {timeLabel(r.is_end)} <span className="muted">({r.is_bars})</span>
                    </td>
                    <td>
                      {timeLabel(r.oos_start)} → {timeLabel(r.oos_end)} <span className="muted">({r.oos_bars})</span>
                    </td>
                    <td>{describe(r.best?.params, planned)}</td>
                    <td>{isValue === undefined || isValue === null ? DASH : job.objective === 'net_pnl' ? money(isValue) : job.objective === 'max_drawdown' ? pct(isValue) : num(isValue, 2)}</td>
                    <td className={r.oos ? ((r.oos.metrics.net_pnl ?? 0) >= 0 ? 'green' : 'red') : ''}>{r.oos ? money(r.oos.metrics.net_pnl) : DASH}</td>
                    <td>{r.oos ? pct(r.oos.metrics.max_drawdown) : DASH}</td>
                    <td title={r.oos ? `${r.oos.trades.filter((x) => x.window_edge_exit).length} closed at the window edge` : undefined}>
                      {r.oos ? num(r.oos.metrics.trade_count, 0) : DASH}
                      {r.oos && r.oos.trades.some((x) => x.window_edge_exit) ? <span className="muted"> ({r.oos.trades.filter((x) => x.window_edge_exit).length} edge)</span> : null}
                    </td>
                    <td>{r.efficiency === null ? DASH : num(r.efficiency, 2)}</td>
                    <td>{r.status === 'no_valid_cell' ? 'no valid cell' : r.status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="results-table" id={`walkforward-stability-${side}`}>
          <div className="panel-title">
            Stability <span className="small">{job.stability.windows_evaluated} window{job.stability.windows_evaluated === 1 ? '' : 's'} evaluated</span>
          </div>
          <table className="small">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Min</th>
                <th>Max</th>
                <th>Mean</th>
                <th>Std</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(job.stability.parameters).map(([path, spread]) => (
                <tr key={path}>
                  <td>{describe({ [path]: NaN }, planned).replace(' NaN', '')}</td>
                  <td>{num(spread.min, 0)}</td>
                  <td>{num(spread.max, 0)}</td>
                  <td>{num(spread.mean, 1)}</td>
                  <td>{num(spread.std, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="legend small" style={{ marginTop: 8 }}>
            <span>
              Positive OOS windows <b>{job.stability.windows_evaluated ? `${job.stability.positive_oos_windows} of ${job.stability.windows_evaluated}` : DASH}</b>
            </span>
            <span>
              Mean efficiency <b>{num(job.stability.mean_efficiency, 2)}</b>
            </span>
          </div>
          <div className="legend" style={{ marginTop: 12 }}>
            <span className="muted">Final window's configuration: {describe(choice, planned)}</span>
            <button
              id="apply-walkforward"
              type="button"
              className="btn btn-primary"
              disabled={!choice || !state.strategy || state.running}
              onClick={apply}
              title="Write the last window's configuration into this side and rerun the combined backtest"
            >
              Apply final configuration
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

export function WalkForwardTab() {
  const { walkforward } = useWorkspace();
  const [side, setSide] = useState<Side>('long');
  const job = walkforward[side];
  return (
    <div className="result-body single">
      <div className="results-table">
        <div className="legend">
          {SIDES.map((s) => {
            const j = walkforward[s];
            return (
              <button key={s} type="button" className={'chip' + (side === s ? ' active' : '')} onClick={() => setSide(s)}>
                {s.toUpperCase()} {j ? `· ${j.status} ${j.windows.done}/${j.windows.total} windows` : '· not run'}
              </button>
            );
          })}
        </div>
        {!job && <div className="empty-state">No walk-forward has been run for the {side.toUpperCase()} side — choose "Walk-forward" in the Optimize popover.</div>}
        {job && <JobView key={job.job_id} side={side} job={job} />}
      </div>
    </div>
  );
}
