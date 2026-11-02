import { describe, expect, it } from 'vitest';
import type { LabConvergence, LabConvergenceBatch, LabEnvelope } from '../results';
import { labCounts } from './analyticsFixtures';
import { bareMetric, bestPieces, convergenceModel, robustRuns, stepValueAt, stepVertices } from './convergenceModel';

const CONSTANTS = { CONVERGENCE_BATCH: 5000, CONVERGENCE_TOP: 0.01, CONVERGENCE_MAX_POINTS: 1000, MIN_BATCHES: 2, NEIGHBOUR_R: 1 };

/** Complete batch `n` as the worker sends it: it ends at trial 5000 (n + 1) - 1. */
function batch(n: number, over: Partial<LabConvergenceBatch> = {}): LabConvergenceBatch {
  return { batch: n, trial_no: 5000 * (n + 1) - 1, median: 100 + n, p25: 50 + n, p75: 150 + n, top: 50, measured: 50, ...over };
}

function view(over: Partial<LabEnvelope<LabConvergence>> = {}): LabEnvelope<LabConvergence> {
  return {
    view: 'convergence',
    filter_hash: 'abcd1234',
    scope: labCounts(),
    snapshot: null,
    provisional: false,
    empty: null,
    metric: 'combined.net_pnl',
    orientation: 1,
    best: [[0, -50], [10, -20], [20, 30], [30, 30], [40, 90]],
    best_total: 41,
    robust: [],
    robust_reason: null,
    batches: 0,
    partial: 41,
    r: 1,
    m: 1,
    basis: 'Tested (exact); neighbours read every completed block-0 trial of the snapshot, the filter selects each batch\'s top trials',
    constants: CONSTANTS,
    ...over,
  };
}

describe('the metric', () => {
  it('is the <scope>.<metric> column; labels use the bare name', () => {
    expect(bareMetric('combined.net_pnl')).toBe('net_pnl');
    expect(bareMetric('long.sharpe_trade')).toBe('sharpe_trade');
    expect(bareMetric('short.max_drawdown')).toBe('max_drawdown');
    expect(bareMetric('mar')).toBe('mar');
  });
});

describe('best-so-far is a step line', () => {
  it('holds each kept value until the next kept trial: horizontal, then vertical, never a ramp', () => {
    expect(stepVertices([[0, 1], [10, 3], [20, 3], [30, 5]])).toEqual([
      { x: 0, y: 1 },
      { x: 10, y: 1 },
      { x: 10, y: 3 },
      { x: 20, y: 3 },
      { x: 30, y: 3 },
      { x: 30, y: 5 },
    ]);
    expect(stepVertices([[7, 2]])).toEqual([{ x: 7, y: 2 }]);
    expect(stepVertices([])).toEqual([]);
  });

  it('has no diagonal segment on any series', () => {
    let v = 0;
    const best: Array<[number, number]> = Array.from({ length: 80 }, (_, i): [number, number] => {
      v += i % 3 === 0 ? 4 : 0;
      return [i * 13, v];
    });
    const vertices = stepVertices(best);
    expect(vertices.length).toBeGreaterThan(best.length);
    for (let i = 1; i < vertices.length; i++) expect(vertices[i].x === vertices[i - 1].x || vertices[i].y === vertices[i - 1].y).toBe(true);
  });

  it('shows an improvement at its trial_no, not before: the value just before it is still the old one', () => {
    const best: Array<[number, number]> = [[0, 1], [100, 5], [200, 9]];
    expect(stepValueAt(best, 99)).toBe(1);
    expect(stepValueAt(best, 100)).toBe(5);
    expect(stepValueAt(best, 150)).toBe(5);
    expect(stepValueAt(best, 200)).toBe(9);
    expect(stepValueAt(best, 201)).toBeNull(); // past the last kept trial nothing is known: the line stops there
    expect(stepValueAt(best, -1)).toBeNull(); // before the first kept trial there is nothing
    expect(stepValueAt([[0, 9], [100, 5]], 99)).toBe(9); // lower is better: the same rule
  });

  it('never shows a better value than was true at that trial, whatever the thinning (late is allowed, early is not)', () => {
    // The true best-so-far over 200 trials, then kept at every 7th trial and the last (what the worker's thinning does).
    const truth: number[] = [];
    let best = -1000;
    for (let t = 0; t < 200; t++) {
      best = Math.max(best, Math.sin(t * 1.7) * 100 + t * 0.5);
      truth.push(best);
    }
    const kept: Array<[number, number]> = truth.map((v, t): [number, number] => [t, v]).filter(([t]) => t % 7 === 0 || t === 199);
    for (let t = 0; t < 200; t++) expect(stepValueAt(kept, t)).toBeLessThanOrEqual(truth[t]);
    // The same series for a metric where lower is better (the true best is the running minimum): never lower than the truth.
    const low = truth.map((v) => -v);
    const keptLow: Array<[number, number]> = low.map((v, t): [number, number] => [t, v]).filter(([t]) => t % 7 === 0 || t === 199);
    for (let t = 0; t < 200; t++) expect(stepValueAt(keptLow, t)).toBeGreaterThanOrEqual(low[t]);
  });

  it('colours the losing part red: a P&L-signed value below break-even, split where a jump crosses it', () => {
    const pieces = bestPieces([[0, -50], [10, -20], [20, 30]], 'net_pnl');
    expect(pieces.map((p) => p.loses)).toEqual([true, true, true, true, false]);
    // The jump from -20 to 30 at trial 20 is cut at 0: its lower half loses, its upper half does not.
    const jump = pieces.filter((p) => p.x0 === 20 && p.x1 === 20);
    expect(jump).toEqual([
      { x0: 20, y0: -20, x1: 20, y1: 0, loses: true },
      { x0: 20, y0: 0, x1: 20, y1: 30, loses: false },
    ]);
    // A drawdown has no profit sign: none of it is a loss. The profit factor breaks even at 1.
    expect(bestPieces([[0, 0.1], [10, 0.4]], 'max_drawdown').some((p) => p.loses)).toBe(false);
    expect(bestPieces([[0, 0.8], [10, 1.2]], 'profit_factor').map((p) => p.loses)).toEqual([true, true, false]);
    // Winning from the first trial: nothing is red.
    expect(bestPieces([[0, 5], [10, 9]], 'net_pnl').some((p) => p.loses)).toBe(false);
  });
});

describe('the robust series', () => {
  it('is one point per batch at its last trial; a batch with no measured neighbour is a gap, never zero or the neighbour value', () => {
    const empty = batch(2, { median: null, p25: null, p75: null, measured: 0 });
    const runs = robustRuns([batch(0), batch(1), empty, batch(3), batch(4)]);
    expect(runs.map((run) => run.map((p) => p.batch))).toEqual([[0, 1], [3, 4]]);
    expect(runs[0][0]).toEqual({ batch: 0, x: 4999, median: 100, p25: 50, p75: 150, measured: 50, top: 50 });
    expect(runs.flat().some((p) => p.batch === 2)).toBe(false);
  });

  it('does not join batches the worker thinned apart: it never draws across batches it did not send', () => {
    expect(robustRuns([batch(0), batch(1), batch(5), batch(6)]).map((run) => run.map((p) => p.batch))).toEqual([[0, 1], [5, 6]]);
    expect(robustRuns([batch(0), batch(9)]).map((run) => run.map((p) => p.batch))).toEqual([[0], [9]]);
    expect(robustRuns([])).toEqual([]);
  });
});

describe('the model', () => {
  it('draws best while the robust series is empty (under two batches) and carries the envelope\'s empty for the full chart', () => {
    const reason = 'fewer than 2 complete batches of 5000 trials with a defined net_pnl (41 so far)';
    const m = convergenceModel(view({ robust: [], robust_reason: reason, empty: reason, batches: 0 }))!;
    expect(m.best.length).toBeGreaterThan(0);
    expect(m.runs).toEqual([]);
    expect(m.emptyReason).toBe(reason);
    expect(m.robustReason).toBe(reason);
  });

  it('with no defined value has nothing to draw and says why', () => {
    const m = convergenceModel(view({ best: [], best_total: 0, partial: 0, robust_reason: 'fewer than 2 complete batches of 5000 trials with a defined net_pnl (0 so far)', empty: 'no trial has a defined net_pnl' }))!;
    expect(m.best).toEqual([]);
    expect(m.xDomain).toBeNull();
    expect(m.yDomain).toBeNull();
    expect(m.emptyReason).toBe('no trial has a defined net_pnl');
  });

  it('labels a provisional answer from the envelope, and only then', () => {
    expect(convergenceModel(view({ provisional: true }))!.provisional).toBe(true);
    expect(convergenceModel(view({ provisional: false }))!.provisional).toBe(false);
  });

  it('keeps the values as the worker sent them: orientation is already applied, nothing is negated or re-sorted', () => {
    const drawdown = convergenceModel(
      view({ metric: 'combined.max_drawdown', orientation: -1, best: [[0, 0.4], [10, 0.25], [20, 0.1]], robust: [batch(0, { median: 0.3, p25: 0.2, p75: 0.35 }), batch(1, { median: 0.28, p25: 0.18, p75: 0.33 })], batches: 2 }),
    )!;
    expect(drawdown.metric).toBe('max_drawdown');
    expect(drawdown.better).toBe('lower is better');
    expect(drawdown.best.map((v) => v.y)).toEqual([0.4, 0.4, 0.25, 0.25, 0.1]);
    expect(drawdown.runs[0][0].p25).toBe(0.2); // p25 <= p75 as sent
    expect(drawdown.runs[0][0].p75).toBe(0.35);
    expect(drawdown.yDomain![0]).toBeLessThanOrEqual(0.1);
    expect(drawdown.yDomain![1]).toBeGreaterThanOrEqual(0.4);
    expect(convergenceModel(view())!.better).toBe('higher is better');
  });

  it('spans best and the band on one scale, pads a flat series, and keeps a break-even line only when it is inside the data', () => {
    const m = convergenceModel(view({ best: [[0, -50], [40, 90]], robust: [batch(0, { median: 10, p25: -200, p75: 300 }), batch(1)], batches: 2 }))!;
    expect(m.yDomain![0]).toBeLessThanOrEqual(-200);
    expect(m.yDomain![1]).toBeGreaterThanOrEqual(300);
    expect(m.breakEven).toBe(0);
    const flat = convergenceModel(view({ best: [[0, 5], [10, 5]] }))!;
    expect(flat.yDomain![1]).toBeGreaterThan(flat.yDomain![0]);
    const winning = convergenceModel(view({ best: [[0, 5], [10, 9]] }))!;
    expect(winning.breakEven).toBeNull(); // every value wins: no line to draw
    expect(convergenceModel(view({ metric: 'combined.max_drawdown', orientation: -1, best: [[0, 0.5], [10, 0.1]] }))!.breakEven).toBeNull();
  });

  it('never extrapolates: nothing is drawn past the last kept trial or the last complete batch', () => {
    const m = convergenceModel(view({ robust: [batch(0), batch(1)], batches: 2, best: [[0, 1], [12000, 9]], best_total: 12001 }))!;
    expect(Math.max(...m.best.map((v) => v.x))).toBe(12000);
    expect(Math.max(...m.runs.flat().map((p) => p.x))).toBe(9999);
    expect(m.xDomain).toEqual([0, 12000]);
    // A batch that ends past the last kept best trial still lies inside the domain.
    const wide = convergenceModel(view({ best: [[0, 1], [3000, 9]], robust: [batch(0), batch(1)], batches: 2 }))!;
    expect(wide.xDomain).toEqual([0, 9999]);
  });

  it('states what the robust series is made of, and how many batches are gaps', () => {
    const m = convergenceModel(view({ robust: [batch(0), batch(1, { median: null, p25: null, p75: null, measured: 0 }), batch(2)], batches: 3 }))!;
    expect(m.robustNote).toBe('robust: 3 batches of 5,000 trials, the neighbourhood P25 of each batch\'s top 1 % (median and quartiles) · 1 with no measured neighbour: a gap');
    expect(convergenceModel(view({ robust: [batch(0), batch(1)], batches: 2 }))!.robustNote).toBe('robust: 2 batches of 5,000 trials, the neighbourhood P25 of each batch\'s top 1 % (median and quartiles)');
    expect(convergenceModel(view())!.robustNote).toBe('');
  });

  it('prints the server\'s basis verbatim and a summary a screen reader can use', () => {
    const v = view({ best_total: 41 });
    const m = convergenceModel(v)!;
    expect(m.basis).toBe(v.basis);
    expect(m.summary).toBe('convergence of net_pnl: best so far $90 after 41 trials, no robust series yet');
    const robust = convergenceModel(view({ robust: [batch(0), batch(1)], batches: 2 }))!;
    expect(robust.summary).toBe('convergence of net_pnl: best so far $90 after 41 trials, latest robust median $101 over 2 batches');
  });
});
