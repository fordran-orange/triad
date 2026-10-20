import { describe, expect, it } from 'vitest';
import type { StudyPlan } from './contracts';
import type { StudyReport } from './results';
import { bestCells, equityPaths, flatShading, planLine, ruleRows, visibleStudy, windowMarks } from './studies';

function plan(overrides: Partial<StudyPlan> = {}): StudyPlan {
  const symbol = (name: string) => ({
    symbol: name,
    bars: 17598,
    windows: 16,
    unused_tail_bars: 137,
    first_window: {},
    mode: 'exhaustive' as const,
    cells_per_window: 252,
    first_pass: 252,
    refinement: 0,
    runs: 4032,
  });
  return {
    experiment_id: 'breakout',
    timeframe: '1h',
    in_sample_bars: 3493,
    out_of_sample_bars: 873,
    symbols: [symbol('QQQ'), symbol('SPY'), symbol('ITOT')],
    total_runs: 12096,
    valid_cells: 252,
    skipped: 0,
    skip_reasons: {},
    estimate_seconds: 120,
    ms_per_cell_bar: 0.0004,
    price_source: 'measured',
    workers: 10,
    levers: [],
    ...overrides,
  } as StudyPlan;
}

const metrics = (mar: number | null) => ({ net_pnl: 1234.5, net_return: 0.0123, cagr: null, max_drawdown: 0.08, mar, trade_count: 12, exposure: 0.4 });

function report(frozenAbsent: string | null = null): StudyReport {
  const rule = (mar: number | null) => ({ metrics: metrics(mar), objective: mar, flat_windows: 1, windows: 4, result_hash: 'a'.repeat(64) });
  return {
    objective: 'mar',
    data_label: 'QQQ 1h 2016-09-19 → 2026-09-18',
    raw_archive: true,
    label: 'RAW ARCHIVE · NOT RESEARCH-ELIGIBLE',
    frozen_absent: frozenAbsent,
    summary: 'plateau rule ahead of the peak rule on 1 of 1 symbols by MAR',
    caveats: ['windows: QQQ 4', 'no significance test is claimed'],
    symbols: {
      QQQ: {
        windows: 4,
        rules: { plateau: rule(0.61), peak: rule(null), frozen: frozenAbsent ? { absent: frozenAbsent } : rule(0.55) },
        flat_line: 'flat in 1 of 4 windows',
        comparison: 'On QQQ …',
        stability: { plateau_share: 0.75, centre_kept_share: 0.5, median_move: 0.25, centre_path: {} },
        curves: {},
        window_rows: [],
      },
    },
  };
}

describe('study helpers', () => {
  it('planLine names the symbols, windows, runs and an estimate with its price source', () => {
    expect(planLine(plan())).toBe('3 symbols · 48 windows · 12,096 runs · ≈ 2 min 0 s (measured on this host)');
    const one = plan({ symbols: [plan().symbols[0]], total_runs: 4032, estimate_seconds: 8, price_source: 'starting_guess' });
    expect(planLine(one)).toBe('1 symbol · 16 windows · 4,032 runs · ≈ 8.0 s (starting guess; no experiment has finished on this host yet)');
    const sampled = plan({ symbols: plan().symbols.map((s) => ({ ...s, mode: 'sampled' as const, cells_per_window: 2000 })), valid_cells: 157542 });
    expect(planLine(sampled)).toContain('· sampled 2,000 of 157,542 cells per window');
  });

  it('ruleRows shows a dash for a null metric and the reason for an absent frozen centre', () => {
    const rows = ruleRows(report(), 'QQQ');
    expect(rows.map((r) => r.rule)).toEqual(['plateau', 'peak', 'frozen']);
    expect(rows[0].cells.mar).toBe('0.61');
    expect(rows[1].cells.mar).toBe('—');
    expect(rows[0].cells.cagr).toBe('—');
    expect(rows[0].cells.trades).toBe('12');
    const absent = ruleRows(report('the parent report has no recommendation'), 'QQQ')[2];
    expect(absent.absent).toBe('the parent report has no recommendation');
  });

  it('equityPaths keeps the first and last points and scales every curve into the box', () => {
    const curves = {
      plateau: [
        { timestamp: '2020-01-01T00:00:00+00:00', equity: 100 },
        { timestamp: '2020-01-03T00:00:00+00:00', equity: 120 },
      ],
      peak: [
        { timestamp: '2020-01-02T00:00:00+00:00', equity: 90 },
        { timestamp: '2020-01-05T00:00:00+00:00', equity: 110 },
      ],
    };
    const { paths, domain } = equityPaths(curves, 400, 100);
    expect(domain).toEqual([Date.parse('2020-01-01T00:00:00+00:00'), Date.parse('2020-01-05T00:00:00+00:00')]);
    expect(paths.plateau?.startsWith('M0.0,')).toBe(true);
    expect(paths.peak?.endsWith('L400.0,33.3')).toBe(true); // 110 of 90..120 in a 100-high box
    expect(paths.plateau).toContain('L200.0,0.0'); // the top of the range sits on the top edge
    expect(equityPaths({}, 400, 100).paths).toEqual({});
  });

  it('flatShading returns one band per flat window and windowMarks one line per window', () => {
    const rows = [
      { index: 0, oos_start: '2020-01-01T00:00:00+00:00', oos_end: '2020-01-02T00:00:00+00:00', flat: false },
      { index: 1, oos_start: '2020-01-03T00:00:00+00:00', oos_end: '2020-01-04T00:00:00+00:00', flat: true },
      { index: 2, oos_start: '2020-01-04T00:00:00+00:00', oos_end: '2020-01-05T00:00:00+00:00', flat: true },
    ];
    const domain: [number, number] = [Date.parse('2020-01-01T00:00:00+00:00'), Date.parse('2020-01-05T00:00:00+00:00')];
    const bands = flatShading(rows, domain, 400);
    expect(bands.map((b) => b.index)).toEqual([1, 2]);
    expect(bands[0].x0).toBeCloseTo(200);
    expect(bands[0].x1).toBeCloseTo(300);
    expect(windowMarks(rows, domain, 400).map((m) => Math.round(m.x))).toEqual([0, 200, 300]);
  });
});

describe('the window cells, best first by the objective (review finding)', () => {
  const rows = [
    { cell: 0, valid: true, 'combined.max_drawdown': 0.3 },
    { cell: 1, valid: true, 'combined.max_drawdown': 0.1 },
    { cell: 2, valid: false, 'combined.max_drawdown': null },
    { cell: 3, valid: true, 'combined.max_drawdown': 0.2 },
  ];
  it('ranks lower drawdown first and drops invalid cells', () => {
    expect(bestCells(rows, 'max_drawdown', 2).map((r) => r.cell)).toEqual([1, 3]);
  });
  it('ranks higher first for every other objective, nulls last', () => {
    const mar = [
      { cell: 0, valid: true, 'combined.mar': 0.5 },
      { cell: 1, valid: true, 'combined.mar': null },
      { cell: 2, valid: true, 'combined.mar': 0.9 },
    ];
    expect(bestCells(mar, 'mar', 20).map((r) => r.cell)).toEqual([2, 0, 1]);
  });

  it('visibleStudy shows a study only while it belongs to the open experiment', () => {
    const items = [{ id: 's1' }, { id: 's2' }];
    expect(visibleStudy('s1', items)).toBe('s1');
    expect(visibleStudy('other-experiments-study', items)).toBeNull();
    expect(visibleStudy('s1', null)).toBeNull(); // still loading this experiment's studies
    expect(visibleStudy(null, items)).toBeNull();
  });
});
