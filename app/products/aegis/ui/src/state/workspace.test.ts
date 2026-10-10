import { describe, expect, it } from 'vitest';
import type { StrategySpec } from '../contracts';
import { initialState, reducer, type RunRecord, type WorkspaceState } from './workspace';

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
});
