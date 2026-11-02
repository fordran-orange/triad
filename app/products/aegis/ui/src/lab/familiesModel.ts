// Parameter Families' decisions (Screen E, spec §5.5, §7.8), nothing React and nothing drawn: the scope breadcrumb's
// counts, the pairs of the trellis and the squares of each (a lattice of up to 16 values per axis, merged past that into
// groups whose trials all stay counted), the filter that defines a square and so its drill-down, the robust
// neighbourhood map's rings, the candidate's A and B states and the family tree's counts. The worker decides everything
// statistical; this only arranges what it sent, and it never filters, interpolates or fills a square: a square no trial
// tested stays untested, and a square with fewer trials (or fewer with a value) than the worker's `TRELLIS_MIN_N` is hatched and
// carries no tone. The trellis's three constants (§5.5: the floor, the squares per axis, the pairs drawn) arrive with the
// worker's answers (the `constants` of its `matrix` and `interactions` views) and are parameters here: this module holds none.
//
// Count-preserving drill-down (§7.8): a square's `n` equals the `page` total of the same filter plus the square, because
// the square IS that filter (`cellFilter`). The page is asked on the worker; nothing here filters rows.
import { DASH, pct } from '../format';
import type { LabCandidateCard, LabCounts, LabInteractions, LabMatrix, LabParameter, LabSnapshot, LabTrellisConstants } from '../results';
import { candidateCardModel } from './candidateModel';
import type { Family } from './catalog';
import { heatModel, valueText, type Tone } from './labHeatmapModel';
import { displayShare, filterLines } from './labQuery';
import { activeFilterCount, filterHash, type LabFilter, type TrellisPick } from './labStore';
import { lowerIsBetter, metricName, objectiveText } from './metricRules';
import { axisLabel } from './parallelBundles';

export type { TrellisPick };

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

/** The lattice `values` (ascending) as at most `limit` (the worker's TRELLIS_MAX_SIDE) contiguous groups of equal width, the
 *  last possibly narrower. A lattice that fits stays one square per value. */
export function groupAxis(values: readonly number[], limit: number): AxisGroup[] {
  const size = Math.max(1, Math.ceil(values.length / limit));
  const groups: AxisGroup[] = [];
  for (let from = 0; from < values.length; from += size) {
    const to = Math.min(values.length, from + size) - 1;
    groups.push({ from, to, lo: Math.min(values[from], values[to]), hi: Math.max(values[from], values[to]) });
  }
  return groups;
}

export type TrellisStat = 'median' | 'mean';

/** The statistic a pair's matrix is asked for: the median (§5.5), unless a lattice is over `maxSide` (the worker's
 *  TRELLIS_MAX_SIDE). Merged squares can only be pooled exactly from means (a median of the whole is not a function of the
 *  medians of its parts), so such a pair asks for the mean. A lattice size not known asks for the median: the model then
 *  withholds a merged value rather than guess it. */
export function trellisStat(rowCount: number | null, colCount: number | null, maxSide: number): TrellisStat {
  return (rowCount ?? 0) > maxSide || (colCount ?? 0) > maxSide ? 'mean' : 'median';
}

/** `untested`: no trial. `thin`: under the floor (`TRELLIS_MIN_N`) in trials, or in trials with a value (hatched, no tone, left
 *  out of the scale). `undefined`: enough trials, but no value at all (the metric is undefined over them, or a merged median
 *  that cannot be pooled). `ok`: drawn. */
export type TrellisState = 'untested' | 'thin' | 'undefined' | 'ok';

export interface TrellisCell {
  r: number;
  c: number;
  /** The trials in the square: the sum of the counts of the lattice squares it holds. */
  n: number;
  /** Of them, the trials with a value: what the statistic rests on, and what the floor is applied to beside `n`. */
  defined: number;
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
  /** The worker's floor and side this model was built with (TRELLIS_MIN_N, TRELLIS_MAX_SIDE). */
  minN: number;
  maxSide: number;
  /** The snapshot the matrix was read at, and the hash of the Lab's filter it was read under; a pick carries both, so the
   *  drill-down compares like with like. */
  snapshot: LabSnapshot | null;
  filterKey: string | null;
  rows: AxisGroup[];
  cols: AxisGroup[];
  merged: boolean;
  cells: TrellisCell[][];
  /** The trials in all the squares (the matrix's own total, merged or not). */
  total: number;
  /** Squares with a trial, those drawn, and those hatched for having too few trials or too few with a value. */
  tested: number;
  included: number;
  thin: number;
  /** What a merged square shows, null when nothing was merged. */
  valueNote: string | null;
  summary: string;
}

const finite = (v: number | null | undefined): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** One square's trials, the trials among them with a value, and its value: a lattice square as the server sent it; a merged one
 *  summed, and valued by the exact pooled mean (each part weighted by its trials with a value) when `stat` is the mean, else
 *  not at all. A part the server sent no statistics for counts its trials as having a value when it has one. */
function pool(matrix: LabMatrix, rows: AxisGroup, cols: AxisGroup, stat: TrellisStat): { n: number; defined: number; value: number | null } {
  let n = 0;
  let defined = 0;
  let weight = 0;
  let sum = 0;
  for (let r = rows.from; r <= rows.to; r++)
    for (let c = cols.from; c <= cols.to; c++) {
      const held = matrix.counts[r]?.[c] ?? 0;
      n += held;
      if (held === 0) continue;
      const value = finite(matrix.values[r]?.[c]);
      const stats = matrix.stats?.[r]?.[c] ?? null;
      const withValue = stats === null ? (value === null ? 0 : held) : stats.n - stats.histogram.nulls;
      defined += withValue;
      if (value !== null && withValue > 0) {
        weight += withValue;
        sum += value * withValue;
      }
    }
  if (rows.from === rows.to && cols.from === cols.to) return { n, defined, value: n > 0 ? finite(matrix.values[rows.from]?.[cols.from]) : null };
  return { n, defined, value: stat === 'mean' && weight > 0 ? sum / weight : null };
}

/** An aggregate matrix answer as the trellis draws it: at most `TRELLIS_MAX_SIDE` × `TRELLIS_MAX_SIDE` squares. `constants` is what
 *  the worker sent with the answer (the floor and the side) and `snapshot` the snapshot it was read at. */
export function trellisModel(
  matrix: LabMatrix,
  stat: TrellisStat,
  metric: string,
  constants: LabTrellisConstants,
  snapshot: LabSnapshot | null = null,
  filterKey: string | null = null,
): TrellisModel {
  const minN = constants.TRELLIS_MIN_N;
  const maxSide = constants.TRELLIS_MAX_SIDE;
  const rows = groupAxis(matrix.rows, maxSide);
  const cols = groupAxis(matrix.cols, maxSide);
  const merged = rows.length < matrix.rows.length || cols.length < matrix.cols.length;
  const pooled = rows.map((rg) => cols.map((cg) => pool(matrix, rg, cg, stat)));
  // Drawn needs the floor in trials and in trials with a value (a square of 40 trials with 5 profit factors says almost
  // nothing); a square with trials but no value at all is its own state.
  const stateOf = (p: { n: number; defined: number; value: number | null }): TrellisState =>
    p.n === 0 ? 'untested' : p.n < minN || (p.defined > 0 && p.defined < minN) ? 'thin' : p.value === null ? 'undefined' : 'ok';
  // The scale is the drawn squares' alone: a thin square sets no colour and a losing one is red whatever its rank.
  const drawn = pooled.map((row) => row.map((p) => (stateOf(p) === 'ok' ? p.value : null)));
  const grid: LabMatrix = {
    rows_path: matrix.rows_path,
    cols_path: matrix.cols_path,
    rows: rows.map((g) => g.lo),
    cols: cols.map((g) => g.lo),
    values: drawn,
    counts: pooled.map((row) => row.map((p) => p.n)),
    basis: matrix.basis,
    legend: matrix.legend,
    constants: matrix.constants,
  };
  const tones = heatModel(grid, metric, 'aggregate', lowerIsBetter(metric)).squares;
  const cells = pooled.map((row, r) =>
    row.map((p, c): TrellisCell => {
      const state = stateOf(p);
      return { r, c, n: p.n, defined: p.defined, value: p.value, tone: state === 'ok' ? tones[r][c].tone : 'empty', state, rows: rows[r], cols: cols[c] };
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
    minN,
    maxSide,
    snapshot,
    filterKey,
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
        ? `squares merged past ${maxSide} per axis show the mean of their parts, pooled exactly (a median of the whole cannot be built from its parts)`
        : `squares merged past ${maxSide} per axis carry no value: a median cannot be built from the medians of its parts`,
    summary: `${size} · ${tested} tested · ${included} with n ≥ ${minN} · ${thin} hatched`,
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
  // The store keeps an `opt:` source's brushes and fixed values under the job's own path (`indicators.ema.length`), the worker
  // names its axes with the side (`long_side.indicators.ema.length`), and the request prefixes the store's keys when it asks. A
  // square writes under the key the store already holds for the parameter, so the request carries one entry for it: written
  // under the other form it would collide with the held one when the keys are prefixed, and one of the two would vanish.
  const keyFor = (record: Record<string, unknown>, path: string): string => {
    const bare = path.replace(/^(long|short)_side\./, '');
    return Object.hasOwn(record, path) || !Object.hasOwn(record, bare) ? path : bare;
  };
  const apply = ([path, [lo, hi]]: readonly [string, readonly [number, number]]): boolean => {
    if (lo === hi) {
      values[keyFor(values, path)] = lo;
      return true;
    }
    const key = keyFor(ranges, path);
    const held = ranges[key];
    const from = held === undefined ? lo : Math.max(lo, Math.min(held[0], held[1]));
    const to = held === undefined ? hi : Math.min(hi, Math.max(held[0], held[1]));
    if (from > to) return false;
    ranges[key] = [from, to];
    return true;
  };
  if (!apply([axes[0], rows]) || !apply([axes[1], cols])) return null;
  return { ...base, ranges, values, pass: [...base.pass], status: [...base.status] };
}

/** The square as a pick (the Lab's store keeps it, see `TrellisPick`): its pair, axes and ranges, the n the matrix gave it and the
 *  snapshot and the filter that matrix was read under. */
export function pickOf(pair: number, model: TrellisModel, cell: TrellisCell): TrellisPick {
  return { pair, axes: [model.rowsPath, model.colsPath], rows: [cell.rows.lo, cell.rows.hi], cols: [cell.cols.lo, cell.cols.hi], n: cell.n, snapshot: model.snapshot, filterKey: model.filterKey };
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

/** The pick with the n its square has now and the snapshot and filter it was read under, when `model` is a newer answer for the
 *  same pair and any of them moved (a running source, a brush); the same object when nothing changed, so the caller writes
 *  nothing. */
export function refreshedPick(pick: TrellisPick, model: TrellisModel): TrellisPick {
  const now = model.cells.flat().find((cell) => isPicked(pick, model, cell));
  if (now === undefined || (now.n === pick.n && sameSnapshot(pick.snapshot, model.snapshot) && pick.filterKey === model.filterKey)) return pick;
  return { ...pick, n: now.n, snapshot: model.snapshot, filterKey: model.filterKey };
}

/** The drill-down's filter: the Lab's filter plus the picked square (null: it holds no trial, see `cellFilter`). */
export function pickFilter(base: LabFilter, pick: TrellisPick): LabFilter | null {
  return cellFilter(base, pick.axes, pick.rows, pick.cols);
}

/** Whether two answers were read at one snapshot of the source (both null: a source without snapshots). */
export function sameSnapshot(a: LabSnapshot | null, b: LabSnapshot | null): boolean {
  return a === null || b === null ? a === b : a.generation === b.generation && a.chunk_watermark === b.chunk_watermark;
}

/** A snapshot as the drill-down names it. */
export function snapshotText(snapshot: LabSnapshot | null): string {
  return snapshot === null ? 'none' : `gen ${snapshot.generation} · chunk ${snapshot.chunk_watermark}`;
}

/** Which total the drill-down is about: the source, the metric and the square's defining filter (null without a source, a pick or a
 *  filter for it). A total read for one scope is shown beside a pick of the same scope, whatever snapshot the pick has moved to. */
export function drillScope(source: string | null, metric: string, filter: LabFilter | null, pick: TrellisPick | null): string | null {
  if (source === null || filter === null || pick === null) return null;
  return [source, metric, filterHash(filter)].join('|');
}

/** The key of the drill-down's total: its scope and the snapshot the pick's n was read at. The snapshot is in it so that when a pair
 *  refreshes the pick (`refreshedPick`) the total is read again at once, and is compared with that same snapshot's n; with no timer
 *  of its own the total moves with the pair, and a finished source is read once more when its pair is settled. */
export function drillKey(source: string | null, metric: string, filter: LabFilter | null, pick: TrellisPick | null): string | null {
  const scope = drillScope(source, metric, filter, pick);
  if (scope === null || pick === null) return null;
  return `${scope}|${pick.snapshot === null ? 'none' : `${pick.snapshot.generation}.${pick.snapshot.chunk_watermark}`}`;
}

/** The drill-down's total as read: for which scope, its value, the snapshot it was read at and the hash of the Lab's filter it was
 *  asked under. */
export interface DrillAnswer {
  scope: string;
  total: number;
  snapshot: LabSnapshot | null;
  filterKey: string | null;
}

/** The last total read, while it is still about the square now picked: kept when only the snapshot moved (a new read is on its
 *  way, and the number does not blink out), dropped for another square, filter, metric or source. */
export function drillHeld(answer: DrillAnswer | null, scope: string | null): DrillAnswer | null {
  return answer !== null && scope !== null && answer.scope === scope ? answer : null;
}

/** Whether the table's total is the square's n. `total` is null while the table's total is being read. Two reads are compared only
 *  when they were made under one filter (a brush moved under the held pick, and the cheap total landed before the matrix) and at
 *  one snapshot (a running source moves between two reads): otherwise `match` is null, neither true nor false, and the text says
 *  which. Under one filter at one snapshot they are equal, or one of them is wrong. */
export function drillCheck(
  square: { n: number; snapshot: LabSnapshot | null; filterKey: string | null },
  table: { total: number | null; snapshot: LabSnapshot | null; filterKey: string | null },
): { match: boolean | null; text: string } {
  if (table.total === null) return { match: null, text: "reading the table's total…" };
  if (square.filterKey !== table.filterKey) return { match: null, text: 'the square was read under another filter: compared when they agree' };
  if (!sameSnapshot(square.snapshot, table.snapshot))
    return { match: null, text: `the square was read at snapshot ${snapshotText(square.snapshot)} and the table at ${snapshotText(table.snapshot)}: compared when they agree` };
  if (table.total === square.n) return { match: true, text: "the square's n and the table's total agree" };
  return { match: false, text: `the square says ${count(square.n)} and the table ${count(table.total)}: one of them is wrong` };
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

/** The first `limit` (the worker's TRELLIS_PAIRS) resolved pairs in the order the worker sent them (its priority: the larger Δ
 *  first). A pair it could not resolve (a thinly covered value grid) is never drawn, and a view with no stage delivered holds no
 *  pair: nothing is guessed. */
export function trellisPairs(view: LabInteractions | null, limit: number): TrellisPairs {
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
 *  hover and nowhere else: it is not drawn and sets no colour. When not every trial has a value, the title says how many do and
 *  what the floor needs of them. */
export function cellTitle(model: TrellisModel, cell: TrellisCell, metric: string): string {
  const where = `${axisLabel(model.rowsPath)} = ${rangeText([cell.rows.lo, cell.rows.hi])} / ${axisLabel(model.colsPath)} = ${rangeText([cell.cols.lo, cell.cols.hi])}`;
  const value = cell.value === null ? null : `${model.stat} ${objectiveText(metric, cell.value)}`;
  const held = cell.defined === cell.n ? `n ${count(cell.n)}` : `n ${count(cell.n)} · ${count(cell.defined)} with a value (needs ${count(model.minN)})`;
  switch (cell.state) {
    case 'untested':
      return `${where} · untested: no trial`;
    case 'thin':
      return `${where} · ${held}: ${cell.n < model.minN ? `under ${count(model.minN)}, ` : ''}hatched and left out of the scale${value === null ? '' : ` (${value}, not drawn)`}`;
    case 'undefined':
      return `${where} · ${held} · no ${metric} value${model.merged ? ' (a merged median is not pooled)' : ''}`;
    default:
      return `${where} · ${value} · ${held}`;
  }
}

/** The trellis legend: what a square is, a loss, a hatched square. The floor and the side are the worker's, printed as it sent them;
 *  before it has sent any the legend names no number. */
export function trellisLegend(metric: string, constants: LabTrellisConstants | null): string {
  const side = constants === null ? 'more values than the worker allows per axis' : `more than ${constants.TRELLIS_MAX_SIDE} values`;
  const floor = constants === null ? 'too few trials, or too few with a value' : `under ${constants.TRELLIS_MIN_N} trials or under ${constants.TRELLIS_MIN_N} with a value`;
  return `Each square is the ${metricName(metric)} of the trials with its two values (the median; the mean where an axis has ${side} and its squares are merged), a loss is red · hatched and without a colour = ${floor}, left out (n is shown) · hatched and empty = untested · the number on a square is its n · click a square for its trials.`;
}

const ARROW_STEPS: Record<string, readonly [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

/** Where an arrow key moves focus inside a grid of `rows` × `cols` squares: the neighbouring square, held at the edge. Null for a
 *  key that is not an arrow (or a grid with no square). */
export function arrowTarget(rows: number, cols: number, from: { r: number; c: number }, key: string): { r: number; c: number } | null {
  const step = ARROW_STEPS[key];
  if (step === undefined || rows <= 0 || cols <= 0) return null;
  return { r: Math.min(Math.max(from.r + step[0], 0), rows - 1), c: Math.min(Math.max(from.c + step[1], 0), cols - 1) };
}

/** The square that is the tab stop of a pair's grid: the picked square, else the first tested one, else the first (a grid with
 *  no tested square is still reached). The other squares are reached by the arrow keys. Null for a grid with no square. */
export function rovingCell(model: TrellisModel, pick: TrellisPick | null): { r: number; c: number } | null {
  const all = model.cells.flat();
  const found = all.find((cell) => isPicked(pick, model, cell)) ?? all.find((cell) => cell.n > 0) ?? all[0];
  return found === undefined ? null : { r: found.r, c: found.c };
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
