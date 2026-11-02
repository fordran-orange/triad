import { Heatmap, profitKind } from '../components/Heatmap';
import { MainEffects } from '../components/MainEffects';
import { DASH, money, num, pct } from '../format';
import { compactMoney } from '../layout';
import { METRIC_LABELS, type AxisMatrix, type Metric } from '../results';
import { AssumptionsLine } from './AssumptionsLine';
import { ImportanceView } from './ImportanceView';
import { InteractionMatrix } from './InteractionMatrix';
import { cursorDims, selectSquareAction } from './labHeatmapModel';
import { LabHeatmap } from './LabHeatmap';
import { useLab, useLabDispatch } from './labState';
import type { LabTab } from './labStore';
import { ParallelCoords } from './ParallelCoords';
import { ParetoView } from './ParetoView';
import { RobustnessView } from './RobustnessView';
import { TrialTable, type ScrollMemory, type TrialSort } from './TrialTable';
import type { LabQueryData } from './useLabQuery';
import { currentMatrix, type LabData, type TrialRow } from './useLabSource';

export const LAB_TABS: Array<{ tab: LabTab; label: string }> = [
  { tab: 'heatmap', label: 'Heatmap' },
  { tab: 'interactions', label: 'Interaction matrix' },
  { tab: 'parallel', label: 'Parallel coords' },
  { tab: 'pareto', label: 'Pareto' },
  { tab: 'importance', label: 'Importance' },
  { tab: 'robustness', label: 'Robustness (A–D)' },
];

/** How a square prints its value: the four optimizer metrics, and the trade Sharpe (per trade, two decimals) for
 *  an experiment's heatmap. */
export const FORMAT: Record<Metric | 'sharpe_trade', (v: number) => string> = {
  net_pnl: compactMoney, // a square holds "$47.2k"; its hover title gives the full amount
  mar: (v) => num(v, 2),
  max_drawdown: pct,
  trade_count: (v) => num(v, 0),
  sharpe_trade: (v) => num(v, 2),
};

/** A job path without the `indicators.` prefix: `ema.length`, `stop_loss_pct`. */
export const jobPathLabel = (path: string) => path.replace(/^indicators\./, '');

/** The four optimizer metrics of a cell, for a hover title or a card. */
export function metricsLine(m: { net_pnl: number | null; mar: number | null; max_drawdown: number | null; trade_count: number | null }): string {
  return `Net P&L ${money(m.net_pnl)} · MAR ${num(m.mar, 2)} · Max DD ${pct(m.max_drawdown)} · Trades ${num(m.trade_count, 0)}`;
}

/** The square at (row r, column c) of a job matrix: its count and the best cell of the rest, from the response. */
export function squareAt(matrix: AxisMatrix, metric: Metric, r: number, c: number) {
  const count = matrix.counts[r]?.[c] ?? 0;
  const at = matrix.metrics[metric]?.cells[r]?.[c] ?? null;
  return { count, best: at === null ? null : (matrix.cells[at] ?? null), value: matrix.metrics[metric]?.values[r]?.[c] ?? null };
}

/** The `opt` source's heatmap: the worker's matrix for the pair and metric in view, each square the best of the
 *  rest, drawn by the dock's Heatmap (which owns the losses-red tones). */
export function JobMatrix({ data }: { data: LabData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const job = data.loaded?.kind === 'opt' ? data.loaded.job : null;
  if (job === null) return null;
  // Only the matrix of the job, pair and metric in view: one built for another (the pair or the metric just changed,
  // its request still on the way) is never drawn under this one's labels. The Lab's keys read it the same way.
  const state = currentMatrix(data);
  const metric = data.optMetric ?? job.objective;
  const m = state.matrix;
  const n = m ? m.counts.flat().reduce((a, b) => a + b, 0) : null;
  const rows = m?.rows.length ?? 0;
  const cols = m?.cols.length ?? 0;
  const square = lab.selected !== null && 'square' in lab.selected ? lab.selected.square : null;
  // The keyboard cursor when there is one, else the selected square.
  const mark = lab.cursor && rows && cols ? { r: Math.min(lab.cursor.r, rows - 1), c: Math.min(lab.cursor.c, cols - 1) } : square ? { r: square.y, c: square.x } : null;
  const highlight = m && mark && m.rows[mark.r] !== undefined && m.cols[mark.c] !== undefined ? { fast: m.rows[mark.r], slow: m.cols[mark.c] } : null;
  const select = (fast: number, slow: number) => {
    const dims = cursorDims(m);
    if (!m || dims === null) return;
    const r = m.rows.indexOf(fast);
    const c = m.cols.indexOf(slow);
    if (r < 0 || c < 0) return;
    // The square carries the filter that defines it: the pair in view and its two values, as Enter sends it.
    dispatch(selectSquareAction(dims, r, c));
    if (lab.cursor) dispatch({ type: 'MOVE_CURSOR', dr: r - lab.cursor.r, dc: c - lab.cursor.c, rows, cols }); // the cursor follows the click
  };
  return (
    <div className="lab-matrix">
      <div className="lab-basis" id="lab-heatmap-basis" title="each square is the best tested cell among those sharing its two values">
        Aggregated from tested (n = {n === null ? '…' : n.toLocaleString('en-US')}) · empty = untested
      </div>
      <div className="sub" id="lab-heatmap-axes">
        Y (rows): {m?.rows_path ?? data.optAxes?.[0] ?? DASH} · X (columns): {m?.cols_path ?? data.optAxes?.[1] ?? DASH} · {METRIC_LABELS[metric]}
        {state.loading ? ' · updating…' : ''}
      </div>
      <AssumptionsLine panel="heatmap" />
      {state.error && <div className="error">Matrix unavailable: {state.error}</div>}
      {state.notice && <div className="notice">{state.notice}</div>}
      {!m && !state.error && !state.notice && <div className="lab-empty">Loading the matrix…</div>}
      {m && !state.notice && (
        <Heatmap
          title="Aggregated: best of the rest"
          metric={METRIC_LABELS[metric]}
          fast={m.rows}
          slow={m.cols}
          matrix={m.metrics[metric]?.values ?? null}
          format={FORMAT[metric]}
          rowLabel={jobPathLabel(m.rows_path) + '↓'}
          colLabel={jobPathLabel(m.cols_path) + '→'}
          selected={highlight}
          onSelect={select}
          empty="No two-axis grid for this job."
          lowerIsBetter={metric === 'max_drawdown'}
          profit={profitKind(metric)}
          detail={(fast, slow) => {
            const at = squareAt(m, metric, m.rows.indexOf(fast), m.cols.indexOf(slow));
            return `n ${at.count}${at.best ? ` · best of the rest: ${metricsLine(at.best.metrics)}` : ''}`;
          }}
        />
      )}
      <div className="sub">Arrow keys move the cursor across the squares, Enter selects one; Esc clears the brush.</div>
    </div>
  );
}

/** The existing report's main effects (the median of its objective at each value), kept under the Importance tab's new
 *  estimators: the plan keeps the report and labels the new estimators as additional, not equal to its medians (§11.1).
 *  A grid job has no report. */
function ReportEffects({ data }: { data: LabData }) {
  const { loaded } = data;
  if (loaded === null || loaded.kind === 'opt') return null;
  const { report } = loaded;
  if (report === null) return <div className="lab-empty">no report yet: recompute it on the Experiments page</div>;
  return (
    <section className="importance-report" id="lab-report-effects">
      <div className="rail-title">The experiment&apos;s report: main effects, a different estimate from the shares above</div>
      <div className="lab-basis" title="the median of the report's objective over the tested cells at each value, with its p25–p75 band">
        Aggregated from tested (median per value)
      </div>
      <div className="sub">
        Report {report.report_id} · objective {report.objective} · {report.valid_cells.toLocaleString('en-US')} valid cells
      </div>
      <MainEffects effects={report.main_effects} objective={report.objective} lowerIsBetter={report.objective === 'max_drawdown'} />
    </section>
  );
}

/** The centre of Trial Lab: the six analysis tabs over the trials table. */
export function LabCenter({
  data,
  sort,
  onSort,
  onSelect,
  memory,
}: {
  data: LabQueryData;
  sort: TrialSort;
  onSort: (sort: TrialSort) => void;
  onSelect: (row: TrialRow) => void;
  memory: ScrollMemory;
}) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { tab } = lab;
  const { loaded, loading } = data;
  const kind = loaded?.kind ?? lab.source?.kind ?? null;
  const none = <div className="lab-empty">{loading ? 'Loading…' : 'No source open: choose one in the context bar.'}</div>;
  // A grid job keeps the Phase 1 heatmap (the worker's best-of-the-rest matrix); an experiment's heatmap and either
  // source's parallel coordinates read the /lab query layer.
  const panel =
    tab === 'heatmap' ? (
      kind === 'opt' ? (
        <JobMatrix data={data} />
      ) : kind === 'exp' ? (
        <LabHeatmap data={data} />
      ) : (
        none
      )
    ) : kind === null ? (
      none
    ) : tab === 'interactions' ? (
      <InteractionMatrix data={data} />
    ) : tab === 'parallel' ? (
      <ParallelCoords data={data} />
    ) : tab === 'pareto' ? (
      <ParetoView data={data} />
    ) : tab === 'importance' ? (
      <ImportanceView data={data}>
        <ReportEffects data={data} />
      </ImportanceView>
    ) : (
      <RobustnessView data={data} />
    );
  return (
    <div className={'lab-center' + (lab.maximized ? ' maximized' : '')} id="lab-center">
      <div className="lab-tabs" id="lab-tabs" role="tablist" aria-label="Analysis views">
        {LAB_TABS.map((t) => (
          <button
            type="button"
            role="tab"
            key={t.tab}
            id={`lab-tab-${t.tab}`}
            className={'tab lab-tab' + (tab === t.tab ? ' active' : '')}
            aria-selected={tab === t.tab}
            aria-controls="lab-panel"
            onClick={() => dispatch({ type: 'SET_TAB', tab: t.tab })}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          className="btn btn-ghost lab-maximize"
          id="lab-maximize"
          aria-pressed={lab.maximized}
          title={lab.maximized ? 'Restore the parameters and the trials (Esc)' : 'Give this panel the whole body (Esc restores)'}
          onClick={() => dispatch({ type: 'SET_MAXIMIZED', maximized: !lab.maximized })}
        >
          {lab.maximized ? 'Restore' : 'Maximize'}
        </button>
      </div>
      <div className="lab-panel" id="lab-panel" role="tabpanel" aria-labelledby={`lab-tab-${tab}`}>
        {panel}
      </div>
      {!lab.maximized &&
        (loaded ? (
          <TrialTable key={`${loaded.kind}:${loaded.id}`} data={data} sort={sort} onSort={onSort} onSelect={onSelect} memory={memory} />
        ) : (
          <div className="lab-trials">
            <div className="lab-empty">{loading ? 'Loading trials…' : 'No source open: choose one in the context bar.'}</div>
          </div>
        ))}
    </div>
  );
}
