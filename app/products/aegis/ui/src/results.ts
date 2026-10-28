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

/** A query's view (`QueryRequest.view`); distinct from the Lab's sub-nav `LabView`. */
export type LabQueryView = 'counts' | 'matrix' | 'page' | 'top' | 'marginals' | 'parallel' | 'square_trials';

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
  k?: number;
  paths?: string[];
  axes?: string[];
  row_value?: number;
  col_value?: number;
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

/** Parallel-coordinate bundles: each axis's q + 1 quantile edges and q centres, the largest bundles first. */
export interface LabParallel {
  axes: string[];
  bins: Array<{ edges: number[]; centres: number[] }>;
  bundles: Array<{ bins: number[]; count: number; median: number | null }>;
  total_bundles: number;
  shown_bundles: number;
  basis: string;
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
