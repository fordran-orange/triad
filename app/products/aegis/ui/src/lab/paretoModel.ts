// The Pareto panel's decisions (spec §7.7), nothing React and nothing drawn: which metrics the pickers offer, the
// frame the front and its dominated cloud share, where each exact front point and each density bin lands on the
// canvas, and the counts and basis the panel prints. `ParetoView` only draws what this returns. The payload's `points`
// and `density` are in REAL values (a drawdown is the drawdown itself): `orientation` is for reading direction and for
// sizing a third objective, never for placing a point. A chart never implies data that was not tested, so nothing here
// joins the front into a line or fills a bin that holds no trial.
import type { ProfitKind } from '../components/Heatmap';
import { profitKind } from '../components/Heatmap';
import type { LabPareto, LabSnapshot } from '../results';
import { linearScale, type Scale } from './charts/canvas';
import { trialLabel } from './candidateModel';
import { metricName } from './labHeatmapModel';
import { panelLabel } from './labQuery';
import { objectiveText } from './LabKpiStrip';

/** The pickers: two required objectives and an optional third (§7.7). The worker's own `OBJECTIVES_MIN` / `MAX` ride on
 *  every response; the number of pickers is the layout of the panel. */
const SLOTS = 3;
/** What the pickers start from, and pad a thin choice with. */
export const DEFAULT_OBJECTIVES = ['net_pnl', 'max_drawdown'];

/** The chosen objectives the source offers: the chosen ones that it does, once each and at most three, then padded from
 *  the defaults and the offered metrics to two. A grid job offers four metrics, an experiment ten: a choice carried over
 *  from one to the other is trimmed here rather than sent to be refused. */
export function usableObjectives(chosen: readonly string[], available: readonly string[]): string[] {
  const out: string[] = [];
  for (const metric of chosen) if (available.includes(metric) && !out.includes(metric) && out.length < SLOTS) out.push(metric);
  for (const metric of [...DEFAULT_OBJECTIVES, ...available]) {
    if (out.length >= 2) break;
    if (available.includes(metric) && !out.includes(metric)) out.push(metric);
  }
  return out;
}

/** What picker `slot` offers: every available metric except those the other pickers hold. */
export function objectiveOptions(chosen: readonly string[], slot: 0 | 1 | 2, available: readonly string[]): string[] {
  return available.filter((metric) => !chosen.some((held, i) => i !== slot && held === metric));
}

/** The choice after picker `slot` is set to `metric`: a metric another picker held changes places with this one's; the
 *  third picker can be emptied (null) and the first two cannot, and a third cannot copy a metric that is already held. */
export function withObjective(chosen: readonly string[], slot: 0 | 1 | 2, metric: string | null): string[] {
  const next = [...chosen];
  if (metric === null) return slot === 2 ? next.slice(0, 2) : next;
  if (slot > next.length) return next;
  const held = next.indexOf(metric);
  if (held === slot) return next;
  if (held >= 0) {
    if (next[slot] === undefined) return next;
    [next[held], next[slot]] = [next[slot], next[held]];
    return next;
  }
  next[slot] = metric;
  return next;
}

export const directionText = (orientation: 1 | -1) => (orientation === 1 ? 'higher is better' : 'lower is better');

/** An axis title: the metric and which way is better. */
export function axisTitle(metric: string, orientation: 1 | -1): string {
  return `${metricName(metric)} · ${directionText(orientation)}`;
}

/** Where a metric stops losing money: 0, or 1 for a ratio such as the profit factor; null for a metric with no profit sign. */
export function breakEven(metric: string): number | null {
  const kind: ProfitKind = profitKind(metric);
  return kind === null ? null : kind === 'ratio' ? 1 : 0;
}

/** Whether `value` of `metric` loses money: strictly below its break-even (break-even itself is neutral); a metric with no
 *  profit sign, such as a drawdown, never does. */
export function losesMoney(metric: string, value: number | null): boolean {
  const even = breakEven(metric);
  return even !== null && value !== null && value < even;
}

/** A front point is a loss when any money-signed objective of it is below break-even, whatever its rank: a losing value is
 *  never drawn as the best. */
export function pointTone(objectives: readonly string[], values: readonly number[]): 'front' | 'loss' {
  return objectives.some((metric, i) => losesMoney(metric, values[i] ?? null)) ? 'loss' : 'front';
}

/** The plot's margins: the y title and tick labels on the left, the x title and tick labels below. */
export const PARETO_MARGIN = { left: 78, right: 18, top: 12, bottom: 44 };
/** A plot narrower or lower than this has no room for a point. */
const MIN_PLOT = 40;

export interface PlotBox {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** The plot's rectangle inside a width × height canvas; null when it would be too small to hold a point. */
export function plotBox(width: number, height: number): PlotBox | null {
  const box = { x0: PARETO_MARGIN.left, x1: width - PARETO_MARGIN.right, y0: PARETO_MARGIN.top, y1: height - PARETO_MARGIN.bottom };
  return box.x1 - box.x0 >= MIN_PLOT && box.y1 - box.y0 >= MIN_PLOT ? box : null;
}

export interface ParetoScales {
  x: Scale;
  y: Scale;
  box: PlotBox;
}

/** The scales of the density's frame, which the front's points share: the first objective along x, the second up y. Null
 *  without a range (no trial has every objective defined) or without room. */
export function paretoScales(view: LabPareto, width: number, height: number): ParetoScales | null {
  const box = plotBox(width, height);
  const { x, y } = view.density;
  if (box === null || x === null || y === null) return null;
  return { x: linearScale(x, [box.x0, box.x1]), y: linearScale(y, [box.y1, box.y0]), box };
}

/** The dot radii: one for two objectives, and with a third, from the worst to the best of the drawn points. */
const R_FLAT = 3.5;
const R_MIN = 2.5;
const R_MAX = 6.5;

export interface PlotPoint {
  id: string;
  x: number;
  y: number;
  r: number;
  tone: 'front' | 'loss';
  values: number[];
}

/** The exact front points at their real values. With three objectives the third sets the radius, the better the bigger
 *  (its orientation read as direction only); a third that is one value everywhere gives every dot the middle radius. */
export function plotPoints(view: LabPareto, scales: ParetoScales | null): PlotPoint[] {
  if (scales === null) return [];
  const third = view.objectives.length > 2;
  const goodness = view.points.map((p) => (third ? view.orientation[2] * (p.values[2] ?? Number.NaN) : 0));
  const finite = goodness.filter(Number.isFinite);
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  return view.points.map((p, i) => ({
    id: p.trial_id,
    x: scales.x(p.values[0]),
    y: scales.y(p.values[1]),
    r: !third ? R_FLAT : !Number.isFinite(goodness[i]) || hi === lo ? (R_MIN + R_MAX) / 2 : R_MIN + ((goodness[i] - lo) / (hi - lo)) * (R_MAX - R_MIN),
    tone: pointTone(view.objectives, p.values),
    values: p.values,
  }));
}

export interface DensityRect {
  /** The bin: `bx` along the first objective, `by` along the second, both ascending. */
  bx: number;
  by: number;
  x: number;
  y: number;
  w: number;
  h: number;
  count: number;
  /** Fuller bins are drawn stronger (log scaled, so one crowded bin does not wash out the rest). */
  alpha: number;
  /** A bin wholly below break-even on a money-signed objective is red; the rest are the neutral cloud. */
  tone: 'cloud' | 'loss';
}

const ALPHA_MIN = 0.15;
const ALPHA_SPAN = 0.75;

/** The dominated cloud as rectangles: one per bin that holds a trial and none for an empty bin, so an untested region is
 *  never painted. `counts[y][x]` ascends along both axes, so the y edges are flipped onto the canvas. */
export function densityRects(view: LabPareto, scales: ParetoScales | null): DensityRect[] {
  const { x: xr, y: yr, counts, bins, axes } = view.density;
  if (scales === null || xr === null || yr === null) return [];
  const most = Math.max(0, ...counts.flat());
  const evenX = breakEven(axes[0] ?? view.objectives[0]);
  const evenY = breakEven(axes[1] ?? view.objectives[1]);
  const edge = (range: [number, number], k: number) => range[0] + ((range[1] - range[0]) * k) / bins;
  const rects: DensityRect[] = [];
  counts.forEach((row, by) =>
    row.forEach((count, bx) => {
      if (count <= 0) return;
      const left = scales.x(edge(xr, bx));
      const top = scales.y(edge(yr, by + 1));
      const loses = (evenX !== null && edge(xr, bx + 1) < evenX) || (evenY !== null && edge(yr, by + 1) < evenY);
      rects.push({
        bx,
        by,
        x: left,
        y: top,
        w: scales.x(edge(xr, bx + 1)) - left,
        h: scales.y(edge(yr, by)) - top,
        count,
        alpha: ALPHA_MIN + (ALPHA_SPAN * Math.log1p(count)) / Math.log1p(most),
        tone: loses ? 'loss' : 'cloud',
      });
    }),
  );
  return rects;
}

const count = (n: number) => n.toLocaleString('en-US');

export interface ParetoCounts {
  /** The true size of the rank-1 front, not the number of points drawn. */
  frontSize: number;
  dominated: number;
  excluded: number;
  drawn: number;
  sampled: boolean;
  sampledLabel: string;
}

/** The counts the panel prints. `sampledLabel` is the server's `Sampled subset (n of N)` when the front was thinned. */
export function paretoCounts(view: LabPareto): ParetoCounts {
  return {
    frontSize: view.front_size,
    dominated: view.dominated,
    excluded: view.excluded,
    drawn: view.points.length,
    sampled: view.sampled,
    sampledLabel: view.sampled ? view.basis : `all ${count(view.front_size)} front points drawn`,
  };
}

/** `#lab-pareto-basis`: the front's basis and the cloud's, verbatim, and the snapshot while the source runs. */
export function paretoBasis(view: LabPareto, answer: { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string }): string {
  return `Front: ${view.basis} · Dominated cloud: ${view.density.basis}${panelLabel(answer)}`;
}

/** The canvas's text twin: the objectives with their direction and every count. */
export function paretoSummary(view: LabPareto): string {
  const c = paretoCounts(view);
  const objectives = view.objectives.map((metric, i) => `${metricName(metric)} (${directionText(view.orientation[i] ?? 1)})`).join(', ');
  return `Pareto front of ${objectives}: ${count(c.frontSize)} on the front, ${count(c.dominated)} dominated, ${count(c.excluded)} excluded, ${count(c.drawn)} drawn`;
}

/** A front point's hover title: its trial and every objective in real units. Empty for no such point. */
export function pointTitle(view: LabPareto, index: number): string {
  const point = view.points[index];
  if (point === undefined) return '';
  const values = view.objectives.map((metric, i) => `${metricName(metric)} ${objectiveText(metric, point.values[i] ?? null)}`);
  return [trialLabel(point.trial_id), ...values].join(' · ');
}
