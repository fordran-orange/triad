import { describe, expect, it } from 'vitest';
import type { StrategySpec } from '../contracts';
import { ruleReferences } from '../rules';
import { autoLayout, graphFromSide, readsAs } from '../builder/graph';
import { applyConfigs, canonical, chartKey, currentLatest, initialState, reducer, runStaleness, selectionText, sideGraph, unsavedEdits, type RunRecord, type WorkspaceState } from './workspace';

// Side-owned indicator parameters (the shape Task 3 makes canonical); typed loosely until then.
function strategy(): StrategySpec {
  const side = (direction: 'long' | 'short') => ({
    direction,
    enabled: true,
    indicators: [
      { id: 'ema', kind: 'EMA', length: 9, source: 'close', overlay: true },
      { id: 'sma', kind: 'SMA', length: 30, source: 'close', overlay: true },
    ],
    entry: { left: 'ema', operator: direction === 'long' ? 'crosses_above' : 'crosses_below', right: 'sma', timing: 'bar_close' },
    exit: { left: 'ema', operator: direction === 'long' ? 'crosses_below' : 'crosses_above', right: 'sma', timing: 'bar_close' },
    optimization: [],
  });
  return {
    id: 'ema9-sma30-cross-v1',
    name: '9 EMA / 30 SMA Cross',
    version: 1,
    description: 'test',
    long_side: side('long'),
    short_side: side('short'),
    temporal: { timezone: 'America/New_York', regular_session_only: true, clock_windows: [], event_windows: [], market_crossovers: [] },
    execution: { signal_timing: 'bar_close', fill_timing: 'next_bar_open', commission_per_side: 0, slippage_bps: 0 },
  } as unknown as StrategySpec;
}

function withStrategy(): WorkspaceState {
  return reducer(initialState, { type: 'SET_STRATEGY', strategy: strategy() });
}

const emaLength = (state: WorkspaceState, side: 'long_side' | 'short_side') =>
  (state.strategy as unknown as { [k: string]: { indicators: { id: string; length: number }[] } })[side].indicators[0].length;

describe('workspace reducer', () => {
  it('linked param change mirrors to the other side', () => {
    let state = withStrategy();
    state = reducer(state, { type: 'SET_LINK_SIDES', linked: true });
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.ema.length', value: 12 });
    expect(emaLength(state, 'long_side')).toBe(12);
    expect(emaLength(state, 'short_side')).toBe(12);
  });

  it('unlinked change affects one side only', () => {
    let state = withStrategy();
    state = reducer(state, { type: 'SET_LINK_SIDES', linked: false });
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'short', path: 'indicators.sma.length', value: 52 });
    expect(emaLength(state, 'long_side')).toBe(9);
    const short = (state.strategy as unknown as { short_side: { indicators: { id: string; length: number }[] } }).short_side;
    expect(short.indicators[1].length).toBe(52);
    expect(state.strategy).not.toBe(initialState.strategy);
  });

  it('RUN_COMPLETED stores run and clears error', () => {
    let state = reducer(withStrategy(), { type: 'RUN_FAILED', error: 'boom' });
    expect(state.runError).toBe('boom');
    const run = { run_id: 'r1', result_hash: 'abc' } as RunRecord;
    state = reducer(state, { type: 'RUN_COMPLETED', run });
    expect(state.lastRun).toBe(run);
    expect(state.runError).toBeNull();
    expect(state.running).toBe(false);
  });

  it('RUN_KEPT marks the shown run saved and leaves another run alone (Mission 10)', () => {
    const run = { run_id: 'r1', result_hash: 'abc', saved: false } as RunRecord;
    let state = reducer(withStrategy(), { type: 'RUN_COMPLETED', run });
    state = reducer(state, { type: 'RUN_KEPT', run_id: 'other' });
    expect(state.lastRun?.saved).toBe(false);
    state = reducer(state, { type: 'RUN_KEPT', run_id: 'r1' });
    expect(state.lastRun?.saved).toBe(true);
    expect(state.lastRun?.result_hash).toBe('abc');
  });

  it('SET_SELECTION keeps the five timeframes and defaults to QQQ 1h', () => {
    expect(initialState.selection.symbol).toBe('QQQ');
    expect(initialState.selection.timeframe).toBe('1h');
    const next = reducer(initialState, { type: 'SET_SELECTION', selection: { timeframe: '1m' } });
    expect(next.selection.timeframe).toBe('1m');
    expect(next.selection.symbol).toBe('QQQ');
  });

  it('SET_WINDOW_MODE changes one clock window and refuses modify_risk', () => {
    const base = strategy();
    const windows = [
      { id: 'open', label: 'Opening', start: '09:30', end: '10:00', mode: 'analyze' as const },
      { id: 'close', label: 'Closing', start: '15:30', end: '16:00', mode: 'analyze' as const },
    ];
    let state = reducer(initialState, { type: 'SET_STRATEGY', strategy: { ...base, temporal: { ...base.temporal, clock_windows: windows } } });
    state = reducer(state, { type: 'SET_WINDOW_MODE', id: 'open', mode: 'block' });
    expect(state.strategy!.temporal.clock_windows.map((w) => w.mode)).toEqual(['block', 'analyze']);
    state = reducer(state, { type: 'SET_WINDOW_MODE', id: 'open', mode: 'modify_risk' });
    expect(state.strategy!.temporal.clock_windows[0].mode).toBe('block');
  });

  it('SET_EXECUTION and SET_SETTINGS update the numbers a run posts', () => {
    let state = reducer(withStrategy(), { type: 'SET_EXECUTION', field: 'commission_per_side', value: 1.5 });
    expect(state.strategy!.execution.commission_per_side).toBe(1.5);
    state = reducer(state, { type: 'SET_SETTINGS', settings: { initial_capital: 50_000 } });
    expect(state.settings).toEqual({ initial_capital: 50_000, allocation_fraction: 1 });
  });

  it('LOAD_RUN restores selection, strategy and the run, keeping its state', () => {
    const loaded = strategy();
    const run = {
      run_id: 'r2',
      result_hash: 'def',
      state: 'source_unavailable',
      state_detail: 'pinned archive sha256 mismatch',
      strategy: loaded,
      data: { symbol: 'SPY', timeframe: '15m', start: '2024-01-02', end: '2024-03-01' },
    } as unknown as RunRecord;
    const state = reducer(reducer(initialState, { type: 'RUN_STARTED' }), { type: 'LOAD_RUN', run });
    expect(state.selection).toEqual({ symbol: 'SPY', timeframe: '15m', start: '2024-01-02', end: '2024-03-01' });
    expect(state.strategy).toBe(loaded);
    expect(state.lastRun?.state).toBe('source_unavailable');
    expect(state.running).toBe(false);
    expect(state.runError).toBeNull();
  });

  it('applyConfigs: None turns a side off; a picked cell sets it and turns it on (operator, 2026-10-15)', () => {
    const base = strategy();
    const shortOff = { ...base, short_side: { ...base.short_side, enabled: false } };
    const applied = applyConfigs(shortOff, { long: 'none', short: { 'indicators.ema.length': 6 } }, { enablePicked: true });
    expect(applied.long_side.enabled).toBe(false);
    expect(applied.long_side.indicators).toEqual(base.long_side.indicators);
    expect(applied.short_side.enabled).toBe(true);
    expect(applied.short_side.indicators!.map((i) => i.length)).toEqual([6, 30]);
    expect(applyConfigs(base, { long: null, short: 'none' }).long_side).toEqual(base.long_side);
    // Without the option (the walk-forward tab's Apply) a picked cell leaves a side's switch alone.
    expect(applyConfigs(shortOff, { long: null, short: { 'indicators.ema.length': 6 } }).short_side.enabled).toBe(false);
  });

  it('SELECT_CONFIG accepts None for one side and leaves the other', () => {
    const none = reducer(initialState, { type: 'SELECT_CONFIG', side: 'short', params: 'none' });
    expect(none.selectedConfigs).toEqual({ long: null, short: 'none' });
    const back = reducer(none, { type: 'SELECT_CONFIG', side: 'short', params: null });
    expect(back.selectedConfigs).toEqual({ long: null, short: null });
  });

  it('selectionText names None as the side being off', () => {
    expect(selectionText('none', () => 'x')).toBe('none (side off)');
    expect(selectionText(null, () => 'x')).toBe('—');
    expect(selectionText({ 'indicators.ema.length': 11 }, (p) => `EMA ${p['indicators.ema.length']}`)).toBe('EMA 11');
  });

  it('applyConfigs sets each side from its selected configuration independently', () => {
    const applied = applyConfigs(strategy(), { long: { 'indicators.ema.length': 11, 'indicators.sma.length': 35 }, short: { 'indicators.ema.length': 6 } });
    const lengths = (s: StrategySpec, side: 'long_side' | 'short_side') => s[side].indicators!.map((i) => i.length);
    expect(lengths(applied, 'long_side')).toEqual([11, 35]);
    expect(lengths(applied, 'short_side')).toEqual([6, 30]);
    expect(applyConfigs(strategy(), { long: null, short: null })).toEqual(strategy());
  });

  it('SET_RANGE edits one optimization range of one side', () => {
    const base = strategy();
    const range = { path: 'indicators.ema.length', enabled: true, start: 5, stop: 20, step: 1 };
    const withRanges = { ...base, long_side: { ...base.long_side, optimization: [range] }, short_side: { ...base.short_side, optimization: [{ ...range }] } };
    let state = reducer(initialState, { type: 'SET_STRATEGY', strategy: withRanges });
    state = reducer(state, { type: 'SET_RANGE', side: 'short', path: 'indicators.ema.length', field: 'stop', value: 12 });
    expect(state.strategy!.short_side.optimization![0].stop).toBe(12);
    expect(state.strategy!.long_side.optimization![0].stop).toBe(20);
  });

  it('BARS_LOADED and SET_RESULTS_TAB keep view state the optimizer needs', () => {
    let state = reducer(initialState, { type: 'BARS_LOADED', bars: { count: 3493, vintage: 'v1' } });
    expect(state.loadedBars).toEqual({ count: 3493, vintage: 'v1' });
    state = reducer(state, { type: 'SET_RESULTS_TAB', tab: 'optimization' });
    expect(state.resultsTab).toBe('optimization');
  });

  it('runStaleness is clean right after a run and names what changed afterwards', () => {
    const spec = strategy();
    let state = reducer(initialState, { type: 'SET_STRATEGY', strategy: spec });
    const run = {
      run_id: 'r3',
      result_hash: 'ghi',
      state: 'ok',
      strategy: spec,
      settings: { initial_capital: 100_000, allocation_fraction: 1 },
      data: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31', vintage: 'v1' },
    } as unknown as RunRecord;
    state = reducer(state, { type: 'RUN_COMPLETED', run });
    expect(runStaleness(state)).toEqual({ selection: false, strategy: false, settings: false, any: false });
    const moved = reducer(state, { type: 'SET_SELECTION', selection: { symbol: 'SPY' } });
    expect(runStaleness(moved)).toMatchObject({ selection: true, strategy: false, any: true });
    const edited = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.ema.length', value: 12 });
    expect(runStaleness(edited)).toMatchObject({ selection: false, strategy: true, any: true });
    const funded = reducer(state, { type: 'SET_SETTINGS', settings: { initial_capital: 50_000 } });
    expect(runStaleness(funded)).toMatchObject({ settings: true, any: true });
    expect(runStaleness(initialState).any).toBe(false); // no run: nothing can be stale
  });

  it('LOAD_RUN restores the settings the run was computed with', () => {
    const run = {
      run_id: 'r4',
      result_hash: 'jkl',
      state: 'ok',
      strategy: strategy(),
      settings: { initial_capital: 50_000, allocation_fraction: 0.5 },
      data: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31' },
    } as unknown as RunRecord;
    const state = reducer(initialState, { type: 'LOAD_RUN', run });
    expect(state.settings).toEqual({ initial_capital: 50_000, allocation_fraction: 0.5 });
    expect(runStaleness(state).any).toBe(false);
  });

  it('JOB_LOST marks a polled job lost and SET_SYMBOLS stores the archive menu', () => {
    const job = { job_id: 'j1', status: 'running', side: 'long', progress: { done: 3, total: 9 } } as unknown as import('../results').JobStatus;
    let state = reducer(initialState, { type: 'JOB_UPDATED', side: 'long', job });
    state = reducer(state, { type: 'JOB_LOST', side: 'long', job_id: 'j1' });
    expect(state.optimization.long?.status).toBe('lost');
    expect(reducer(state, { type: 'JOB_LOST', side: 'long', job_id: 'other' }).optimization.long?.status).toBe('lost');
    const symbols = [{ symbol: 'QQQ', vintage: 'v1' }] as unknown as import('../api/client').SymbolInfo[];
    expect(reducer(state, { type: 'SET_SYMBOLS', symbols }).symbols).toEqual(symbols);
  });

  it('WALKFORWARD_UPDATED and WALKFORWARD_LOST track a walk-forward per side', () => {
    const job = { job_id: 'w1', kind: 'walkforward', status: 'running', side: 'long', progress: { done: 3, total: 65 }, windows: { done: 0, total: 13 } } as unknown as import('../results').WalkForwardStatus;
    let state = reducer(initialState, { type: 'WALKFORWARD_UPDATED', side: 'long', job });
    expect(state.walkforward.long?.windows.total).toBe(13);
    expect(state.walkforward.short).toBeUndefined();
    state = reducer(state, { type: 'WALKFORWARD_LOST', side: 'long', job_id: 'w1' });
    expect(state.walkforward.long?.status).toBe('lost');
    expect(reducer(state, { type: 'SET_RESULTS_TAB', tab: 'walkforward' }).resultsTab).toBe('walkforward');
  });
});

describe('chart focus and latest values', () => {
  it('starts on the long side with no values and follows the focus and fetched values', () => {
    expect(initialState.focusSide).toBe('long');
    expect(initialState.latest).toEqual({ key: '', values: {} });
    let state = reducer(initialState, { type: 'SET_FOCUS_SIDE', side: 'short' });
    expect(state.focusSide).toBe('short');
    state = reducer(state, { type: 'SET_LATEST', key: 'k', values: { rsi: 41.5, 'donchian.upper': null } });
    expect(state.latest).toEqual({ key: 'k', values: { rsi: 41.5, 'donchian.upper': null } });
  });
});

describe('indicator and rule editing', () => {
  const long = (state: WorkspaceState) => state.strategy!.long_side;
  const short = (state: WorkspaceState) => state.strategy!.short_side;

  it('adds an indicator with a unique id, its default length and disabled ranges', () => {
    let state = withStrategy();
    state = reducer(state, { type: 'ADD_INDICATOR', side: 'long', kind: 'RSI' });
    state = reducer(state, { type: 'ADD_INDICATOR', side: 'long', kind: 'RSI' });
    expect(long(state).indicators!.map((i) => i.id)).toEqual(['ema', 'sma', 'rsi', 'rsi_2']);
    expect(long(state).indicators![2]).toMatchObject({ kind: 'RSI', length: 14, source: 'close' });
    expect(long(state).optimization).toEqual([
      { path: 'indicators.rsi.length', enabled: false, start: 7, stop: 28, step: 1 },
      { path: 'indicators.rsi_2.length', enabled: false, start: 7, stop: 28, step: 1 },
    ]);
    expect(short(state).indicators!.map((i) => i.id)).toEqual(['ema', 'sma']); // P11: the focused side only
    state = reducer(state, { type: 'ADD_INDICATOR', side: 'long', kind: 'MACD' });
    expect(long(state).optimization!.slice(2).map((r) => [r.path, r.start, r.stop, r.step])).toEqual([
      ['indicators.macd.length', 6, 24, 1],
      ['indicators.macd.params.slow', 13, 52, 7],
      ['indicators.macd.params.signal', 5, 18, 2],
    ]);
  });

  it('refuses to remove an indicator a rule reads and drops an unreferenced one with its ranges', () => {
    let state = reducer(withStrategy(), { type: 'ADD_INDICATOR', side: 'long', kind: 'BB' });
    const refused = reducer(state, { type: 'REMOVE_INDICATOR', side: 'long', id: 'ema' });
    expect(refused).toBe(state);
    expect(ruleReferences(long(state), 'ema')).toEqual(['entry rule', 'exit rule']);
    state = reducer(state, { type: 'REMOVE_INDICATOR', side: 'long', id: 'bb' });
    expect(long(state).indicators!.map((i) => i.id)).toEqual(['ema', 'sma']);
    expect(long(state).optimization).toEqual([]);
  });

  it('mirrors a linked parameter edit only where the other side has that indicator', () => {
    let state = reducer(withStrategy(), { type: 'SET_LINK_SIDES', linked: true });
    state = reducer(state, { type: 'ADD_INDICATOR', side: 'long', kind: 'RSI' });
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.rsi.length', value: 21 });
    expect(long(state).indicators![2].length).toBe(21);
    expect(short(state).indicators!.map((i) => i.id)).toEqual(['ema', 'sma']);
    state = reducer(state, { type: 'ADD_INDICATOR', side: 'long', kind: 'BB' });
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.bb.params.multiplier', value: 2.5 });
    expect(long(state).indicators![3].params).toEqual({ multiplier: 2.5 });
  });

  it('refuses to remove an indicator a nested condition reads (Review Focus 5)', () => {
    let state = reducer(withStrategy(), { type: 'ADD_INDICATOR', side: 'long', kind: 'RSI' });
    const exit = {
      any_of: [
        { left: 'ema', operator: 'crosses_below', right: 'sma', timing: 'bar_close' },
        { all_of: [{ left: 'rsi', operator: 'greater_than', right: '70', timing: 'bar_close' }, { left: 'price.close', operator: 'less_than', right: 'sma', timing: 'bar_close' }] },
      ],
    };
    state = reducer(state, { type: 'SET_RULE', side: 'long', which: 'exit', rule: exit });
    expect(ruleReferences(long(state), 'rsi')).toEqual(['exit rule']);
    expect(reducer(state, { type: 'REMOVE_INDICATOR', side: 'long', id: 'rsi' })).toBe(state);
  });

  it('sets a rule or a two-condition group on one side', () => {
    const group = {
      all_of: [
        { left: 'price.close', operator: 'crosses_above', right: 'donchian.upper', timing: 'bar_close' },
        { left: 'rsi', operator: 'less_than', right: '70', timing: 'bar_close' },
      ],
    };
    const state = reducer(withStrategy(), { type: 'SET_RULE', side: 'long', which: 'entry', rule: group });
    expect(canonical(long(state).entry)).toBe(canonical(group));
    expect(short(state).entry).toEqual(withStrategy().strategy!.short_side.entry);
    expect(reducer(state, { type: 'SET_RIGHT_TAB', tab: 'indicators' }).rightTab).toBe('indicators');
  });
});

describe('strategy documents in the workspace', () => {
  const doc = (spec: StrategySpec) =>
    ({ id: spec.id, name: spec.name, spec, created_at: null, updated_at: null, strategy_hash: 'h', parent: null, builtin: true }) as const;

  it('tracks unsaved edits against the loaded document', () => {
    let state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(strategy()) });
    expect(state.strategy).toEqual(strategy());
    expect(unsavedEdits(state)).toBe(false);
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.ema.length', value: 12 });
    expect(unsavedEdits(state)).toBe(true);
    const edited = state.strategy!;
    state = reducer(state, { type: 'ADOPT_DOCUMENT', document: doc(edited) });
    expect(state.strategy).toBe(edited);
    expect(unsavedEdits(state)).toBe(false);
    expect(unsavedEdits(reducer(state, { type: 'ADOPT_DOCUMENT', document: null }))).toBe(false);
  });

  it('switches pages without touching the strategy', () => {
    const state = reducer(withStrategy(), { type: 'SET_PAGE', page: 'lab' });
    expect(state.page).toBe('lab');
    expect(state.strategy).toEqual(withStrategy().strategy);
    expect(initialState.page).toBe('charts');
  });
});

describe('honest document and indicator state (review findings #5, #6)', () => {
  const doc = (spec: StrategySpec, name = spec.name) =>
    ({ id: spec.id, name, spec: { ...spec, name }, created_at: null, updated_at: null, strategy_hash: 'h', parent: null, builtin: false }) as const;

  it('renaming the loaded document does not invent unsaved edits and keeps real ones', () => {
    let state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(strategy()) });
    state = reducer(state, { type: 'DOCUMENT_RENAMED', document: doc(strategy(), 'Renamed') });
    expect(state.strategy!.name).toBe('Renamed');
    expect(unsavedEdits(state)).toBe(false);
    state = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.ema.length', value: 12 });
    state = reducer(state, { type: 'DOCUMENT_RENAMED', document: doc(strategy(), 'Again') });
    expect(state.strategy!.name).toBe('Again');
    expect(unsavedEdits(state)).toBe(true);
    expect(state.strategy!.long_side.indicators![0].length).toBe(12);
  });

  it('renaming another document leaves the workspace alone', () => {
    const other = { ...strategy(), id: 'other' } as StrategySpec;
    let state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(strategy()) });
    state = reducer(state, { type: 'DOCUMENT_RENAMED', document: doc(other, 'Other renamed') });
    expect(state.document!.id).toBe(strategy().id);
    expect(state.strategy!.name).toBe(strategy().name);
  });

  it('shows latest values only for the selection and indicators they were fetched for', () => {
    let state = withStrategy();
    const key = chartKey(state);
    state = reducer(state, { type: 'SET_LATEST', key, values: { ema: 510.15, sma: 517.2 } });
    expect(currentLatest(state)).toEqual({ ema: 510.15, sma: 517.2 });
    const edited = reducer(state, { type: 'SET_SIDE_PARAM', side: 'long', path: 'indicators.ema.length', value: 21 });
    expect(currentLatest(edited)).toEqual({});
    const moved = reducer(state, { type: 'SET_SELECTION', selection: { timeframe: '1D' } });
    expect(currentLatest(moved)).toEqual({});
  });
});

describe('the experiments page', () => {
  it('is a third page beside charts and the lab', () => {
    const state = reducer(withStrategy(), { type: 'SET_PAGE', page: 'experiments' });
    expect(state.page).toBe('experiments');
    expect(state.strategy).toEqual(withStrategy().strategy);
  });
});

describe('the builder in the workspace (Mission 13)', () => {
  const doc = (spec: StrategySpec, canvas?: unknown) =>
    ({ id: spec.id, name: spec.name, spec, created_at: null, updated_at: null, strategy_hash: 'h', parent: null, builtin: false, canvas }) as never;

  it('SET_SIDE_GRAPH replaces the side and its graph', () => {
    let state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(strategy()) });
    const side = { ...strategy().long_side, stop_loss_pct: 2 };
    const graph = graphFromSide(side);
    state = reducer(state, { type: 'SET_SIDE_GRAPH', side: 'long', graph, spec: side });
    expect(state.strategy!.long_side).toEqual(side);
    expect(sideGraph(state, 'long')).toBe(graph);
    expect(state.strategy!.short_side).toEqual(strategy().short_side);
    expect(unsavedEdits(state)).toBe(true);
  });

  it('marks a graph-only change (a moved block) as an edit and keeps the strategy', () => {
    let state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(strategy()) });
    const moved = graphFromSide(strategy().long_side);
    moved.blocks[0] = { ...moved.blocks[0], x: 999, y: 7 };
    state = reducer(state, { type: 'SET_SIDE_GRAPH', side: 'long', graph: moved, spec: null });
    expect(state.strategy).toEqual(strategy());
    expect(sideGraph(state, 'long').blocks[0]).toMatchObject({ x: 999, y: 7 });
    expect(unsavedEdits(state)).toBe(true);
    expect(unsavedEdits(reducer(state, { type: 'SET_DOCUMENT', document: doc(strategy()) }))).toBe(false);
  });

  it('lays a stale saved side out afresh and keeps the other side as saved', () => {
    const spec = strategy();
    const stale = graphFromSide({ ...spec.long_side, exit: { left: 'ema', operator: 'less_than', right: 'sma', timing: 'bar_close' } });
    const short = autoLayout(graphFromSide(spec.short_side));
    short.blocks = short.blocks.map((b) => ({ ...b, x: b.x + 5 }));
    const state = reducer(initialState, { type: 'SET_DOCUMENT', document: doc(spec, { version: 1, long: stale, short }) });
    expect(readsAs(sideGraph(state, 'long'), spec.long_side)).toBe(true);
    expect(sideGraph(state, 'short')).toEqual(short);
    expect(unsavedEdits(state)).toBe(false);
  });
});

describe('the Optimization Lab page and its dock hand-off', () => {
  it('opens the Optimization Lab with a lab focus and clears it', () => {
    const opened = reducer(initialState, { type: 'SET_PAGE', page: 'optlab', focus: { lab: { source: 'opt:job-1', axes: ['a', 'b'], metric: 'mar' } } });
    expect(opened.page).toBe('optlab');
    expect(opened.focus?.lab?.source).toBe('opt:job-1');
    expect(reducer(opened, { type: 'CLEAR_FOCUS' }).focus).toBeNull();
  });
});
