import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import type { StrategySpec } from '../contracts';

export const TIMEFRAMES = ['1m', '15m', '30m', '1h', '1D'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export type Side = 'long' | 'short';

export interface Selection {
  symbol: string;
  timeframe: Timeframe;
  start: string; // YYYY-MM-DD, America/New_York, inclusive
  end: string;
}

/** A persisted backtest envelope as returned by POST /aegis/api/backtest (typed loosely until Task 8). */
export interface RunRecord {
  run_id: string;
  created_at?: string;
  elapsed_ms?: number;
  result_hash: string;
  [key: string]: unknown;
}

export interface JobRecord {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'cancelled' | 'failed' | 'lost';
  progress: { done: number; total: number };
  [key: string]: unknown;
}

export interface WorkspaceState {
  strategy: StrategySpec | null;
  selection: Selection;
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
  | { type: 'RUN_STARTED' }
  | { type: 'RUN_COMPLETED'; run: RunRecord }
  | { type: 'RUN_FAILED'; error: string }
  | { type: 'JOB_UPDATED'; side: Side; job: JobRecord }
  | { type: 'SELECT_CONFIG'; side: Side; params: Record<string, number> | null };

export const initialState: WorkspaceState = {
  strategy: null,
  selection: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31' },
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
    case 'RUN_STARTED':
      return { ...state, running: true, runError: null };
    case 'RUN_COMPLETED':
      return { ...state, running: false, runError: null, lastRun: action.run };
    case 'RUN_FAILED':
      return { ...state, running: false, runError: action.error };
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
