// Thin typed fetch wrappers for the Aegis worker routes (spec §7). Same-origin under /aegis/api.
import type { BacktestRequest, StrategySpec } from '../contracts';
import type { JobRecord, RunRecord, Selection, Side } from '../state/workspace';

const BASE = '/aegis/api';

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
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

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Provenance {
  source: 'raw_archive';
  symbol: string;
  vintage: string;
  research_eligible: false;
  [key: string]: unknown;
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

export interface IndicatorSeries {
  [indicatorId: string]: Array<number | null>;
}

export const api = {
  status: () => request<{ product: string; mode: string; status: string; exchange: string }>('/status'),
  defaultStrategy: () => request<StrategySpec>('/strategy/default'),
  symbols: () => request<SymbolInfo[]>('/data/symbols'),
  bars: (s: Selection) =>
    request<BarsResponse>(`/data/bars?symbol=${encodeURIComponent(s.symbol)}&timeframe=${s.timeframe}&start=${s.start}&end=${s.end}`),
  indicators: (s: Selection, indicators: unknown[]) =>
    request<{ series: IndicatorSeries; times: number[] }>('/indicators', {
      method: 'POST',
      body: JSON.stringify({ symbol: s.symbol, timeframe: s.timeframe, start: s.start, end: s.end, indicators }),
    }),
  backtest: (body: Partial<BacktestRequest> & { data?: Selection }) =>
    request<RunRecord>('/backtest', { method: 'POST', body: JSON.stringify(body) }),
  runs: () => request<RunRecord[]>('/runs'),
  run: (id: string) => request<RunRecord>(`/runs/${encodeURIComponent(id)}`),
  optimize: (body: { strategy: StrategySpec; side: Side; data: Selection; settings?: unknown; objective: string }) =>
    request<{ job_id: string; total_cells: number; skipped_cells: number; estimated_seconds: number }>('/optimize', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  job: (id: string) => request<JobRecord>(`/optimize/${encodeURIComponent(id)}`),
  cancel: (id: string) => request<{ cancelled: boolean }>(`/optimize/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
};
