// Thin typed fetch wrappers for the Aegis worker routes (spec §7). Same-origin under /aegis/api.
import type { ExperimentDocument, IndicatorSpec, Plan, StrategyDocument, StrategySpec, StudyDocument, StudyPlan } from '../contracts';
import type { Canvas } from '../builder/graph';
import type {
  AxisMatrix,
  Cell,
  CellsPage,
  CompareResult,
  ExperimentReport,
  ExperimentSummary,
  JobStatus,
  JobSummary,
  LibraryEntry,
  LibraryFilters,
  LibraryKind,
  LibraryPage,
  Metric,
  Objective,
  OptimizePlan,
  OptimizeStarted,
  Provenance,
  RunEnvelope,
  RunSummary,
  StudySummary,
  WalkForwardPlan,
  WalkForwardStarted,
  WalkForwardStatus,
  WalkForwardSummary,
} from '../results';
import { queryString } from '../library';
import type { Selection, Settings, Side } from '../state/workspace';

export type { Provenance } from '../results';

const BASE = '/aegis/api';

/** FastAPI's `detail`: a string, or for a 422 the list of errors whose `msg` carries the text.
 *  The `Value error, ...` messages (our validators) are joined by "; "; failing that, the last
 *  entry's message stands for the lot (Mission 5 review minor, plan P14 item 1). */
export function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => {
      const msg = (entry as { msg?: unknown } | null)?.msg;
      return typeof msg === 'string' ? msg : JSON.stringify(entry);
    });
    const prefix = 'Value error, ';
    const valueErrors = messages.filter((m) => m.startsWith(prefix)).map((m) => m.slice(prefix.length));
    if (valueErrors.length) return valueErrors.join('; ');
    return messages[messages.length - 1] ?? JSON.stringify(detail);
  }
  return JSON.stringify(detail);
}

export class ApiError extends Error {
  readonly detail: string;
  constructor(
    public status: number,
    detail: unknown,
  ) {
    const text = detailText(detail);
    super(text);
    this.detail = text;
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
    let detail: unknown = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail !== undefined && body.detail !== null) detail = body.detail;
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

/** One discovered raw archive (ArchiveSource in data.py) as GET /data/symbols lists it. */
export interface SymbolInfo {
  symbol: string;
  vintage: string;
  relative_path: string;
  sha256: string;
  first_bar: string;
  last_bar: string;
  row_count: number;
  coverage_pct?: number | null;
  vendor_sources?: string[];
  source: 'raw_archive';
  research_eligible: false;
  [key: string]: unknown;
}

export interface BarsResponse {
  symbol: string;
  timeframe: string;
  timezone: string;
  bars: Bar[];
  count: number; // the native bars of the whole selection
  shown: number; // the candles drawn (Mission 10)
  display_timeframe: string; // the drawn candles' timeframe: the native one unless aggregated
  window: { from_ms: number | null; to_ms: number | null };
  data: Provenance;
}

export interface IndicatorsResponse {
  times: number[];
  series: Record<string, Array<number | null>>; // keyed by reference spelling: `id` or `id.output`
  outputs: Record<string, string[]>; // indicator id → its outputs ([] for single-series kinds)
  pane: Record<string, 'price' | 'own'>; // indicator id → the chart pane its series belong on
  display_timeframe: string; // index-aligned to GET /data/bars' candles for the same view
  data: Provenance;
}

/** Whether every backtest is saved or only what the operator keeps (Mission 10). */
export type SaveMode = 'every' | 'kept';

export interface Preferences {
  save_runs: SaveMode;
}

/** The candles a chart asks for (Mission 10): at most `maxBars` over [from, to] epoch ms. */
export interface ChartView {
  maxBars: number;
  from?: number;
  to?: number;
  atLeast?: string; // candles at least this coarse (QA D1)
}

function viewQuery(view?: ChartView): string {
  if (!view) return '';
  return (
    `&max_bars=${view.maxBars}` +
    (view.from !== undefined ? `&from_ms=${Math.floor(view.from)}` : '') +
    (view.to !== undefined ? `&to_ms=${Math.ceil(view.to)}` : '') +
    (view.atLeast ? `&at_least=${view.atLeast}` : '')
  );
}

function viewBody(view?: ChartView): Record<string, number | string> {
  if (!view) return {};
  return {
    max_bars: view.maxBars,
    ...(view.from !== undefined ? { from_ms: Math.floor(view.from) } : {}),
    ...(view.to !== undefined ? { to_ms: Math.ceil(view.to) } : {}),
    ...(view.atLeast ? { at_least: view.atLeast } : {}),
  };
}

/** POST /optimize and /optimize/plan body (OptimizeRequest in contracts.ts, selection as the data reference). */
export interface OptimizeBody {
  strategy: StrategySpec;
  side: Side;
  data: Selection;
  settings: Settings;
  objective: Metric;
}

/** POST /walkforward and /walkforward/plan body (WalkForwardRequest in contracts.ts). */
export interface WalkForwardBody extends OptimizeBody {
  in_sample_bars: number;
  out_of_sample_bars: number;
}

/** GET /strategies: one row per document, the built-in first (spec §8). */
export interface StrategySummary {
  id: string;
  name: string;
  created_at: string | null;
  updated_at: string | null;
  strategy_hash: string;
  parent: string | null;
  builtin: boolean;
  kinds: string[];
  usage: { runs: number; optimizations: number; walkforwards: number };
}

const put = (body: unknown): RequestInit => ({ method: 'PUT', body: JSON.stringify(body) });
const doc = (id: string) => `/strategies/${encodeURIComponent(id)}`;
const exp = (id: string) => `/experiments/${encodeURIComponent(id)}`;
const study = (id: string) => `/studies/${encodeURIComponent(id)}`;

/** POST /experiments and /experiments/plan body (ExperimentRequest in contracts.ts). */
export interface ExperimentBody {
  name: string;
  strategy_id: string;
  data: Selection;
  settings: Settings;
  objective: Objective;
  surface: { parameters: Array<{ path: string; start: number; stop: number; step: number }> };
  budget: { runs?: number | null; seconds?: number | null };
  tolerance: number;
  seed: number;
}

export interface ExperimentStarted {
  experiment_id: string;
  job_id: string | null;
  status: 'queued' | 'running';
  plan: Plan;
}

/** POST /studies and /studies/plan body (StudyRequest in contracts.ts). */
export interface StudyBody {
  experiment_id: string;
  name?: string | null;
  symbols: string[];
  start?: string | null;
  end?: string | null;
  in_sample_bars?: number | null;
  out_of_sample_bars?: number | null;
}

export interface StudyStarted {
  study_id: string;
  job_id: string;
  status: 'running';
  plan: StudyPlan;
}

/** GET /studies/{id}: the stored document as the runner last saved it, with its progress. */
export type StudyStatus = StudyDocument & { units?: { done: number; total: number }; estimated_seconds?: number; elapsed_ms?: number };

export interface StudyCellsPage {
  total: number;
  rows: Array<Record<string, unknown>>;
  columns: string[];
}

export const api = {
  status: () => request<{ product: string; mode: string; status: string; exchange: string }>('/status'),
  defaultStrategy: () => request<StrategySpec>('/strategy/default'),
  symbols: () => request<{ timeframes: string[]; symbols: SymbolInfo[] }>('/data/symbols'),
  bars: (s: Selection, view?: ChartView) =>
    request<BarsResponse>(`/data/bars?symbol=${encodeURIComponent(s.symbol)}&timeframe=${s.timeframe}&start=${s.start}&end=${s.end}${viewQuery(view)}`),
  indicators: (s: Selection, indicators: IndicatorSpec[], view?: ChartView) =>
    request<IndicatorsResponse>('/indicators', post({ symbol: s.symbol, timeframe: s.timeframe, start: s.start, end: s.end, indicators, ...viewBody(view) })),
  backtest: (body: { strategy: StrategySpec; data: Selection; settings: Settings }) => request<RunEnvelope>('/backtest', post(body)),
  runs: () => request<RunSummary[]>('/runs'),
  run: (id: string) => request<RunEnvelope>(`/runs/${encodeURIComponent(id)}`),
  keepRun: (id: string) => request<{ saved: string }>(`/runs/${encodeURIComponent(id)}/keep`, post({})),
  preferences: () => request<Preferences>('/preferences'),
  setPreferences: (save_runs: SaveMode) => request<Preferences>('/preferences', put({ save_runs })),
  optimizePlan: (body: OptimizeBody) => request<OptimizePlan>('/optimize/plan', post(body)),
  optimize: (body: OptimizeBody) => request<OptimizeStarted>('/optimize', post(body)),
  optimizations: () => request<JobSummary[]>('/optimize'),
  job: (id: string) => request<JobStatus>(`/optimize/${encodeURIComponent(id)}`),
  optimizeCells: (id: string, offset: number, limit: number) =>
    request<{ total: number; rows: Cell[] }>(`/optimize/${encodeURIComponent(id)}/cells?offset=${offset}&limit=${limit}`),
  optimizeMatrix: (id: string, rows: string, cols: string, metric?: string) =>
    request<AxisMatrix>(
      `/optimize/${encodeURIComponent(id)}/matrix?rows=${encodeURIComponent(rows)}&cols=${encodeURIComponent(cols)}${metric ? `&metric=${encodeURIComponent(metric)}` : ''}`,
    ),
  optimizeSquare: (id: string, rows: string, cols: string, row: number, col: number, metric: string) =>
    request<Cell>(
      `/optimize/${encodeURIComponent(id)}/square?rows=${encodeURIComponent(rows)}&cols=${encodeURIComponent(cols)}&row=${row}&col=${col}&metric=${encodeURIComponent(metric)}`,
    ),
  cancel: (id: string) => request<{ cancelled: boolean }>(`/optimize/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  walkforwardPlan: (body: WalkForwardBody) => request<WalkForwardPlan>('/walkforward/plan', post(body)),
  walkforward: (body: WalkForwardBody) => request<WalkForwardStarted>('/walkforward', post(body)),
  walkforwards: () => request<WalkForwardSummary[]>('/walkforward'),
  walkforwardJob: (id: string) => request<WalkForwardStatus>(`/walkforward/${encodeURIComponent(id)}`),
  cancelWalkforward: (id: string) => request<{ cancelled: boolean }>(`/walkforward/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  strategies: () => request<StrategySummary[]>('/strategies'),
  strategyDocument: (id: string) => request<StrategyDocument>(doc(id)),
  createStrategy: (name: string, spec: StrategySpec) => request<StrategyDocument>('/strategies', post({ name, spec })),
  updateStrategy: (id: string, patch: { name?: string; spec?: StrategySpec; canvas?: Canvas }) => request<StrategyDocument>(doc(id), put(patch)),
  duplicateStrategy: (id: string, name: string) => request<StrategyDocument>(doc(id) + '/duplicate', post({ name })),
  deleteStrategy: (id: string) => request<{ deleted: string }>(doc(id), { method: 'DELETE' }),
  experimentPlan: (body: ExperimentBody) => request<Plan>('/experiments/plan', post(body)),
  createExperiment: (body: ExperimentBody) => request<ExperimentStarted>('/experiments', post(body)),
  experiments: () => request<ExperimentSummary[]>('/experiments'),
  experiment: (id: string) => request<ExperimentDocument>(exp(id)),
  experimentCells: (id: string, query: { offset?: number; limit?: number; sort?: string; descending?: boolean; valid_only?: boolean }) => {
    const q = new URLSearchParams();
    if (query.offset !== undefined) q.set('offset', String(query.offset));
    if (query.limit !== undefined) q.set('limit', String(query.limit));
    if (query.sort) q.set('sort', query.sort);
    if (query.descending !== undefined) q.set('descending', String(query.descending));
    if (query.valid_only !== undefined) q.set('valid_only', String(query.valid_only));
    return request<CellsPage>(`${exp(id)}/cells?${q.toString()}`);
  },
  experimentCurves: (id: string, cells: number[]) => request<Record<string, number[]>>(`${exp(id)}/curves?cells=${cells.join(',')}`),
  pauseExperiment: (id: string) => request<{ paused: string }>(`${exp(id)}/pause`, { method: 'POST' }),
  resumeExperiment: (id: string) => request<ExperimentStarted>(`${exp(id)}/resume`, { method: 'POST' }),
  cancelExperiment: (id: string) => request<{ cancelled: boolean }>(`${exp(id)}/cancel`, { method: 'POST' }),
  materializeCell: (id: string, cell: number) => request<RunEnvelope>(`${exp(id)}/cells/${cell}/materialize`, { method: 'POST' }),
  recomputeReport: (id: string, body: { objective?: Objective; tolerance?: number }) => request<ExperimentReport>(`${exp(id)}/report`, post(body)),
  experimentReport: (id: string, n?: number) => request<ExperimentReport>(`${exp(id)}/report${n === undefined ? '' : `?n=${n}`}`),
  decideExperiment: (id: string, body: { verdict: 'accepted' | 'rejected' | 'deferred'; notes: string }) => request<ExperimentDocument>(`${exp(id)}/decision`, put(body)),
  refineExperiment: (id: string) => request<ExperimentDocument>(`${exp(id)}/refine`, { method: 'POST' }),
  deleteExperiment: (id: string) => request<{ deleted: string }>(exp(id), { method: 'DELETE' }),
  studyPlan: (body: StudyBody) => request<StudyPlan>('/studies/plan', post(body)),
  createStudy: (body: StudyBody) => request<StudyStarted>('/studies', post(body)),
  studies: (experimentId?: string) => request<StudySummary[]>(experimentId ? `/studies?experiment_id=${encodeURIComponent(experimentId)}` : '/studies'),
  study: (id: string) => request<StudyStatus>(study(id)),
  pauseStudy: (id: string) => request<{ paused: string }>(`${study(id)}/pause`, { method: 'POST' }),
  resumeStudy: (id: string) => request<{ study_id: string; job_id: string; status: string }>(`${study(id)}/resume`, { method: 'POST' }),
  cancelStudy: (id: string) => request<{ cancelled: boolean }>(`${study(id)}/cancel`, { method: 'POST' }),
  deleteStudy: (id: string) => request<{ deleted: string }>(study(id), { method: 'DELETE' }),
  decideStudy: (id: string, body: { verdict: 'accepted' | 'rejected' | 'deferred'; notes: string }) => request<StudyDocument>(`${study(id)}/decision`, put(body)),
  studyWindowCells: (id: string, symbol: string, w: number, query: { offset?: number; limit?: number } = {}) =>
    request<StudyCellsPage>(`${study(id)}/windows/${encodeURIComponent(symbol)}/${w}/cells?offset=${query.offset ?? 0}&limit=${query.limit ?? 200}`),
  studyMarkdownUrl: (id: string) => `${BASE}${study(id)}/report.md`,
  library: (filters: LibraryFilters) => request<LibraryPage>(`/library?${queryString(filters)}`),
  libraryEntry: (kind: LibraryKind, id: string) => request<LibraryEntry>(`/library/${kind}/${encodeURIComponent(id)}`),
  annotate: (kind: LibraryKind, id: string, body: { label?: string; notes?: string; starred?: boolean }) =>
    request<{ kind: LibraryKind; id: string; label: string; notes: string; starred: boolean }>(`/library/${kind}/${encodeURIComponent(id)}/annotation`, put(body)),
  libraryDelete: (kind: LibraryKind, id: string) => request<{ deleted: string }>(`/library/${kind}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  libraryRestore: (kind: LibraryKind, id: string) => request<{ restored: string }>(`/library/${kind}/${encodeURIComponent(id)}/restore`, { method: 'POST' }),
  libraryEmpty: (items: Array<{ kind: LibraryKind; id: string }> | null) => request<{ erased: number }>('/library/trash/empty', post({ items })),
  libraryCompare: (a: string, b: string) => request<CompareResult>(`/library/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
};
