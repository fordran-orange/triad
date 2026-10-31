// Test fixtures for the Phase 3 analytics models: payloads as the worker sends them, small and valid. Only the
// tests import this module; the app never does.
import type {
  LabCandidateCard,
  LabCounts,
  LabCategoryA,
  LabCategoryB,
  LabCategoryC,
  LabCategoryD,
  LabImportanceConstants,
  LabImportanceResult,
  LabInteractionPair,
  LabInteractions,
  LabNumber,
  LabPareto,
  LabParameterStatus,
  LabRankings,
  LabRobustnessConstants,
  LabTask,
} from '../results';

export const CAVEAT_TEXT = 'conditional on these ranges, this data, this sampler and this partition; a share is evidence about where exploration pays, not proof that a parameter is irrelevant';

export const IMPORTANCE_CONSTANTS: LabImportanceConstants = {
  THETA_MIN: 0.01,
  RESIDUAL_VETO: 0.3,
  RESIDUAL_INCONSISTENT: -0.05,
  BOOTSTRAP_B: 200,
  PERMUTATION_P: 200,
  COARSE_BOOTSTRAP_B: 50,
  COARSE_PERMUTATION_P: 50,
  COARSE_BINS: 4,
  INTERVAL: 0.9,
  FLOOR_QUANTILE: 0.95,
  ALIAS_V: 0.3,
  PAIR_MIN_N: 4,
  PAIR_MIN_COVERAGE: 0.5,
  PAIR_BALANCE_TVD: 0.25,
  IMPORTANCE_MIN_N_FACTOR: 30,
  IMPORTANCE_MIN_PER_VALUE: 20,
  IMPORTANCE_ROWS: 50000,
  TRIPLE_TOP: 20,
  INTERACTIONS_MAX_PAIRS: 190,
};

export const ROBUSTNESS_CONSTANTS: LabRobustnessConstants = {
  PLATEAU_MIN_COVERAGE: 0.5,
  NEIGHBOUR_R: 1,
  NEIGHBOUR_M_GRID: 1,
  NEIGHBOUR_M_SAMPLED: 2,
  PEAK_IQR_FACTOR: 3,
  REGION_RADIUS: 0.15,
  REGION_AXES: 6,
  REGION_MIN_N: 30,
  FOLDS_MIN: 3,
  FOLD_MIN_TRADES: 30,
  FOLD_RATIO_BAND: [0.5, 2],
  FOLD_DRAWDOWN_FACTOR: 1.5,
  STRESS_KEEP: 0.7,
  STRESS_DRAWDOWN_FACTOR: 1.3,
  PER_BARS: 1000,
  RANKING_K: 20,
  RANK_POOL: 300,
  RANK_B_MAX: 20,
  BREAK_EVEN: { net_pnl: 0, sharpe_trade: 0, profit_factor: 1 },
};

/** A d × d matrix of one value. */
export const square = (d: number, v: LabNumber = null): LabNumber[][] => Array.from({ length: d }, () => Array.from({ length: d }, () => v));

export const PATHS = ['ema.length', 'sma.length', 'stop_loss_pct', 'take_profit_pct'];

export function task(over: Partial<LabTask> = {}): LabTask {
  return { id: 't1', label: 'importance', state: 'running', stage: 1, stages: 3, progress: 1 / 3, error: null, started_at: null, finished_at: null, sharing_cpu: false, ...over };
}

export function parameterStatus(path: string, status: LabParameterStatus['status'], over: Partial<LabParameterStatus> = {}): LabParameterStatus {
  return {
    path,
    status,
    reason: `reason of ${path}`,
    flags: [],
    label: status === 'Insufficient coverage · unresolved' ? 'Insufficient coverage' : 'Measured',
    proposable: status === 'Deprioritized · proposable',
    failing: status === 'Deprioritized · proposable' ? null : `failing of ${path}`,
    ...over,
  };
}

/** Four parameters: three Measured with shares 0.10, 0.45 and 0.02, and the fourth (share 0.30) with insufficient
 *  coverage. Stage 2 of 3, partial; the screening K = 4 blocks are measured. */
export function importanceResult(over: Partial<LabImportanceResult> = {}): LabImportanceResult {
  const d = PATHS.length;
  const S = [0.1, 0.45, 0.02, 0.3];
  const terms = (S_: LabNumber[]) => ({ S: S_, J: square(d), D: square(d) });
  return {
    paths: PATHS,
    B: [5, 5, 6, 4],
    n: 1200,
    N: 1200,
    attempted: 1200,
    sampled_from: null,
    missing: { invalid: 0, failed: 0, undefined: 0 },
    invalid_share: 0,
    metric: 'net_pnl',
    scope: 'combined',
    seed: 1,
    snapshot: { generation: 3, chunk_watermark: 41 },
    labels: ['Measured', 'Measured', 'Measured', 'Insufficient coverage'],
    values_held: [5, 5, 6, 2],
    pair_coverage: square(d, 1),
    pair_balance: square(d, 0.05),
    cramers_v: square(d, 0),
    aliased: [],
    fine: {
      ...terms(S),
      I: square(d),
      lo: terms([0.06, 0.38, -0.01, 0.2]),
      hi: terms([0.15, 0.52, 0.05, 0.4]),
      floor: { S: [0.03, 0.03, 0.03, 0.03], D: square(d) },
      tick: { S: [0.02, 0.02, 0.02, 0.02], D: square(d) },
      t: { mains: 1.2 },
    },
    K: 4,
    blocks: null,
    coarse: null,
    coarse_bounds: null,
    coarse_null: null,
    triples_top: [],
    availability: {
      available: false,
      reason: 'inputs are not a product design (12 % of the grid is invalid)',
      reasons: ['inputs are not a product design (12 % of the grid is invalid)'],
      hint: 'freeze or narrow the constrained ranges',
      message: 'empirical deprioritization unavailable: inputs are not a product design (12 % of the grid is invalid)',
    },
    veto: null,
    warnings: [],
    note: null,
    statuses: [
      parameterStatus('ema.length', 'Active · detected'),
      parameterStatus('sma.length', 'Investigate · interaction not ruled out'),
      parameterStatus('stop_loss_pct', 'Active · not detected'),
      parameterStatus('take_profit_pct', 'Insufficient coverage · unresolved'),
    ],
    constants: IMPORTANCE_CONSTANTS,
    stage: 2,
    stages: 3,
    partial: true,
    block_range: [[0.02, 0.2], [0.3, 0.6], [0, 0.04], null],
    uncertainty: { design: 'interval: sampling of trials, this data', period: 'block range over 4 screening blocks', detection: 'detection floor: a detection threshold, not a practical-significance threshold' },
    caveat: CAVEAT_TEXT,
    elapsed_s: 4.2,
    ...over,
  };
}

export function pair(a: number, b: number, over: Partial<LabInteractionPair> = {}): LabInteractionPair {
  const interval = (value: number) => ({ value, lo: value - 0.02, hi: value + 0.02 });
  const increment = (value: number) => ({ ...interval(value), floor: 0.03, detected: value > 0.03 });
  return {
    pair: [PATHS[a], PATHS[b]],
    index: [a, b],
    J: interval(0.2),
    D_ij: increment(0.1),
    D_ji: increment(0.02),
    I: 0.05,
    coverage: 0.9,
    balance: 0.1,
    unbalanced: false,
    unresolved: false,
    ...over,
  };
}

export function interactions(over: Partial<LabInteractions> = {}): LabInteractions {
  const pairs = [pair(0, 1), pair(0, 2, { J: { value: 0.05, lo: 0.03, hi: 0.07 } }), pair(1, 2, { coverage: 0.3, unresolved: true }), pair(0, 3, { coverage: 0.1, unresolved: true }), pair(1, 3), pair(2, 3, { unbalanced: true })];
  return {
    task: task({ state: 'done', stage: 3 }),
    reason: null,
    snapshot_label: null,
    computed: { stage: 3, stages: 3, partial: false, seed: 1, snapshot: null, metric: 'net_pnl', scope: 'combined', n: 1200, N: 1200, attempted: 1200, sampled_from: null, elapsed_s: 9 },
    pairs,
    total_pairs: 6,
    unresolved_pairs: 2,
    truncated: false,
    constants: IMPORTANCE_CONSTANTS,
    ...over,
  };
}

export function categoryA(over: Partial<LabCategoryA> = {}): LabCategoryA {
  return {
    name: 'A',
    resolved: true,
    classification: 'stable local',
    reason: null,
    inputs: {
      n: 7, valid: 8, tested: 7, undefined: 0, coverage: 0.875, min_coverage: 0.5, required_n: 7, r: 1, m: 1, probes: 8, valid_basis: 'the frame: 8 valid positions, none ruled out',
      p25: 1.39, p75: 1.73, iqr: 0.34, tau: 0.69, value: 1.26, distance: 0.13, peak_factor: 3, peak_line: 2.74, orientation: 1,
    },
    ...over,
  };
}

export function categoryB(over: Partial<LabCategoryB> = {}): LabCategoryB {
  return {
    name: 'B',
    resolved: false,
    classification: null,
    reason: 'too few sampled trials in the region (n 12 of 30)',
    inputs: {
      axes: ['ema.length', 'sma.length'], radius: 0.15, n: 12, min_n: 30, population: 400, region_share: 0.04, density: 0.8, adaptive_excluded: 0, undefined: 0,
      p25: null, p75: null, iqr: null, tau: 0.69, value: 1.26, distance: null, orientation: 1,
    },
    ...over,
  };
}

export function categoryC(over: Partial<LabCategoryC> = {}): LabCategoryC {
  return {
    name: 'C',
    resolved: false,
    classification: null,
    reason: 'no blocks or folds',
    inputs: { folds: 0, folds_min: 3, fold_min_trades: 30, ratio_band: [0.5, 2], drawdown_factor: 1.5, blocks: 0 },
    ...over,
  };
}

export function categoryD(over: Partial<LabCategoryD> = {}): LabCategoryD {
  return {
    name: 'D',
    resolved: false,
    classification: null,
    reason: 'no replay yet (stage 2)',
    inputs: { scenarios: [], stress_keep: 0.7, drawdown_factor: 1.3, base: null, stressed: null, ratio: null },
    ...over,
  };
}

export function candidateCard(over: Partial<LabCandidateCard> = {}): LabCandidateCard {
  return {
    trial_id: 'exp:e1#5',
    trial_no: 5,
    metric: 'mar',
    scope: 'combined',
    value: 1.26,
    orientation: 1,
    tolerance: 0.15,
    tolerance_label: null,
    tau: 0.69,
    categories: { A: categoryA(), B: categoryB(), C: categoryC(), D: categoryD() },
    tested: ['A'],
    unknown: ['B', 'C', 'D'],
    findings: [],
    ...over,
  };
}

export function rankings(over: Partial<LabRankings> = {}): LabRankings {
  return {
    peak: ['exp:e1#223', 'exp:e1#710'],
    robust: ['exp:e1#710', 'exp:e1#223'],
    disagree: true,
    stable: 'exp:e1#710',
    stable_reason: null,
    k: 20,
    pool: 300,
    b_max: 20,
    ranked: [
      { trial_id: 'exp:e1#710', value: 5.9, ranked_by: 'A', classification: 'stable local', reason: null },
      { trial_id: 'exp:e1#223', value: 6.7, ranked_by: null, classification: null, reason: 'untested surroundings (n 3 of 7)' },
    ],
    peak_ranked: [
      { trial_id: 'exp:e1#223', value: 6.7, ranked_by: null, classification: null, reason: 'untested surroundings (n 3 of 7)' },
      { trial_id: 'exp:e1#710', value: 5.9, ranked_by: 'A', classification: 'stable local', reason: null },
    ],
    ...over,
  };
}

/** A two-objective front of net P&L and max drawdown: 3 of 5 drawn points, 40 dominated, 2 excluded. */
export function pareto(over: Partial<LabPareto> = {}): LabPareto {
  const bins = 4;
  return {
    objectives: ['net_pnl', 'max_drawdown'],
    orientation: [1, -1],
    front: ['exp:e1#1', 'exp:e1#2', 'exp:e1#3'],
    front_size: 5,
    dominated: 40,
    excluded: 2,
    sampled: true,
    points: [
      { trial_id: 'exp:e1#1', values: [-100, 0.05] },
      { trial_id: 'exp:e1#2', values: [500, 0.12] },
      { trial_id: 'exp:e1#3', values: [900, 0.3] },
    ],
    density: {
      bins,
      axes: ['net_pnl', 'max_drawdown'],
      x: [-200, 1000],
      y: [0, 0.4],
      counts: [
        [0, 6, 0, 0],
        [4, 10, 8, 0],
        [0, 2, 5, 1],
        [0, 0, 3, 1],
      ],
      basis: 'Aggregated from tested (n = 40)',
    },
    basis: 'Sampled subset (3 of 5)',
    constants: { PARETO_FRONT_MAX: 2000, PARETO_DENSITY_BINS: 64, OBJECTIVES_MIN: 2, OBJECTIVES_MAX: 3 },
    ...over,
  };
}

/** The §6.4 counts of a source with 12,000 completed trials and no filter. */
export function labCounts(over: Partial<LabCounts> = {}): LabCounts {
  return {
    space: 1_000_000,
    valid: 900_000,
    budget_total: 12_000,
    reserved: 0,
    scheduled: 12_000,
    evaluations: 12_000,
    remaining: 0,
    reused: 0,
    attempted: 12_000,
    evaluations_done: 12_000,
    completed: 12_000,
    invalid: 0,
    failed: 0,
    pending: 0,
    unique: 11_800,
    duplicates: 200,
    filtered: 12_000,
    shown: 0,
    undefined: 0,
    basis: 'Tested (exact)',
    block: 0,
    filters_active: 0,
    ...over,
  };
}
