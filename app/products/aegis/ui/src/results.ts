// Result shapes exactly as POST /aegis/api/backtest and GET /aegis/api/runs/{id} return them
// (products/aegis/backtest.py, results.py, api.py). Nothing here is computed in the browser.
import type { StrategySpec } from './contracts';

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
  created_at: string;
  elapsed_ms: number;
  result_hash: string;
  data: Provenance;
  strategy: StrategySpec;
  result: ResultPayload;
  series: Record<'long' | 'short', Record<string, Array<number | null>>>;
  markers: TradeMarker[];
  settings?: { initial_capital: number; allocation_fraction: number }; // absent on runs persisted before the fix pass
  state: RunState;
  state_detail?: string;
}

/** What GET /aegis/api/runs lists: the envelope without result, series or markers. */
export interface RunSummary {
  run_id: string;
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
