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
  estimated_seconds: number;
  bars: number;
}

export interface OptimizeStarted {
  job_id: string;
  total_cells: number;
  skipped_cells: number;
  estimated_seconds: number;
}
