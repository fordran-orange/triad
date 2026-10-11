import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import type { SymbolInfo } from '../api/client';
import type { StrategySpec, WindowMode } from '../contracts';
import type { JobStatus, RunEnvelope, WalkForwardStatus } from '../results';

export const TIMEFRAMES = ['1m', '15m', '30m', '1h', '1D'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export type Side = 'long' | 'short';
export const SIDES: Side[] = ['long', 'short'];
export const SIDE_KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

export interface Selection {
  symbol: string;
  timeframe: Timeframe;
  start: string; // YYYY-MM-DD, America/New_York, inclusive
  end: string;
}

/** Backtest settings posted with every run: BacktestSettings with the engine's defaults filled in. */
export interface Settings {
  initial_capital: number;
  allocation_fraction: number;
}

export const DEFAULT_SETTINGS: Settings = { initial_capital: 100_000, allocation_fraction: 1 };

/** A persisted backtest envelope as POST /aegis/api/backtest and GET /aegis/api/runs/{id} return it. */
export type RunRecord = RunEnvelope;

/** GET /aegis/api/status: the governance line the shell shows comes from here, never from copy. */
export interface ApiStatus {
  product: string;
  mode: string;
  status: string;
  exchange: string;
}

export type ExecutionField = 'commission_per_side' | 'slippage_bps';
export type RangeField = 'start' | 'stop' | 'step' | 'enabled';
export type ResultsTab = 'summary' | 'trades' | 'optimization' | 'walkforward' | 'equity';
export type SelectedConfigs = { long: Record<string, number> | null; short: Record<string, number> | null };

export interface WorkspaceState {
  strategy: StrategySpec | null;
  selection: Selection;
  settings: Settings;
  symbols: SymbolInfo[] | null; // what /data/symbols found on disk; null until loaded
  status: ApiStatus | null;
  linkSides: boolean;
  running: boolean;
  runError: string | null;
  lastRun: RunRecord | null;
  loadedBars: { count: number; vintage: string } | null;
  resultsTab: ResultsTab;
  optimization: { long?: JobStatus; short?: JobStatus };
  walkforward: { long?: WalkForwardStatus; short?: WalkForwardStatus };
  selectedConfigs: SelectedConfigs;
  focusSide: Side; // the side the chart and the Indicators tab show (plan ruling P9)
  latest: Record<string, number | null>; // last value per drawn series, from the chart's fetch
}

export type Action =
  | { type: 'SET_STRATEGY'; strategy: StrategySpec }
  | { type: 'SET_SELECTION'; selection: Partial<Selection> }
  | { type: 'SET_SYMBOLS'; symbols: SymbolInfo[] | null }
  | { type: 'SET_STATUS'; status: ApiStatus | null }
  | { type: 'SET_LINK_SIDES'; linked: boolean }
  | { type: 'SET_SIDE_PARAM'; side: Side; path: string; value: number | string | boolean }
  | { type: 'SET_WINDOW_MODE'; id: string; mode: WindowMode }
  | { type: 'SET_EXECUTION'; field: ExecutionField; value: number }
  | { type: 'SET_SETTINGS'; settings: Partial<Settings> }
  | { type: 'SET_RANGE'; side: Side; path: string; field: RangeField; value: number | boolean }
  | { type: 'BARS_LOADED'; bars: { count: number; vintage: string } | null }
  | { type: 'SET_RESULTS_TAB'; tab: ResultsTab }
  | { type: 'RUN_STARTED' }
  | { type: 'RUN_COMPLETED'; run: RunRecord }
  | { type: 'RUN_FAILED'; error: string }
  | { type: 'LOAD_RUN'; run: RunRecord }
  | { type: 'JOB_UPDATED'; side: Side; job: JobStatus }
  | { type: 'JOB_LOST'; side: Side; job_id: string }
  | { type: 'WALKFORWARD_UPDATED'; side: Side; job: WalkForwardStatus }
  | { type: 'WALKFORWARD_LOST'; side: Side; job_id: string }
  | { type: 'SELECT_CONFIG'; side: Side; params: Record<string, number> | null }
  | { type: 'SET_FOCUS_SIDE'; side: Side }
  | { type: 'SET_LATEST'; values: Record<string, number | null> };

export const initialState: WorkspaceState = {
  strategy: null,
  selection: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31' },
  settings: DEFAULT_SETTINGS,
  symbols: null,
  status: null,
  linkSides: true,
  running: false,
  runError: null,
  lastRun: null,
  loadedBars: null,
  resultsTab: 'summary',
  optimization: {},
  walkforward: {},
  selectedConfigs: { long: null, short: null },
  focusSide: 'long',
  latest: {},
};

/**
 * Set a side-relative path such as `indicators.ema.length`: the second segment of an
 * `indicators` path is an indicator id, resolved by `id`, not an array index. Returns a new object.
 */
export function setPath<T>(target: T, path: string, value: unknown): T {
  const [head, ...rest] = path.split('.');
  if (head === undefined) return target;
  const source = target as unknown as Record<string, unknown>;
  if (Array.isArray(source[head]) && rest.length > 0) {
    const list = source[head] as Record<string, unknown>[];
    const [id, ...tail] = rest;
    return {
      ...source,
      [head]: list.map((item) => (item.id === id ? setPath(item, tail.join('.'), value) : item)),
    } as T;
  }
  if (rest.length === 0) return { ...source, [head]: value } as T;
  return { ...source, [head]: setPath(source[head], rest.join('.'), value) } as T;
}

/** The strategy with each side's selected optimizer configuration applied; sides stay independent. */
export function applyConfigs(strategy: StrategySpec, configs: SelectedConfigs): StrategySpec {
  let next = strategy;
  for (const side of SIDES) {
    const params = configs[side];
    if (!params) continue;
    const key = SIDE_KEY[side];
    let spec = next[key];
    for (const [path, value] of Object.entries(params)) spec = setPath(spec, path, value);
    next = { ...next, [key]: spec };
  }
  return next;
}

function isTimeframe(value: unknown): value is Timeframe {
  return typeof value === 'string' && (TIMEFRAMES as readonly string[]).includes(value);
}

/** The selection a persisted run was made against, when its pinned source carries one. */
export function selectionOf(run: RunRecord, fallback: Selection): Selection {
  const d = run.data;
  if (!d || typeof d.symbol !== 'string' || !isTimeframe(d.timeframe) || typeof d.start !== 'string' || typeof d.end !== 'string') {
    return fallback;
  }
  return { symbol: d.symbol, timeframe: d.timeframe, start: d.start, end: d.end };
}

/** JSON with object keys sorted at every level, so two documents compare by content, not key order. */
export function canonical(value: unknown): string {
  const sort = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sort);
    if (v && typeof v === 'object') {
      return Object.fromEntries(
        Object.keys(v as Record<string, unknown>)
          .sort()
          .map((k) => [k, sort((v as Record<string, unknown>)[k])]),
      );
    }
    return v;
  };
  return JSON.stringify(sort(value));
}

export interface Staleness {
  selection: boolean;
  strategy: boolean;
  settings: boolean;
  any: boolean;
}

/** What has changed since the last run was computed; results are only current when nothing has. */
export function runStaleness(state: WorkspaceState): Staleness {
  const run = state.lastRun;
  if (!run) return { selection: false, strategy: false, settings: false, any: false };
  const d = run.data ?? {};
  const s = state.selection;
  const selection = d.symbol !== s.symbol || d.timeframe !== s.timeframe || d.start !== s.start || d.end !== s.end;
  const strategy = state.strategy !== null && run.strategy !== undefined && canonical(run.strategy) !== canonical(state.strategy);
  const settings =
    run.settings !== undefined &&
    (run.settings.initial_capital !== state.settings.initial_capital || run.settings.allocation_fraction !== state.settings.allocation_fraction);
  return { selection, strategy, settings, any: selection || strategy || settings };
}

export function reducer(state: WorkspaceState, action: Action): WorkspaceState {
  switch (action.type) {
    case 'SET_STRATEGY':
      return { ...state, strategy: action.strategy };
    case 'SET_SELECTION':
      return { ...state, selection: { ...state.selection, ...action.selection } };
    case 'SET_SYMBOLS':
      return { ...state, symbols: action.symbols };
    case 'SET_STATUS':
      return { ...state, status: action.status };
    case 'SET_LINK_SIDES':
      return { ...state, linkSides: action.linked };
    case 'SET_SIDE_PARAM': {
      if (!state.strategy) return state;
      let strategy = state.strategy;
      const sides: Side[] = state.linkSides && action.path.startsWith('indicators.') ? ['long', 'short'] : [action.side];
      for (const side of sides) {
        const key = SIDE_KEY[side];
        strategy = { ...strategy, [key]: setPath(strategy[key], action.path, action.value) };
      }
      return { ...state, strategy };
    }
    case 'SET_WINDOW_MODE': {
      // The engine rejects MODIFY_RISK (temporal.py); the UI never puts it in a spec.
      if (!state.strategy || action.mode === 'modify_risk') return state;
      const temporal = state.strategy.temporal;
      const clock_windows = temporal.clock_windows.map((w) => (w.id === action.id ? { ...w, mode: action.mode } : w));
      return { ...state, strategy: { ...state.strategy, temporal: { ...temporal, clock_windows } } };
    }
    case 'SET_EXECUTION':
      if (!state.strategy) return state;
      return { ...state, strategy: { ...state.strategy, execution: { ...state.strategy.execution, [action.field]: action.value } } };
    case 'SET_SETTINGS':
      return { ...state, settings: { ...state.settings, ...action.settings } };
    case 'SET_RANGE': {
      if (!state.strategy) return state;
      const key = SIDE_KEY[action.side];
      const side = state.strategy[key];
      const optimization = (side.optimization ?? []).map((r) => (r.path === action.path ? { ...r, [action.field]: action.value } : r));
      return { ...state, strategy: { ...state.strategy, [key]: { ...side, optimization } } };
    }
    case 'BARS_LOADED':
      return { ...state, loadedBars: action.bars };
    case 'SET_RESULTS_TAB':
      return { ...state, resultsTab: action.tab };
    case 'RUN_STARTED':
      return { ...state, running: true, runError: null };
    case 'RUN_COMPLETED':
      return { ...state, running: false, runError: null, lastRun: action.run };
    case 'RUN_FAILED':
      return { ...state, running: false, runError: action.error };
    case 'LOAD_RUN':
      return {
        ...state,
        running: false,
        runError: null,
        lastRun: action.run,
        strategy: action.run.strategy ?? state.strategy,
        settings: action.run.settings ?? state.settings,
        selection: selectionOf(action.run, state.selection),
      };
    case 'JOB_UPDATED':
      return { ...state, optimization: { ...state.optimization, [action.side]: action.job } };
    case 'JOB_LOST': {
      const job = state.optimization[action.side];
      if (!job || job.job_id !== action.job_id) return state;
      return { ...state, optimization: { ...state.optimization, [action.side]: { ...job, status: 'lost' } } };
    }
    case 'WALKFORWARD_UPDATED':
      return { ...state, walkforward: { ...state.walkforward, [action.side]: action.job } };
    case 'WALKFORWARD_LOST': {
      const job = state.walkforward[action.side];
      if (!job || job.job_id !== action.job_id) return state;
      return { ...state, walkforward: { ...state.walkforward, [action.side]: { ...job, status: 'lost' } } };
    }
    case 'SELECT_CONFIG':
      return { ...state, selectedConfigs: { ...state.selectedConfigs, [action.side]: action.params } };
    case 'SET_FOCUS_SIDE':
      return { ...state, focusSide: action.side };
    case 'SET_LATEST':
      return { ...state, latest: action.values };
    default:
      return state;
  }
}

const StateContext = createContext<WorkspaceState>(initialState);
const DispatchContext = createContext<Dispatch<Action>>(() => undefined);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>{children}</DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export const useWorkspace = () => useContext(StateContext);
export const useDispatch = () => useContext(DispatchContext);
