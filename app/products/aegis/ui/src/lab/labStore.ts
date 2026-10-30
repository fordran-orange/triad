// The Optimization Lab's own state: one pure reducer, nothing React. A later task wraps it in a context.

/** What the Lab is looking at: an experiment (`exp:<id>`) or an optimization job (`opt:<id>`). */
export type LabSource = { kind: 'exp' | 'opt'; id: string };

export function parseSource(text: string): LabSource | null {
  for (const kind of ['exp', 'opt'] as const) {
    const prefix = `${kind}:`;
    if (text.startsWith(prefix) && text.length > prefix.length) return { kind, id: text.slice(prefix.length) };
  }
  return null;
}

export function sourceText(source: LabSource): string {
  return `${source.kind}:${source.id}`;
}

export type LabView = 'monitor' | 'trials' | 'families' | 'variables' | 'walkforward' | 'lineage' | 'compare';
/** The analysis tab of the trials view's centre panel. It lives in the store (Phase 3), so any view can open another
 *  and a trip to another sub-view and back finds the tab where it was left. */
export type LabTab = 'heatmap' | 'interactions' | 'parallel' | 'pareto' | 'importance' | 'robustness';
export type LabScope = 'combined' | 'long' | 'short';
export type LabMode = 'exact' | 'aggregate';
export type LabStat = 'best' | 'median' | 'mean' | 'worst';

/** The trials the Lab shows: a [lo, hi] range or one fixed value per parameter path, a side scope,
 *  and the pass and status chips. */
export interface LabFilter {
  ranges: Record<string, [number, number]>;
  values: Record<string, number>;
  scope: LabScope;
  pass: string[];
  status: string[];
}

/** A heatmap square: its column (x) and row (y), the two axis paths ([rows, columns]) and its two values ([row value,
 *  column value]) — the filter that defines it (`squareFilter`). A click and Enter send all four alike
 *  (`selectSquareAction`). */
export type SquareSelection = { x: number; y: number; axes: [string, string]; values: [number, number] };
export type LabSelection = { trials: string[] } | { square: SquareSelection } | null;
export type PinSlot = 'A' | 'B' | 'C';

export interface LabState {
  source: LabSource | null;
  sourceError: string | null;
  view: LabView;
  tab: LabTab;
  filter: LabFilter;
  axes: [string, string] | null;
  mode: LabMode;
  stat: LabStat;
  metric: string;
  objectives: string[];
  selected: LabSelection;
  pins: Partial<Record<PinSlot, string>>;
  cursor: { r: number; c: number } | null;
  maximized: boolean;
}

export type LabAction =
  | { type: 'OPEN_SOURCE'; source: LabSource; axes?: [string, string]; metric?: string }
  | { type: 'SOURCE_FAILED'; message: string }
  | { type: 'SET_VIEW'; view: LabView }
  | { type: 'SET_TAB'; tab: LabTab }
  | { type: 'SET_AXES'; axes: [string, string] }
  | { type: 'SET_MODE'; mode: LabMode }
  | { type: 'SET_STAT'; stat: LabStat }
  | { type: 'SET_METRIC'; metric: string }
  | { type: 'SET_SCOPE'; scope: LabScope }
  | { type: 'SET_RANGE'; path: string; range: [number, number] | null }
  | { type: 'FIX_VALUE'; path: string; value: number | null }
  | { type: 'SELECT_TRIALS'; ids: string[] }
  | { type: 'SELECT_SQUARE'; x: number; y: number; axes: [string, string]; values: [number, number] }
  | { type: 'CLEAR_SELECTION' }
  | { type: 'PIN'; slot: PinSlot; trialId: string }
  | { type: 'UNPIN'; slot: PinSlot }
  | { type: 'MOVE_CURSOR'; dr: number; dc: number; rows: number; cols: number }
  | { type: 'ESCAPE' }
  | { type: 'SET_MAXIMIZED'; maximized: boolean }
  | { type: 'ROWS_REFRESHED' };

const PIN_SLOTS: PinSlot[] = ['A', 'B', 'C'];

function emptyFilter(): LabFilter {
  return { ranges: {}, values: {}, scope: 'combined', pass: [], status: [] };
}

export const initialLabState: LabState = {
  source: null,
  sourceError: null,
  view: 'trials',
  tab: 'heatmap',
  filter: emptyFilter(),
  axes: null,
  mode: 'exact',
  stat: 'best',
  metric: 'net_pnl',
  objectives: ['net_pnl', 'max_drawdown'],
  selected: null,
  pins: {},
  cursor: null,
  maximized: false,
};

/** A record without one key (the reducer never leaves an `undefined` entry behind). */
function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const { [key]: _removed, ...rest } = record;
  return rest;
}

function clamp(value: number, size: number): number {
  return Math.min(Math.max(value, 0), Math.max(size - 1, 0));
}

export function labReducer(state: LabState, action: LabAction): LabState {
  switch (action.type) {
    case 'OPEN_SOURCE':
      return {
        ...state,
        source: action.source,
        sourceError: null,
        filter: emptyFilter(),
        selected: null,
        pins: {},
        cursor: null,
        axes: action.axes ?? state.axes,
        metric: action.metric ?? state.metric,
      };
    case 'SOURCE_FAILED':
      return { ...state, source: null, sourceError: action.message };
    case 'SET_VIEW':
      return { ...state, view: action.view };
    case 'SET_TAB':
      return { ...state, tab: action.tab }; // the filter, the selection and the pins are the Lab's, not the tab's
    case 'SET_AXES':
      return { ...state, axes: action.axes };
    case 'SET_MODE':
      return { ...state, mode: action.mode };
    case 'SET_STAT':
      return { ...state, stat: action.stat };
    case 'SET_METRIC':
      return { ...state, metric: action.metric };
    case 'SET_SCOPE':
      return { ...state, filter: { ...state.filter, scope: action.scope } };
    case 'SET_RANGE': {
      if (action.range === null) return { ...state, filter: { ...state.filter, ranges: without(state.filter.ranges, action.path) } };
      const [a, b] = action.range;
      return { ...state, filter: { ...state.filter, ranges: { ...state.filter.ranges, [action.path]: [Math.min(a, b), Math.max(a, b)] } } };
    }
    case 'FIX_VALUE': {
      if (action.value === null) return { ...state, filter: { ...state.filter, values: without(state.filter.values, action.path) } };
      return { ...state, filter: { ...state.filter, values: { ...state.filter.values, [action.path]: action.value } } };
    }
    case 'SELECT_TRIALS':
      return { ...state, selected: action.ids.length > 0 ? { trials: action.ids } : null }; // an empty selection is no selection
    case 'SELECT_SQUARE': {
      const square: SquareSelection = { x: action.x, y: action.y, axes: action.axes, values: action.values };
      return { ...state, selected: { square } };
    }
    case 'CLEAR_SELECTION':
      return { ...state, selected: null };
    case 'PIN': {
      if (state.selected !== null && 'square' in state.selected) return state; // a square is not a trial
      if (state.pins[action.slot] === action.trialId) return state;
      // An id sits in at most one slot: pinning it elsewhere moves it.
      const pins: Partial<Record<PinSlot, string>> = {};
      for (const slot of PIN_SLOTS) {
        const held = state.pins[slot];
        if (held !== undefined && held !== action.trialId) pins[slot] = held;
      }
      pins[action.slot] = action.trialId;
      return { ...state, pins };
    }
    case 'UNPIN': {
      if (state.pins[action.slot] === undefined) return state;
      const { [action.slot]: _removed, ...pins } = state.pins;
      return { ...state, pins };
    }
    case 'MOVE_CURSOR': {
      // An empty grid has no square to stand on: the key press changes nothing.
      if (action.rows <= 0 || action.cols <= 0) return state;
      // The first key press only makes the cursor appear at (0, 0); later presses move it.
      if (state.cursor === null) return { ...state, cursor: { r: 0, c: 0 } };
      return { ...state, cursor: { r: clamp(state.cursor.r + action.dr, action.rows), c: clamp(state.cursor.c + action.dc, action.cols) } };
    }
    case 'ESCAPE': {
      if (Object.keys(state.filter.ranges).length > 0 || Object.keys(state.filter.values).length > 0) {
        return { ...state, filter: { ...state.filter, ranges: {}, values: {} } };
      }
      if (state.maximized) return { ...state, maximized: false };
      return state;
    }
    case 'SET_MAXIMIZED':
      return { ...state, maximized: action.maximized };
    case 'ROWS_REFRESHED':
      return state; // the table marks a refresh; the selection and the pins stay as they are
    default:
      return state;
  }
}

/** The filter as one stable string: keys sorted at every level, each range as [lo, hi], pass and
 *  status sorted. Two filters that select the same trials give the same text. */
export function canonicalFilter(filter: LabFilter): string {
  const sorted = <T>(record: Record<string, T>, value: (v: T) => unknown = (v) => v): Record<string, unknown> =>
    Object.fromEntries(Object.keys(record).sort().map((key) => [key, value(record[key] as T)]));
  return JSON.stringify({
    pass: [...filter.pass].sort(),
    ranges: sorted(filter.ranges, ([a, b]) => [Math.min(a, b), Math.max(a, b)]),
    scope: filter.scope,
    status: [...filter.status].sort(),
    values: sorted(filter.values),
  });
}

/** FNV-1a 32-bit over the UTF-16 code units of the canonical filter, as 8 lowercase hex characters. */
export function filterHash(filter: LabFilter): string {
  const text = canonicalFilter(filter);
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

/** The index of the cell whose parameters are exactly `wanted` (the same keys, the same numbers), or -1. The dock's
 *  Expand Lab hands over its selected configuration this way; the Lab selects the job's matching trial. */
export function cellIndex(cells: ReadonlyArray<{ params: Record<string, number | null> }>, wanted: Record<string, number>): number {
  const keys = Object.keys(wanted);
  return cells.findIndex(
    (cell) => Object.keys(cell.params).length === keys.length && keys.every((key) => key in cell.params && cell.params[key] === wanted[key]),
  );
}

/** How many constraints the filter holds: ranges, fixed values, a side scope, pass and status chips. */
export function activeFilterCount(filter: LabFilter): number {
  return Object.keys(filter.ranges).length + Object.keys(filter.values).length + (filter.scope !== 'combined' ? 1 : 0) + filter.pass.length + filter.status.length;
}
