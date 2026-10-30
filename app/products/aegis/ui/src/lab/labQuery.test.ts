import { describe, expect, it } from 'vitest';
import { SHARPE_MIN_TRADES } from '../contracts';
import {
  METRICS,
  OBJECTIVES,
  type LabCandidateCard,
  type LabCategoryA,
  type LabCategoryB,
  type LabCategoryC,
  type LabCategoryD,
  type LabRankings,
  type LabRobustness,
  type LabRobustnessConstants,
  type LabRow,
  type LabSummary,
} from '../results';
import { cellIndex, filterHash, initialLabState, type LabFilter, type LabScope, type LabState } from './labStore';
import {
  datasetLabel,
  defaultSort,
  displayShare,
  dockChipText,
  emptyTableText,
  exactFixed,
  expMatrixKey,
  failedSource,
  handOverBody,
  isCandidateCard,
  isCurrentHash,
  kpiTrialsText,
  lowN,
  matchTrialByParams,
  metricList,
  optBody,
  optRowFromLab,
  pageKey,
  panelLabel,
  queryBody,
  SHARPE,
  snapshotLabel,
  stableEntry,
  statusLabel,
  tableValueColumns,
  undefinedLast,
} from './labQuery';

function filter(over: Partial<LabFilter> = {}): LabFilter {
  return { ...initialLabState.filter, ...over };
}

function state(over: Partial<LabState> = {}): LabState {
  return { ...initialLabState, ...over };
}

const SNAPSHOT = { generation: 3, chunk_watermark: 41 };
const AT = '2026-10-27T18:03:04Z';

function summary(over: Partial<LabSummary> = {}): LabSummary {
  return {
    source: 'exp:e1',
    kind: 'exp',
    layout: 2,
    status: 'done',
    counts: {} as LabSummary['counts'],
    parameters: [],
    headline: { objective: 'net_pnl', best: null, completed: 0, undefined: 0 },
    snapshots: { latest: SNAPSHOT },
    provisional: false,
    versions: null,
    data_pinned: null,
    engine: 'kernel',
    spec_values: null,
    filter_hash: null,
    ...over,
  };
}

function row(trialNo: number, value: number | null, over: Partial<LabRow> = {}): LabRow {
  return {
    trial_id: `exp:e1#${trialNo}`,
    trial_no: trialNo,
    cell: trialNo,
    params: { p: trialNo % 3 },
    values: { 'combined.net_pnl': value },
    valid: true,
    status: 'ok',
    pass: 'grid',
    design: 'uniform',
    ...over,
  };
}

describe('queryBody', () => {
  it('sets filter_hash from the store filterHash, whatever extra says', () => {
    const f = filter({ ranges: { p: [5, 10] }, scope: 'long' });
    const body = queryBody(state({ filter: f }), 'counts');
    expect(body.filter).toBe(f);
    expect(body.view).toBe('counts');
    expect(body.filter_hash).toBe(filterHash(f));
    expect(queryBody(state({ filter: f }), 'page', { filter_hash: 'deadbeef' }).filter_hash).toBe(filterHash(f));
  });

  it('a matrix body carries the axes, the metric, the mode and the stat, then the extra', () => {
    const body = queryBody(state({ axes: ['a', 'b'], metric: 'mar', mode: 'aggregate', stat: 'median' }), 'matrix', { fixed: { c: 3 } });
    expect(body).toMatchObject({ view: 'matrix', rows: 'a', cols: 'b', metric: 'mar', mode: 'aggregate', stat: 'median', fixed: { c: 3 } });
  });

  it("queryBody(state, 'page') never defaults the sort to *.sharpe_trade, even when lab.metric is sharpe_trade", () => {
    for (const view of ['page', 'top'] as const) {
      const body = queryBody(state({ metric: 'sharpe_trade' }), view);
      expect(body.sort ?? '').not.toMatch(/sharpe_trade/);
      expect(body.metric).not.toBe('sharpe_trade'); // the server's default sort is the metric's column
    }
    expect(queryBody(state({ metric: 'mar' }), 'page').metric).toBe('mar');
    // An explicit column the operator chose is not a default: it is sent as given.
    expect(queryBody(state({ metric: 'sharpe_trade' }), 'page', { sort: 'combined.sharpe_trade' }).sort).toBe('combined.sharpe_trade');
  });

  it("defaultSort orders by the metric in view, best first, and by the objective when that metric is sharpe_trade", () => {
    expect(defaultSort('combined', 'sharpe_trade', 'net_pnl')).toEqual({ column: 'combined.net_pnl', descending: true });
    expect(defaultSort('long', 'sharpe_trade', 'max_drawdown')).toEqual({ column: 'long.max_drawdown', descending: false });
    expect(defaultSort('short', 'mar', 'net_pnl')).toEqual({ column: 'short.mar', descending: true });
    expect(defaultSort('combined', 'max_drawdown', 'net_pnl')).toEqual({ column: 'combined.max_drawdown', descending: false });
    for (const scope of ['combined', 'long', 'short'] as const) {
      for (const objective of OBJECTIVES) expect(defaultSort(scope, 'sharpe_trade', objective).column).not.toMatch(/sharpe_trade/);
    }
  });
});

describe('exactFixed (the §7.1 default slice)', () => {
  const spec = { a: 1, b: 2, c: 3 };
  const axes: [string, string] = ['a', 'b'];

  it('is the spec values minus the two axes when nothing is selected, never null when spec values exist', () => {
    expect(exactFixed(null, spec, axes, {})).toEqual({ c: 3 });
    expect(exactFixed(null, { a: 1, b: 2 }, axes, {})).toEqual({});
  });

  it("prefers the selected trial's params", () => {
    expect(exactFixed({ a: 5, b: 6, c: 7 }, spec, axes, {})).toEqual({ c: 7 });
    expect(exactFixed({ a: 5, b: 6, c: 7 }, null, axes, {})).toEqual({ c: 7 });
  });

  it('a filter value on a non-axis path overrides both; an axis value is never fixed in the slice', () => {
    expect(exactFixed({ a: 5, b: 6, c: 7 }, spec, axes, { c: 9, a: 4 })).toEqual({ c: 9 });
    expect(exactFixed(null, spec, axes, { c: 9 })).toEqual({ c: 9 });
  });

  it('is null only when both the selection and the spec values are null', () => {
    expect(exactFixed(null, null, axes, {})).toBeNull();
  });

  it('expMatrixKey moves with the axes, the mode, the stat, the metric, the filter and the slice', () => {
    const base = state({ axes: ['a', 'b'] });
    const key = expMatrixKey('exp:e1', base, { c: 3 });
    expect(expMatrixKey('exp:e1', base, { c: 3 })).toBe(key);
    expect(expMatrixKey('exp:e1', state({ axes: ['b', 'a'] }), { c: 3 })).not.toBe(key);
    expect(expMatrixKey('exp:e1', state({ axes: ['a', 'b'], mode: 'aggregate' }), null)).not.toBe(key);
    expect(expMatrixKey('exp:e1', state({ axes: ['a', 'b'], metric: 'mar' }), { c: 3 })).not.toBe(key);
    expect(expMatrixKey('exp:e1', state({ axes: ['a', 'b'], filter: filter({ ranges: { c: [1, 2] } }) }), { c: 3 })).not.toBe(key);
    expect(expMatrixKey('exp:e1', base, { c: 4 })).not.toBe(key);
    expect(expMatrixKey('exp:e1', state(), null)).toBeNull();
  });
});

describe('isCurrentHash (the stale-discard rule of §7.8)', () => {
  it('keeps a response whose filter_hash is the store filter hash and drops a stale one', () => {
    const now = filter({ ranges: { p: [1, 2] } });
    expect(isCurrentHash({ filter_hash: filterHash(now) }, { filter: now })).toBe(true);
    expect(isCurrentHash({ filter_hash: filterHash(filter()) }, { filter: now })).toBe(false);
    expect(isCurrentHash({ filter_hash: null }, { filter: now })).toBe(false);
  });
});

describe('provisional labels', () => {
  it('snapshotLabel names the receipt time and the generation', () => {
    expect(snapshotLabel(SNAPSHOT, AT)).toBe('PROVISIONAL · snapshot 18:03:04 · gen 3');
    expect(snapshotLabel(null, AT)).toBe('PROVISIONAL · snapshot 18:03:04');
    expect(snapshotLabel(SNAPSHOT, '2026-10-27T18:03:04.512Z')).toBe('PROVISIONAL · snapshot 18:03:04 · gen 3');
  });

  it('statusLabel is the context bar form: n of N', () => {
    expect(statusLabel(SNAPSHOT, AT, 4210, 12000)).toBe('PROVISIONAL · snapshot 18:03:04 · 4,210 of 12,000');
    expect(/^PROVISIONAL · snapshot \d\d:\d\d:\d\d/.test(statusLabel(null, AT, 0, 9))).toBe(true); // the walk's regex
  });

  it('panelLabel is empty when not provisional, else the generation of the panel', () => {
    expect(panelLabel(null)).toBe('');
    expect(panelLabel({ provisional: false, snapshot: SNAPSHOT, receivedAt: AT })).toBe('');
    expect(panelLabel({ provisional: true, snapshot: SNAPSHOT, receivedAt: AT })).toBe(' · PROVISIONAL · snapshot 18:03:04 · gen 3');
  });
});

describe('pageKey', () => {
  it('changes with the filter, and not with the order its keys were set in', () => {
    const key = pageKey('exp:e1', 'combined.net_pnl', true, filter());
    expect(pageKey('exp:e1', 'combined.net_pnl', true, filter({ ranges: { p: [1, 2] } }))).not.toBe(key);
    expect(pageKey('exp:e1', 'combined.net_pnl', false, filter())).not.toBe(key);
    expect(pageKey('exp:e1', 'trial_no', true, filter())).not.toBe(key);
    const one = filter({ ranges: { a: [1, 2], b: [3, 4] } });
    const two = filter({ ranges: { b: [3, 4], a: [1, 2] } });
    expect(pageKey('exp:e1', 'trial_no', true, one)).toBe(pageKey('exp:e1', 'trial_no', true, two));
    expect(key).toBe(`exp:e1|combined.net_pnl|true|${filterHash(filter())}`);
  });
});

describe('dockChipText', () => {
  it('reads Exact slice for a two-parameter job and the aggregated text otherwise', () => {
    expect(dockChipText(2)).toBe('Exact slice');
    expect(dockChipText(3)).toBe('Aggregated: best of the rest');
    expect(dockChipText(10)).toBe('Aggregated: best of the rest');
  });
});

describe('kpiTrialsText', () => {
  it('returns the completed count and, with a filter, the filtered count as its sub line', () => {
    expect(kpiTrialsText(12000, 12000, 0)).toEqual({ primary: '12,000', sub: null });
    expect(kpiTrialsText(12000, 4210, 1)).toEqual({ primary: '12,000', sub: '4,210 filtered' });
    expect(kpiTrialsText(12000, 0, 2)).toEqual({ primary: '12,000', sub: '0 filtered' });
  });
});

describe('undefinedLast', () => {
  const rows = [row(0, 3), row(1, null), row(2, 5), row(3, 1), row(4, null), row(5, 3)];
  const order = (out: LabRow[]) => out.map((r) => r.trial_no);

  it('keeps nulls last both ways, ties in the order they came', () => {
    expect(order(undefinedLast(rows, 'combined.net_pnl', true))).toEqual([2, 0, 5, 3, 1, 4]);
    expect(order(undefinedLast(rows, 'combined.net_pnl', false))).toEqual([3, 0, 5, 2, 1, 4]);
  });

  it('reads a parameter, trial_no, and treats a non-finite or absent value as undefined', () => {
    expect(order(undefinedLast(rows, 'p', false))).toEqual([0, 3, 1, 4, 2, 5]);
    expect(order(undefinedLast(rows, 'trial_no', true))).toEqual([5, 4, 3, 2, 1, 0]);
    expect(order(undefinedLast([row(0, NaN), row(1, 2), row(2, Infinity)], 'combined.net_pnl', true))).toEqual([1, 0, 2]);
    expect(order(undefinedLast([row(0, 1), row(1, 2)], 'combined.mar', true))).toEqual([0, 1]);
  });

  it('does not reorder the input array', () => {
    const copy = [...rows];
    undefinedLast(rows, 'combined.net_pnl', true);
    expect(rows).toEqual(copy);
  });
});

describe('metricList', () => {
  it('lists the ten objectives for an experiment and adds sharpe_trade only for layout 2', () => {
    expect(metricList('exp', summary({ layout: 2 }))).toEqual([...OBJECTIVES, 'sharpe_trade']);
    expect(metricList('exp', summary({ layout: 1 }))).toEqual([...OBJECTIVES]);
    expect(metricList('exp', null)).toEqual([...OBJECTIVES]);
  });

  it('lists the optimizer metrics for a grid job', () => {
    expect(metricList('opt', summary({ kind: 'opt', layout: null }))).toEqual([...METRICS]);
    expect(metricList('opt', null)).toEqual([...METRICS]);
  });
});

describe('datasetLabel', () => {
  it('says the provenance was not recorded for a layout-1 source', () => {
    expect(datasetLabel(summary({ layout: 1 }))).toBe('data provenance not recorded');
  });

  it('names the pinned archive by its sha256 prefix and its vintage otherwise', () => {
    const pinned = { source: 'raw_archive' as const, sha256: 'ad3cdc78a91c9ba3bd16a9e42ae3a806', vintage: '20260919T233952760505Z' };
    expect(datasetLabel(summary({ layout: 2, data_pinned: pinned }))).toBe('ad3cdc78a91c · vintage 20260919T233952760505Z');
    expect(datasetLabel(summary({ layout: 2, data_pinned: null }))).toBe('data provenance not recorded');
    expect(datasetLabel(summary({ layout: 2, data_pinned: { source: 'raw_archive', sha256: undefined, vintage: 'DEMO synthetic' } }))).toBe('vintage DEMO synthetic');
    expect(datasetLabel(summary({ kind: 'opt', layout: null, data_pinned: pinned }))).toBe('ad3cdc78a91c · vintage 20260919T233952760505Z');
    expect(datasetLabel(null)).toBe('');
  });
});

describe('emptyTableText', () => {
  it('reads 0 of N match with the chip lines', () => {
    expect(emptyTableText(12000, filter({ ranges: { p: [5, 10] } }))).toBe('0 of 12,000 match: p ∈ [5, 10]');
    expect(emptyTableText(12000, filter({ ranges: { p: [5, 10] }, values: { q: 3 }, status: ['invalid'] }))).toBe('0 of 12,000 match: p ∈ [5, 10], q = 3, status: invalid');
  });
});

describe('lowN', () => {
  it('flags fewer than SHARPE_MIN_TRADES trades', () => {
    expect(SHARPE_MIN_TRADES).toBe(20);
    expect(lowN(19)).toBe(true);
    expect(lowN(20)).toBe(false);
    expect(lowN(0)).toBe(true);
  });
});

describe('tableValueColumns', () => {
  it('lists the objective, net P&L, drawdown, trades and exposure, and the trade Sharpe only for layout 2', () => {
    expect(tableValueColumns('long', 'mar', 1)).toEqual(['long.mar', 'long.net_pnl', 'long.max_drawdown', 'long.trade_count', 'long.exposure']);
    expect(tableValueColumns('combined', 'net_pnl', 2)).toEqual(['combined.net_pnl', 'combined.max_drawdown', 'combined.trade_count', 'combined.exposure', 'combined.sharpe_trade']);
  });

  it('sharpeNeverAlone: whenever the trade Sharpe is a column, net P&L, drawdown, trades and exposure are too', () => {
    let seen = 0;
    for (const scope of ['combined', 'long', 'short'] as LabScope[]) {
      for (const objective of OBJECTIVES) {
        for (const layout of [1, 2] as const) {
          const columns = tableValueColumns(scope, objective, layout);
          if (!columns.includes(`${scope}.sharpe_trade`)) continue;
          seen += 1;
          for (const metric of ['net_pnl', 'max_drawdown', 'trade_count', 'exposure']) expect(columns, `${scope} ${objective}`).toContain(`${scope}.${metric}`);
          expect(columns[0]).toBe(`${scope}.${objective}`);
        }
      }
    }
    expect(seen).toBe(3 * OBJECTIVES.length);
  });
});

describe('the optimizer source on /lab', () => {
  it('optBody forces the side and prefixes the job paths, keeping the filter_hash', () => {
    const f = filter({ ranges: { 'indicators.ema.length': [5, 6] }, values: { 'indicators.sma.length': 20 } });
    const body = optBody(queryBody(state({ filter: f, axes: ['indicators.ema.length', 'indicators.sma.length'] }), 'matrix'), 'short');
    expect(body.filter).toEqual({ ...f, scope: 'short', ranges: { 'short_side.indicators.ema.length': [5, 6] }, values: { 'short_side.indicators.sma.length': 20 } });
    expect(body.filter_hash).toBe(filterHash(f));
    expect([body.rows, body.cols]).toEqual(['short_side.indicators.ema.length', 'short_side.indicators.sma.length']);
    expect(optBody(queryBody(state(), 'page', { sort: 'trial_no' }), 'long').sort).toBe('trial_no');
    expect(optBody(queryBody(state(), 'page', { sort: 'long.mar' }), 'long').sort).toBe('long.mar');
    expect(optBody(queryBody(state(), 'page', { sort: 'long_side.indicators.ema.length' }), 'long').sort).toBe('long_side.indicators.ema.length');
    expect(optBody(queryBody(state(), 'page', { sort: 'indicators.ema.length' }), 'long').sort).toBe('long_side.indicators.ema.length');
  });

  it("optRowFromLab gives the Phase 1 job row: the job's paths and the side's metrics by name", () => {
    const lab: LabRow = row(4, null, {
      trial_id: 'opt:j1#4',
      params: { 'long_side.indicators.ema.length': 6 },
      values: { 'long.net_pnl': 12, 'long.trade_count': 3 },
    });
    expect(optRowFromLab(lab, 'long')).toEqual({ id: 'opt:j1#4', label: '#4', params: { 'indicators.ema.length': 6 }, values: { net_pnl: 12, trade_count: 3 }, valid: null });
  });
});

describe('failedSource (the X state of a source that would not open)', () => {
  it('names the source the message starts with, or null', () => {
    expect(failedSource('exp:does-not-exist: 404: experiment does-not-exist not found')).toBe('exp:does-not-exist');
    expect(failedSource('opt:j1: 500: boom')).toBe('opt:j1');
    expect(failedSource('bogus: not a Lab source (exp:<id> or opt:<id>)')).toBeNull();
    expect(failedSource(null)).toBeNull();
  });
});

describe('a grid job above CELLS_SENT: the dock list is the best cells re-ordered, the /lab frame is every cell', () => {
  // The /lab frame numbers a job's trials by evaluation order; the dock's (and GET /optimize's) list is its best
  // cells by the objective. The two orders differ, so an index into one is never a trial number of the other.
  const frame: LabRow[] = [
    row(0, -5, { trial_id: 'opt:j1#0', params: { 'long_side.indicators.ema.length': 5, 'long_side.indicators.sma.length': 20 } }),
    row(1, 7, { trial_id: 'opt:j1#1', params: { 'long_side.indicators.ema.length': 6, 'long_side.indicators.sma.length': 20 } }),
    row(2, 9, { trial_id: 'opt:j1#2', params: { 'long_side.indicators.ema.length': 6, 'long_side.indicators.sma.length': 25 } }),
  ];
  const bestList = [
    { params: { 'indicators.ema.length': 6, 'indicators.sma.length': 25 } },
    { params: { 'indicators.ema.length': 6, 'indicators.sma.length': 20 } },
    { params: { 'indicators.ema.length': 5, 'indicators.sma.length': 20 } },
  ];

  it("matchTrialByParams resolves the dock's selected best-list entry to its /lab trial by params, not by index", () => {
    const selected = bestList[0].params; // the dock's first row: the best cell
    expect(cellIndex(bestList, selected)).toBe(0); // its place in the dock's list...
    const found = matchTrialByParams(frame, selected, 'long');
    expect(found?.trial_id).toBe('opt:j1#2'); // ...is trial 2 in the frame
    expect(matchTrialByParams([...frame].reverse(), bestList[2].params, 'long')?.trial_id).toBe('opt:j1#0'); // whatever order the rows came in
  });

  it('matches the same keys and the same numbers only', () => {
    expect(matchTrialByParams(frame, { 'indicators.ema.length': 7, 'indicators.sma.length': 20 }, 'long')).toBeNull();
    expect(matchTrialByParams(frame, { 'indicators.ema.length': 6 }, 'long')).toBeNull(); // a key missing
    expect(matchTrialByParams(frame, { ...bestList[0].params, 'indicators.rsi.length': 14 }, 'long')).toBeNull(); // a key extra
    expect(matchTrialByParams(frame, bestList[0].params, 'short')).toBeNull(); // the other side's paths
    expect(matchTrialByParams([], bestList[0].params, 'long')).toBeNull();
  });

  it('handOverBody asks the job side for that configuration, its paths prefixed', () => {
    const body = handOverBody(bestList[0].params, 'long');
    expect(body.view).toBe('page');
    expect(body.filter).toEqual({
      ranges: {},
      values: { 'long_side.indicators.ema.length': 6, 'long_side.indicators.sma.length': 25 },
      scope: 'long',
      pass: [],
      status: [],
    });
    expect(body.sort).toBe('trial_no');
  });

  it('a /lab row becomes the rail card row with its own trial id, params and values', () => {
    expect(optRowFromLab(frame[2], 'long')).toEqual({
      id: 'opt:j1#2',
      label: '#2',
      params: { 'indicators.ema.length': 6, 'indicators.sma.length': 25 },
      values: { 'combined.net_pnl': 9 },
      valid: null,
    });
  });
});

// --- Phase 3: the request bodies of the analytics views, and the helpers their panels share -----------------------

describe('the Phase 3 requests (queryBody and optBody)', () => {
  it('optBody prefixes axes and leaves objectives bare', () => {
    // The worker reads `objectives` as metric names in the filter's scope: a prefixed one answers 422.
    const sent = queryBody(state(), 'pareto', { objectives: ['net_pnl', 'max_drawdown'], axes: ['indicators.ema.length', 'indicators.sma.length'] });
    const body = optBody(sent, 'long');
    expect(body.objectives).toEqual(['net_pnl', 'max_drawdown']);
    expect(body.axes).toEqual(['long_side.indicators.ema.length', 'long_side.indicators.sma.length']);
    expect(body.filter.scope).toBe('long');
    expect(sent.objectives).toEqual(['net_pnl', 'max_drawdown']); // the input is left alone
  });

  it('optBody leaves a trial id, the seed, k, the parallel mode and rerun as the panel sent them', () => {
    const sent = queryBody(state(), 'robustness', { trial: 'opt:j1#4', seed: 7, k: 12, parallel_mode: 'sample', rerun: true });
    expect(optBody(sent, 'short')).toMatchObject({ trial: 'opt:j1#4', seed: 7, k: 12, parallel_mode: 'sample', rerun: true });
  });

  it('queryBody carries the new arguments, and sends none of them unless a panel asks', () => {
    const body = queryBody(state(), 'importance', { seed: 3, rerun: true });
    expect(body).toMatchObject({ view: 'importance', seed: 3, rerun: true });
    const plain = queryBody(state(), 'importance');
    for (const name of ['seed', 'rerun', 'trial', 'objectives', 'parallel_mode', 'k'] as const) expect(name in plain).toBe(false);
    expect(queryBody(state(), 'parallel', { parallel_mode: 'sample', axes: ['a', 'b'], k: 500 })).toMatchObject({ parallel_mode: 'sample', axes: ['a', 'b'], k: 500 });
    expect(queryBody(state(), 'neighbourhood', { trial: 'exp:e1#9' }).trial).toBe('exp:e1#9');
  });

  it("a poll never asks for a rerun: only the panel's Run again sets it", () => {
    const poll = queryBody(state({ metric: 'net_pnl' }), 'interactions', { seed: 1 });
    expect(poll.rerun).toBeUndefined();
    expect(optBody(poll, 'long').rerun).toBeUndefined();
  });

  it('pareto ranks trials by its objectives, so the trade Sharpe is never sent as its default metric', () => {
    const sharpe = state({ metric: SHARPE });
    expect(queryBody(sharpe, 'pareto', { objectives: ['net_pnl', 'max_drawdown'] }).metric).toBeUndefined();
    expect(queryBody(state({ metric: 'mar' }), 'pareto', { objectives: ['net_pnl', 'max_drawdown'] }).metric).toBe('mar');
    // The views that read the metric in view still send the trade Sharpe when that is the metric.
    for (const view of ['importance', 'robustness', 'convergence', 'parallel'] as const) expect(queryBody(sharpe, view).metric).toBe(SHARPE);
    for (const view of ['page', 'top'] as const) expect(queryBody(sharpe, view).metric).toBeUndefined();
  });
});

describe('displayShare (a share is shown at 0 or above; the stored value stays as the server sent it)', () => {
  it('clamps a negative share at 0 and leaves the rest', () => {
    expect(displayShare(-0.004)).toBe(0);
    expect(Object.is(displayShare(-0), 0)).toBe(true);
    expect(displayShare(0)).toBe(0);
    expect(displayShare(0.0123)).toBe(0.0123);
    expect(displayShare(1.07)).toBe(1.07); // a share above 1 is not clamped
  });

  it('keeps an undefined share undefined: null is never shown as 0', () => {
    expect(displayShare(null)).toBeNull();
  });

  it('does not change what it was given', () => {
    const shares = Object.freeze([-0.01, 0.2]);
    expect(shares.map((share) => displayShare(share))).toEqual([0, 0.2]);
    expect(shares).toEqual([-0.01, 0.2]);
  });
});

describe('robustness answers one of two exclusive shapes', () => {
  const CONSTANTS: LabRobustnessConstants = {
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
  const A: LabCategoryA = {
    name: 'A',
    resolved: true,
    classification: 'stable local',
    reason: null,
    inputs: {
      n: 7, valid: 7, tested: 7, undefined: 0, coverage: 1, min_coverage: 0.5, required_n: 7, r: 1, m: 1, probes: 7, valid_basis: 'frame',
      p25: 1.39, p75: 1.73, iqr: 0.34, tau: 0.69, value: 1.26, distance: 0.13, peak_factor: 3, peak_line: 2.74, orientation: 1,
    },
  };
  const B: LabCategoryB = {
    name: 'B',
    resolved: false,
    classification: null,
    reason: 'importance not computed for this snapshot',
    inputs: {
      axes: [], radius: 0.15, n: 0, min_n: 30, population: null, region_share: null, density: null, adaptive_excluded: 0, undefined: 0,
      p25: null, p75: null, iqr: null, tau: 0.69, value: 1.26, distance: null, orientation: 1,
    },
  };
  const C: LabCategoryC = {
    name: 'C',
    resolved: false,
    classification: null,
    reason: 'no blocks or folds',
    inputs: { folds: 0, folds_min: 3, fold_min_trades: 30, ratio_band: [0.5, 2], drawdown_factor: 1.5, blocks: 0 },
  };
  const D: LabCategoryD = {
    name: 'D',
    resolved: false,
    classification: null,
    reason: 'no replay yet (stage 2)',
    inputs: { scenarios: [], stress_keep: 0.7, drawdown_factor: 1.3, base: null, stressed: null, ratio: null },
  };
  const card: LabCandidateCard = {
    trial_id: 'exp:e1#5',
    trial_no: 5,
    metric: 'net_pnl',
    scope: 'combined',
    value: 1.26,
    orientation: 1,
    tolerance: 0.15,
    tolerance_label: null,
    tau: 0.69,
    categories: { A, B, C, D },
    tested: ['A'],
    unknown: ['B', 'C', 'D'],
    findings: [],
  };
  const rankings: LabRankings = {
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
  };
  const common = { tolerance: 0.15, tolerance_label: null, axes: [], constants: CONSTANTS };
  const cardAnswer: LabRobustness = { ...common, card, rankings: null };
  const rankingsAnswer: LabRobustness = { ...common, card: null, rankings };

  // Reading the other shape's field after the guard is a compile error, so the build checks the narrowing too.
  const read = (answer: LabRobustness) => (isCandidateCard(answer) ? `card of ${answer.card.trial_id}` : `rankings of ${answer.rankings.k}`);

  it('isCandidateCard is true for a trial asked for and false for the rankings', () => {
    expect(isCandidateCard(cardAnswer)).toBe(true);
    expect(isCandidateCard(rankingsAnswer)).toBe(false);
  });

  it('narrows to the field the answer carries', () => {
    expect(read(cardAnswer)).toBe('card of exp:e1#5');
    expect(read(rankingsAnswer)).toBe('rankings of 20');
  });

  it('stableEntry finds the stable candidate in either list, and tolerates one that is in neither', () => {
    expect(stableEntry(rankings)?.trial_id).toBe('exp:e1#710');
    // `stable` is chosen from the whole pool: it may sit past the k rows listed, or among the peak rows alone.
    const peakOnly: LabRankings = { ...rankings, ranked: rankings.ranked.slice(1), stable: 'exp:e1#710', peak_ranked: [rankings.peak_ranked[1]] };
    expect(stableEntry(peakOnly)?.trial_id).toBe('exp:e1#710');
    const outside: LabRankings = { ...rankings, ranked: [], peak_ranked: [], stable: 'exp:e1#999' };
    expect(stableEntry(outside)).toBeNull();
    expect(stableEntry({ ...rankings, stable: null, stable_reason: 'none among the top 300 by peak' })).toBeNull();
  });
});
