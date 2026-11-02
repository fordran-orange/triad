// The convergence chart's decisions (spec §7.10), nothing React and nothing drawn: best-so-far as a step line, the
// robust series per batch with its gaps, the scale they share, what the chart says about itself, and how often it is
// asked. The worker's `convergence` view sends both series in the metric's own units with `orientation` beside them
// (orientation -1: lower is better), so nothing here negates or re-sorts a value. `ConvergenceChart` only draws what
// this returns.
//
// What the chart never does: ramp between kept trials (an improvement is shown at the kept trial that has it, which is
// at or after the trial that made it, never before), join batches across a batch without a measured neighbour or across
// batches the worker thinned apart, or draw past the last kept trial or the last complete batch.
import type { LabConvergence, LabConvergenceBatch, LabEnvelope } from '../results';
import { bareMetric, breakEven, objectiveText } from './metricRules';

export { bareMetric };

// The cadence the chart began with is every expensive panel's now (`refreshRule.ts`); it is re-exported for the chart's own tests.
export { CONVERGENCE_REFRESH_MS, refreshDelay } from './refreshRule';

export interface Vertex {
  x: number;
  y: number;
}

/** Best-so-far as the vertices of a step line: each kept value is held until the next kept trial, where the line rises
 *  (or falls) straight. A kept point is true at its `trial_no`; the improvements between two kept points show late, at the
 *  second, and never early. A ramp would show them early. */
export function stepVertices(best: ReadonlyArray<readonly [number, number]>): Vertex[] {
  const out: Vertex[] = [];
  best.forEach(([x, y], i) => {
    if (i > 0 && best[i - 1][1] !== y) out.push({ x, y: best[i - 1][1] });
    out.push({ x, y });
  });
  return out;
}

/** The value of the step line at trial `x`: the last kept point at or before it. Null before the first kept trial and
 *  past the last one, where nothing is known. */
export function stepValueAt(best: ReadonlyArray<readonly [number, number]>, x: number): number | null {
  if (best.length === 0 || x < best[0][0] || x > best[best.length - 1][0]) return null;
  let value: number | null = null;
  for (const [trial, v] of best) {
    if (trial > x) break;
    value = v;
  }
  return value;
}

/** One straight piece of the step line and whether it is a loss: a P&L-signed metric below its break-even is red, never
 *  the blue of a best. A jump across the break-even is cut there so each half has its own colour. */
export interface Piece {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  loses: boolean;
}

export function bestPieces(best: ReadonlyArray<readonly [number, number]>, metric: string): Piece[] {
  const even = breakEven(metric);
  const vertices = stepVertices(best);
  const loses = (a: number, b: number) => even !== null && (a + b) / 2 < even;
  const pieces: Piece[] = [];
  for (let i = 1; i < vertices.length; i++) {
    const a = vertices[i - 1];
    const b = vertices[i];
    if (even !== null && a.x === b.x && Math.min(a.y, b.y) < even && Math.max(a.y, b.y) > even) {
      pieces.push({ x0: a.x, y0: a.y, x1: b.x, y1: even, loses: loses(a.y, even) }, { x0: b.x, y0: even, x1: b.x, y1: b.y, loses: loses(even, b.y) });
    } else {
      pieces.push({ x0: a.x, y0: a.y, x1: b.x, y1: b.y, loses: loses(a.y, b.y) });
    }
  }
  return pieces;
}

/** One complete batch with a value: the median and quartiles of its neighbourhood P25, placed at the batch's last trial. */
export interface RobustPoint {
  batch: number;
  x: number;
  median: number;
  p25: number;
  p75: number;
  measured: number;
  top: number;
}

/** The robust series as runs to draw: consecutive batches that all have a value. A batch with no measured neighbour (its
 *  values are null) is a gap, and so is the distance between two batches the worker thinned apart: neither is joined across,
 *  zero-filled or interpolated. */
export function robustRuns(robust: readonly LabConvergenceBatch[]): RobustPoint[][] {
  const runs: RobustPoint[][] = [];
  let run: RobustPoint[] | null = null;
  let previous: number | null = null;
  for (const b of robust) {
    if (b.median === null || b.p25 === null || b.p75 === null) {
      run = null;
      previous = b.batch;
      continue;
    }
    if (run === null || previous === null || b.batch !== previous + 1) {
      run = [];
      runs.push(run);
    }
    run.push({ batch: b.batch, x: b.trial_no, median: b.median, p25: b.p25, p75: b.p75, measured: b.measured, top: b.top });
    previous = b.batch;
  }
  return runs;
}

export interface ConvergenceModel {
  /** The `<scope>.<metric>` column, and the bare metric the labels use. */
  column: string;
  metric: string;
  orientation: 1 | -1;
  better: 'higher is better' | 'lower is better';
  /** The step line's vertices and its pieces coloured by loss. */
  best: Vertex[];
  pieces: Piece[];
  /** The points the worker sent, and the trials they were thinned from. */
  bestPoints: number;
  bestTotal: number;
  runs: RobustPoint[][];
  /** Complete batches the view counted (`LabConvergence.batches`). */
  batches: number;
  xDomain: [number, number] | null;
  yDomain: [number, number] | null;
  /** Where the metric stops losing money, only when the data reaches it. */
  breakEven: number | null;
  provisional: boolean;
  /** The envelope's `empty`, which the full chart reads; the compact chart draws `best` whatever it says. */
  emptyReason: string | null;
  /** Why the robust series is empty (under MIN_BATCHES complete batches), null when it is not. */
  robustReason: string | null;
  robustNote: string;
  basis: string;
  summary: string;
}

const count = (n: number) => n.toLocaleString('en-US');
/** `1 trial`, `2 trials`; `es` for the words that take it (`batch`). */
const plural = (n: number, word: string, ending = 's') => `${count(n)} ${word}${n === 1 ? '' : ending}`;

/** A scale over the data with a margin, never of zero height. */
function paddedDomain(values: readonly number[]): [number, number] | null {
  if (values.length === 0) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = hi === lo ? Math.abs(lo) * 0.1 || 1 : (hi - lo) * 0.06;
  return [lo - pad, hi + pad];
}

/** A `convergence` answer as the chart draws it. */
export function convergenceModel(view: LabEnvelope<LabConvergence>): ConvergenceModel {
  const metric = bareMetric(view.metric);
  const runs = robustRuns(view.robust);
  const points = runs.flat();
  const xs = [...view.best.map(([x]) => x), ...points.map((p) => p.x)];
  const ys = [...view.best.map(([, y]) => y), ...points.flatMap((p) => [p.p25, p.p75])];
  const even = breakEven(metric);
  const reached = even !== null && ys.length > 0 && even >= Math.min(...ys) && even <= Math.max(...ys);
  const gaps = view.robust.filter((b) => b.median === null || b.p25 === null || b.p75 === null).length;
  const { constants } = view;

  const robustNote =
    view.robust.length === 0
      ? ''
      : `robust: ${plural(view.robust.length, 'batch', 'es')} of ${count(constants.CONVERGENCE_BATCH)} trials, the neighbourhood P25 of each batch's top ${Number((constants.CONVERGENCE_TOP * 100).toPrecision(3))} % (median and quartiles)${
          gaps > 0 ? ` · ${gaps} with no measured neighbour: ${gaps === 1 ? 'a gap' : 'gaps'}` : ''
        }`;

  const lastBest = view.best.length > 0 ? view.best[view.best.length - 1][1] : null;
  const latest = points.length > 0 ? points.reduce((a, b) => (b.batch > a.batch ? b : a)) : null;
  const head = `convergence of ${metric}`;
  const fmt = (v: number) => objectiveText(metric, v);
  let summary: string;
  if (lastBest === null) summary = `${head}: no trial with a defined value`;
  else {
    const robust =
      latest !== null ? `latest robust median ${fmt(latest.median)} over ${plural(view.robust.length, 'batch', 'es')}` : view.robust.length > 0 ? 'no batch has a measured neighbour' : 'no robust series yet';
    summary = `${head}: best so far ${fmt(lastBest)} after ${plural(view.best_total, 'trial')}, ${robust}`;
  }

  return {
    column: view.metric,
    metric,
    orientation: view.orientation,
    better: view.orientation === -1 ? 'lower is better' : 'higher is better',
    best: stepVertices(view.best),
    pieces: bestPieces(view.best, metric),
    bestPoints: view.best.length,
    bestTotal: view.best_total,
    runs,
    batches: view.batches,
    xDomain: xs.length === 0 ? null : [Math.min(...xs), Math.max(...xs)],
    yDomain: paddedDomain(ys),
    breakEven: reached ? even : null,
    provisional: view.provisional,
    emptyReason: view.empty,
    robustReason: view.robust_reason,
    robustNote,
    basis: view.basis,
    summary,
  };
}

