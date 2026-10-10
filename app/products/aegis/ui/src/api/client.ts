// Thin typed fetch wrappers for the Aegis worker routes (spec §7). Same-origin under /aegis/api.
import type { IndicatorSpec, StrategySpec } from '../contracts';
import type { JobStatus, JobSummary, Metric, OptimizePlan, OptimizeStarted, Provenance, RunEnvelope, RunSummary } from '../results';
import type { Selection, Settings, Side } from '../state/workspace';

export type { Provenance } from '../results';

const BASE = '/aegis/api';

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

/** One line for the UI: the HTTP status and the worker's detail, or the transport error. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.status}: ${error.detail}`;
  return error instanceof Error ? error.message : String(error);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SymbolInfo {
  symbol: string;
  vintage: string;
  first_bar: string;
  last_bar: string;
  row_count: number;
  timeframes: string[];
  coverage_pct: number | null;
  vendor_sources: string[];
  source: 'raw_archive';
  research_eligible: false;
}

export interface BarsResponse {
  symbol: string;
  timeframe: string;
  timezone: string;
  bars: Bar[];
  count: number;
  data: Provenance;
}

export interface IndicatorsResponse {
  times: number[];
  series: Record<string, Array<number | null>>;
  data: Provenance;
}

/** POST /optimize and /optimize/plan body (OptimizeRequest in contracts.ts, selection as the data reference). */
export interface OptimizeBody {
  strategy: StrategySpec;
  side: Side;
  data: Selection;
  settings: Settings;
  objective: Metric;
}

export const api = {
  status: () => request<{ product: string; mode: string; status: string; exchange: string }>('/status'),
  defaultStrategy: () => request<StrategySpec>('/strategy/default'),
  symbols: () => request<{ timeframes: string[]; symbols: SymbolInfo[] }>('/data/symbols'),
  bars: (s: Selection) =>
    request<BarsResponse>(`/data/bars?symbol=${encodeURIComponent(s.symbol)}&timeframe=${s.timeframe}&start=${s.start}&end=${s.end}`),
  indicators: (s: Selection, indicators: IndicatorSpec[]) =>
    request<IndicatorsResponse>('/indicators', post({ symbol: s.symbol, timeframe: s.timeframe, start: s.start, end: s.end, indicators })),
  backtest: (body: { strategy: StrategySpec; data: Selection; settings: Settings }) => request<RunEnvelope>('/backtest', post(body)),
  runs: () => request<RunSummary[]>('/runs'),
  run: (id: string) => request<RunEnvelope>(`/runs/${encodeURIComponent(id)}`),
  optimizePlan: (body: OptimizeBody) => request<OptimizePlan>('/optimize/plan', post(body)),
  optimize: (body: OptimizeBody) => request<OptimizeStarted>('/optimize', post(body)),
  optimizations: () => request<JobSummary[]>('/optimize'),
  job: (id: string) => request<JobStatus>(`/optimize/${encodeURIComponent(id)}`),
  cancel: (id: string) => request<{ cancelled: boolean }>(`/optimize/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
};
