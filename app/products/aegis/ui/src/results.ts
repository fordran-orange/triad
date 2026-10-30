// Result shapes exactly as POST /aegis/api/backtest and GET /aegis/api/runs/{id} return them
// (products/aegis/backtest.py, results.py, api.py). Nothing here is computed in the browser.
import type { StrategySpec } from './contracts';
import type { LabFilter } from './lab/labStore';

export interface Metrics {
  net_pnl: number | null;
  net_return: number | null;
  cagr: number | null; // null when the range is shorter than a year
  max_drawdown: number | null;
  mar: number | null;
  win_rate: number | null;
  expectancy: number | null;
  profit_factor: number | null;
  trade_count: number;
  exposure: number;
  /** The Lab's trade Sharpe (per trade, not annualized): never one of the engine's metrics, so a run or a cell
   *  leaves it out; a Lab trial carries it per scope, null below two trades or with zero variance. */
  sharpe_trade?: number | null;
}

export interface Trade {
  side: 'LONG' | 'SHORT';
  signal_time: string;
  entry_time: string;
  entry_price: number;
  exit_signal_time: string;
  exit_time: string;
  exit_price: number;
  quantity: number;
  gross_pnl: number;
  net_pnl: number;
  return: number;
  temporal_tags: string[];
  window_edge_exit?: boolean; // walk-forward only: closed by the engine at a window's last bar
  carried_from_window?: number | null; // walk-forward only: entered in that earlier window
  exit_reason?: 'stop_loss' | 'take_profit'; // Mission 13: closed by a level, not a rule
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
}

export interface Breakdown {
  trades: number;
  net_pnl: number;
  win_rate: number | null;
  expectancy: number | null;
}

export interface SideResult {
  enabled: boolean;
  series: Record<string, Array<number | null>>;
  trades: Trade[];
  equity: EquityPoint[];
  metrics: Metrics;
}

export interface CombinedResult {
  trades: Trade[];
  equity: EquityPoint[];
  metrics: Metrics;
}

export type ResultSide = 'long' | 'short' | 'combined';

export interface TradeMarker {
  time: number; // epoch ms
  price: number;
  side: 'LONG' | 'SHORT';
  kind: 'entry' | 'exit';
}

/** Pinned raw-archive provenance (PinnedSource) or the supplied-bars identity. */
export interface Provenance {
  source: 'raw_archive' | 'supplied_bars';
  symbol?: string;
  vintage?: string;
  relative_path?: string;
  sha256?: string;
  data_hash?: string;
  timeframe?: string;
  start?: string;
  end?: string;
  bar_count?: number;
  research_eligible?: false;
  [key: string]: unknown;
}

export interface ResultPayload {
  strategy: StrategySpec;
  data: Provenance;
  long: SideResult;
  short: SideResult;
  combined: CombinedResult;
  temporal: Record<ResultSide, Record<string, Breakdown>>;
  markers: TradeMarker[];
}

export type RunState = 'ok' | 'source_unavailable';

export interface RunEnvelope {
  run_id: string;
  saved?: boolean; // Mission 10: false while a "kept"-mode run is held unsaved (gone on restart)
  created_at: string;
  elapsed_ms: number;
  result_hash: string;
  data: Provenance;
  strategy: StrategySpec;
  result: ResultPayload;
  series?: Record<'long' | 'short', Record<string, Array<number | null>>>; // runs saved before Mission 10 only
  stored?: StoredFormat; // Mission 10: absent on runs saved before slim runs
  markers: TradeMarker[];
  settings?: { initial_capital: number; allocation_fraction: number }; // absent on runs persisted before the fix pass
  state: RunState;
  state_detail?: string;
  strategy_id?: string | null;
  strategy_hash?: string; // absent on runs persisted before Mission 5
  engine?: string;
}

/** How a run was stored (Mission 10): format 2 drops per-bar series and resamples each side's
 *  per-bar equity; `equity_points` keeps each side's true per-bar count. */
export interface StoredFormat {
  format: number;
  equity_points: Record<'long' | 'short', number>;
}

/** What GET /aegis/api/runs lists: the envelope without result, series or markers. */
export interface RunSummary {
  run_id: string;
  kept?: false; // Mission 10: present only on a run held unsaved
  created_at?: string;
  elapsed_ms?: number;
  result_hash: string;
  data?: Provenance;
  strategy?: StrategySpec;
}

// --- optimizer (OptimizerRunner.status snapshots and the optimize routes) ---------------------

export type JobState = 'queued' | 'running' | 'done' | 'cancelled' | 'failed' | 'lost';
export const TERMINAL_JOB_STATES: ReadonlySet<JobState> = new Set<JobState>(['done', 'cancelled', 'failed', 'lost']);
export type JobSide = 'long' | 'short';
export type Metric = 'net_pnl' | 'mar' | 'max_drawdown' | 'trade_count';
export const METRICS: Metric[] = ['net_pnl', 'mar', 'max_drawdown', 'trade_count'];
export const METRIC_LABELS: Record<Metric, string> = { net_pnl: 'Net P&L', mar: 'MAR', max_drawdown: 'Max drawdown', trade_count: 'Trades' };

/** Every metric an experiment may rank by (Mission 6 spec §5.1); the optimizer keeps its four. */
export type Objective = 'net_pnl' | 'net_return' | 'cagr' | 'max_drawdown' | 'mar' | 'win_rate' | 'expectancy' | 'profit_factor' | 'trade_count' | 'exposure';
export const OBJECTIVES: Objective[] = ['net_pnl', 'net_return', 'cagr', 'max_drawdown', 'mar', 'win_rate', 'expectancy', 'profit_factor', 'trade_count', 'exposure'];
export const OBJECTIVE_LABELS: Record<Objective, string> = {
  net_pnl: 'Net P&L',
  net_return: 'Net return',
  cagr: 'CAGR',
  max_drawdown: 'Max drawdown',
  mar: 'MAR',
  win_rate: 'Win rate',
  expectancy: 'Expectancy',
  profit_factor: 'Profit factor',
  trade_count: 'Trades',
  exposure: 'Exposure',
};
export const PERCENT_OBJECTIVES = new Set<Objective>(['net_return', 'cagr', 'max_drawdown', 'win_rate', 'exposure']);

export interface Cell {
  params: Record<string, number>;
  fast: number | null;
  slow: number | null;
  metrics: Metrics;
}

/** rows = fast values ascending, columns = slow values ascending; null = skipped or pending */
export type Matrix = Array<Array<number | null>>;

export interface JobStatus {
  job_id: string;
  status: JobState;
  side: JobSide;
  objective: Metric;
  created_at: string;
  progress: { done: number; total: number };
  total_cells: number;
  skipped_cells: number;
  skipped: Record<string, number>[];
  elapsed_ms: number;
  estimated_seconds: number;
  cells: Cell[];
  matrices: Record<Metric, Partial<Record<JobSide, Matrix>>>;
  fast_values: number[];
  slow_values: number[];
  fast_path: string;
  slow_path: string;
  bars: number;
  cache_hits: number;
  data: Provenance;
  strategy: StrategySpec;
  settings: { initial_capital: number; allocation_fraction: number };
  error: string | null;
  cells_done?: number; // every evaluated cell (the limits change); `cells` may hold only the best
  cells_shown?: number;
  pooled?: boolean; // more than 400 cells: run in chunks on the process pool
  matrix_squares?: number; // the stored pair's squares; above the page's budget `matrices` is empty
}

/** GET /optimize/{id}/matrix: any two of a job's parameters; each square is the best of the rest. */
export interface AxisMatrix {
  rows_path: string;
  cols_path: string;
  rows: number[];
  cols: number[];
  counts: number[][];
  metrics: Partial<Record<Metric, { values: Matrix; cells: Array<Array<number | null>> }>>; // one metric when asked for one
  cells: Cell[];
}

export interface JobSummary {
  job_id: string;
  status: JobState;
  side?: JobSide;
  objective?: Metric;
  created_at?: string;
  elapsed_ms?: number;
  progress?: { done: number; total: number };
  total_cells?: number;
  skipped_cells?: number;
  data?: Provenance;
  strategy?: StrategySpec;
}

export interface OptimizePlan {
  total_cells: number;
  skipped_cells: number;
  skip_reason: string | null; // why cells were skipped: 'fast ≥ slow', 'invalid parameter combinations'
  estimated_seconds: number;
  ms_per_bar: number; // the runner's last observed cell cost on this host
  bars: number;
  pooled?: boolean; // more than 400 cells: priced and run on the process pool
  workers?: number;
}

export interface OptimizeStarted {
  job_id: string;
  total_cells: number;
  skipped_cells: number;
  estimated_seconds: number;
}

// --- walk-forward (WalkForwardJob snapshots and the walkforward routes) ----------------------

export interface WindowRecord {
  index: number;
  status: 'pending' | 'done' | 'no_valid_cell';
  is_start: string;
  is_end: string;
  oos_start: string;
  oos_end: string;
  is_bars: number;
  oos_bars: number;
  cells_evaluated: number;
  best: { params: Record<string, number>; metrics: Partial<Metrics> } | null;
  oos: { trades: Trade[]; equity: EquityPoint[]; metrics: Metrics } | null;
  efficiency: number | null;
  carried_in: boolean; // a position entered in an earlier window was held into this one
  open_at_end: boolean; // this window ended holding a position, carried into the next
  ending_cash: number | null;
  ending_equity: number | null;
  inherited_from: number | null; // no valid in-sample cell: managed the carry with that window's choice
}

// --- experiments (Mission 6 spec §5–8) ----------------------------------------------------

export interface ExperimentLever {
  kind: 'coarsen' | 'narrow' | 'freeze' | 'shorten' | 'coarser_timeframe' | 'raise_budget';
  parameter: string | null;
  label: string;
  valid_cells: number;
  estimate_seconds: number;
  fits: boolean;
  surface?: { parameters: Array<{ path: string; start: number; stop: number; step: number }> } | null;
  budget?: { runs?: number | null; seconds?: number | null } | null;
  data_hint?: string | null;
}

export interface ExperimentProgress {
  cells_done: number;
  cells_planned: number;
  chunks_done: number;
  chunks_total: number;
}

export type ExperimentStatus = 'queued' | 'running' | 'paused' | 'done' | 'cancelled' | 'failed';

export interface ExperimentDecision {
  verdict: 'accepted' | 'rejected' | 'deferred';
  notes: string;
  decided_at: string;
}

/** GET /experiments: one row per experiment (the document's summary). */
export interface ExperimentSummary {
  id: string;
  name: string;
  strategy_id: string;
  strategy_hash: string;
  objective: Objective;
  status: ExperimentStatus;
  progress: ExperimentProgress;
  created_at: string;
  updated_at: string;
  parent: string | null;
  decision: ExperimentDecision | null;
  latest_report: number | null;
  job_id: string | null;
  engine: string;
  budget: { runs?: number | null; seconds?: number | null };
  tolerance: number;
  ms_per_cell_bar: number | null;
  error: string | null;
  mode: 'exhaustive' | 'sampled' | null;
  planned_runs: number | null;
  valid_cells: number | null;
  sampled_fraction: number | null;
  estimate_seconds: number | null;
  parameters: number;
  paths: string[];
}

export interface NamedCell {
  cell: number;
  params: Record<string, number>;
  objective: number;
}

export interface Recommendation {
  plateau: number;
  centre: NamedCell & { metrics: Record<string, number | null> };
  supported_peak: NamedCell | null;
  fragile_peaks: NamedCell[];
  statement: string;
}

export interface Plateau {
  id: number;
  cells: number[];
  size: number;
  median: number;
  iqr: number;
  cliff: number | null;
  counts: boolean;
  peaks: number[];
  centre: NamedCell & { metrics: Record<string, number | null> };
}

export interface PeakEntry extends NamedCell {
  fragile: boolean;
  plateau: number | null;
}

export interface MainEffectPoint {
  value: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
  count: number;
}

export interface Interaction {
  paths: [string, string];
  values_a: number[];
  values_b: number[];
  matrix: Array<Array<number | null>>;
  strength: number;
}

export interface ClusterGroup {
  size: number;
  medians: Record<string, number>;
  parameter_ranges: Record<string, [number, number]>;
  exemplar: number;
  cells: number[];
}

export interface ExperimentReport {
  report_id: number;
  generated_at: string;
  objective: Objective;
  tolerance: number;
  tau: number;
  mode: 'exhaustive' | 'sampled';
  sampled_fraction: number;
  valid_cells: number;
  skipped: number;
  null_objective_cells: number;
  neighbour_rule: string;
  recommendation: Recommendation | null;
  plateaus: Plateau[];
  peaks: PeakEntry[];
  main_effects: Record<string, MainEffectPoint[]>;
  interactions: Interaction[] | null;
  sensitivity: { shares: Record<string, number>; remainder: number | null };
  clusters: { k: number; silhouette: number; groups: ClusterGroup[]; metrics: string[] } | { refused: string };
  uncertainty: { iqr: number; cells: number; sampled_fraction: number; statement: string } | null;
  cells_named: number[];
  statement: string;
}

export interface CellsPage {
  total: number;
  rows: Array<Record<string, unknown> & { cell: number; valid: boolean }>;
  columns: string[];
}

// --- the Optimization Lab's query layer (Phase 2: GET /lab/{src}/summary, POST /lab/{src}/query,
// GET /lab/{src}/trials/{trial}, GET /lab/build; products/aegis/lab/query.py and sources.py) -------------

/** A query's view (`QueryRequest.view`); distinct from the Lab's sub-nav `LabView`. The last seven are Phase 3's:
 *  `importance`, `interactions` and `triples` are answered from the importance task (`LabTaskView`); `neighbourhood`,
 *  `robustness`, `pareto` and `convergence` from the frame. */
export type LabQueryView =
  | 'counts'
  | 'matrix'
  | 'page'
  | 'top'
  | 'marginals'
  | 'parallel'
  | 'square_trials'
  | 'importance'
  | 'interactions'
  | 'triples'
  | 'neighbourhood'
  | 'robustness'
  | 'pareto'
  | 'convergence';

/** The §6.4 counts of one filter (`scope_counts`, its 22 keys in order). `space` is a string above 2^63. */
export interface LabCounts {
  space: number | string;
  valid: number;
  budget_total: number;
  reserved: number;
  scheduled: number;
  evaluations: number;
  remaining: number;
  reused: number;
  attempted: number;
  evaluations_done: number;
  completed: number;
  invalid: number;
  failed: number;
  pending: number;
  unique: number;
  duplicates: number;
  filtered: number;
  shown: number;
  undefined: number;
  basis: string;
  block: 0;
  filters_active: number;
}

/** The file set a response was read at: a layout-2 manifest generation and its chunk watermark (generation 0 for
 *  a legacy folder's synthesized snapshot). An optimizer source has none. */
export interface LabSnapshot {
  generation: number;
  chunk_watermark: number;
}

/** One searched parameter of a source, with the completed trials at each value (or bucket). */
export interface LabParameter {
  path: string;
  side: string;
  family: string;
  type: 'int' | 'float';
  start: number;
  stop: number;
  step: number;
  n_values: number;
  values: number[] | null;
  tested_per_value: number[];
  bucketed: boolean;
}

/** GET /lab/{src}/summary. `layout` is null for an optimizer source (not a cells folder); `versions` is null for a
 *  legacy experiment and an optimizer; `spec_values` (the §7.1 default slice) is null for an optimizer. */
export interface LabSummary {
  source: string;
  kind: 'exp' | 'opt';
  layout: 1 | 2 | null;
  status: string;
  counts: LabCounts;
  parameters: LabParameter[];
  headline: { objective: string; best: { trial_id: string; value: number | null; params: Record<string, number> } | null; completed: number; undefined: number };
  snapshots: { latest: LabSnapshot | null };
  provisional: boolean;
  versions: Record<string, unknown> | null;
  data_pinned: Provenance | null;
  engine: string | null;
  spec_values: Record<string, number> | null;
  filter_hash: null;
}

/** Every query answer: the echoed `filter_hash`, the filter's counts, the snapshot read and the explicit empty
 *  state (`no trials match: k filters active`, or the view's own), beside the view's payload. A `counts` query
 *  carries no payload: `LabEnvelope<{}>`. */
export type LabEnvelope<T> = {
  view: LabQueryView;
  filter_hash: string | null;
  scope: LabCounts;
  snapshot: LabSnapshot | null;
  provisional: boolean;
  empty: string | null;
} & T;

/** POST /lab/{src}/query, field for field (`QueryRequest`, extra fields forbidden): only `filter` and `view` are
 *  required; a view checks its own arguments. */
export interface LabQueryBody {
  filter: LabFilter;
  view: LabQueryView;
  filter_hash: string | null;
  rows?: string;
  cols?: string;
  metric?: string;
  mode?: 'exact' | 'aggregate';
  stat?: 'best' | 'median' | 'mean' | 'worst';
  fixed?: Record<string, number> | null;
  sort?: string;
  descending?: boolean;
  offset?: number;
  limit?: number;
  /** `top`'s row count (the worker defaults it to 200). Sent, it is also the exact parallel sample's line bound and
   *  the robustness rankings' list length; unsent, those read PARALLEL_MAX_LINES and RANKING_K. */
  k?: number;
  paths?: string[];
  /** The parallel view's axes (every parameter without them). A grid job's `optBody` prefixes them with its side. */
  axes?: string[];
  row_value?: number;
  col_value?: number;
  /** The importance task's resample seed, in its key and every answer (the worker reads 1 without it), and the
   *  exact parallel sample's. */
  seed?: number;
  /** The operator's own "Run again" of a cancelled or failed task. A poll never sends it: without it a stopped key
   *  answers its stopped task, and `rerun: true` while a task still reads `running` would queue a new one. */
  rerun?: boolean;
  /** A trial id `<src>#<n>`: the `neighbourhood` view's trial, and the `robustness` view's candidate (without one,
   *  that view answers the rankings). */
  trial?: string;
  /** The `pareto` view's two or three metric names, bare: `optBody` never prefixes them (the worker answers 422 on
   *  a prefixed one), and each is read in the filter's scope. */
  objectives?: string[];
  /** The `parallel` view's mode: its bundles (the worker's default), or `sample`'s exact lines. */
  parallel_mode?: 'bundles' | 'sample';
}

/** A trial as the page, top and square-trials views send it: `values` holds the loaded `<scope>.<metric>` columns,
 *  an undefined metric as null. An optimizer row's `cell` is its `trial_no`. */
export interface LabRow {
  trial_id: string;
  trial_no: number;
  cell: number | null;
  params: Record<string, number>;
  values: Record<string, number | null>;
  valid: boolean | null;
  status: string | null;
  pass: string | null;
  design: string | null;
}

/** An aggregate square's distribution (§7.2); null for a square no trial tested. */
export interface LabSquareStats {
  n: number;
  p25: number | null;
  p75: number | null;
  min: number | null;
  max: number | null;
  low_n: boolean;
  confounded: string[];
  histogram: { edges: number[]; counts: number[]; nulls: number };
}

/** The matrix view: exact squares carry their lowest trial's id and the duplicates beside it; aggregate squares
 *  carry their statistics instead. An untested square's value is null and its count 0. */
export interface LabMatrix {
  rows_path: string;
  cols_path: string;
  rows: number[];
  cols: number[];
  values: Array<Array<number | null>>;
  counts: number[][];
  basis: string;
  legend: string;
  trial_ids?: Array<Array<string | null>>;
  duplicates?: number[][];
  stats?: Array<Array<LabSquareStats | null>>;
}

/** The page and square-trials views: one offset window of the filtered trials, `total` of them in all. */
export interface LabPage {
  total: number;
  rows: LabRow[];
  columns: string[];
}

/** The best k filtered trials with a defined value; `metric` is the `<scope>.<metric>` column ranked. */
export interface LabTop {
  metric: string;
  rows: LabRow[];
}

export interface LabMarginal {
  values?: number[];
  buckets?: Array<[number, number]>;
  n: number[];
  best: Array<number | null>;
  median: Array<number | null>;
}

export interface LabMarginals {
  metric: string;
  marginals: Record<string, LabMarginal>;
}

/** One line of the exact parallel sample: a trial's values on the axes (null where undefined) and its metric. */
export interface LabParallelLine {
  trial_id: string;
  values: Array<number | null>;
  metric: number;
}

/** Parallel-coordinate bundles: each axis's q + 1 quantile edges and q centres, the largest bundles first. With
 *  `parallel_mode = "sample"` the bundle fields are sent empty (`bins`, `bundles` and both totals 0) and the sample's
 *  own are present: `lines` (at most `constants.PARALLEL_MAX_LINES`, stratified by decile of `metric`, the
 *  `<scope>.<metric>` column), `sampled_from` the trials it drew from, its `seed`, and `excluded`, the trials with an
 *  undefined metric (never drawn). Its `basis` reads `Sampled n of N (stratified by decile of <metric>)`. */
export interface LabParallel {
  axes: string[];
  bins: Array<{ edges: number[]; centres: number[] }>;
  bundles: Array<{ bins: number[]; count: number; median: number | null }>;
  total_bundles: number;
  shown_bundles: number;
  basis: string;
  lines?: LabParallelLine[];
  sampled_from?: number;
  metric?: string;
  strata?: number;
  seed?: number;
  excluded?: number;
  constants?: { PARALLEL_MAX_LINES: number; PARALLEL_STRATA: number };
}

// --- Phase 3's views (products/aegis/lab/importance.py, rule.py, neighbours.py, robustness.py, pareto.py,
// convergence.py; the envelope is `LabEnvelope<...>`) ------------------------------------------------------------

/** A number the worker could not compute is sent as null (NaN and infinity never reach the client). */
export type LabNumber = number | null;

/** A Lab task's state. During a pending cancel the status still reads `running` until the task reaches a checkpoint,
 *  so only `cancelled` and `failed` are states a "Run again" may follow (`canRerun` in labTask.ts). */
export type LabTaskState = 'queued' | 'running' | 'done' | 'cancelled' | 'failed';

/** `tasks.TaskStatus` as a view sends it (`status_json`: neither its key nor its result). `stage` counts the stages
 *  delivered, 0 to `stages`; `progress` is `stage / stages`; `label` is the task's method (`importance`);
 *  `sharing_cpu` is true while an experiment job runs beside a queued or running task. The times are ISO UTC. */
export interface LabTask {
  id: string;
  label: string;
  state: LabTaskState;
  stage: number;
  stages: number;
  progress: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  sharing_cpu: boolean;
}

/** What the three importance-task views (`importance`, `interactions`, `triples`) send beside their own payload.
 *  `task` is the computing task (the one running, never the waiter behind it), or null when none was requested, and
 *  then `reason` says why (a grid job still running: `importance is available when the optimization finishes`).
 *  `snapshot_label` is `snapshot gX cN · current gY cM` when the answer is of a snapshot the source has moved on
 *  from, else null: print it, and never compare two snapshot objects in the UI (after a bare compaction a result's
 *  snapshot can be an older generation than the envelope's and still be the same evidence). The answer is the newest
 *  finished result, else the computing task's delivered stage (a cancelled or failed task's included), else absent. The
 *  filter is ignored (§7.3): the scope is the unfiltered one of the request's side, and `scope.basis` is the basis
 *  line. */
export interface LabTaskView {
  task: LabTask | null;
  reason: string | null;
  snapshot_label: string | null;
}

/** The point estimates, the interval bounds or the floors of the fine grid (`shares.fine_parts`): `S[i]` a main's
 *  share, `J[i][j]` the pair's (the mains on its diagonal), `D[i][j]` the increment Δ_{i|j} (a parameter's, beyond j).
 *  Shares are adjusted and unclamped: one can be slightly below 0, so print it through `displayShare`, never stored
 *  clamped. */
export interface LabTerms {
  S: LabNumber[];
  J: LabNumber[][];
  D: LabNumber[][];
}

/** The fine grid (stage 1): the point estimates, `I` the interaction (display only, no interval), the 90 % bounds
 *  (`lo`, `hi`), the family-wise detection floors and the shares' 95th-percentile ticks, and each family's critical
 *  value `t`. A floor is null where its member has none (the diagonal of `D`). */
export interface LabFine extends LabTerms {
  I: LabNumber[][];
  lo: LabTerms;
  hi: LabTerms;
  floor: { S: LabNumber[]; D: LabNumber[][] };
  tick: { S: LabNumber[]; D: LabNumber[][] };
  t: Record<string, LabNumber>;
}

/** One screening block's fine mains: the shares, their bounds and their family floor, per parameter. */
export interface LabBlockMains {
  S: LabNumber[];
  lo: LabNumber[];
  hi: LabNumber[];
  floor: LabNumber[];
}

/** The coarse decomposition's point estimates (stage 2) without the triple-level arrays, which the `triples` view
 *  sends for the top triples. `lo` / `hi` are R's interval, null until stage 3. */
export interface LabCoarse extends LabTerms {
  R: LabNumber;
  lo: LabNumber;
  hi: LabNumber;
}

/** The coarse bootstrap's bounds (stage 3): R's always, the rest only for the `candidates` (indices into `paths`);
 *  every other entry is null. */
export interface LabCoarseBounds {
  candidates: number[];
  R_lo: LabNumber;
  R_hi: LabNumber;
  S_lo: LabNumber[];
  S_hi: LabNumber[];
  D_lo: LabNumber[][];
  D_hi: LabNumber[][];
}

/** The coarse null (stage 3): each family's critical value; its floors ride on the `triples` view. */
export interface LabCoarseNull {
  t: Record<string, LabNumber>;
}

export type LabCoverageLabel = 'Measured' | 'Insufficient coverage';

/** Decision 21's recommended statuses, the first rule that holds. Phase 3 recommends; nothing persists a status. */
export type LabParameterStatusName =
  | 'Insufficient coverage · unresolved'
  | 'Deprioritized · proposable'
  | 'Investigate · period-dependent'
  | 'Active · detected'
  | 'Investigate · interaction not ruled out'
  | 'Investigate · three-way effect not ruled out'
  | 'Active · not detected';

/** One parameter's recommended status with its `reason`, its `flags`, its coverage `label`, `proposable` (the status
 *  `Deprioritized · proposable` alone) and, for every parameter that is not proposable, `failing`: the availability
 *  reason, else the veto, else `not proposable: condition <n> (<what>)`. The `Measured` parameters come in path order,
 *  then the unresolved ones. */
export interface LabParameterStatus {
  path: string;
  status: LabParameterStatusName;
  reason: string;
  flags: string[];
  label: LabCoverageLabel;
  proposable: boolean;
  failing: string | null;
}

/** Whether the rule may propose (§7.4a): the first failing reason, every failing reason in order, and the hint of
 *  the first (reasons 3 and 4 carry one). `message` is the panel's line, `empirical deprioritization unavailable:
 *  <reason>`, null when available. */
export interface LabAvailability {
  available: boolean;
  reason: string | null;
  reasons: string[];
  hint: string | null;
  message: string | null;
}

/** The constants the rule and its panel print (`rule.CONSTANTS`, `lab/policy.py`): read from the response, never from a
 *  UI literal. Named key by key, so a misspelt one does not compile. */
export interface LabImportanceConstants {
  /** The practical-significance floor, applied to upper bounds (§7.4a). */
  THETA_MIN: number;
  /** The residual's lower bound above which no `Deprioritized` proposal is made. */
  RESIDUAL_VETO: number;
  /** The residual's upper bound below which the decomposition is inconsistent. */
  RESIDUAL_INCONSISTENT: number;
  /** Bootstrap resamples of the fine grid, and shuffles of its permutation null. */
  BOOTSTRAP_B: number;
  PERMUTATION_P: number;
  /** The same for the coarse decomposition. */
  COARSE_BOOTSTRAP_B: number;
  COARSE_PERMUTATION_P: number;
  COARSE_BINS: number;
  /** The interval's coverage (0.9: a 90 % interval) and the null's quantile that sets a detection floor. */
  INTERVAL: number;
  FLOOR_QUANTILE: number;
  /** Cramér's V above which a pair is aliased. */
  ALIAS_V: number;
  /** A pair's cell needs this many rows; a pair is unresolved under PAIR_MIN_COVERAGE of its grid so held, and
   *  unbalanced above PAIR_BALANCE_TVD. */
  PAIR_MIN_N: number;
  PAIR_MIN_COVERAGE: number;
  PAIR_BALANCE_TVD: number;
  /** `Measured` needs n ≥ IMPORTANCE_MIN_N_FACTOR × the parameter's values and IMPORTANCE_MIN_PER_VALUE rows at each. */
  IMPORTANCE_MIN_N_FACTOR: number;
  IMPORTANCE_MIN_PER_VALUE: number;
  /** The rows a bootstrap reads at most (a seeded subsample beyond), the triples shown, the pairs a view sends. */
  IMPORTANCE_ROWS: number;
  TRIPLE_TOP: number;
  INTERACTIONS_MAX_PAIRS: number;
}

/** An importance stage as the `importance` view sends it (`ImportanceResult.to_json` plus the stage fields, without
 *  the triple-level arrays). Each stage is whole for the stages run so far: stage 1 holds `fine` alone, stage 2 adds
 *  `blocks` and `coarse`, stage 3 `coarse_bounds` and `coarse_null`; the later ones are null before. `partial` is true
 *  until the last. `n` uniform trials were used of `N` scheduled (`attempted` of them attempted while a run is in
 *  progress; `sampled_from` is set when more than IMPORTANCE_ROWS were subsampled). Index `i` of every per-parameter
 *  array is `paths[i]`; `B[i]` is its value count. */
export interface LabImportanceResult {
  paths: string[];
  B: number[];
  n: number;
  N: number;
  attempted: number;
  sampled_from: number | null;
  missing: { invalid: number; failed: number; undefined: number };
  invalid_share: number;
  metric: string;
  scope: string;
  seed: number;
  snapshot: LabSnapshot | null;
  labels: LabCoverageLabel[];
  values_held: number[];
  pair_coverage: LabNumber[][];
  pair_balance: LabNumber[][];
  cramers_v: LabNumber[][];
  aliased: Array<[number, number]>;
  fine: LabFine;
  /** The experiment's screening blocks K, 0 for none. */
  K: number;
  /** Per block number (a string key, "1".."K") the fine mains, once stage 2 has run; null at K = 0. */
  blocks: Record<string, LabBlockMains> | null;
  coarse: LabCoarse | null;
  coarse_bounds: LabCoarseBounds | null;
  coarse_null: LabCoarseNull | null;
  /** The top triples by their coarse increment, as indices into `paths` (the `triples` view lists them). */
  triples_top: Array<[number, number, number]>;
  availability: LabAvailability;
  veto: string | null;
  warnings: string[];
  note: string | null;
  statuses: LabParameterStatus[];
  constants: LabImportanceConstants;
  stage: number;
  stages: number;
  partial: boolean;
  /** Per parameter `[min, max]` of its per-block share estimates (null where no block measured it); null at K = 0 and
   *  before stage 2. */
  block_range: Array<[number, number] | null> | null;
  /** §7.3's three uncertainties, always shown together. */
  uncertainty: { design: string; period: string; detection: string };
  /** §7.3's caveat, printed verbatim. */
  caveat: string;
  elapsed_s: number;
}

/** The `importance` view. `importance` is null before any stage was delivered. */
export interface LabImportance extends LabTaskView {
  importance: LabImportanceResult | null;
}

/** Which stage an `interactions` or `triples` answer was read from, and on what; null before a stage was delivered. */
export interface LabComputed {
  stage: number;
  stages: number;
  partial: boolean;
  seed: number;
  snapshot: LabSnapshot | null;
  metric: string;
  scope: string;
  n: number;
  N: number;
  attempted: number;
  sampled_from: number | null;
  elapsed_s: number;
}

/** A value with its 90 % bounds. */
export interface LabInterval {
  value: LabNumber;
  lo: LabNumber;
  hi: LabNumber;
}

/** An increment with its family floor; `detected` is true when its value exceeds the floor. */
export interface LabIncrement extends LabInterval {
  floor: LabNumber;
  detected: boolean;
}

/** One pair on the fine grid. `D_ij` is Δ_{i|j}, what `pair[0]` adds beyond `pair[1]`; `D_ji` the other direction;
 *  `index` are the parameters' places in `paths`. `I` has no interval (display only). `coverage` is the share of the
 *  pair's value grid holding enough rows; `unresolved` when it is under PAIR_MIN_COVERAGE, `unbalanced` when its
 *  cells are far from uniform. */
export interface LabInteractionPair {
  pair: [string, string];
  index: [number, number];
  J: LabInterval;
  D_ij: LabIncrement;
  D_ji: LabIncrement;
  I: LabNumber;
  coverage: number;
  balance: LabNumber;
  unbalanced: boolean;
  unresolved: boolean;
}

/** The `interactions` view: the pairs resolved first by their larger increment, the unresolved last, at most
 *  INTERACTIONS_MAX_PAIRS. `truncated` says the list was cut and `total_pairs` counts them all. `constants` is null
 *  before a stage was delivered. */
export interface LabInteractions extends LabTaskView {
  computed: LabComputed | null;
  pairs: LabInteractionPair[];
  total_pairs: number;
  unresolved_pairs: number;
  truncated: boolean;
  constants: LabImportanceConstants | null;
}

/** A triple's increment in the direction of one of its parameters. `lo` / `hi` are the coarse bootstrap's (stage 3, a
 *  candidate's triples only), `floor` the coarse null's; null before they exist. */
export interface LabTripleIncrement {
  own: string;
  value: LabNumber;
  lo: LabNumber;
  hi: LabNumber;
  floor: LabNumber;
}

export interface LabTriple {
  triple: [string, string, string];
  index: [number, number, number];
  T: LabNumber;
  /** The largest own-direction increment. */
  delta: LabNumber;
  increments: LabTripleIncrement[];
}

/** The `triples` view: the top TRIPLE_TOP by their increment, empty before stage 2. `bounded` is true once the coarse
 *  bootstrap has bounded them (stage 3); `total_triples` counts every triple. (The `interactions` view's flag for a cut
 *  list is `truncated`: this one means something else.) */
export interface LabTriples extends LabTaskView {
  computed: LabComputed | null;
  triples: LabTriple[];
  total_triples: number;
  bounded: boolean;
}

/** The `neighbourhood` view's trial: the tested trials within `r` steps in at most `m` parameters. `values`, `p25`,
 *  `p75` and `iqr` are ORIENTED (higher is better, so `max_drawdown` is negated; `orientation` says so), `trials`
 *  and `values` are the tested ones by trial number; `valid` the positions the frame does not rule out, `coverage` is
 *  tested / valid. */
export interface LabNeighbourhoodResult {
  trial_no: number;
  probes: number;
  valid: number;
  tested: number;
  coverage: number;
  trials: number[];
  values: number[];
  p25: LabNumber;
  p75: LabNumber;
  iqr: LabNumber;
  r: number;
  m: number;
  undefined: number;
  orientation: 1 | -1;
  valid_basis: string;
}

/** The §7.6 constants a robustness panel prints, from the response. */
export interface LabRobustnessConstants {
  PLATEAU_MIN_COVERAGE: number;
  NEIGHBOUR_R: number;
  NEIGHBOUR_M_GRID: number;
  NEIGHBOUR_M_SAMPLED: number;
  PEAK_IQR_FACTOR: number;
  REGION_RADIUS: number;
  REGION_AXES: number;
  REGION_MIN_N: number;
  FOLDS_MIN: number;
  FOLD_MIN_TRADES: number;
  FOLD_RATIO_BAND: [number, number];
  FOLD_DRAWDOWN_FACTOR: number;
  STRESS_KEEP: number;
  STRESS_DRAWDOWN_FACTOR: number;
  PER_BARS: number;
  RANKING_K: number;
  RANK_POOL: number;
  RANK_B_MAX: number;
  /** Where a metric stops losing money, by metric name (a metric absent here has none). */
  BREAK_EVEN: Record<string, number>;
}

/** The `neighbourhood` view. */
export interface LabNeighbourhood {
  trial_id: string;
  neighbourhood: LabNeighbourhoodResult;
  constants: LabRobustnessConstants;
}

export type LabCategoryName = 'A' | 'B' | 'C' | 'D';

/** One robustness category: resolved with a `classification` (its `reason` then null), or unresolved with its
 *  `reason` (its `classification` then null), and the `inputs` that decided it either way. */
export interface LabCategoryOf<N extends LabCategoryName, C extends string, I> {
  name: N;
  resolved: boolean;
  classification: C | null;
  reason: string | null;
  inputs: I;
}

/** A's inputs, ORIENTED like the neighbourhood's (`max_drawdown` negated): `value` is the candidate's, `p25` the
 *  neighbours' lower quartile, `distance` = |value − p25|, resolved `stable local` when it is within `tau`. Converting a
 *  negated metric back to its real units (`orientation * x`) swaps `p25` and `p75`: the oriented lower quartile is the
 *  real upper one. `iqr`, `tau` and `distance` are widths and keep their sign. */
export interface LabAInputs {
  n: number;
  valid: number;
  tested: number;
  undefined: number;
  coverage: number;
  min_coverage: number;
  required_n: number;
  r: number;
  m: number;
  probes: number;
  valid_basis: string;
  p25: LabNumber;
  p75: LabNumber;
  iqr: LabNumber;
  tau: number;
  value: LabNumber;
  distance: LabNumber;
  peak_factor: number;
  peak_line: LabNumber;
  orientation: 1 | -1;
}

/** B's inputs (the sampled region), ORIENTED. `a_unresolved` rides along when A is unresolved: B is never reported as
 *  A. `density` is the region's trials over what a uniform draw would put in it. As for A, converting a negated metric
 *  back swaps `p25` and `p75` (`iqr` and `tau` are widths and keep their sign). */
export interface LabBInputs {
  axes: string[];
  radius: number;
  n: number;
  min_n: number;
  population: number | null;
  region_share: number | null;
  density: number | null;
  adaptive_excluded: number;
  undefined: number;
  p25: LabNumber;
  p75: LabNumber;
  iqr: LabNumber;
  tau: number;
  value: LabNumber;
  distance: LabNumber;
  orientation: 1 | -1;
  a_unresolved?: string | null;
}

/** One evaluation's figures (a fold, a block, the full range or a replay): net P&L and max drawdown as the engine
 *  reports them (not oriented), and their per-1,000-bar statistics. */
export interface LabFigures {
  bars: number;
  trades: number;
  net_pnl: LabNumber;
  max_drawdown: LabNumber;
  net_pnl_per_1000_bars: LabNumber;
  trades_per_1000_bars: LabNumber;
  expectancy_per_trade: LabNumber;
}

/** C's inputs. Without folds (Phase 3 supplies none) they hold the counts and the constants; with folds they add the
 *  full range's `full` and each fold's `fold_figures` with its ratio to it. */
export interface LabCInputs {
  folds: number;
  folds_min: number;
  fold_min_trades: number;
  ratio_band: [number, number];
  drawdown_factor: number;
  blocks?: number;
  full?: LabFigures | null;
  fold_figures?: Array<LabFigures & { ratio: LabNumber }>;
}

/** D's inputs: the replay scenarios there are (none in Phase 3), the constants, the base and stressed figures. */
export interface LabDInputs {
  scenarios: string[];
  stress_keep: number;
  drawdown_factor: number;
  base: LabFigures | null;
  stressed: LabFigures | null;
  ratio: LabNumber;
}

export type LabCategoryA = LabCategoryOf<'A', 'stable local' | 'isolated peak' | 'mixed', LabAInputs>;
export type LabCategoryB = LabCategoryOf<'B', 'stable region' | 'unstable region', LabBInputs>;
export type LabCategoryC = LabCategoryOf<'C', 'consistent' | 'inconsistent' | 'not profitable on the full range', LabCInputs>;
export type LabCategoryD = LabCategoryOf<'D', 'holds' | 'degrades' | 'fails' | 'not profitable at base', LabDInputs>;

/** An informational result beside the categories, which it never changes: the blocks' `selection-period consistency`.
 *  `classification` is null when the evidence gives no verdict, and `reason` says why. */
export interface LabFinding {
  name: string;
  classification: 'consistent' | 'inconsistent' | 'not profitable on the full range' | null;
  inputs: {
    full: LabFigures | null;
    block_figures: Array<LabFigures & { block: number; ratio: LabNumber }>;
    ratio_band: [number, number];
    drawdown_factor: number;
  };
  reason: string | null;
}

/** One candidate's four categories side by side (the `robustness` view with a `trial`), never summed: `tested` lists
 *  the resolved ones and `unknown` the rest. `value`, A's and B's inputs are ORIENTED (higher is better): a
 *  `max_drawdown` candidate's value is negated, and `orientation` says so, so print the real value as
 *  `orientation * value` (Pareto's `points` are real values already). `tau` is the tolerance band. */
export interface LabCandidateCard {
  trial_id: string;
  trial_no: number;
  metric: string;
  scope: string;
  value: LabNumber;
  orientation: 1 | -1;
  tolerance: number;
  tolerance_label: string | null;
  tau: number;
  categories: { A: LabCategoryA; B: LabCategoryB; C: LabCategoryC; D: LabCategoryD };
  tested: LabCategoryName[];
  unknown: LabCategoryName[];
  findings: LabFinding[];
}

/** One row of a ranking: the trial, its ORIENTED `value`, and what placed it (`ranked_by` A or B, null when neither
 *  resolved, then `reason` says why). The rankings carry no `orientation` of their own (the card does): it is the
 *  asked metric's, and `max_drawdown` is the one metric where lower is better (`orientationOf` in candidateModel.ts). */
export interface LabRankedEntry {
  trial_id: string;
  value: number;
  ranked_by: 'A' | 'B' | null;
  classification: LabCategoryA['classification'] | LabCategoryB['classification'];
  reason: string | null;
}

/** The two rankings of the filter: `peak` (the metric alone) and `robust` (lexicographic over the resolved
 *  categories, with the metric breaking a tie), `k` rows each at most, chosen from the top `pool` by peak (RANK_POOL),
 *  B read on at most `b_max` of them. `ranked` / `peak_ranked` list each with what placed it. `stable` names the first
 *  robust candidate that is stable and above its metric's break-even, untied; it comes from the whole pool, so it may
 *  name a trial outside `ranked` (`stableEntry` looks it up and tolerates that). When it names none, `stable_reason`
 *  says why. Values are ORIENTED (`max_drawdown` negated). */
export interface LabRankings {
  peak: string[];
  robust: string[];
  disagree: boolean;
  stable: string | null;
  stable_reason: string | null;
  k: number;
  pool: number;
  b_max: number;
  ranked: LabRankedEntry[];
  peak_ranked: LabRankedEntry[];
}

interface LabRobustnessCommon {
  tolerance: number;
  /** `default tolerance 0.15` for a grid job, which has none of its own; null for an experiment. */
  tolerance_label: string | null;
  /** B's axes: the top parameters of a finished importance result (none without one). */
  axes: string[];
  constants: LabRobustnessConstants;
}

/** A `robustness` answer with a `trial` in the request: the candidate card. */
export interface LabRobustnessCard extends LabRobustnessCommon {
  card: LabCandidateCard;
  rankings: null;
}

/** A `robustness` answer without one: the rankings. */
export interface LabRobustnessRankings extends LabRobustnessCommon {
  card: null;
  rankings: LabRankings;
}

/** The `robustness` view answers one of two exclusive shapes, by whether the request sent a `trial`: tell them apart
 *  with `isCandidateCard`. A and B values are ORIENTED, so `max_drawdown` is negated (print `orientation * value`). */
export type LabRobustness = LabRobustnessCard | LabRobustnessRankings;

/** One front point: the trial and its objectives' REAL values, in the order of `LabPareto.objectives`. */
export interface LabParetoPoint {
  trial_id: string;
  values: number[];
}

/** The dominated cloud over the first two objectives: `counts[y][x]`, both axes ascending, over the ranges `x` and
 *  `y` (null with no trial defined on every objective), which the front's points share. */
export interface LabParetoDensity {
  bins: number;
  axes: string[];
  x: [number, number] | null;
  y: [number, number] | null;
  counts: number[][];
  basis: string;
}

/** The `pareto` view: the rank-1 front of two or three objectives. `points` are REAL values (a `max_drawdown`
 *  objective is the drawdown itself), `orientation` says which way each objective is better (-1: lower is). At most
 *  PARETO_FRONT_MAX points are drawn (`front` and `points` aligned, each objective's best among them); `sampled` is
 *  true when that is not all of `front_size`, and `basis` then reads `Sampled subset (n of N)`. A trial with an
 *  undefined objective is compared with nothing and counted in `excluded`, so `front_size + dominated + excluded` is
 *  the scope's `filtered`. */
export interface LabPareto {
  objectives: string[];
  orientation: Array<1 | -1>;
  front: string[];
  front_size: number;
  dominated: number;
  excluded: number;
  sampled: boolean;
  points: LabParetoPoint[];
  density: LabParetoDensity;
  basis: string;
  constants: { PARETO_FRONT_MAX: number; PARETO_DENSITY_BINS: number; OBJECTIVES_MIN: number; OBJECTIVES_MAX: number };
}

/** One complete batch of the robust series: the median and quartiles, in the metric's own units, of the
 *  neighbourhood P25 of the batch's top trials; `measured` of the `top` had a tested neighbour. */
export interface LabConvergenceBatch {
  batch: number;
  trial_no: number;
  median: LabNumber;
  p25: LabNumber;
  p75: LabNumber;
  top: number;
  measured: number;
}

/** The `convergence` view, in the metric's own units (`orientation` -1: lower is better). `best` is best-so-far as
 *  `[trial_no, value]` pairs (at most CONVERGENCE_MAX_POINTS, from the first trial on) and `robust` one entry per
 *  complete batch. Below MIN_BATCHES complete batches `robust` is empty and `robust_reason` / the envelope's `empty`
 *  carry the reason WHILE `best` is full: the compact sparkline draws `best` whatever `empty` says, and the full chart
 *  reads `empty` to state why it has no robust series. `best_total` is how many trials `best` thinned from,
 *  `partial` the trials in no complete batch, `r` and `m` the reach their neighbourhoods read. The envelope's
 *  `provisional` follows the source's status. `metric` is the `<scope>.<metric>` column, as `LabParallel.metric` is. */
export interface LabConvergence {
  metric: string;
  orientation: 1 | -1;
  best: Array<[number, number]>;
  best_total: number;
  robust: LabConvergenceBatch[];
  robust_reason: string | null;
  batches: number;
  partial: number;
  r: number;
  m: number;
  basis: string;
  constants: { CONVERGENCE_BATCH: number; CONVERGENCE_TOP: number; CONVERGENCE_MAX_POINTS: number; MIN_BATCHES: number; NEIGHBOUR_R: number };
}

/** POST /lab/{src}/tasks/{task_id}/cancel: false only when the task's key has nothing live left to stop. */
export interface LabCancelled {
  cancelled: boolean;
}

/** One scope of a trial: the ten experiment metrics, the trade Sharpe and its `low_n` flag. */
export type LabTrialMetrics = Record<Objective, number | null> & { sharpe_trade: number | null; low_n: boolean };

/** GET /lab/{src}/trials/{trial}: one trial's canonical row, every scope's metrics with the trade Sharpe and its
 *  `low_n` flag (fewer than SHARPE_MIN_TRADES trades, or none known). */
export interface LabTrial {
  trial_id: string;
  trial_no: number;
  cell: number | null;
  params: Record<string, number>;
  pos: Array<number | null>;
  param_key: string | null;
  status: string | null;
  attempt: number | null;
  block: number | null;
  pass: string | null;
  design: string | null;
  metrics: Record<'combined' | 'long' | 'short', LabTrialMetrics>;
  elapsed_ms: number | null;
  engine: string | null;
  chunk: number | null;
  finished_at: string | null;
  identity: { inputs_key: string | null; strategy_hash: string | null; data_pinned?: Record<string, unknown> | null; data?: Record<string, unknown> };
}

/** GET /lab/build: the worker's engine build and versions, its roots, the Lab cache and the data root's disk. */
export interface LabBuild {
  engine_build: string;
  versions: Record<string, unknown>;
  app_root: string;
  data_root: string;
  cache: { bytes: number; entries: number; hits: number; misses: number };
  disk: { free_gb: number; low: boolean; root: string };
}

export interface Spread {
  min: number | null;
  max: number | null;
  mean: number | null;
  std: number | null;
}

export interface Stability {
  parameters: Record<string, Spread>;
  positive_oos_windows: number;
  windows_evaluated: number;
  mean_efficiency: number | null;
}

export interface WalkForwardStatus {
  job_id: string;
  kind: 'walkforward';
  status: JobState;
  side: JobSide;
  objective: Metric;
  created_at: string;
  progress: { done: number; total: number };
  windows: { done: number; total: number };
  current_window: number;
  in_sample_bars: number;
  out_of_sample_bars: number;
  cells_per_window: number;
  unused_tail_bars: number;
  window_records: WindowRecord[];
  stitched: { trades: Trade[]; equity: EquityPoint[]; metrics: Metrics };
  stability: Stability;
  elapsed_ms: number;
  estimated_seconds: number;
  ms_per_bar: number | null;
  bars: number;
  cache_hits: number;
  data: Provenance;
  strategy: StrategySpec;
  settings: { initial_capital: number; allocation_fraction: number; evaluate_from?: string | null };
  result_hash: string | null;
  error: string | null;
}

export interface WalkForwardSummary {
  job_id: string;
  kind?: 'walkforward';
  status: JobState;
  side?: JobSide;
  objective?: Metric;
  created_at?: string;
  windows?: { done: number; total: number };
  in_sample_bars?: number;
  out_of_sample_bars?: number;
  data?: Provenance;
  strategy?: StrategySpec;
  result_hash?: string | null;
}

export interface WalkForwardPlan {
  windows: number;
  cells_per_window: number;
  total_units: number;
  unused_tail_bars: number;
  bars: number;
  estimated_seconds: number;
  ms_per_bar: number;
}

export interface WalkForwardStarted {
  job_id: string;
  windows: number;
  cells_per_window: number;
  total_units: number;
  estimated_seconds: number;
}

// --- studies (Mission 8 spec §7) ---------------------------------------------------------------

export type StudyRule = 'plateau' | 'peak' | 'frozen';
export const STUDY_RULES: StudyRule[] = ['plateau', 'peak', 'frozen'];
export const STUDY_RULE_LABELS: Record<StudyRule, string> = { plateau: 'Plateau rule', peak: 'Peak rule', frozen: 'Frozen centre' };

export interface StudyRuleMetrics {
  net_pnl: number | null;
  net_return: number | null;
  cagr: number | null;
  max_drawdown: number | null;
  mar: number | null;
  trade_count: number | null;
  exposure: number | null;
}

export interface StudyRuleReport {
  metrics: StudyRuleMetrics;
  objective: number | null;
  flat_windows: number;
  windows: number;
  result_hash: string;
}

export interface StudyCurvePoint {
  timestamp: string;
  equity: number;
  drawdown?: number;
}

export interface StudyWindowRow {
  index: number;
  oos_start: string;
  oos_end: string;
  choice?: string;
  best?: { cell: number; params: Record<string, number>; objective: number | null } | null;
  net_pnl?: Partial<Record<StudyRule, number | null>>;
  flat: boolean;
  flat_rules?: Partial<Record<StudyRule, boolean>>;
  peaks?: number | null;
  fragile?: number | null;
  centre_inside?: boolean | null;
  moved?: number | null;
}

export interface StudySymbolReport {
  windows: number;
  rules: Record<StudyRule, StudyRuleReport | { absent: string }>;
  flat_line: string;
  comparison: string;
  stability: {
    plateau_share: number | null;
    centre_kept_share: number | null;
    median_move: number | null;
    centre_path: Record<string, Array<number | null>>;
  };
  curves: Partial<Record<StudyRule, StudyCurvePoint[]>>;
  window_rows: StudyWindowRow[];
}

export interface StudyReport {
  objective: string;
  data_label: string;
  raw_archive: boolean;
  label: string;
  frozen_absent: string | null;
  symbols: Record<string, StudySymbolReport>;
  summary: string;
  caveats: string[];
}

export interface StudyProgress {
  windows_done: number;
  windows_total: number;
  symbol: string | null;
  window: number | null;
  cells_done: number;
}

export interface StudySummary {
  id: string;
  name: string;
  experiment_id: string;
  status: 'queued' | 'running' | 'paused' | 'done' | 'cancelled' | 'failed';
  progress: StudyProgress;
  symbols: string[];
  objective: string;
  created_at: string;
  updated_at: string;
  decision: ExperimentDecision | null;
  job_id?: string | null;
  error?: string | null;
}

// --- the Results library (Mission 9) --------------------------------------------------------------

export type LibraryKind = 'backtest' | 'optimization' | 'walkforward' | 'experiment' | 'study';
export const LIBRARY_KINDS: LibraryKind[] = ['backtest', 'optimization', 'walkforward', 'experiment', 'study'];

export interface LibraryEntry {
  kind: LibraryKind;
  id: string;
  name: string;
  label: string;
  notes: string;
  starred: boolean;
  symbols: string[];
  timeframe: string | null;
  start: string | null;
  end: string | null;
  strategy_id: string | null;
  strategy_name: string | null;
  created_at: string | null;
  status: string | null;
  decision: ExperimentDecision | null;
  headline: Record<string, unknown>;
  links: Record<string, unknown>;
  deleted_at?: string | null;
  ready?: boolean; // false while the headline waits for the backfill
}

export interface LibraryPage {
  total: number;
  entries: LibraryEntry[];
  preparing: number;
  counts_by_kind: Record<LibraryKind, number>;
}

export interface LibraryFilters {
  kinds: LibraryKind[];
  symbol: string;
  timeframe: string;
  strategy: string;
  starred: boolean;
  decision: string;
  q: string;
  sort: 'created' | 'net_pnl' | 'mar';
  offset: number;
  limit: number;
  deleted: boolean;
}

export type CompareMark = 'better' | 'worse' | null;

export interface CompareMetricRow {
  metric: string;
  a: number | null;
  b: number | null;
  diff: number | null;
  mark: CompareMark;
}

export interface ComparePoint {
  t: string;
  pct: number;
  usd: number;
  dd: number;
}

export interface CompareSideTrades {
  count: number;
  avg_net: number | null;
  win_rate: number | null;
  avg_hold_hours: number | null;
  max_hold_hours: number | null;
}

export interface CompareIdentity {
  run_id: string;
  label?: string;
  symbol: string | null;
  timeframe: string | null;
  start: string | null;
  end: string | null;
  strategy_name: string | null;
  strategy_hash: string | null;
  result_hash: string | null;
  data_hash: string | null;
  initial_capital: number;
  created_at: string | null;
}

export interface CompareResult {
  identity: { a: CompareIdentity; b: CompareIdentity };
  notes: string[];
  differences: Array<{ path: string; a: unknown; b: unknown }>;
  metrics: Record<'combined' | 'long' | 'short', CompareMetricRow[]>;
  equity: { a: ComparePoint[]; b: ComparePoint[] };
  domain: { start: string; end: string } | null;
  trades: { a: Record<'long' | 'short', CompareSideTrades>; b: Record<'long' | 'short', CompareSideTrades> };
  capital_assumed: { a: boolean; b: boolean };
}
