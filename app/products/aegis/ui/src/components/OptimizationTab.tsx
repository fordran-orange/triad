import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { StrategySide } from '../contracts';
import { money, num, pct } from '../format';
import { compactMoney } from '../layout';
import { axisChoices, axisLength, squareTitle, tooManySquares } from '../optimizer';
import { METRICS, METRIC_LABELS, TERMINAL_JOB_STATES, type AxisMatrix, type Cell, type JobStatus, type Metric } from '../results';
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

/** One optimization job's matrix and table; the Library passes its own pick (Mission 9). */
export function OptimizationJobView({
  side,
  job,
  selected: chosen,
  onPick,
  library = false,
}: {
  side: Side;
  job: JobStatus;
  selected?: Record<string, number> | null;
  onPick?: (cell: Cell) => void;
  library?: boolean;
}) {
  const { selectedConfigs } = useWorkspace();
  const dispatch = useDispatch();
  const [metric, setMetric] = useState<Metric>(job.objective);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const live = !TERMINAL_JOB_STATES.has(job.status);
  const pickedSelection = chosen !== undefined ? chosen : selectedConfigs[side];
  const selected = pickedSelection && pickedSelection !== 'none' ? pickedSelection : null;
  const planned = job.strategy[SIDE_KEY[side]];
  const label = (path: string) => describeParams({ [path]: NaN }, planned).replace(' NaN', '');
  // Three or more parameters (the limits change): any two make the matrix, each square the
  // best of the rest, built on the worker for the chosen pair.
  const choices = axisChoices(job);
  const [axes, setAxes] = useState<[string, string]>([job.fast_path, job.slow_path]);
  // The worker builds the matrix only for a pair the stored matrices do not hold (the limits
  // review: a trimmed two-parameter job resolves a square's cell on click instead).
  const custom = choices.length >= 3 || axes[0] !== job.fast_path || axes[1] !== job.slow_path;
  const tooMany = custom
    ? tooManySquares(axisLength(job, axes[0]), axisLength(job, axes[1]))
    : tooManySquares(job.fast_values.length, job.slow_values.length);
  const [axisMatrix, setAxisMatrix] = useState<AxisMatrix | null>(null);
  const done = job.cells_done ?? job.progress.done;
  useEffect(() => {
    if (!custom || tooMany || !axes[0] || !axes[1]) {
      setAxisMatrix(null);
      return;
    }
    let cancelled = false;
    api
      .optimizeMatrix(job.job_id, axes[0], axes[1], metric)
      .then((m) => !cancelled && setAxisMatrix(m))
      .catch(() => !cancelled && setAxisMatrix(null));
    return () => {
      cancelled = true;
    };
  }, [job.job_id, axes, custom, tooMany, metric, done, job.status]);
  const view =
    custom && axisMatrix
      ? {
          fast: axisMatrix.rows,
          slow: axisMatrix.cols,
          matrix: axisMatrix.metrics[metric]?.values ?? null,
          rowPath: axes[0],
          colPath: axes[1],
          cellAt: (fast: number, slow: number) => {
            const r = axisMatrix.rows.indexOf(fast);
            const c = axisMatrix.cols.indexOf(slow);
            if (r < 0 || c < 0) return { cell: null, count: 0 };
            const at = axisMatrix.metrics[metric]?.cells[r][c] ?? null;
            return { cell: at === null ? null : axisMatrix.cells[at], count: axisMatrix.counts[r][c] };
          },
        }
      : {
          fast: job.fast_values,
          slow: job.slow_values,
          matrix: job.matrices[metric]?.[side] ?? null,
          rowPath: job.fast_path,
          colPath: job.slow_path,
          cellAt: (fast: number, slow: number) => {
            const cell = job.cells.find((c) => c.fast === fast && c.slow === slow) ?? null;
            return { cell, count: cell ? 1 : 0 };
          },
        };
  const selectedCell = selected ? { fast: selected[view.rowPath], slow: selected[view.colPath] } : null;
  // The table: the best cells the status sends, then the rest a page at a time.
  const shown = job.cells_shown ?? job.cells.length;
  const PAGE = shown < done ? shown : 1000; // the status sends its best cells; the rest page in
  const [page, setPage] = useState(0);
  const [pageRows, setPageRows] = useState<Cell[] | null>(null);
  useEffect(() => {
    if (page === 0) {
      setPageRows(null);
      return;
    }
    let cancelled = false;
    api
      .optimizeCells(job.job_id, page * PAGE, PAGE)
      .then((r) => !cancelled && setPageRows(r.rows))
      .catch(() => !cancelled && setPageRows([]));
    return () => {
      cancelled = true;
    };
  }, [page, job.job_id]);
  const tableCells = page === 0 ? rankCells(job.cells, job.objective) : (pageRows ?? []);
  const pages = Math.max(1, Math.ceil(done / PAGE));
  // A square whose cell the page was not sent: one small lookup on the worker, then the pick.
  const pickSquare = async (fast: number, slow: number) => {
    const { cell } = view.cellAt(fast, slow);
    if (cell) return pick(cell);
    try {
      pick(await api.optimizeSquare(job.job_id, view.rowPath, view.colPath, fast, slow, metric));
    } catch {
      // no cell with a value there: nothing to pick
    }
  };
  const pick = (cell: Cell) => (onPick ? onPick(cell) : dispatch({ type: 'SELECT_CONFIG', side, params: sameParams(selected, cell.params) ? null : cell.params }));
  const cancel = async () => {
    setCancelError(null);
    try {
      await api.cancel(job.job_id);
    } catch (e) {
      setCancelError(errorMessage(e));
    }
  };
  const pctDone = job.progress.total ? (100 * job.progress.done) / job.progress.total : 0;
  // Expand Lab: the Optimization Lab page opens on this job, on the pair and metric the dock shows,
  // with the side's selected configuration (when there is one) selected there too.
  const expandLab = () =>
    dispatch({
      type: 'SET_PAGE',
      page: 'optlab',
      focus: { lab: { source: 'opt:' + job.job_id, axes: choices.length >= 3 ? axes : [job.fast_path, job.slow_path], metric, ...(selected ? { selected } : {}) } },
    });

  return (
    <>
      <div className="job-head">
        <span className={'badge' + (job.status === 'failed' || job.status === 'lost' ? ' error' : '')}>{job.status.toUpperCase()}</span>
        <span>
          {done.toLocaleString()} / {(job.total_cells ?? job.progress.total).toLocaleString()} cells · {job.skipped_cells} skipped · {job.bars.toLocaleString()} bars · objective {METRIC_LABELS[job.objective]}
          {job.pooled ? ' · on the pool' : ''}
        </span>
        <span className="muted">
          {(job.elapsed_ms / 1000).toFixed(1)} s elapsed{live ? ` · ≈ ${formatSeconds(job.estimated_seconds)} remaining` : ''} · cache hits {job.cache_hits}
        </span>
        {live && !library && (
          <button type="button" className="btn" id="cancel-optimization" onClick={cancel}>
            Cancel
          </button>
        )}
        {!library && (
          <button type="button" className="btn" id={`expand-lab-${side}`} onClick={expandLab} title="Open this job in the Optimization Lab">
            Expand Lab
          </button>
        )}
        {choices.length >= 3 && (
          <>
            <label className="muted">
              Rows{' '}
              <select id={`matrix-rows-${side}`} value={axes[0]} aria-label="Matrix rows" onChange={(e) => setAxes(([r, c]) => [e.target.value, c === e.target.value ? r : c])}>
                {choices.map((p) => (
                  <option key={p} value={p}>
                    {label(p)}
                  </option>
                ))}
              </select>
            </label>
            <label className="muted">
              Columns{' '}
              <select id={`matrix-cols-${side}`} value={axes[1]} aria-label="Matrix columns" onChange={(e) => setAxes(([r, c]) => [r === e.target.value ? c : r, e.target.value])}>
                {choices.map((p) => (
                  <option key={p} value={p}>
                    {label(p)}
                  </option>
                ))}
              </select>
            </label>
          </>
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
        <div className="dock-matrix">
          {tooMany ? (
            <div className="heatmap">
              <div className="notice" id={`matrix-too-large-${side}`}>
                {tooMany}
              </div>
            </div>
          ) : (
          <Heatmap
            title={`${side.toUpperCase()} heatmap`}
            metric={METRIC_LABELS[metric]}
            fast={view.fast}
            slow={view.slow}
            matrix={view.matrix}
            format={FORMAT[metric]}
            profit={profitKind(metric)}
            detail={(fast, slow) => {
              const { cell, count } = view.cellAt(fast, slow);
              if (!cell) return null;
              const m = cell.metrics;
              const line = `Net P&L ${money(m.net_pnl)} · MAR ${num(m.mar, 2)} · Max DD ${pct(m.max_drawdown)} · Trades ${num(m.trade_count, 0)}`;
              return custom ? `${line} · ${squareTitle(count, cell, [view.rowPath, view.colPath], (p) => describeParams(p, planned))}` : line;
            }}
            rowLabel={label(view.rowPath) + '↓'}
            colLabel={label(view.colPath) + '→'}
            selected={selectedCell && selectedCell.fast !== undefined && selectedCell.slow !== undefined ? selectedCell : null}
            onSelect={(fast, slow) => {
              void pickSquare(fast, slow);
            }}
            empty="No two-axis grid for this job."
          />
          )}
          <div className="sub" id={`dock-basis-${side}`}>
            Aggregated: best of the rest · empty = untested
          </div>
          <div className="sub" id={`dock-validation-${side}`}>
            Validation: no partition (grid job) · Strategy Gate: not built
          </div>
        </div>
        <div className="results-table">
          <div className="panel-title">
            Parameter sets <span className="small">{done.toLocaleString()} evaluated · best first by {METRIC_LABELS[job.objective]}</span>
          </div>
          {job.cells.length === 0 && <div className="empty-state">{live ? 'Waiting for the first cell…' : 'No cells were evaluated.'}</div>}
          {shown < done && (
            <div className="legend small" id={`optimization-cells-pages-${side}`}>
              <span className="muted">
                {page === 0 ? `the best ${shown.toLocaleString()} of ${done.toLocaleString()}` : `cells ${(page * PAGE + 1).toLocaleString()}–${Math.min((page + 1) * PAGE, done).toLocaleString()} of ${done.toLocaleString()}`}
              </span>
              <button type="button" className="btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                ‹ Better
              </button>
              <button type="button" className="btn" id={`optimization-cells-next-${side}`} disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                Next {PAGE.toLocaleString()} ›
              </button>
            </div>
          )}
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
                {tableCells.map((cell) => {
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
                {s.toUpperCase()} {j ? `· ${j.status} ${j.cells_done ?? j.progress.done}/${j.total_cells ?? j.progress.total}` : '· not run'}
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
        {job && <OptimizationJobView key={job.job_id} side={side} job={job} />}
      </div>
    </div>
  );
}
