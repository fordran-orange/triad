import { describe, expect, it } from 'vitest';
import type { Plan } from '../contracts';
import { experimentBody, planLine, type PlannerFields } from './ExperimentPlanner';

const params = [{ path: 'long_side.indicators.donchian.length', start: 10, stop: 20, step: 5 }];

function fields(overrides: Partial<PlannerFields> = {}): PlannerFields {
  return {
    name: 'screened',
    strategyId: 'breakout',
    data: { symbol: 'QQQ', timeframe: '1h', start: '2023-01-01', end: '2024-12-31' },
    settings: { initial_capital: 100_000, allocation_fraction: 1 },
    objective: 'net_pnl',
    params,
    budgetRuns: '2000',
    budgetSeconds: '',
    tolerance: 0.15,
    screened: false,
    ...overrides,
  } as PlannerFields;
}

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    mode: 'exhaustive',
    grid_cells: 3,
    valid_cells: 3,
    skipped: 0,
    skip_reasons: {},
    planned_runs: 3,
    first_pass: 3,
    refinement: 0,
    sampled_fraction: 1,
    estimate_seconds: 2,
    ms_per_cell_bar: 0.01,
    workers: 2,
    bars: 1000,
    blocks: 0,
    evaluations: 3,
    price_source: 'measured',
    ...overrides,
  };
}

describe('the experiment planner (Lab Phase 3 screening blocks)', () => {
  it('sends blocks: 4 when "Screen across periods" is ticked and 0 when it is not', () => {
    expect(experimentBody(fields({ screened: true }))?.blocks).toBe(4);
    expect(experimentBody(fields({ screened: false }))?.blocks).toBe(0);
    expect(experimentBody(fields({ params: [] }))).toBeNull();
    const body = experimentBody(fields({ budgetRuns: '', budgetSeconds: '60' }));
    expect(body?.budget).toEqual({ runs: null, seconds: 60 });
    expect(body?.surface.parameters).toEqual(params);
  });

  it('shows "evaluations: N × 5" on the plan line only for a screened plan', () => {
    const screened = planLine(params, plan({ blocks: 4, evaluations: 15 }));
    expect(screened).toContain(' · evaluations: 3 × 5');
    expect(screened.startsWith('1 parameter · 3 cells · exhaustive · ≈ ')).toBe(true);
    const plain = planLine(params, plan());
    expect(plain).not.toContain('evaluations');
    expect(plain).toContain('on 2 workers at 10.0 ms per cell (measured on this host)');
    expect(planLine(params, plan({ skipped: 2, skip_reasons: { 'insufficient bars': 2 } }))).toContain(' · 2 skipped (insufficient bars)');
  });
});
