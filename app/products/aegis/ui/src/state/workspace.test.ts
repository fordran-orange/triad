import { describe, expect, it } from 'vitest';
import type { StrategySpec } from '../contracts';
import { applyConfigs, initialState, reducer, runStaleness, type RunRecord, type WorkspaceState } from './workspace';

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
});
