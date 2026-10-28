// The Lab's side of the Phase 2 query layer (`/aegis/api/lab`): pure request and response helpers, nothing React
// and nothing fetched. Every decision the panels make about a request body, a stale answer, a label or a column
// list lives here, so it runs under vitest in node.
import { SHARPE_MIN_TRADES } from '../contracts';
import { METRICS, OBJECTIVES, type LabQueryBody, type LabQueryView, type LabRow, type LabSnapshot, type LabSummary } from '../results';
import { filterHash, parseSource, type LabFilter, type LabScope, type LabState, type SquareSelection } from './labStore';
import type { TrialRow } from './useLabSource';

/** The trade Sharpe's metric name, and how it is labelled wherever it is shown (spec §7.12): per trade, not
 *  annualized, and never alone. */
export const SHARPE = 'sharpe_trade';
export const SHARPE_LABEL = 'trade Sharpe · per trade · not annualized';
export const SHARPE_TITLE = `${SHARPE_LABEL} · temporal consistency: Phase 3`;
export const NOT_RECORDED = 'data provenance not recorded';

type QueryState = Pick<LabState, 'filter' | 'axes' | 'mode' | 'stat' | 'metric'>;

/** The views that rank trials: their default order is the metric's column, so the trade Sharpe is never sent as
 *  their default metric (§7.12: the default sort of every candidate view stays the experiment's own objective). */
const RANKED: ReadonlySet<LabQueryView> = new Set<LabQueryView>(['page', 'top']);

/** The body of one query from the store: the filter, the view, the matrix's axes, metric, mode and stat, then
 *  `extra` (a page's window and sort, a matrix's slice). `filter_hash` is always the store filter's, so the answer
 *  can be matched to the filter it was asked under. */
export function queryBody(state: QueryState, view: LabQueryView, extra: Partial<LabQueryBody> = {}): LabQueryBody {
  const body: LabQueryBody = { filter: state.filter, view, filter_hash: null };
  if (view === 'matrix') {
    if (state.axes) {
      body.rows = state.axes[0];
      body.cols = state.axes[1];
    }
    body.metric = state.metric;
    body.mode = state.mode;
    body.stat = state.stat;
  } else if (!RANKED.has(view) || state.metric !== SHARPE) body.metric = state.metric;
  return { ...body, ...extra, filter_hash: filterHash(state.filter) };
}

/** The table's order before the operator picks a column: the metric in view, best first (ascending only for max
 *  drawdown) — the objective's column when that metric is the trade Sharpe. */
export function defaultSort(scope: string, metric: string, objective: string): { column: string; descending: boolean } {
  const ranked = metric === SHARPE ? objective : metric;
  return { column: `${scope}.${ranked}`, descending: ranked !== 'max_drawdown' };
}

/** The exact slice's fixed values (§7.1, spec:667): the selected trial's params when a trial is selected, else the
 *  pinned spec's values, minus the two axes, overlaid with the filter's fixed values on the other paths (a value
 *  fixed in the catalog is fixed in the slice too). Null only when there is neither a selection nor spec values
 *  (an `opt:` source with nothing selected). */
export function exactFixed(
  selected: Record<string, number> | null,
  specValues: Record<string, number> | null,
  axes: [string, string],
  values: Record<string, number>,
): Record<string, number> | null {
  if (selected === null && specValues === null) return null;
  const fixed: Record<string, number> = {};
  for (const source of [specValues ?? {}, selected ?? {}, values]) {
    for (const [path, value] of Object.entries(source)) if (path !== axes[0] && path !== axes[1]) fixed[path] = value;
  }
  return fixed;
}

const canonicalFixed = (fixed: Record<string, number> | null) =>
  fixed === null ? 'null' : JSON.stringify(Object.keys(fixed).sort().map((path) => [path, fixed[path]]));

/** The key of an experiment's matrix: the source, the axes, the mode, the stat, the metric, the filter's hash and,
 *  in exact mode, the slice; null without axes. A matrix whose key is not the current one is never drawn. */
export function expMatrixKey(source: string, state: QueryState, fixed: Record<string, number> | null): string | null {
  if (state.axes === null) return null;
  const slice = state.mode === 'exact' ? canonicalFixed(fixed) : '';
  return [source, state.axes[0], state.axes[1], state.mode, state.stat, state.metric, filterHash(state.filter), slice].join('|');
}

/** §7.8's stale-discard rule: an answer counts only when it echoes the hash of the filter now in the store. */
export function isCurrentHash(envelope: { filter_hash: string | null }, state: Pick<LabState, 'filter'>): boolean {
  return envelope.filter_hash !== null && envelope.filter_hash === filterHash(state.filter);
}

/** An aggregate square as the filter that defines it: its two axis values fixed, nothing else. */
export function squareFilter(square: SquareSelection): LabFilter {
  const values: Record<string, number> = { [square.axes[0]]: square.values[0], [square.axes[1]]: square.values[1] };
  return { ranges: {}, values, scope: 'combined', pass: [], status: [] };
}

/** `hh:mm:ss` of an ISO time (the hook stamps answers with `new Date().toISOString()`, so UTC). */
function clock(iso: string): string {
  return /T(\d\d:\d\d:\d\d)/.exec(iso)?.[1] ?? iso;
}

const count = (n: number) => n.toLocaleString('en-US');

/** A panel's provisional line: `PROVISIONAL · snapshot hh:mm:ss · gen g` (no generation for a source without
 *  snapshots); `takenAt` is when the answer arrived. */
export function snapshotLabel(snapshot: LabSnapshot | null, takenAt: string): string {
  const base = `PROVISIONAL · snapshot ${clock(takenAt)}`;
  return snapshot === null ? base : `${base} · gen ${snapshot.generation}`;
}

/** The context bar's run status while the source runs (spec:390): `PROVISIONAL · snapshot hh:mm:ss · n of N`, the
 *  completed trials of the scheduled ones. */
export function statusLabel(_snapshot: LabSnapshot | null, takenAt: string, completed: number, scheduled: number): string {
  return `PROVISIONAL · snapshot ${clock(takenAt)} · ${count(completed)} of ${count(scheduled)}`;
}

/** What a panel appends to its basis line: nothing for a settled answer, else ` · ` and its own snapshot. */
export function panelLabel(envelope: { provisional: boolean; snapshot: LabSnapshot | null; receivedAt: string } | null): string {
  if (envelope === null || !envelope.provisional) return '';
  return ` · ${snapshotLabel(envelope.snapshot, envelope.receivedAt)}`;
}

/** What `#lab-dataset` says about the pinned data: a legacy (layout 1) experiment never recorded it (spec:576);
 *  otherwise the archive's sha256 prefix and vintage (a source without a file hash, such as the synthetic
 *  benchmark data, by its vintage alone). Empty while the summary loads. */
export function datasetLabel(summary: LabSummary | null): string {
  if (summary === null) return '';
  if (summary.layout === 1) return NOT_RECORDED;
  const pinned = summary.data_pinned;
  const sha = typeof pinned?.sha256 === 'string' && pinned.sha256 !== '' ? pinned.sha256.slice(0, 12) : null;
  const vintage = typeof pinned?.vintage === 'string' && pinned.vintage !== '' ? `vintage ${pinned.vintage}` : null;
  if (sha === null && vintage === null) return NOT_RECORDED;
  return [sha, vintage].filter((part) => part !== null).join(' · ');
}

/** One line per active constraint of a filter, as the Linked chip lists them. */
export function filterLines(filter: LabFilter): string[] {
  const lines: string[] = [];
  for (const [path, [lo, hi]] of Object.entries(filter.ranges)) lines.push(`${path} ∈ [${lo}, ${hi}]`);
  for (const [path, value] of Object.entries(filter.values)) lines.push(`${path} = ${value}`);
  if (filter.scope !== 'combined') lines.push(`direction: ${filter.scope} only`);
  for (const pass of filter.pass) lines.push(`pass: ${pass}`);
  for (const status of filter.status) lines.push(`status: ${status}`);
  return lines;
}

/** The table's empty state (spec:441): `0 of N match: <the chip's lines>`. */
export function emptyTableText(completed: number, filter: LabFilter): string {
  return `0 of ${count(completed)} match: ${filterLines(filter).join(', ')}`;
}

/** The trade Sharpe's `low n` flag: fewer trades than SHARPE_MIN_TRADES (the generated contract, never a literal). */
export function lowN(tradeCount: number): boolean {
  return tradeCount < SHARPE_MIN_TRADES;
}

/** The value columns the table shows: the objective, then net P&L, max drawdown, trade count and exposure, and the
 *  trade Sharpe last and only for layout 2 — so it never appears without the four beside it (§7.12). */
export function tableValueColumns(scope: LabScope, objective: string, layout: 1 | 2): string[] {
  const metrics = [objective, 'net_pnl', 'max_drawdown', 'trade_count', 'exposure', ...(layout === 2 ? [SHARPE] : [])];
  return [...new Set(metrics)].map((metric) => `${scope}.${metric}`);
}

/** The X state every panel renders on a failed query: its message and a Retry that re-issues that one query. */
export function xState(message: string): { message: string; retryLabel: 'Retry' } {
  return { message, retryLabel: 'Retry' };
}

/** The rows by `column` (`trial_no`, a parameter or a `<scope>.<metric>`), the undefined values (null, absent or
 *  not finite) last whichever the direction, ties in the order they came. A copy; the input is left alone. */
export function undefinedLast<R extends Pick<LabRow, 'trial_no' | 'params' | 'values'>>(rows: readonly R[], column: string, descending: boolean): R[] {
  const valueOf = (row: R): number | null => {
    const v: unknown = column === 'trial_no' ? row.trial_no : column in row.params ? row.params[column] : row.values[column];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };
  const indexed = rows.map((row, i) => ({ row, i, v: valueOf(row) }));
  indexed.sort((a, b) => {
    if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
    if (a.v !== b.v) return descending ? b.v - a.v : a.v - b.v;
    return a.i - b.i;
  });
  return indexed.map((x) => x.row);
}

/** The metrics the context bar offers: an experiment's ten objectives, with the trade Sharpe for a layout-2 one;
 *  a grid job's four optimizer metrics. */
export function metricList(kind: 'exp' | 'opt', summary: LabSummary | null): string[] {
  if (kind === 'opt') return [...METRICS];
  return summary?.layout === 2 ? [...OBJECTIVES, SHARPE] : [...OBJECTIVES];
}

/** The table's page cache key: the source, the sort and the filter's hash, so a new filter drops the cached page
 *  and the remembered scroll position. */
export function pageKey(source: string, sortColumn: string, descending: boolean, filter: LabFilter): string {
  return `${source}|${sortColumn}|${descending}|${filterHash(filter)}`;
}

/** The dock's mode chip (spec §5.1): a two-parameter job's matrix is its exact grid; with more, each square is the
 *  best of the rest. */
export function dockChipText(parameterCount: number): string {
  return parameterCount === 2 ? 'Exact slice' : 'Aggregated: best of the rest';
}

/** The Trials KPI: the completed trials, and with a filter active the filtered count as its sub line. */
export function kpiTrialsText(completed: number, filtered: number, filtersActive: number): { primary: string; sub: string | null } {
  return { primary: count(completed), sub: filtersActive > 0 ? `${count(filtered)} filtered` : null };
}

// --- the optimizer source: the Lab keeps a job's own paths and names, the worker prefixes them ------------------

const SCOPED = /^(combined|long|short)\./;

/** A job path as the `/lab` source names it: `<side>_side.<path>` (a path already prefixed is kept). */
export function optPath(path: string, side: 'long' | 'short'): string {
  return path.startsWith(`${side}_side.`) ? path : `${side}_side.${path}`;
}

/** A body for an `opt:` source: the job's side as the scope (the worker refuses any other: `an optimizer source
 *  has one side`) and every parameter path prefixed with it; `filter_hash` stays the store filter's. */
export function optBody(body: LabQueryBody, side: 'long' | 'short'): LabQueryBody {
  const keyed = <T>(record: Record<string, T>) => Object.fromEntries(Object.entries(record).map(([path, v]) => [optPath(path, side), v]));
  const out: LabQueryBody = { ...body, filter: { ...body.filter, scope: side, ranges: keyed(body.filter.ranges), values: keyed(body.filter.values) } };
  if (body.rows !== undefined) out.rows = optPath(body.rows, side);
  if (body.cols !== undefined) out.cols = optPath(body.cols, side);
  if (body.fixed) out.fixed = keyed(body.fixed);
  if (body.paths) out.paths = body.paths.map((path) => optPath(path, side));
  if (body.axes) out.axes = body.axes.map((path) => optPath(path, side));
  if (body.sort !== undefined && body.sort !== 'trial_no' && !SCOPED.test(body.sort)) out.sort = optPath(body.sort, side);
  return out;
}

/** A job's trial from the `/lab` page as the rail card and the selection read it: its own trial id, the job's own
 *  paths and the side's metrics by name. Never `optRow(job, trial_no)`: above CELLS_SENT the status lists the
 *  job's best cells re-ordered, so its index is not a trial number. */
export function optRowFromLab(row: LabRow, side: 'long' | 'short'): TrialRow {
  const prefix = `${side}_side.`;
  const params = Object.fromEntries(Object.entries(row.params).map(([path, v]) => [path.startsWith(prefix) ? path.slice(prefix.length) : path, v]));
  const values = Object.fromEntries(Object.entries(row.values).map(([column, v]) => [column.startsWith(`${side}.`) ? column.slice(side.length + 1) : column, v]));
  return { id: row.trial_id, label: `#${row.trial_no}`, params, values, valid: null };
}

/** The `/lab` trial of a grid job with exactly `params` (the job's own paths, as the dock's selection names them):
 *  the same keys and the same numbers, whatever order the rows came in; null when none has them. The dock's list
 *  is the job's best cells by its objective, the `/lab` frame every evaluated cell in order, so the dock's index
 *  is never a trial number. */
export function matchTrialByParams(rows: readonly LabRow[], params: Record<string, number>, side: 'long' | 'short'): LabRow | null {
  const keys = Object.keys(params);
  const found = rows.find((row) => Object.keys(row.params).length === keys.length && keys.every((key) => row.params[optPath(key, side)] === params[key]));
  return found ?? null;
}

/** The page body that finds the dock's selected configuration among a job's `/lab` trials: the job's side, its
 *  parameters fixed (the job's paths prefixed), lowest trial number first. */
export function handOverBody(params: Record<string, number>, side: 'long' | 'short'): LabQueryBody {
  const filter: LabFilter = { ranges: {}, values: { ...params }, scope: 'combined', pass: [], status: [] };
  return optBody({ filter, view: 'page', filter_hash: null, sort: 'trial_no', limit: 10 }, side);
}

/** An experiment's trial from the `/lab` page as the table and the rail card read it. */
export function expRowFromLab(row: LabRow): TrialRow {
  return { id: row.trial_id, label: `trial ${row.trial_no}`, params: { ...row.params }, values: { ...row.values }, valid: row.valid };
}

/** The source a failed open names (`<source>: <why>`), so the X state's Retry can open it again; null when the
 *  message names none. */
export function failedSource(sourceError: string | null): string | null {
  if (sourceError === null) return null;
  const end = sourceError.indexOf(': ');
  const text = end < 0 ? sourceError : sourceError.slice(0, end);
  return parseSource(text) === null ? null : text;
}
