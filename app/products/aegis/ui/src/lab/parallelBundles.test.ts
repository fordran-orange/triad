import { describe, expect, it } from 'vitest';
import type { LabParallel, LabParallelLine } from '../results';
import { linearScale } from './charts/canvas';
import { answered } from './labQuery';
import { initialLabState, labReducer } from './labStore';
import { axisLabel, axisPositions, binEdges, brushToFilter, bundleKey, exactLine, isSampleView, nearestAxis, opacityFor, parallelBasis, parallelRequest, parallelSummary, polyline, sampleLine, sampleNote, sampleOrder } from './parallelBundles';

/** The bin a value falls in under `edges`: [edges[i], edges[i + 1]), the last bin closed. */
const binsHolding = (edges: number[], v: number) =>
  edges.slice(0, -1).filter((lo, i) => v >= lo && (v < edges[i + 1] || (i === edges.length - 2 && v === edges[i + 1]))).length;

describe('parallelBundles', () => {
  it('bin math: quantile edges on a known vector, duplicates collapsed, every value in exactly one bin', () => {
    // numpy's np.quantile(values, linspace(0, 1, q + 1)), linear interpolation: 1, 2.75, 4.5, 6.25, 8.
    expect(binEdges([1, 2, 3, 4, 5, 6, 7, 8], 4)).toEqual([1, 2.75, 4.5, 6.25, 8]);
    expect(binEdges([8, 1, 7, 2, 6, 3, 5, 4], 4)).toEqual([1, 2.75, 4.5, 6.25, 8]); // order does not matter
    // Quantiles 1, 1, 1, 2.25, 4: the repeated edge collapses, two bins remain.
    const skewed = [1, 1, 1, 1, 1, 2, 3, 4];
    expect(binEdges(skewed, 4)).toEqual([1, 2.25, 4]);
    // One value: a single closed bin, never zero bins.
    expect(binEdges([3, 3, 3], 4)).toEqual([3, 3]);
    expect(binEdges([], 4)).toEqual([]);
    for (const values of [[1, 2, 3, 4, 5, 6, 7, 8], skewed, [3, 3, 3], [0.1, 0.2, 0.2, 0.2, 0.9, 1.5, 1.5]]) {
      const edges = binEdges(values, 4);
      for (const v of values) expect(binsHolding(edges, v)).toBe(1);
    }
  });

  it('bundleKey: one key per bin vector', () => {
    expect(bundleKey([0, 3, 1])).toBe('0|3|1');
    expect(bundleKey([1, 23])).not.toBe(bundleKey([12, 3]));
  });

  it('brush → filter: SET_RANGE on the path with an ordered range; null clears', () => {
    expect(brushToFilter('p', [0.2, 0.6])).toEqual({ type: 'SET_RANGE', path: 'p', range: [0.2, 0.6] });
    expect(brushToFilter('p', [0.6, 0.2])).toEqual({ type: 'SET_RANGE', path: 'p', range: [0.2, 0.6] });
    expect(brushToFilter('p', [12.000000000000002, 30.999999999999996])).toEqual({ type: 'SET_RANGE', path: 'p', range: [12, 31] });
    expect(brushToFilter('p', null)).toEqual({ type: 'SET_RANGE', path: 'p', range: null });
    const brushed = labReducer(initialLabState, brushToFilter('p', [0.6, 0.2]));
    expect(brushed.filter.ranges).toEqual({ p: [0.2, 0.6] });
    expect(labReducer(brushed, brushToFilter('p', null)).filter.ranges).toEqual({});
  });

  it('opacityFor is monotone in the count with a floor', () => {
    const series = [0, 1, 2, 5, 10, 50, 99, 100].map((n) => opacityFor(n, 100));
    for (let i = 1; i < series.length; i++) expect(series[i]).toBeGreaterThanOrEqual(series[i - 1]);
    expect(opacityFor(0, 100)).toBe(0.08);
    expect(opacityFor(1, 1000)).toBe(0.08);
    expect(opacityFor(50, 100)).toBe(0.5);
    expect(opacityFor(100, 100)).toBe(1);
    expect(opacityFor(5, 0)).toBe(0.08); // no bundles counted: the floor, never NaN
    expect(opacityFor(200, 100)).toBe(1);
  });

  it('axis positions: pad … width − pad evenly; one axis in the middle; the first is the pad the walk reads', () => {
    expect(axisPositions(3, 400, 20)).toEqual([20, 200, 380]);
    expect(axisPositions(1, 400, 20)).toEqual([200]);
    expect(axisPositions(0, 400, 20)).toEqual([]);
    const ten = axisPositions(10, 1000, 40);
    expect(ten).toHaveLength(10);
    expect(ten[0]).toBe(40);
    expect(ten[9]).toBeCloseTo(960, 10);
    const gaps = ten.slice(1).map((x, i) => x - ten[i]);
    for (const gap of gaps) expect(gap).toBeCloseTo(gaps[0], 10);
  });

  it('polyline: each axis at its x, the bundle through its bins’ centres on that axis’s scale', () => {
    const axes = [linearScale([0, 10], [100, 0]), linearScale([0, 100], [100, 0])];
    const centres = [
      [1, 5, 9],
      [10, 50],
    ];
    expect(polyline({ bins: [2, 0] }, axes, centres, [20, 180])).toEqual([
      [20, 10],
      [180, 90],
    ]);
    expect(polyline({ bins: [0, 1] }, axes, centres)).toEqual([
      [0, 90],
      [1, 50],
    ]);
    // A pinned trial through its own values; a value it lacks breaks the line.
    expect(exactLine({ a: 5, b: 25 }, ['a', 'b'], axes, [20, 180])).toEqual([
      [20, 50],
      [180, 75],
    ]);
    expect(exactLine({ a: 5, b: null }, ['a', 'b'], axes, [20, 180])).toEqual([[20, 50], null]);
  });

  it('axisLabel shortens a path to its side and field', () => {
    expect(axisLabel('long_side.indicators.ema.length')).toBe('L ema.length');
    expect(axisLabel('short_side.indicators.rsi.params.upper')).toBe('S rsi.params.upper');
    expect(axisLabel('long_side.stop_loss_pct')).toBe('L stop_loss_pct');
    expect(axisLabel('indicators.sma.length')).toBe('sma.length'); // a grid job's own path
  });

  it('nearestAxis picks the closest axis within the tolerance', () => {
    expect(nearestAxis([20, 200, 380], 26, 12)).toBe(0);
    expect(nearestAxis([20, 200, 380], 195, 12)).toBe(1);
    expect(nearestAxis([20, 200, 380], 110, 12)).toBe(-1);
    expect(nearestAxis([], 10, 12)).toBe(-1);
  });

  it('the basis is the server’s verbatim without a pin; with pins its tail names the pinned lines drawn', () => {
    const basis = 'Aggregated: 12 of 40 bundles (≥ 3 trials each) · 0 raw lines drawn';
    expect(parallelBasis(basis, null)).toBe(basis);
    expect(parallelBasis(basis, 2)).toBe('Aggregated: 12 of 40 bundles (≥ 3 trials each) · 2 pinned trials drawn exactly');
    expect(parallelBasis(basis, 1)).toBe('Aggregated: 12 of 40 bundles (≥ 3 trials each) · 1 pinned trial drawn exactly');
  });

  it('the basis line carries only answered text: the answer verbatim, else the last answer of this source, never a loading literal', () => {
    const view = (basis: string): LabParallel => ({ axes: ['a'], bins: [], bundles: [], total_bundles: 0, shown_bundles: 0, basis });
    const first = { source: 'exp:e1', envelope: view('Aggregated: 12 of 40 bundles (≥ 3 trials each) · 0 raw lines drawn') };
    const next = { source: 'exp:e1', envelope: view('Aggregated: 9 of 21 bundles (≥ 1 trials each) · 0 raw lines drawn') };
    const line = (shown: typeof first | null) => (shown === null ? '' : parallelBasis(shown.envelope.basis, null));
    expect(line(answered(next, first, 'exp:e1'))).toBe(next.envelope.basis);
    // While a brush's answer is asked the line keeps the last one: it changes only when the new answer lands.
    expect(line(answered(null, first, 'exp:e1'))).toBe(first.envelope.basis);
    expect(line(answered(null, first, 'opt:j1'))).toBe('');
    expect(line(answered<typeof first>(null, null, 'exp:e1'))).toBe('');
    expect([line(answered(null, first, 'exp:e1')), line(null)].some((t) => /loading|updating/i.test(t))).toBe(false);
  });

  it('the summary names the bundles, the axes, the largest bundle and the best median', () => {
    const view: LabParallel = {
      axes: ['a', 'b', 'c'],
      bins: [],
      bundles: [
        { bins: [0, 0, 0], count: 40, median: -5 },
        { bins: [1, 0, 0], count: 12, median: 30 },
        { bins: [1, 1, 0], count: 3, median: null },
      ],
      total_bundles: 9,
      shown_bundles: 3,
      basis: '',
    };
    expect(parallelSummary(view, 'net_pnl', false, String)).toBe('parallel coordinates: 3 bundles over 3 axes, largest 40 trials, best median net_pnl 30');
    expect(parallelSummary(view, 'max_drawdown', true, String)).toBe('parallel coordinates: 3 bundles over 3 axes, largest 40 trials, best median max_drawdown -5');
    expect(parallelSummary({ ...view, bundles: [], shown_bundles: 0 }, 'net_pnl', false, String)).toBe('parallel coordinates: 0 bundles over 3 axes');
  });
});

// --- sample mode (spec §7.9, exact mode): a stratified sample of actual trials ----------------------------------------

/** The `parallel_mode = "sample"` answer: the bundle fields empty, the sample's own present. */
function sampleView(over: Partial<LabParallel> = {}): LabParallel {
  const lines: LabParallelLine[] = [
    { trial_id: 'exp:e1#4', values: [10, 0.5, null], metric: -120 },
    { trial_id: 'exp:e1#9', values: [20, 1, 3], metric: 40 },
    { trial_id: 'exp:e1#17', values: [30, 1.5, 4], metric: 900 },
  ];
  return {
    axes: ['a', 'b', 'c'],
    bins: [],
    bundles: [],
    total_bundles: 0,
    shown_bundles: 0,
    basis: 'Sampled 3 of 6904 (stratified by decile of net_pnl)',
    lines,
    sampled_from: 6904,
    metric: 'combined.net_pnl',
    strata: 10,
    seed: 1,
    excluded: 12,
    constants: { PARALLEL_MAX_LINES: 5000, PARALLEL_STRATA: 10 },
    ...over,
  };
}

describe('parallel coordinates in sample mode', () => {
  it('prints the server\'s basis line verbatim, and with pins appends only the pinned lines drawn exactly', () => {
    const basis = 'Sampled 4000 of 6904 (stratified by decile of net_pnl)';
    expect(parallelBasis(basis, null)).toBe(basis);
    expect(parallelBasis(basis, 2)).toBe(`${basis} · 2 pinned trials drawn exactly`);
    expect(parallelBasis(basis, 1)).toBe(`${basis} · 1 pinned trial drawn exactly`);
    // The bundles' tail ("0 raw lines drawn") is that mode's; the sample's basis has none to strip, nor to add.
    expect(parallelBasis('Sampled 5000 of 5000 (stratified by decile of mar)', null)).toBe('Sampled 5000 of 5000 (stratified by decile of mar)');
  });

  it('asks for bundles exactly as before, and for the sample only when it is chosen', () => {
    expect(parallelRequest('bundles', ['a', 'b'], 'net_pnl')).toEqual({ axes: ['a', 'b'], metric: 'net_pnl' });
    expect('parallel_mode' in parallelRequest('bundles', ['a', 'b'], 'net_pnl')).toBe(false); // the unchanged request of Phase 2
    expect(parallelRequest('sample', ['a', 'b'], 'net_pnl')).toEqual({ axes: ['a', 'b'], metric: 'net_pnl', parallel_mode: 'sample' });
  });

  it('tells a sample from bundles by its lines', () => {
    expect(isSampleView(sampleView())).toBe(true);
    expect(isSampleView({ axes: [], bins: [], bundles: [], total_bundles: 0, shown_bundles: 0, basis: '' })).toBe(false);
    expect(isSampleView(sampleView({ lines: [] }))).toBe(true); // an empty sample is still a sample
  });

  it('draws the best lines last so they stay on top: worst first, ties in the order they came', () => {
    const lines = sampleView().lines!;
    expect(sampleOrder(lines, false)).toEqual([0, 1, 2]);
    expect(sampleOrder([...lines].reverse(), false)).toEqual([2, 1, 0]);
    // Lower is better (a drawdown): the largest value is the worst and goes first.
    expect(sampleOrder(lines, true)).toEqual([2, 1, 0]);
    expect(sampleOrder([{ ...lines[0], metric: 5 }, { ...lines[1], metric: 5 }], false)).toEqual([0, 1]);
  });

  it('a sampled line runs through its own values; a value it lacks breaks it', () => {
    const axes = [linearScale([0, 10], [100, 0]), linearScale([0, 100], [100, 0])];
    expect(sampleLine([5, 25], axes, [20, 180])).toEqual([
      [20, 50],
      [180, 75],
    ]);
    expect(sampleLine([5, null], axes, [20, 180])).toEqual([[20, 50], null]);
    expect(sampleLine([], axes, [20, 180])).toEqual([null, null]);
  });

  it('the summary counts the sampled lines of the trials they were drawn from, never bundles', () => {
    const fmt = (v: number) => String(v);
    expect(parallelSummary(sampleView(), 'net_pnl', false, fmt)).toBe('parallel coordinates: 3 sampled lines of 6,904 trials over 3 axes, best net_pnl 900');
    expect(parallelSummary(sampleView(), 'max_drawdown', true, fmt)).toBe('parallel coordinates: 3 sampled lines of 6,904 trials over 3 axes, best max_drawdown -120');
    expect(parallelSummary(sampleView({ lines: [], sampled_from: 0 }), 'net_pnl', false, fmt)).toBe('parallel coordinates: 0 sampled lines of 0 trials over 3 axes');
  });

  it('says how the sample was drawn, and what it left out', () => {
    expect(sampleNote(sampleView())).toBe('a stratified sample, 10 strata by decile of net_pnl, seed 1; 12 trials with no net_pnl value are not drawn');
    expect(sampleNote(sampleView({ excluded: 0 }))).toBe('a stratified sample, 10 strata by decile of net_pnl, seed 1');
    expect(sampleNote({ axes: [], bins: [], bundles: [], total_bundles: 0, shown_bundles: 0, basis: '' })).toBe('');
  });
});
