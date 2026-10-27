import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import type { SymbolInfo } from '../api/client';
import { graphFromSide, readsAs, type Canvas, type SideGraph } from '../builder/graph';
import { INDICATOR_KINDS, type IndicatorSpec, type OptimizationParameter, type StrategyDocument, type StrategySide, type StrategySpec, type WindowMode } from '../contracts';
import { ruleReferences, type Rule } from '../rules';
import { DASH } from '../format';
import type { JobStatus, LibraryKind, Provenance, RunEnvelope, WalkForwardStatus } from '../results';

export const TIMEFRAMES = ['1m', '15m', '30m', '1h', '1D'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export type Side = 'long' | 'short';
export const SIDES: Side[] = ['long', 'short'];
export const SIDE_KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

export type Page = 'charts' | 'lab' | 'library' | 'experiments' | 'optlab';

/** What the compact dock hands the Optimization Lab: the result to open, and optionally the two
 *  axes, the metric to look at and the selected configuration (its parameters by path, as the
 *  job's cells carry them). `source` is `exp:<experiment_id>` or `opt:<job_id>`. */
export interface LabFocus {
  source: string;
  axes?: [string, string];
  metric?: string;
  selected?: Record<string, number>;
}

/** A deep link the target page consumes once (Mission 9 plan ruling P10). */
export interface Focus {
  experimentId?: string;
  studyId?: string;
  libraryKind?: LibraryKind;
  libraryId?: string;
  lab?: LabFocus;
}

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
/** A side's pick in the Optimization tab: a cell's parameters, 'none' (turn the side off), or
 *  null (leave the side as it is). */
export type SideSelection = Record<string, number> | 'none' | null;
export type SelectedConfigs = { long: SideSelection; short: SideSelection };

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
  rightTab: 'strategy' | 'indicators';
  page: Page;
  focus: Focus | null;
  document: StrategyDocument | null; // the saved document the workspace strategy came from
  latest: { key: string; values: Record<string, number | null> }; // last value per drawn series, for the chartKey it was fetched under
  // Mission 13: the builder's graph per side as last set, and the side it was drawn for
  // (canonical); `sideGraph` lays a side out afresh when the strategy has moved on.
  canvas: Partial<Record<Side, SideGraph>>;
  canvasBase: Partial<Record<Side, string>>;
  canvasEdited: boolean;
  builderSide: Side;
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
  | { type: 'RUN_KEPT'; run_id: string }
  | { type: 'JOB_UPDATED'; side: Side; job: JobStatus }
  | { type: 'JOB_LOST'; side: Side; job_id: string }
  | { type: 'WALKFORWARD_UPDATED'; side: Side; job: WalkForwardStatus }
  | { type: 'WALKFORWARD_LOST'; side: Side; job_id: string }
  | { type: 'SELECT_CONFIG'; side: Side; params: SideSelection }
  | { type: 'SET_FOCUS_SIDE'; side: Side }
  | { type: 'SET_LATEST'; key: string; values: Record<string, number | null> }
  | { type: 'SET_RIGHT_TAB'; tab: 'strategy' | 'indicators' }
  | { type: 'ADD_INDICATOR'; side: Side; kind: string }
  | { type: 'REMOVE_INDICATOR'; side: Side; id: string }
  | { type: 'SET_RULE'; side: Side; which: 'entry' | 'exit'; rule: Rule }
  | { type: 'SET_PAGE'; page: Page; focus?: Focus | null }
  | { type: 'CLEAR_FOCUS' }
  | { type: 'SET_DOCUMENT'; document: StrategyDocument }
  | { type: 'ADOPT_DOCUMENT'; document: StrategyDocument | null }
  | { type: 'DOCUMENT_RENAMED'; document: StrategyDocument }
  | { type: 'SET_SIDE_GRAPH'; side: Side; graph: SideGraph; spec: StrategySide | null }
  | { type: 'SET_BUILDER_SIDE'; side: Side };

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
  rightTab: 'strategy',
  page: 'charts',
  focus: null,
  document: null,
  latest: { key: '', values: {} },
  canvas: {},
  canvasBase: {},
  canvasEdited: false,
  builderSide: 'long',
};

/** What the chart fetched for: the selection and the focused side's indicators. */
export function chartKey(state: Pick<WorkspaceState, 'selection' | 'strategy' | 'focusSide'>): string {
  const s = state.selection;
  const indicators = state.strategy ? (state.strategy[SIDE_KEY[state.focusSide]].indicators ?? []) : [];
  return JSON.stringify([s.symbol, s.timeframe, s.start, s.end, indicators.map((i) => [i.id, i.kind, i.length, i.source ?? 'close', i.params ?? {}])]);
}

/** Latest values only while they describe what is selected and configured now (review finding #6). */
export function currentLatest(state: Pick<WorkspaceState, 'selection' | 'strategy' | 'focusSide' | 'latest'>): Record<string, number | null> {
  return state.latest.key === chartKey(state) ? state.latest.values : {};
}

/** The workspace strategy differs from the loaded document's saved spec (plan ruling P2). */
export function unsavedEdits(state: Pick<WorkspaceState, 'document' | 'strategy'> & { canvasEdited?: boolean }): boolean {
  return state.document !== null && state.strategy !== null && (canonical(state.document.spec) !== canonical(state.strategy) || !!state.canvasEdited);
}

/** A fresh layout that keeps the place of every block the old graph also had (same id, type). */
function keepPositions(fresh: SideGraph, old: SideGraph): SideGraph {
  const placed = new Map(old.blocks.map((b) => [`${b.type}:${b.id}`, b]));
  return { ...fresh, blocks: fresh.blocks.map((b) => {
    const was = placed.get(`${b.type}:${b.id}`);
    return was ? { ...b, x: was.x, y: was.y } : b;
  }) };
}

/** The graph the builder shows for a side (Mission 13): the one last set while the strategy is
 * still the one it was drawn for or still reads as it; otherwise the side laid out afresh. */
export function sideGraph(state: Pick<WorkspaceState, 'strategy' | 'canvas' | 'canvasBase'>, side: Side): SideGraph {
  const spec = state.strategy![SIDE_KEY[side]];
  const saved = state.canvas[side];
  if (!saved) return graphFromSide(spec);
  if (state.canvasBase[side] === canonical(spec) || readsAs(saved, spec)) return saved;
  return keepPositions(graphFromSide(spec), saved);
}

/** Both sides' graphs, as a document saves them. */
export function currentCanvas(state: Pick<WorkspaceState, 'strategy' | 'canvas' | 'canvasBase'>): Canvas {
  return { version: 1, long: sideGraph(state, 'long'), short: sideGraph(state, 'short') };
}

function savedCanvas(document: StrategyDocument): Partial<Record<Side, SideGraph>> {
  const canvas = document.canvas as Partial<Canvas> | null | undefined;
  if (!canvas || canvas.version !== 1) return {};
  return { ...(canvas.long ? { long: canvas.long } : {}), ...(canvas.short ? { short: canvas.short } : {}) };
}

/** A new indicator of `kind` with an id unique on the side, its default length, no parameters. */
export function newIndicator(kind: string, taken: string[]): IndicatorSpec {
  const name = kind.toUpperCase();
  const base = kind.toLowerCase();
  let id = base;
  for (let n = 2; taken.includes(id); n++) id = `${base}_${n}`;
  return { id, kind: name, length: INDICATOR_KINDS[name]?.default_length ?? 14, source: 'close', overlay: true };
}

/** Plan ruling P14: disabled ranges for a new indicator's length and parameters. */
export function defaultRanges(spec: IndicatorSpec): OptimizationParameter[] {
  const info = INDICATOR_KINDS[spec.kind.toUpperCase()];
  const L = spec.length;
  const ranges: OptimizationParameter[] = [
    { path: `indicators.${spec.id}.length`, enabled: false, start: Math.max(2, Math.floor(L / 2)), stop: 2 * L, step: Math.max(1, Math.round(L / 10)) },
  ];
  for (const [name, value] of Object.entries(info?.params ?? {})) {
    const whole = info.integer_params.includes(name);
    ranges.push({
      path: `indicators.${spec.id}.params.${name}`,
      enabled: false,
      start: whole ? Math.round(value / 2) : value / 2,
      stop: whole ? Math.round(value * 2) : value * 2,
      step: whole ? Math.max(1, Math.round(value / 4)) : value / 4,
    });
  }
  return ranges;
}

/**
 * Set a side-relative path such as `indicators.ema.length`: the second segment of an
 * `indicators` path is an indicator id, resolved by `id`, not an array index. Returns a new object.
 */
export function setPath<T>(target: T, path: string, value: unknown): T {
  const [head, ...rest] = path.split('.');
  if (head === undefined) return target;
  const source = (target ?? {}) as unknown as Record<string, unknown>; // e.g. params not set yet
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
/** Write each side's pick into the strategy. 'none' turns the side off; with `enablePicked` (the
 *  Optimization tab's Apply) a picked cell also turns its side on; null leaves the side alone. */
export function applyConfigs(strategy: StrategySpec, configs: SelectedConfigs, options: { enablePicked?: boolean } = {}): StrategySpec {
  let next = strategy;
  for (const side of SIDES) {
    const params = configs[side];
    if (!params) continue;
    const key = SIDE_KEY[side];
    if (params === 'none') {
      next = { ...next, [key]: { ...next[key], enabled: false } };
      continue;
    }
    let spec = next[key];
    for (const [path, value] of Object.entries(params)) spec = setPath(spec, path, value);
    if (options.enablePicked) spec = { ...spec, enabled: true };
    next = { ...next, [key]: spec };
  }
  return next;
}

/** How a side's pick reads on the "Selected:" line. */
export function selectionText(selection: SideSelection, describe: (params: Record<string, number>) => string): string {
  if (selection === 'none') return 'none (side off)';
  return selection ? describe(selection) : DASH;
}

function isTimeframe(value: unknown): value is Timeframe {
  return typeof value === 'string' && (TIMEFRAMES as readonly string[]).includes(value);
}

/** The selection a persisted run was made against, when its pinned source carries one. */
export function selectionOf(run: RunRecord, fallback: Selection): Selection {
  return selectionFromData(run.data, fallback);
}

/** The selection a saved result ran on, or the fallback when its data names none. */
export function selectionFromData<F extends Selection | null>(d: Provenance | undefined | null, fallback: F): Selection | F {
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
    case 'RUN_KEPT':
      return state.lastRun?.run_id === action.run_id ? { ...state, lastRun: { ...state.lastRun, saved: true } } : state;
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
    case 'SET_RIGHT_TAB':
      return { ...state, rightTab: action.tab };
    case 'SET_PAGE':
      return { ...state, page: action.page, focus: action.focus ?? null };
    case 'CLEAR_FOCUS':
      return { ...state, focus: null };
    case 'SET_DOCUMENT':
      return { ...state, document: action.document, strategy: action.document.spec, canvas: savedCanvas(action.document), canvasBase: {}, canvasEdited: false };
    case 'SET_SIDE_GRAPH': {
      if (!state.strategy) return state;
      const key = SIDE_KEY[action.side];
      const strategy = action.spec ? { ...state.strategy, [key]: action.spec } : state.strategy;
      return {
        ...state,
        strategy,
        canvas: { ...state.canvas, [action.side]: action.graph },
        canvasBase: { ...state.canvasBase, [action.side]: canonical(strategy[key]) },
        canvasEdited: true,
      };
    }
    case 'SET_BUILDER_SIDE':
      return { ...state, builderSide: action.side };
    case 'ADOPT_DOCUMENT':
      return { ...state, document: action.document };
    case 'DOCUMENT_RENAMED': {
      // A rename changes the spec's name too; carry it into the workspace strategy so the header
      // does not report edits nobody made (review finding #5). Other edits stay as they are.
      const renamed = action.document;
      return {
        ...state,
        document: state.document?.id === renamed.id ? renamed : state.document,
        strategy: state.strategy && state.strategy.id === renamed.id ? { ...state.strategy, name: renamed.spec.name } : state.strategy,
      };
    }
    case 'ADD_INDICATOR': {
      if (!state.strategy) return state;
      const key = SIDE_KEY[action.side];
      const side = state.strategy[key];
      const spec = newIndicator(action.kind, (side.indicators ?? []).map((i) => i.id));
      const next = { ...side, indicators: [...(side.indicators ?? []), spec], optimization: [...(side.optimization ?? []), ...defaultRanges(spec)] };
      return { ...state, strategy: { ...state.strategy, [key]: next } };
    }
    case 'REMOVE_INDICATOR': {
      if (!state.strategy) return state;
      const key = SIDE_KEY[action.side];
      const side = state.strategy[key];
      if (ruleReferences(side, action.id).length > 0) return state; // the panel names the rule
      const prefix = `indicators.${action.id}.`;
      const next = {
        ...side,
        indicators: (side.indicators ?? []).filter((i) => i.id !== action.id),
        optimization: (side.optimization ?? []).filter((r) => !r.path.startsWith(prefix)),
      };
      return { ...state, strategy: { ...state.strategy, [key]: next } };
    }
    case 'SET_RULE': {
      if (!state.strategy) return state;
      const key = SIDE_KEY[action.side];
      return { ...state, strategy: { ...state.strategy, [key]: { ...state.strategy[key], [action.which]: action.rule } } };
    }
    case 'SET_LATEST':
      return { ...state, latest: { key: action.key, values: action.values } };
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
