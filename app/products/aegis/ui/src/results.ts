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
