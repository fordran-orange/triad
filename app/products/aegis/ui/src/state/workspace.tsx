import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import type { StrategySpec, WindowMode } from '../contracts';
import type { RunEnvelope } from '../results';

export const TIMEFRAMES = ['1m', '15m', '30m', '1h', '1D'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export type Side = 'long' | 'short';

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

export interface JobRecord {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'cancelled' | 'failed' | 'lost';
  progress: { done: number; total: number };
  [key: string]: unknown;
}

export type ExecutionField = 'commission_per_side' | 'slippage_bps';

export interface WorkspaceState {
  strategy: StrategySpec | null;
  selection: Selection;
  settings: Settings;
  linkSides: boolean;
  running: boolean;
  runError: string | null;
  lastRun: RunRecord | null;
  optimization: { long?: JobRecord; short?: JobRecord };
  selectedConfigs: { long: Record<string, number> | null; short: Record<string, number> | null };
}

export type Action =
  | { type: 'SET_STRATEGY'; strategy: StrategySpec }
  | { type: 'SET_SELECTION'; selection: Partial<Selection> }
  | { type: 'SET_LINK_SIDES'; linked: boolean }
  | { type: 'SET_SIDE_PARAM'; side: Side; path: string; value: number | string | boolean }
  | { type: 'SET_WINDOW_MODE'; id: string; mode: WindowMode }
  | { type: 'SET_EXECUTION'; field: ExecutionField; value: number }
  | { type: 'SET_SETTINGS'; settings: Partial<Settings> }
  | { type: 'RUN_STARTED' }
  | { type: 'RUN_COMPLETED'; run: RunRecord }
  | { type: 'RUN_FAILED'; error: string }
  | { type: 'LOAD_RUN'; run: RunRecord }
  | { type: 'JOB_UPDATED'; side: Side; job: JobRecord }
  | { type: 'SELECT_CONFIG'; side: Side; params: Record<string, number> | null };

export const initialState: WorkspaceState = {
  strategy: null,
  selection: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31' },
  settings: DEFAULT_SETTINGS,
  linkSides: true,
  running: false,
  runError: null,
  lastRun: null,
  optimization: {},
  selectedConfigs: { long: null, short: null },
};

const SIDE_KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

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

export function reducer(state: WorkspaceState, action: Action): WorkspaceState {
  switch (action.type) {
    case 'SET_STRATEGY':
      return { ...state, strategy: action.strategy };
    case 'SET_SELECTION':
      return { ...state, selection: { ...state.selection, ...action.selection } };
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
        selection: selectionOf(action.run, state.selection),
      };
    case 'JOB_UPDATED':
      return { ...state, optimization: { ...state.optimization, [action.side]: action.job } };
    case 'SELECT_CONFIG':
      return { ...state, selectedConfigs: { ...state.selectedConfigs, [action.side]: action.params } };
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
