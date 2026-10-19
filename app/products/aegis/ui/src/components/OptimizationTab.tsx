import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { StrategySide } from '../contracts';
import { money, num, pct } from '../format';
import { compactMoney } from '../layout';
import { METRICS, METRIC_LABELS, TERMINAL_JOB_STATES, type Cell, type JobStatus, type Metric } from '../results';
import { useRunBacktest } from '../state/run';
import { applyConfigs, selectionText, SIDES, SIDE_KEY, useDispatch, useWorkspace, type Side } from '../state/workspace';
import { formatSeconds } from './OptimizePopover';
import { Heatmap, profitKind } from './Heatmap';

const FORMAT: Record<Metric, (v: number) => string> = {
  net_pnl: compactMoney, // a cell holds "$47.2k"; its hover title gives the full amount
  mar: (v) => num(v, 2),
  max_drawdown: pct,
  trade_count: (v) => num(v, 0),
};

/** `indicators.ema.length` → `EMA 11`, using the side the job was planned from. */
export function describeParams(params: Record<string, number>, side: StrategySide | undefined): string {
  return Object.entries(params)
    .map(([path, value]) => {
      const id = path.split('.')[1];
      const indicator = side?.indicators?.find((i) => i.id === id);
      return `${indicator ? indicator.kind.toUpperCase() : id} ${value}`;
    })
    .join(' / ');
}

/** Cells ordered by the objective: best first (max drawdown ascending, everything else descending), nulls last. */
export function rankCells(cells: Cell[], objective: Metric): Cell[] {
  const sign = objective === 'max_drawdown' ? 1 : -1;
  return [...cells].sort((a, b) => {
    const x = a.metrics[objective];
    const y = b.metrics[objective];
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return sign * (x - y);
  });
}

const sameParams = (a: Record<string, number> | null, b: Record<string, number>) =>
  a !== null && Object.keys(b).length === Object.keys(a).length && Object.entries(b).every(([k, v]) => a[k] === v);

function JobView({ side, job }: { side: Side; job: JobStatus }) {
  const { selectedConfigs } = useWorkspace();
  const dispatch = useDispatch();
  const [metric, setMetric] = useState<Metric>(job.objective);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const live = !TERMINAL_JOB_STATES.has(job.status);
  const pickedSelection = selectedConfigs[side];
  const selected = pickedSelection && pickedSelection !== 'none' ? pickedSelection : null;
  const planned = job.strategy[SIDE_KEY[side]];
  const matrix = job.matrices[metric]?.[side] ?? null;
  const selectedCell = selected ? { fast: selected[job.fast_path], slow: selected[job.slow_path] } : null;
  const pick = (cell: Cell) => dispatch({ type: 'SELECT_CONFIG', side, params: sameParams(selected, cell.params) ? null : cell.params });
  const cancel = async () => {
    setCancelError(null);
    try {
      await api.cancel(job.job_id);
    } catch (e) {
      setCancelError(errorMessage(e));
    }
  };
  const pctDone = job.progress.total ? (100 * job.progress.done) / job.progress.total : 0;

  return (
    <>
      <div className="job-head">
        <span className={'badge' + (job.status === 'failed' || job.status === 'lost' ? ' error' : '')}>{job.status.toUpperCase()}</span>
        <span>
          {job.progress.done} / {job.progress.total} cells · {job.skipped_cells} skipped · {job.bars.toLocaleString()} bars · objective {METRIC_LABELS[job.objective]}
        </span>
        <span className="muted">
          {(job.elapsed_ms / 1000).toFixed(1)} s elapsed{live ? ` · ≈ ${formatSeconds(job.estimated_seconds)} remaining` : ''} · cache hits {job.cache_hits}
        </span>
        {live && (
          <button type="button" className="btn" id="cancel-optimization" onClick={cancel}>
            Cancel
          </button>
        )}
        <label className="muted">
          Metric{' '}
          <select value={metric} onChange={(e) => setMetric(e.target.value as Metric)} aria-label="Heatmap metric">
            {METRICS.map((m) => (
              <option key={m} value={m}>
                {METRIC_LABELS[m]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={job.progress.total} aria-valuenow={job.progress.done}>
        <i style={{ width: `${pctDone}%` }} />
      </div>
      {job.error && <div className="error">{job.error}</div>}
      {job.status === 'lost' && <div className="notice warn">This job was still running when the worker restarted; its partial cells are what was saved.</div>}
      {cancelError && <div className="error">{cancelError}</div>}
      <div className="result-body opt">
        <Heatmap
          title={`${side.toUpperCase()} heatmap`}
          metric={METRIC_LABELS[metric]}
          fast={job.fast_values}
          slow={job.slow_values}
          matrix={matrix}
          format={FORMAT[metric]}
          profit={profitKind(metric)}
          detail={(fast, slow) => {
            const cell = job.cells.find((c) => c.fast === fast && c.slow === slow);
            if (!cell) return null;
            const m = cell.metrics;
            return `Net P&L ${money(m.net_pnl)} · MAR ${num(m.mar, 2)} · Max DD ${pct(m.max_drawdown)} · Trades ${num(m.trade_count, 0)}`;
          }}
          rowLabel={describeParams({ [job.fast_path]: NaN }, planned).replace(' NaN', '') + '↓'}
          colLabel={describeParams({ [job.slow_path]: NaN }, planned).replace(' NaN', '') + '→'}
          selected={selectedCell && selectedCell.fast !== undefined && selectedCell.slow !== undefined ? selectedCell : null}
          onSelect={(fast, slow) => {
            const cell = job.cells.find((c) => c.fast === fast && c.slow === slow);
            if (cell) pick(cell);
          }}
          empty="No two-axis grid for this job."
        />
        <div className="results-table">
          <div className="panel-title">
            Parameter sets <span className="small">{job.cells.length} evaluated · best first by {METRIC_LABELS[job.objective]}</span>
          </div>
          {job.cells.length === 0 && <div className="empty-state">{live ? 'Waiting for the first cell…' : 'No cells were evaluated.'}</div>}
          {job.cells.length > 0 && (
            <table id={`optimization-cells-${side}`}>
              <thead>
                <tr>
                  <th>Parameter set</th>
                  <th>Net P&L</th>
                  <th>Max DD</th>
                  <th>MAR</th>
                  <th>Win rate</th>
                  <th>Trades</th>
                  <th>Exposure</th>
                </tr>
              </thead>
              <tbody>
                {rankCells(job.cells, job.objective).map((cell) => {
                  const isSelected = sameParams(selected, cell.params);
                  return (
                    <tr key={JSON.stringify(cell.params)} className={'selectable' + (isSelected ? ' selected' : '')} onClick={() => pick(cell)} aria-selected={isSelected}>
                      <td>{describeParams(cell.params, planned)}</td>
                      <td className={(cell.metrics.net_pnl ?? 0) >= 0 ? 'green' : 'red'}>{money(cell.metrics.net_pnl)}</td>
                      <td>{pct(cell.metrics.max_drawdown)}</td>
                      <td>{num(cell.metrics.mar, 2)}</td>
                      <td>{pct(cell.metrics.win_rate)}</td>
                      <td>{num(cell.metrics.trade_count, 0)}</td>
                      <td>{pct(cell.metrics.exposure)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

export function OptimizationTab() {
  const { optimization, selectedConfigs, strategy, running } = useWorkspace();
  const dispatch = useDispatch();
  const run = useRunBacktest();
  const [side, setSide] = useState<Side>('long');
  const job = optimization[side];
  const anySelected = SIDES.some((s) => selectedConfigs[s] !== null);

  const apply = () => {
    if (!strategy) return;
    const applied = applyConfigs(strategy, selectedConfigs, { enablePicked: true });
    dispatch({ type: 'SET_STRATEGY', strategy: applied });
    dispatch({ type: 'SET_LINK_SIDES', linked: false }); // the sides were chosen independently; the panel must show both
    dispatch({ type: 'SET_RESULTS_TAB', tab: 'summary' });
    void run(applied);
  };

  return (
    <div className="result-body single opt-tab">
      <div className="results-table">
        <div className="legend">
          {SIDES.map((s) => {
            const j = optimization[s];
            return (
              <button key={s} type="button" className={'chip' + (side === s ? ' active' : '')} onClick={() => setSide(s)}>
                {s.toUpperCase()} {j ? `· ${j.status} ${j.progress.done}/${j.progress.total}` : '· not run'}
              </button>
            );
          })}
          <span className="muted" style={{ marginLeft: 'auto' }}>
            Selected: LONG {selectionText(selectedConfigs.long, (p) => describeParams(p, optimization.long?.strategy.long_side))} · SHORT{' '}
            {selectionText(selectedConfigs.short, (p) => describeParams(p, optimization.short?.strategy.short_side))}
          </span>
          {SIDES.map((s) => (
            <button
              key={`none-${s}`}
              id={`none-${s}`}
              type="button"
              className={'chip' + (selectedConfigs[s] === 'none' ? ' active' : '')}
              aria-pressed={selectedConfigs[s] === 'none'}
              title={`Apply turns the ${s.toUpperCase()} side off`}
              onClick={() => dispatch({ type: 'SELECT_CONFIG', side: s, params: selectedConfigs[s] === 'none' ? null : 'none' })}
            >
              {s.toUpperCase()} none
            </button>
          ))}
          <button id="apply-configs" type="button" className="btn btn-primary" disabled={!anySelected || !strategy || running} onClick={apply} title="Write the selected configurations into the strategy and rerun the combined backtest">
            Apply selected long + short
          </button>
        </div>
        {!job && <div className="empty-state">No optimization has been run for the {side.toUpperCase()} side — use Optimize in the top bar.</div>}
        {job && <JobView key={job.job_id} side={side} job={job} />}
      </div>
    </div>
  );
}
