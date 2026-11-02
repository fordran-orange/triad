// The parallel coordinates' decisions (spec §7.9), nothing React and nothing drawn: the bin math the server's bundles
// rest on, where each axis stands, a bundle's line and opacity, a pinned trial's exact line, the sample mode's lines (a
// stratified sample of actual trials, §7.9's exact mode) and the order they are drawn in, which axis a press lands on,
// what a brush writes to the shared filter, and the basis and live-region texts. ParallelCoords only draws what this
// returns.
import type { LabParallel, LabParallelLine, LabQueryBody, LabSnapshot } from '../results';
import type { Scale } from './charts/canvas';
import { panelLabel } from './labQuery';
import type { LabAction } from './labStore';
import { bareMetric } from './metricRules';

/** Phase 2 draws at most this many axes: the active parameters in catalog order. */
export const PARALLEL_MAX_AXES = 10;
/** The lowest opacity a bundle is drawn at, however few trials it holds. */
export const OPACITY_FLOOR = 0.08;

/** The `p` quantile of sorted values, linear between neighbours (numpy's default). */
function quantile(sorted: number[], p: number): number {
  const at = (sorted.length - 1) * p;
  const lo = Math.floor(at);
  const hi = Math.ceil(at);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
}

/** The edges of q quantile bins over `values` (the server's `np.quantile` cut), a repeated edge collapsed: a bin is
 *  [edges[i], edges[i + 1]), the last one closed, so every value lands in exactly one bin. One distinct value is
 *  one closed bin [v, v]; no values, no edges. */
export function binEdges(values: number[], q: number): number[] {
  const finite = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (finite.length === 0 || q < 1) return [];
  const edges: number[] = [];
  for (let i = 0; i <= q; i++) {
    const edge = quantile(finite, i / q);
    if (edges.length === 0 || edge !== edges[edges.length - 1]) edges.push(edge);
  }
  return edges.length === 1 ? [edges[0], edges[0]] : edges;
}

/** A bundle's identity: its bin vector, one bin index per axis. */
export function bundleKey(bins: number[]): string {
  return bins.join('|');
}

/** A bundle's line: on each axis, the centre of its bin there on that axis's scale. Axis i stands at xs[i] (the
 *  canvas passes `axisPositions`); without xs, at its index. */
export function polyline(bundle: { bins: number[] }, axes: Scale[], centres: number[][], xs: readonly number[] = axes.map((_, i) => i)): Array<[number, number]> {
  return axes.map((axis, i) => [xs[i], axis(centres[i]?.[bundle.bins[i]] ?? Number.NaN)]);
}

/** A trial's exact line through its own parameter values; an axis it has no value on breaks the line (null). */
export function exactLine(params: Record<string, number | null>, paths: string[], axes: Scale[], xs: readonly number[]): Array<[number, number] | null> {
  return paths.map((path, i) => {
    const v = params[path];
    return typeof v === 'number' && Number.isFinite(v) ? [xs[i], axes[i](v)] : null;
  });
}

/** A bundle's opacity: proportional to its count against the largest, never under the floor, never over 1. */
export function opacityFor(count: number, maxCount: number): number {
  if (!(maxCount > 0) || !(count > 0)) return OPACITY_FLOOR;
  return Math.min(1, Math.max(OPACITY_FLOOR, count / maxCount));
}

/** A brush on an axis as the shared filter's range on that parameter (ordered, binary noise trimmed); null, a
 *  click without a drag, clears it. */
export function brushToFilter(axis: string, range: [number, number] | null): LabAction {
  if (range === null) return { type: 'SET_RANGE', path: axis, range: null };
  const trim = (v: number) => Number(v.toPrecision(6));
  const [a, b] = range;
  return { type: 'SET_RANGE', path: axis, range: [trim(Math.min(a, b)), trim(Math.max(a, b))] };
}

/** The x pixel of each axis: pad, …, width − pad, evenly spaced; one axis in the middle. The one computation the
 *  canvas, the brushes and the `.parallel-axis` labels share. */
export function axisPositions(count: number, width: number, pad: number): number[] {
  if (count <= 0) return [];
  if (count === 1) return [width / 2];
  const step = (width - 2 * pad) / (count - 1);
  return Array.from({ length: count }, (_, i) => pad + i * step);
}

/** The axis a press at `px` lands on: the closest within `tolerance` pixels, else -1. */
export function nearestAxis(xs: readonly number[], px: number, tolerance: number): number {
  let best = -1;
  for (let i = 0; i < xs.length; i++) {
    const d = Math.abs(xs[i] - px);
    if (d <= tolerance && (best < 0 || d < Math.abs(xs[best] - px))) best = i;
  }
  return best;
}

/** An axis's name where ten share a canvas: the side as L / S and the path without `<side>_side.indicators.` (a
 *  grid job's own path without `indicators.`); the full path is the label's title. */
export function axisLabel(path: string): string {
  const side = /^(long|short)_side\./.exec(path);
  const rest = (side ? path.slice(side[0].length) : path).replace(/^indicators\./, '');
  return side ? `${side[1] === 'long' ? 'L' : 'S'} ${rest}` : rest;
}

const RAW_TAIL = ' · 0 raw lines drawn';

/** `#lab-parallel-basis`: the server's basis verbatim while no pin is active (`pinned` null); with pins, its
 *  `· 0 raw lines drawn` tail becomes `· k pinned trials drawn exactly` (k the pinned lines drawn). */
export function parallelBasis(basis: string, pinned: number | null): string {
  if (pinned === null) return basis;
  const head = basis.endsWith(RAW_TAIL) ? basis.slice(0, -RAW_TAIL.length) : basis;
  return `${head} · ${pinned} pinned trial${pinned === 1 ? '' : 's'} drawn exactly`;
}

/** What the panel says about the answer for the view now asked for: its basis line, and the lead of its explanation (what a line
 *  is, which depends on the mode the answer is of). Both are blank without that answer: after the mode, the metric or the filter
 *  changes the canvas is blank until the new answer lands, and a basis or a sentence about the previous answer would be false. */
export function parallelCaption(
  answer: (LabParallel & { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string }) | null,
  pinned: number | null,
): { basis: string; lead: string } {
  if (answer === null) return { basis: '', lead: '' };
  return {
    basis: `${parallelBasis(answer.basis, pinned)}${panelLabel(answer)}`,
    lead: isSampleView(answer) ? `Each line is one sampled trial through its own values (${sampleNote(answer)}); ` : 'Each line is a bundle of trials sharing a quantile bin on every axis; ',
  };
}

/** The note under the toolbar: what a line is (`lead`, which depends on the answer) and then the tail that tells how to brush. Blank
 *  when the lead is: a tail alone would open on a lower-case fragment, and the note describes an answer that is not there. */
export function parallelNote(lead: string, tail: string): string {
  return lead === '' ? '' : `${lead}${tail}`;
}

/** Everything the panel says about its answer, from the answer for the key now asked for or from none: the basis line, the note
 *  under the toolbar, and the summary (`#lab-parallel-summary` and the canvas's label). All four are blank while a new view loads
 *  (after the mode, the metric or the filter changed, the canvas is blank until its answer lands, and any of the words would
 *  describe the previous one). `metric` is the one the answer was asked for; `format` prints one of its values. */
export function parallelWords(
  answer: { envelope: LabParallel & { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string }; metric: string } | null,
  pinned: number | null,
  tail: string,
  format: (metric: string, value: number) => string,
): { basis: string; lead: string; note: string; summary: string } {
  if (answer === null) return { basis: '', lead: '', note: '', summary: '' };
  const { basis, lead } = parallelCaption(answer.envelope, pinned);
  const { metric } = answer;
  return { basis, lead, note: parallelNote(lead, tail), summary: parallelSummary(answer.envelope, metric, metric === 'max_drawdown', (v) => format(metric, v)) };
}

/** `#lab-parallel-summary`, the chart's DOM twin: the bundles drawn over the axes, the largest bundle and the best
 *  defined median (`format` prints it). */
export function parallelSummary(view: LabParallel, metric: string, lowerIsBetter: boolean, format: (v: number) => string): string {
  if (isSampleView(view)) return sampleSummary(view, metric, lowerIsBetter, format);
  const head = `parallel coordinates: ${view.shown_bundles.toLocaleString('en-US')} bundles over ${view.axes.length} axes`;
  if (view.bundles.length === 0) return head;
  const largest = Math.max(...view.bundles.map((b) => b.count));
  let best: number | null = null;
  for (const { median } of view.bundles) {
    if (median === null || !Number.isFinite(median)) continue;
    if (best === null || (lowerIsBetter ? median < best : median > best)) best = median;
  }
  return `${head}, largest ${largest.toLocaleString('en-US')} trials, best median ${metric} ${best === null ? '—' : format(best)}`;
}

// --- sample mode (§7.9, exact mode) ----------------------------------------------------------------------------------

/** The parallel view's two modes: its aggregated bundles (the default), or a stratified sample of actual trials. */
export type ParallelMode = 'bundles' | 'sample';

/** What the request adds to the filter for the mode. Bundles are the worker's default and are asked exactly as in Phase 2
 *  (no `parallel_mode` at all); the sample is asked for by name, and the worker bounds and seeds it. */
export function parallelRequest(mode: ParallelMode, axes: string[], metric: string): Partial<LabQueryBody> {
  return mode === 'sample' ? { axes, metric, parallel_mode: 'sample' } : { axes, metric };
}

/** A sample answer carries its lines (the bundle fields are sent empty beside them). */
export function isSampleView(view: LabParallel): boolean {
  return view.lines !== undefined;
}

/** The order the sampled lines are drawn in, as indexes into `lines`: the worst first, so the best lie on top; lines of
 *  equal value keep the order they came in. `lowerIsBetter` is the metric's (a drawdown). */
export function sampleOrder(lines: readonly LabParallelLine[], lowerIsBetter: boolean): number[] {
  const goodness = (k: number) => (lowerIsBetter ? -lines[k].metric : lines[k].metric);
  return lines.map((_, k) => k).sort((a, b) => goodness(a) - goodness(b) || a - b);
}

/** A sampled trial's line through its own values on the axes; an axis it has no value on breaks the line (null). */
export function sampleLine(values: ReadonlyArray<number | null>, axes: Scale[], xs: readonly number[]): Array<[number, number] | null> {
  return axes.map((axis, i) => {
    const v = values[i];
    return typeof v === 'number' && Number.isFinite(v) ? [xs[i], axis(v)] : null;
  });
}

/** `#lab-parallel-summary` for a sample: the lines drawn, the trials they were drawn from, and the best metric among them. */
function sampleSummary(view: LabParallel, metric: string, lowerIsBetter: boolean, format: (v: number) => string): string {
  const lines = view.lines ?? [];
  const from = (view.sampled_from ?? 0).toLocaleString('en-US');
  const head = `parallel coordinates: ${lines.length.toLocaleString('en-US')} sampled lines of ${from} trials over ${view.axes.length} axes`;
  if (lines.length === 0) return head;
  const best = lines.reduce((a, b) => ((lowerIsBetter ? b.metric < a : b.metric > a) ? b.metric : a), lines[0].metric);
  return `${head}, best ${metric} ${format(best)}`;
}

/** How the sample was drawn and what it left out (§7.9): its strata, its seed, and the trials with no value of the metric,
 *  which have no decile and are never drawn. Empty for bundles. */
export function sampleNote(view: LabParallel): string {
  if (!isSampleView(view)) return '';
  const metric = bareMetric(view.metric ?? '');
  const left = view.excluded ?? 0;
  return `a stratified sample, ${view.strata ?? 0} strata by decile of ${metric}, seed ${view.seed ?? 0}${left > 0 ? `; ${left.toLocaleString('en-US')} trials with no ${metric} value are not drawn` : ''}`;
}
