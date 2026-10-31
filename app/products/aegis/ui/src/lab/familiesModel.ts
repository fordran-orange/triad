// Parameter Families' decisions (Screen E, spec §5.5, §7.8), nothing React and nothing drawn: the scope breadcrumb's
// counts, the pairs of the trellis and the squares of each (a lattice of up to 16 values per axis, merged past that into
// groups whose trials all stay counted), the filter that defines a square and so its drill-down, the robust
// neighbourhood map's rings, the candidate's A and B states and the family tree's counts. The worker decides everything
// statistical; this only arranges what it sent, and it never filters, interpolates or fills a square: a square no trial
// tested stays untested, and a square with fewer than `TRELLIS_MIN_N` trials is hatched and carries no tone.
//
// Count-preserving drill-down (§7.8): a square's `n` equals the `page` total of the same filter plus the square, because
// the square IS that filter (`cellFilter`). The page is asked on the worker; nothing here filters rows.
import { DASH, pct } from '../format';
import type { LabCandidateCard, LabCounts, LabInteractions, LabMatrix, LabParameter } from '../results';
import { candidateCardModel } from './candidateModel';
import type { Family } from './catalog';
import { heatModel, valueText, type Tone } from './labHeatmapModel';
import { displayShare, filterLines } from './labQuery';
import { activeFilterCount, type LabFilter } from './labStore';
import { lowerIsBetter, objectiveText } from './metricRules';
import { axisLabel } from './parallelBundles';

/** A trellis matrix shows at most this many squares per axis (§5.5). */
export const TRELLIS_MAX_SIDE = 16;
/** A square under this many trials is hatched and left out of the scale and of the importance (§5.5). The worker has no
 *  constant for it, so it is the spec's own number, printed on the panel. */
export const TRELLIS_MIN_N = 30;
/** How many of the top pairs the trellis draws. A display choice, printed on the panel. */
export const TRELLIS_PAIRS = 6;

const count = (n: number) => n.toLocaleString('en-US');
const plural = (n: number, word: string) => `${count(n)} ${word}${n === 1 ? '' : 's'}`;

// --- the squares of a pair ------------------------------------------------------------------------------------------

/** A run of neighbouring lattice values drawn as one square on an axis: their index range and the first and last value. */
export interface AxisGroup {
  from: number;
  to: number;
  lo: number;
  hi: number;
}

/** The lattice `values` (ascending) as at most `limit` contiguous groups of equal width, the last possibly narrower. A
 *  lattice that fits stays one square per value. */
export function groupAxis(values: readonly number[], limit = TRELLIS_MAX_SIDE): AxisGroup[] {
  const size = Math.max(1, Math.ceil(values.length / limit));
  const groups: AxisGroup[] = [];
  for (let from = 0; from < values.length; from += size) {
    const to = Math.min(values.length, from + size) - 1;
    groups.push({ from, to, lo: Math.min(values[from], values[to]), hi: Math.max(values[from], values[to]) });
  }
  return groups;
}

export type TrellisStat = 'median' | 'mean';

/** The statistic a pair's matrix is asked for: the median (§5.5), unless a lattice is over the limit. Merged squares can
 *  only be pooled exactly from means (a median of the whole is not a function of the medians of its parts), so such a pair
 *  asks for the mean. A lattice size not known asks for the median: the model then withholds a merged value rather than
 *  guess it. */
export function trellisStat(rowCount: number | null, colCount: number | null): TrellisStat {
  return (rowCount ?? 0) > TRELLIS_MAX_SIDE || (colCount ?? 0) > TRELLIS_MAX_SIDE ? 'mean' : 'median';
}

/** `untested`: no trial. `thin`: under `TRELLIS_MIN_N` trials (hatched, no tone, left out of the scale). `undefined`: enough
 *  trials, but no value (the metric is undefined over them, or a merged median that cannot be pooled). `ok`: drawn. */
export type TrellisState = 'untested' | 'thin' | 'undefined' | 'ok';

export interface TrellisCell {
  r: number;
  c: number;
  /** The trials in the square: the sum of the counts of the lattice squares it holds. */
  n: number;
  /** The statistic over them. A thin square keeps its value for the hover and never draws it. */
  value: number | null;
  tone: Tone;
  state: TrellisState;
  rows: AxisGroup;
  cols: AxisGroup;
}

export interface TrellisModel {
  rowsPath: string;
  colsPath: string;
  stat: TrellisStat;
  rows: AxisGroup[];
  cols: AxisGroup[];
  merged: boolean;
  cells: TrellisCell[][];
  /** The trials in all the squares (the matrix's own total, merged or not). */
  total: number;
  /** Squares with a trial, with n >= `TRELLIS_MIN_N`, and hatched for having fewer. */
  tested: number;
  included: number;
  thin: number;
  /** What a merged square shows, null when nothing was merged. */
  valueNote: string | null;
  summary: string;
}

const finite = (v: number | null | undefined): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** One square's trials and its value: a lattice square as the server sent it; a merged one summed, and valued by the exact
 *  pooled mean (each part weighted by its trials with a value) when `stat` is the mean, else not at all. */
function pool(matrix: LabMatrix, rows: AxisGroup, cols: AxisGroup, stat: TrellisStat): { n: number; value: number | null } {
  let n = 0;
  let weight = 0;
  let sum = 0;
  for (let r = rows.from; r <= rows.to; r++)
    for (let c = cols.from; c <= cols.to; c++) {
      const held = matrix.counts[r]?.[c] ?? 0;
      n += held;
      const value = finite(matrix.values[r]?.[c]);
      const stats = matrix.stats?.[r]?.[c] ?? null;
      if (held === 0 || value === null || stats === null) continue;
      const defined = stats.n - stats.histogram.nulls;
      if (defined > 0) {
        weight += defined;
        sum += value * defined;
      }
    }
  if (rows.from === rows.to && cols.from === cols.to) return { n, value: n > 0 ? finite(matrix.values[rows.from]?.[cols.from]) : null };
  return { n, value: stat === 'mean' && weight > 0 ? sum / weight : null };
}

/** An aggregate matrix answer as the trellis draws it: at most 16 × 16 squares. */
export function trellisModel(matrix: LabMatrix, stat: TrellisStat, metric: string): TrellisModel {
  const rows = groupAxis(matrix.rows);
  const cols = groupAxis(matrix.cols);
  const merged = rows.length < matrix.rows.length || cols.length < matrix.cols.length;
  const pooled = rows.map((rg) => cols.map((cg) => pool(matrix, rg, cg, stat)));
  const stateOf = (n: number, value: number | null): TrellisState => (n === 0 ? 'untested' : n < TRELLIS_MIN_N ? 'thin' : value === null ? 'undefined' : 'ok');
  // The scale is the drawn squares' alone: a thin square sets no colour and a losing one is red whatever its rank.
  const drawn = pooled.map((row) => row.map((p) => (stateOf(p.n, p.value) === 'ok' ? p.value : null)));
  const grid: LabMatrix = {
    rows_path: matrix.rows_path,
    cols_path: matrix.cols_path,
    rows: rows.map((g) => g.lo),
    cols: cols.map((g) => g.lo),
    values: drawn,
    counts: pooled.map((row) => row.map((p) => p.n)),
    basis: matrix.basis,
    legend: matrix.legend,
  };
  const tones = heatModel(grid, metric, 'aggregate', lowerIsBetter(metric)).squares;
  const cells = pooled.map((row, r) =>
    row.map((p, c): TrellisCell => {
      const state = stateOf(p.n, p.value);
      return { r, c, n: p.n, value: p.value, tone: state === 'ok' ? tones[r][c].tone : 'empty', state, rows: rows[r], cols: cols[c] };
    }),
  );
  const all = cells.flat();
  const tested = all.filter((cell) => cell.n > 0).length;
  const included = all.filter((cell) => cell.state === 'ok').length;
  const thin = all.filter((cell) => cell.state === 'thin').length;
  const size = merged ? `${rows.length} × ${cols.length} squares (merged from ${matrix.rows.length} × ${matrix.cols.length} values)` : `${rows.length} × ${cols.length} squares`;
  return {
    rowsPath: matrix.rows_path,
    colsPath: matrix.cols_path,
    stat,
    rows,
    cols,
    merged,
    cells,
    total: all.reduce((sum, cell) => sum + cell.n, 0),
    tested,
    included,
    thin,
    valueNote: !merged
      ? null
      : stat === 'mean'
        ? 'squares merged past 16 per axis show the mean of their parts, pooled exactly (a median of the whole cannot be built from its parts)'
        : 'squares merged past 16 per axis carry no value: a median cannot be built from the medians of its parts',
    summary: `${size} · ${tested} tested · ${included} with n ≥ ${TRELLIS_MIN_N} · ${thin} hatched`,
  };
}

// --- a square is a filter, and so is its drill-down ----------------------------------------------------------------------

/** The filter `base` plus a square: each of its two axes fixed to its value when the square holds one lattice value, else
 *  ranged over its group, cut to the filter's own range on that axis. This is the square's defining filter (§7.8): the
 *  `page` total under it is the square's n. Nothing in `base` is edited. Null when a group lies wholly outside the
 *  filter's range on its axis: the worker reorders a reversed range, so an empty intersection cannot be written as a
 *  filter, and such a square holds no trial anyway. */
export function cellFilter(base: LabFilter, axes: readonly [string, string], rows: readonly [number, number], cols: readonly [number, number]): LabFilter | null {
  const ranges = { ...base.ranges };
  const values = { ...base.values };
  const apply = ([path, [lo, hi]]: readonly [string, readonly [number, number]]): boolean => {
    if (lo === hi) {
      values[path] = lo;
      return true;
    }
    const held = ranges[path];
    const from = held === undefined ? lo : Math.max(lo, Math.min(held[0], held[1]));
    const to = held === undefined ? hi : Math.min(hi, Math.max(held[0], held[1]));
    if (from > to) return false;
    ranges[path] = [from, to];
    return true;
  };
  if (!apply([axes[0], rows]) || !apply([axes[1], cols])) return null;
  return { ...base, ranges, values, pass: [...base.pass], status: [...base.status] };
}

/** A picked square: which pair, its two axes and value ranges (equal ends: one value) and the n the matrix gave it. */
export interface TrellisPick {
  pair: number;
  axes: [string, string];
  rows: [number, number];
  cols: [number, number];
  n: number;
}

export function pickOf(pair: number, model: TrellisModel, cell: TrellisCell): TrellisPick {
  return { pair, axes: [model.rowsPath, model.colsPath], rows: [cell.rows.lo, cell.rows.hi], cols: [cell.cols.lo, cell.cols.hi], n: cell.n };
}

/** Whether `cell` of `model` is the picked square: the same pair of parameters and the same two value ranges. */
export function isPicked(pick: TrellisPick | null, model: TrellisModel, cell: TrellisCell): boolean {
  return (
    pick !== null &&
    pick.axes[0] === model.rowsPath &&
    pick.axes[1] === model.colsPath &&
    pick.rows[0] === cell.rows.lo &&
    pick.rows[1] === cell.rows.hi &&
    pick.cols[0] === cell.cols.lo &&
    pick.cols[1] === cell.cols.hi
  );
}

/** The pick with the n its square has now, when `model` is a newer answer for the same pair and that n moved (a running
 *  source); the same object when nothing changed, so the caller writes nothing. */
export function refreshedPick(pick: TrellisPick, model: TrellisModel): TrellisPick {
  const now = model.cells.flat().find((cell) => isPicked(pick, model, cell));
  return now === undefined || now.n === pick.n ? pick : { ...pick, n: now.n };
}

/** The drill-down's filter: the Lab's filter plus the picked square (null: it holds no trial, see `cellFilter`). */
export function pickFilter(base: LabFilter, pick: TrellisPick): LabFilter | null {
  return cellFilter(base, pick.axes, pick.rows, pick.cols);
}

/** Whether the table's total is the square's n. `total` is null while the table's total is being read. */
export function drillCheck(squareN: number, total: number | null): { match: boolean | null; text: string } {
  if (total === null) return { match: null, text: "reading the table's total…" };
  if (total === squareN) return { match: true, text: "the square's n and the table's total agree" };
  return { match: false, text: `the square says ${count(squareN)} and the table ${count(total)}: they were read at different moments, or one of them is wrong` };
}

// --- the pairs ------------------------------------------------------------------------------------------------------

export interface TrellisPairSpec {
  /** The parameters' places in the importance task's list. */
  index: [number, number];
  /** The paths as the worker names them: the matrix is asked for these. */
  axes: [string, string];
  label: string;
  /** The larger of the pair's two increments Δ: what ranked it. */
  priority: string;
  coverage: number;
}

export interface TrellisPairs {
  pairs: TrellisPairSpec[];
  /** The resolved pairs the answer holds. */
  resolved: number;
  line: string;
}

/** The first `limit` resolved pairs in the order the worker sent them (its priority: the larger Δ first). A pair it could
 *  not resolve (a thinly covered value grid) is never drawn, and a view with no stage delivered holds no pair: nothing is
 *  guessed. */
export function trellisPairs(view: LabInteractions | null, limit = TRELLIS_PAIRS): TrellisPairs {
  if (view === null || view.computed === null) return { pairs: [], resolved: 0, line: '' };
  const resolved = view.pairs.filter((p) => !p.unresolved);
  const pairs = resolved.slice(0, limit).map((p): TrellisPairSpec => {
    const deltas = [p.D_ij.value, p.D_ji.value].filter((v): v is number => v !== null);
    return {
      index: p.index,
      axes: p.pair,
      label: `${axisLabel(p.pair[0])} × ${axisLabel(p.pair[1])}`,
      priority: deltas.length === 0 ? `Δ ${DASH}` : `Δ ${pct(displayShare(Math.max(...deltas)), 1)}`,
      coverage: p.coverage,
    };
  });
  const rest = `${plural(view.total_pairs, 'pair')} in all${view.unresolved_pairs > 0 ? `, ${view.unresolved_pairs} unresolved and not shown` : ''}`;
  return { pairs, resolved: resolved.length, line: resolved.length === 0 ? `no resolved pair yet · ${rest}` : `top ${pairs.length} of ${resolved.length} resolved pairs by the larger Δ · ${rest}` };
}

// --- the scope breadcrumb ---------------------------------------------------------------------------------------------

/** The filters whose counts the worker is asked for; null where the count is the step before it. */
export interface CrumbPlan {
  filtered: LabFilter | null;
  brushed: LabFilter | null;
}

/** "Filtered" is the Lab's filter without its brushes (a side, fixed values, pass and status chips); "brushed" adds the
 *  brushed ranges. With no filter the first adds nothing to completed, and with no brush the second adds nothing to the
 *  first: no count is asked for either. */
export function breadcrumbPlan(filter: LabFilter): CrumbPlan {
  const unbrushed: LabFilter = { ...filter, ranges: {} };
  return { filtered: activeFilterCount(unbrushed) > 0 ? unbrushed : null, brushed: Object.keys(filter.ranges).length > 0 ? filter : null };
}

export interface CrumbStep {
  key: 'completed' | 'unique' | 'filtered' | 'brushed';
  label: string;
  unit: 'trials' | 'configurations';
  /** Null while the count is not known; never a zero standing for it. */
  n: number | null;
  note: string;
}

/** completed → valid unique → filtered → brushed (§5.5). `summary` is the source's unfiltered counts; `filtered` and
 *  `brushed` are the counts of the filters in `plan`, when they have been answered. */
export function breadcrumbSteps(summary: LabCounts | null, filtered: LabCounts | null, brushed: LabCounts | null, plan: CrumbPlan): CrumbStep[] {
  const completed = summary?.completed ?? null;
  const filteredN = plan.filtered === null ? completed : (filtered?.filtered ?? null);
  const brushedN = plan.brushed === null ? filteredN : (brushed?.filtered ?? null);
  const brushLines = plan.brushed === null ? [] : filterLines({ ranges: plan.brushed.ranges, values: {}, scope: 'combined', pass: [], status: [] });
  return [
    { key: 'completed', label: 'completed', unit: 'trials', n: completed, note: 'the trials the run has finished' },
    { key: 'unique', label: 'valid unique', unit: 'configurations', n: summary?.unique ?? null, note: 'distinct valid parameter sets among them' },
    { key: 'filtered', label: 'filtered', unit: 'trials', n: filteredN, note: plan.filtered === null ? 'no filter' : filterLines(plan.filtered).join(' · ') },
    { key: 'brushed', label: 'brushed', unit: 'trials', n: brushedN, note: plan.brushed === null ? 'no brush' : brushLines.join(' · ') },
  ];
}

// --- the robust neighbourhood map -----------------------------------------------------------------------------------------

export interface NeighbourhoodSquare {
  r: number;
  c: number;
  n: number;
  value: number | null;
  tone: Tone;
  /** No trial tested it: hatched, never filled. */
  untested: boolean;
  lowN: boolean;
  /** p75 − p25 of the square's trials; null where the server sent no quartiles. */
  iqr: number | null;
  /** The square's IQR is above the 75th percentile of the IQRs of the squares it can be compared with. */
  ring: boolean;
}

export interface NeighbourhoodModel {
  rowsPath: string;
  colsPath: string;
  rows: number[];
  cols: number[];
  squares: NeighbourhoodSquare[][];
  p75Iqr: number | null;
  rings: number;
  summary: string;
}

/** The `p` quantile of ascending values, linear between neighbours (numpy's default). */
function quantile(sorted: readonly number[], p: number): number {
  const at = (sorted.length - 1) * p;
  const lo = Math.floor(at);
  const hi = Math.ceil(at);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
}

/** An aggregate median matrix with its IQR rings (§5.5): a ring marks a tested square whose IQR is above the 75th
 *  percentile of the IQRs of the tested squares that are not flagged low n (a handful of trials say little about spread, so
 *  they neither set the line nor earn a ring). An untested square is hatched, with no value and no ring. */
export function neighbourhoodModel(matrix: LabMatrix, metric: string): NeighbourhoodModel {
  const heat = heatModel(matrix, metric, 'aggregate', lowerIsBetter(metric)).squares;
  const iqrOf = (r: number, c: number): number | null => {
    const stats = matrix.stats?.[r]?.[c] ?? null;
    return stats === null || stats.p25 === null || stats.p75 === null ? null : stats.p75 - stats.p25;
  };
  const compared = heat.flat().flatMap((s) => (s.n > 0 && !s.lowN && iqrOf(s.r, s.c) !== null ? [iqrOf(s.r, s.c) as number] : []));
  const p75Iqr = compared.length === 0 ? null : quantile([...compared].sort((a, b) => a - b), 0.75);
  const squares = heat.map((row) =>
    row.map((s): NeighbourhoodSquare => {
      const iqr = iqrOf(s.r, s.c);
      return { r: s.r, c: s.c, n: s.n, value: s.untested ? null : s.value, tone: s.tone, untested: s.untested, lowN: s.lowN, iqr, ring: p75Iqr !== null && s.n > 0 && !s.lowN && iqr !== null && iqr > p75Iqr };
    }),
  );
  const rings = squares.flat().filter((s) => s.ring).length;
  const tested = squares.flat().filter((s) => s.n > 0).length;
  return {
    rowsPath: matrix.rows_path,
    colsPath: matrix.cols_path,
    rows: matrix.rows,
    cols: matrix.cols,
    squares,
    p75Iqr,
    rings,
    summary:
      p75Iqr === null
        ? `${matrix.rows.length} × ${matrix.cols.length} squares · ${tested} tested · no IQR to compare`
        : `${matrix.rows.length} × ${matrix.cols.length} squares · ${tested} tested · ${rings} ringed: IQR above ${objectiveText(metric, p75Iqr)}, the 75th percentile of the squares' IQRs`,
  };
}

/** The square a selected candidate sits on, found by its values on the pair's two parameters (a grid job's rows name them
 *  without the side prefix); null when it lacks either or one is off the lattice. */
export function candidateSquare(matrix: Pick<LabMatrix, 'rows' | 'cols' | 'rows_path' | 'cols_path'>, params: Record<string, number | null>): { r: number; c: number } | null {
  const value = (path: string) => params[path] ?? params[path.replace(/^(long|short)_side\./, '')];
  const a = value(matrix.rows_path);
  const b = value(matrix.cols_path);
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  const r = matrix.rows.indexOf(a);
  const c = matrix.cols.indexOf(b);
  return r < 0 || c < 0 ? null : { r, c };
}

export interface CandidateState {
  name: 'A' | 'B';
  state: 'tested' | 'unknown';
  text: string;
}

/** The candidate's categories A (local) and B (sampled region) as the rail's card states them, each with the n and the
 *  coverage that decided it (§7.6). Taken from the card's own model, so the oriented values the worker sends are converted
 *  once, there, and nothing is recomputed. */
export function candidateStates(card: LabCandidateCard): CandidateState[] {
  return candidateCardModel(card).categories.flatMap((category) => {
    if (category.name !== 'A' && category.name !== 'B') return [];
    const decided = category.inputs.filter((input) => input.label === 'n' || input.label === 'coverage').map((input) => `${input.label} ${input.text}`);
    return [{ name: category.name, state: category.stateText, text: [category.name, category.stateText, category.verdict, ...decided].join(' · ') }];
  });
}

// --- the family tree --------------------------------------------------------------------------------------------------

export interface FamilyEntryNode {
  path: string;
  field: string;
  count: number;
  /** Values (or buckets) with at least one completed trial, of `of`; null where the summary does not hold the parameter. */
  tested: number | null;
  of: number | null;
  bucketed: boolean;
}

export interface FamilyNode {
  key: string;
  label: string;
  side: 'long' | 'short';
  /** The indicator id (or `levels`). */
  id: string;
  parameters: number;
  /** The values of the family's ranges. */
  values: number;
  /** Tested values of `of`, known only when the summary holds every parameter of the family. */
  tested: number | null;
  of: number | null;
  entries: FamilyEntryNode[];
  text: string;
}

const SIDE_ORDER: Record<string, number> = { long: 0, short: 1 };

/** The catalog's families by side (long first) and then indicator id, each with its counts. `parameters` is the summary's:
 *  without it, or without a parameter, the tested counts are unknown, never zero. */
export function familyTree(list: readonly Family[], parameters: readonly LabParameter[] | null): FamilyNode[] {
  const byPath = new Map((parameters ?? []).map((p) => [p.path, p]));
  const nodes = list.map((family): FamilyNode => {
    const entries = family.entries.map((entry): FamilyEntryNode => {
      const known = byPath.get(entry.path);
      return {
        path: entry.path,
        field: entry.field,
        count: entry.count,
        tested: known === undefined ? null : known.tested_per_value.filter((n) => n > 0).length,
        of: known === undefined ? null : known.tested_per_value.length,
        bucketed: known?.bucketed ?? false,
      };
    });
    const allKnown = entries.length > 0 && entries.every((e) => e.tested !== null);
    const tested = allKnown ? entries.reduce((sum, e) => sum + (e.tested ?? 0), 0) : null;
    const of = allKnown ? entries.reduce((sum, e) => sum + (e.of ?? 0), 0) : null;
    const values = entries.reduce((sum, e) => sum + e.count, 0);
    return {
      key: family.key,
      label: family.label,
      side: family.side,
      id: family.key.slice(family.side.length + 1),
      parameters: entries.length,
      values,
      tested,
      of,
      entries,
      text: `${plural(entries.length, 'parameter')} · ${tested === null ? `${count(values)} values` : `${count(tested)} of ${count(of ?? 0)} values tested`}`,
    };
  });
  return nodes.map((node, i) => ({ node, i })).sort((a, b) => SIDE_ORDER[a.node.side] - SIDE_ORDER[b.node.side] || a.i - b.i).map(({ node }) => node);
}

// --- what a square prints ----------------------------------------------------------------------------------------------

/** A count as a square fits it: 3, 999, 1.2k, 12k, 2.5M. */
export function countLabel(n: number): string {
  if (n < 1000) return String(n);
  const short = (v: number) => Number(v.toFixed(v < 10 ? 1 : 0));
  const thousands = short(n / 1000);
  return n < 1_000_000 && thousands < 1000 ? `${thousands}k` : `${short(n / 1_000_000)}M`; // 999,999 rounds up to 1M, never to 1000k
}

/** A range of lattice values as a square names it: the value, or `lo–hi` for a merged group. */
export function rangeText([lo, hi]: readonly [number, number]): string {
  return lo === hi ? valueText(lo) : `${valueText(lo)}–${valueText(hi)}`;
}

/** A square's hover title: where it is, and then what it holds, or why it shows nothing. A thin square's value is named in its
 *  hover and nowhere else: it is not drawn and sets no colour. */
export function cellTitle(model: TrellisModel, cell: TrellisCell, metric: string): string {
  const where = `${axisLabel(model.rowsPath)} = ${rangeText([cell.rows.lo, cell.rows.hi])} / ${axisLabel(model.colsPath)} = ${rangeText([cell.cols.lo, cell.cols.hi])}`;
  const value = cell.value === null ? null : `${model.stat} ${objectiveText(metric, cell.value)}`;
  switch (cell.state) {
    case 'untested':
      return `${where} · untested: no trial`;
    case 'thin':
      return `${where} · n ${count(cell.n)}: under ${TRELLIS_MIN_N}, hatched and left out of the scale${value === null ? '' : ` (${value}, not drawn)`}`;
    case 'undefined':
      return `${where} · n ${count(cell.n)} · no ${metric} value${model.merged ? ' (a merged median is not pooled)' : ''}`;
    default:
      return `${where} · ${value} · n ${count(cell.n)}`;
  }
}

/** A neighbourhood-map square's hover: where it is and what it holds, its spread, and why it is ringed. */
export function neighbourhoodTitle(model: NeighbourhoodModel, square: NeighbourhoodSquare, metric: string): string {
  const where = `${axisLabel(model.rowsPath)} = ${valueText(model.rows[square.r])} / ${axisLabel(model.colsPath)} = ${valueText(model.cols[square.c])}`;
  if (square.untested) return `${where} · untested: no trial`;
  const parts = [where, square.value === null ? `no ${metric} value` : `median ${objectiveText(metric, square.value)}`, `n ${count(square.n)}`];
  if (square.lowN) parts.push('low n');
  if (square.iqr !== null) parts.push(`IQR ${objectiveText(metric, square.iqr)}${square.ring ? ', ringed: above the 75th percentile of the IQRs' : ''}`);
  return parts.join(' · ');
}
