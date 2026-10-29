import { describe, expect, it } from 'vitest';
import type { StrategySpec } from './contracts';
import { applyCellToStrategy, bestPoint, cellsView, evaluationsLine, leverLabel, priceLabel, recommendationText, surfaceLine } from './experiments';

function strategy(): StrategySpec {
  const side = (direction: 'long' | 'short') => ({
    direction,
    enabled: true,
    indicators: [
      { id: 'ema', kind: 'EMA', length: 9, source: 'close', overlay: true },
      { id: 'sma', kind: 'SMA', length: 30, source: 'close', overlay: true },
      { id: 'bb', kind: 'BB', length: 20, source: 'close', overlay: true },
    ],
    entry: { left: 'ema', operator: 'crosses_above', right: 'sma', timing: 'bar_close' },
    exit: { left: 'ema', operator: 'crosses_below', right: 'sma', timing: 'bar_close' },
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

const surface = {
  parameters: [
    { path: 'long_side.indicators.ema.length', start: 5, stop: 20, step: 1 },
    { path: 'short_side.indicators.sma.length', start: 20, stop: 40, step: 10 },
  ],
};

describe('experiment helpers', () => {
  it('surfaceLine names the parameters, the cells and the mode', () => {
    expect(surfaceLine(surface, { mode: 'exhaustive', valid_cells: 48, planned_runs: 48, sampled_fraction: 1 })).toBe('2 parameters · 48 cells · exhaustive');
    expect(surfaceLine(surface, { mode: 'sampled', valid_cells: 157542, planned_runs: 2000, sampled_fraction: 2000 / 157542 })).toBe(
      '2 parameters · 157,542 cells · sampled 1.3% (2,000 runs)',
    );
    expect(surfaceLine({ parameters: [surface.parameters[0]] }, null)).toBe('1 parameter · plan pending');
  });

  it('applyCellToStrategy sets side-prefixed paths and leaves the other side alone', () => {
    const applied = applyCellToStrategy(strategy(), {
      'long_side.indicators.ema.length': 12,
      'short_side.indicators.bb.params.multiplier': 2.5,
    });
    expect(applied.long_side.indicators![0].length).toBe(12);
    expect(applied.short_side.indicators![0].length).toBe(9);
    expect(applied.short_side.indicators![2].params).toEqual({ multiplier: 2.5 });
    expect(applied.long_side.indicators![2].params).toBeUndefined();
    expect(strategy().long_side.indicators![0].length).toBe(9);
  });

  it('cellsView sorts by a metric and filters by plateau', () => {
    const rows = [
      { cell: 0, valid: true, 'combined.net_pnl': 10, plateau: 1 },
      { cell: 1, valid: true, 'combined.net_pnl': 30, plateau: null },
      { cell: 2, valid: false, 'combined.net_pnl': null, plateau: null },
      { cell: 3, valid: true, 'combined.net_pnl': 20, plateau: 1 },
    ];
    expect(cellsView(rows, { sort: 'combined.net_pnl', descending: true }).map((r) => r.cell)).toEqual([1, 3, 0, 2]);
    expect(cellsView(rows, { sort: 'combined.net_pnl', descending: false }).map((r) => r.cell)).toEqual([0, 3, 1, 2]);
    expect(cellsView(rows, { sort: 'cell', descending: false, plateau: 1 }).map((r) => r.cell)).toEqual([0, 3]);
  });

  it('recommendationText is honest in every case', () => {
    expect(recommendationText({ recommendation: null, statement: 'the surface is flat: every valid cell has the same net_pnl (7)' })).toBe(
      'No recommendation: the surface is flat: every valid cell has the same net_pnl (7)',
    );
    expect(recommendationText({ recommendation: null, statement: 'no valid objective values for mar: nothing to rank' })).toBe(
      'No recommendation: no valid objective values for mar: nothing to rank',
    );
    const rec = {
      plateau: 1,
      centre: { cell: 30, params: { 'long_side.indicators.ema.length': 12 }, objective: 10, metrics: {} },
      supported_peak: { cell: 31, params: { 'long_side.indicators.ema.length': 13 }, objective: 10 },
      fragile_peaks: [{ cell: 70, params: { 'long_side.indicators.ema.length': 19 }, objective: 12 }],
      statement: 'plateau 1 of 16 cells, median net_pnl 10; use its centre',
    };
    expect(recommendationText({ recommendation: rec, statement: rec.statement })).toBe(
      'Plateau 1: use cell 30 (long_side.indicators.ema.length 12); supported peak at cell 31; 1 fragile peak marked',
    );
  });

  it('leverLabel reads as a sentence with the resulting count', () => {
    expect(leverLabel({ kind: 'freeze', parameter: 'short_side.indicators.sma.length', label: 'freeze short_side.indicators.sma.length at 30', valid_cells: 682, estimate_seconds: 3.1, fits: true })).toBe(
      'freeze short_side.indicators.sma.length at 30 → 682 cells, fits',
    );
    expect(leverLabel({ kind: 'coarsen', parameter: 'x', label: 'coarsen x: step 1 → 2', valid_cells: 40656, estimate_seconds: 180, fits: false })).toBe(
      'coarsen x: step 1 → 2 → 40,656 cells, 3 min 0 s',
    );
  });
});


describe('bestPoint', () => {
  const points = [
    { value: 10, median: 1 },
    { value: 20, median: 5 },
    { value: 30, median: 3 },
  ];
  it('picks the highest median, or the lowest when lower is better (max_drawdown)', () => {
    expect(bestPoint(points, false)?.value).toBe(20);
    expect(bestPoint(points, true)?.value).toBe(10);
  });
  it('is null when no level has a median', () => {
    expect(bestPoint([{ value: 1, median: null }], false)).toBeNull();
  });
});

describe('priceLabel', () => {
  it('says whether the plan was priced from a measurement or the starting guess', () => {
    expect(priceLabel({ price_source: 'measured' })).toBe('measured on this host');
    expect(priceLabel({ price_source: 'starting_guess' })).toBe('starting guess; no experiment has finished on this host yet');
  });
});

describe('evaluationsLine', () => {
  it('counts every screening block of a configuration beside the configurations', () => {
    expect(evaluationsLine({ planned_runs: 2000, blocks: 4 })).toBe('evaluations: 2,000 × 5');
    expect(evaluationsLine({ planned_runs: 12, blocks: 8 })).toBe('evaluations: 12 × 9');
    expect(evaluationsLine({ planned_runs: 12, blocks: 0 })).toBe('');
    expect(evaluationsLine({ planned_runs: 12 })).toBe('');
  });
});
