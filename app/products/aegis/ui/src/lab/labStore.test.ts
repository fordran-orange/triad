import { describe, expect, it } from 'vitest';
import {
  activeFilterCount,
  canonicalFilter,
  filterHash,
  initialLabState,
  labReducer,
  parseSource,
  sourceText,
  type LabFilter,
  type LabState,
} from './labStore';

const EXP = { kind: 'exp', id: 'e1' } as const;

function filter(over: Partial<LabFilter> = {}): LabFilter {
  return { ...initialLabState.filter, ...over };
}

function state(over: Partial<LabState> = {}): LabState {
  return { ...initialLabState, ...over };
}

describe('initialLabState', () => {
  it('opens on the trial table with exact mode, the best statistic and the net_pnl metric', () => {
    expect(initialLabState.source).toBeNull();
    expect(initialLabState.sourceError).toBeNull();
    expect(initialLabState.view).toBe('trials');
    expect(initialLabState.mode).toBe('exact');
    expect(initialLabState.stat).toBe('best');
    expect(initialLabState.metric).toBe('net_pnl');
    expect(initialLabState.objectives).toEqual(['net_pnl', 'max_drawdown']);
    expect(initialLabState.filter).toEqual({ ranges: {}, values: {}, scope: 'combined', pass: [], status: [] });
    expect(initialLabState.axes).toBeNull();
    expect(initialLabState.selected).toBeNull();
    expect(initialLabState.pins).toEqual({});
    expect(initialLabState.cursor).toBeNull();
    expect(initialLabState.maximized).toBe(false);
  });
});

describe('parseSource and sourceText', () => {
  it('parses an experiment source', () => {
    expect(parseSource('exp:e1')).toEqual({ kind: 'exp', id: 'e1' });
  });

  it('parses an optimization job source', () => {
    expect(parseSource('opt:j1')).toEqual({ kind: 'opt', id: 'j1' });
  });

  it('returns null for text that is not a source', () => {
    expect(parseSource('nonsense')).toBeNull();
    expect(parseSource('')).toBeNull();
    expect(parseSource('exp:')).toBeNull();
    expect(parseSource('run:r1')).toBeNull();
  });

  it('keeps everything after the first colon as the id', () => {
    expect(parseSource('exp:a:b')).toEqual({ kind: 'exp', id: 'a:b' });
  });

  it('sourceText is the inverse of parseSource', () => {
    expect(sourceText(parseSource('exp:e1')!)).toBe('exp:e1');
    expect(sourceText(parseSource('opt:j1')!)).toBe('opt:j1');
    expect(sourceText({ kind: 'opt', id: 'x' })).toBe('opt:x');
  });
});

describe('labReducer OPEN_SOURCE', () => {
  it('resets the filter, selection, pins, cursor and source error, and keeps the view', () => {
    const dirty = state({
      source: { kind: 'opt', id: 'old' },
      sourceError: 'experiment not found: old',
      view: 'families',
      filter: filter({ ranges: { a: [1, 2] }, values: { b: 3 }, scope: 'long', pass: ['p'], status: ['done'] }),
      selected: { trials: ['t1'] },
      pins: { A: 't1' },
      cursor: { r: 4, c: 2 },
    });
    const next = labReducer(dirty, { type: 'OPEN_SOURCE', source: EXP });
    expect(next.source).toEqual(EXP);
    expect(next.sourceError).toBeNull();
    expect(next.view).toBe('families');
    expect(next.filter).toEqual(initialLabState.filter);
    expect(next.selected).toBeNull();
    expect(next.pins).toEqual({});
    expect(next.cursor).toBeNull();
  });

  it('keeps mode, stat and objectives, and keeps axes and metric when the action carries none', () => {
    const before = state({ mode: 'aggregate', stat: 'median', objectives: ['sharpe'], axes: ['x', 'y'], metric: 'sharpe' });
    const next = labReducer(before, { type: 'OPEN_SOURCE', source: EXP });
    expect(next.mode).toBe('aggregate');
    expect(next.stat).toBe('median');
    expect(next.objectives).toEqual(['sharpe']);
    expect(next.axes).toEqual(['x', 'y']);
    expect(next.metric).toBe('sharpe');
  });

  it('takes axes and metric when the action carries them', () => {
    const next = labReducer(initialLabState, { type: 'OPEN_SOURCE', source: EXP, axes: ['long_side.indicators.ema.length', 'long_side.indicators.sma.length'], metric: 'sharpe' });
    expect(next.axes).toEqual(['long_side.indicators.ema.length', 'long_side.indicators.sma.length']);
    expect(next.metric).toBe('sharpe');
  });

  // Review Focus 1: a job with fewer than three parameters still opens on its two axes and the dock's metric.
  it('OPEN_SOURCE from a two-parameter job opens on the job fast and slow paths and the dock metric', () => {
    const axes: [string, string] = ['long_side.indicators.fast.length', 'long_side.indicators.slow.length'];
    const next = labReducer(initialLabState, { type: 'OPEN_SOURCE', source: { kind: 'opt', id: 'j2' }, axes, metric: 'win_rate' });
    expect(next.source).toEqual({ kind: 'opt', id: 'j2' });
    expect(next.axes).toEqual(axes);
    expect(next.metric).toBe('win_rate');
    expect(next.sourceError).toBeNull();
  });

  it('takes only the axes when the metric is absent, and only the metric when the axes are absent', () => {
    const onlyAxes = labReducer(state({ metric: 'sharpe' }), { type: 'OPEN_SOURCE', source: EXP, axes: ['a', 'b'] });
    expect(onlyAxes.axes).toEqual(['a', 'b']);
    expect(onlyAxes.metric).toBe('sharpe');
    const onlyMetric = labReducer(state({ axes: ['x', 'y'] }), { type: 'OPEN_SOURCE', source: EXP, metric: 'win_rate' });
    expect(onlyMetric.axes).toEqual(['x', 'y']);
    expect(onlyMetric.metric).toBe('win_rate');
  });
});

describe('labReducer SOURCE_FAILED', () => {
  it('sets the error and clears the source', () => {
    const open = labReducer(initialLabState, { type: 'OPEN_SOURCE', source: EXP });
    const next = labReducer(open, { type: 'SOURCE_FAILED', message: 'experiment not found: e1' });
    expect(next.sourceError).toBe('experiment not found: e1');
    expect(next.source).toBeNull();
  });
});

describe('labReducer SET_*', () => {
  it('SET_VIEW changes nothing but the view', () => {
    const before = state({ filter: filter({ ranges: { a: [1, 2] } }), selected: { trials: ['t1'] }, pins: { B: 't1' }, cursor: { r: 1, c: 1 } });
    const next = labReducer(before, { type: 'SET_VIEW', view: 'variables' });
    expect(next).toEqual({ ...before, view: 'variables' });
  });

  it('SET_AXES, SET_MODE, SET_STAT and SET_METRIC set one field each', () => {
    expect(labReducer(initialLabState, { type: 'SET_AXES', axes: ['a', 'b'] })).toEqual({ ...initialLabState, axes: ['a', 'b'] });
    expect(labReducer(initialLabState, { type: 'SET_MODE', mode: 'aggregate' })).toEqual({ ...initialLabState, mode: 'aggregate' });
    expect(labReducer(initialLabState, { type: 'SET_STAT', stat: 'worst' })).toEqual({ ...initialLabState, stat: 'worst' });
    expect(labReducer(initialLabState, { type: 'SET_METRIC', metric: 'sharpe' })).toEqual({ ...initialLabState, metric: 'sharpe' });
  });

  it('SET_SCOPE sets the filter scope and leaves the rest of the filter alone', () => {
    const before = state({ filter: filter({ ranges: { a: [1, 2] } }) });
    const next = labReducer(before, { type: 'SET_SCOPE', scope: 'short' });
    expect(next.filter).toEqual({ ...before.filter, scope: 'short' });
  });
});

describe('labReducer SET_RANGE and FIX_VALUE', () => {
  it('SET_RANGE stores the pair', () => {
    const next = labReducer(initialLabState, { type: 'SET_RANGE', path: 'a', range: [2, 5] });
    expect(next.filter.ranges).toEqual({ a: [2, 5] });
  });

  it('SET_RANGE stores a reversed pair ordered', () => {
    const next = labReducer(initialLabState, { type: 'SET_RANGE', path: 'a', range: [9, 3] });
    expect(next.filter.ranges.a).toEqual([3, 9]);
  });

  it('SET_RANGE with null removes the key, leaving no undefined entry', () => {
    const before = state({ filter: filter({ ranges: { a: [1, 2], b: [3, 4] } }) });
    const next = labReducer(before, { type: 'SET_RANGE', path: 'a', range: null });
    expect(next.filter.ranges).toEqual({ b: [3, 4] });
    expect('a' in next.filter.ranges).toBe(false);
  });

  it('SET_RANGE does not mutate the previous state', () => {
    const before = state({ filter: filter({ ranges: { a: [1, 2] } }) });
    labReducer(before, { type: 'SET_RANGE', path: 'b', range: [3, 4] });
    labReducer(before, { type: 'SET_RANGE', path: 'a', range: null });
    expect(before.filter.ranges).toEqual({ a: [1, 2] });
  });

  it('FIX_VALUE stores the value, and null removes the key', () => {
    const fixed = labReducer(initialLabState, { type: 'FIX_VALUE', path: 'a', value: 7 });
    expect(fixed.filter.values).toEqual({ a: 7 });
    const cleared = labReducer(fixed, { type: 'FIX_VALUE', path: 'a', value: null });
    expect(cleared.filter.values).toEqual({});
    expect('a' in cleared.filter.values).toBe(false);
  });

  it('FIX_VALUE keeps a fixed zero', () => {
    const next = labReducer(initialLabState, { type: 'FIX_VALUE', path: 'a', value: 0 });
    expect(next.filter.values).toEqual({ a: 0 });
  });
});

describe('labReducer selection', () => {
  it('SELECT_TRIALS selects the ids', () => {
    const next = labReducer(initialLabState, { type: 'SELECT_TRIALS', ids: ['t1', 't2'] });
    expect(next.selected).toEqual({ trials: ['t1', 't2'] });
  });

  it('SELECT_SQUARE selects the square', () => {
    const next = labReducer(initialLabState, { type: 'SELECT_SQUARE', x: 3, y: 4 });
    expect(next.selected).toEqual({ square: { x: 3, y: 4 } });
  });

  it('a square replaces a trial selection and the trials replace a square', () => {
    const square = labReducer(state({ selected: { trials: ['t1'] } }), { type: 'SELECT_SQUARE', x: 0, y: 0 });
    expect(square.selected).toEqual({ square: { x: 0, y: 0 } });
    const trials = labReducer(square, { type: 'SELECT_TRIALS', ids: ['t2'] });
    expect(trials.selected).toEqual({ trials: ['t2'] });
  });

  it('CLEAR_SELECTION clears the selection and keeps the pins', () => {
    const next = labReducer(state({ selected: { trials: ['t1'] }, pins: { A: 't1' } }), { type: 'CLEAR_SELECTION' });
    expect(next.selected).toBeNull();
    expect(next.pins).toEqual({ A: 't1' });
  });
});

describe('labReducer PIN and UNPIN', () => {
  it('PIN puts the trial into the slot', () => {
    const next = labReducer(initialLabState, { type: 'PIN', slot: 'A', trialId: 't1' });
    expect(next.pins).toEqual({ A: 't1' });
  });

  it('PIN replaces the id the slot already holds', () => {
    const next = labReducer(state({ pins: { A: 't1' } }), { type: 'PIN', slot: 'A', trialId: 't2' });
    expect(next.pins).toEqual({ A: 't2' });
  });

  it('PIN is refused (same state object) while a square is selected', () => {
    const before = state({ selected: { square: { x: 1, y: 1 } } });
    expect(labReducer(before, { type: 'PIN', slot: 'A', trialId: 't1' })).toBe(before);
  });

  it('PIN is refused (same state object) when the slot already holds that id', () => {
    const before = state({ pins: { B: 't1' } });
    expect(labReducer(before, { type: 'PIN', slot: 'B', trialId: 't1' })).toBe(before);
  });

  it('PIN of an id another slot holds moves it and clears the old slot', () => {
    const next = labReducer(state({ pins: { A: 't1', B: 't2' } }), { type: 'PIN', slot: 'C', trialId: 't1' });
    expect(next.pins).toEqual({ B: 't2', C: 't1' });
    expect('A' in next.pins).toBe(false);
  });

  it('PIN moving an id onto an occupied slot replaces that slot and clears the old one', () => {
    const next = labReducer(state({ pins: { A: 't1', B: 't2' } }), { type: 'PIN', slot: 'B', trialId: 't1' });
    expect(next.pins).toEqual({ B: 't1' });
  });

  it('the three slots hold at most three distinct ids', () => {
    let s = initialLabState;
    for (const [slot, trialId] of [['A', 't1'], ['B', 't2'], ['C', 't3'], ['A', 't3'], ['B', 't1']] as const) {
      s = labReducer(s, { type: 'PIN', slot, trialId });
      const ids = Object.values(s.pins);
      expect(new Set(ids).size).toBe(ids.length);
      expect(ids.length).toBeLessThanOrEqual(3);
    }
    expect(s.pins).toEqual({ A: 't3', B: 't1' });
  });

  it('UNPIN empties the slot and leaves the others', () => {
    const next = labReducer(state({ pins: { A: 't1', B: 't2' } }), { type: 'UNPIN', slot: 'A' });
    expect(next.pins).toEqual({ B: 't2' });
    expect('A' in next.pins).toBe(false);
  });

  it('UNPIN of an empty slot returns the same state object', () => {
    const before = state({ pins: { B: 't2' } });
    expect(labReducer(before, { type: 'UNPIN', slot: 'A' })).toBe(before);
  });
});

describe('labReducer MOVE_CURSOR', () => {
  it('starts at (0, 0) when the cursor is null and applies the step', () => {
    const next = labReducer(initialLabState, { type: 'MOVE_CURSOR', dr: 1, dc: 2, rows: 5, cols: 5 });
    expect(next.cursor).toEqual({ r: 1, c: 2 });
  });

  it('stays at (0, 0) for a zero step from null', () => {
    const next = labReducer(initialLabState, { type: 'MOVE_CURSOR', dr: 0, dc: 0, rows: 5, cols: 5 });
    expect(next.cursor).toEqual({ r: 0, c: 0 });
  });

  it('moves relative to the current cursor', () => {
    const next = labReducer(state({ cursor: { r: 2, c: 3 } }), { type: 'MOVE_CURSOR', dr: -1, dc: 1, rows: 10, cols: 10 });
    expect(next.cursor).toEqual({ r: 1, c: 4 });
  });

  it('clamps to the last row and column', () => {
    const next = labReducer(state({ cursor: { r: 3, c: 3 } }), { type: 'MOVE_CURSOR', dr: 5, dc: 5, rows: 4, cols: 6 });
    expect(next.cursor).toEqual({ r: 3, c: 5 });
  });

  it('clamps to the first row and column', () => {
    const next = labReducer(state({ cursor: { r: 1, c: 1 } }), { type: 'MOVE_CURSOR', dr: -5, dc: -5, rows: 4, cols: 6 });
    expect(next.cursor).toEqual({ r: 0, c: 0 });
  });

  it('clamps to (0, 0) when there are no rows or columns', () => {
    const next = labReducer(initialLabState, { type: 'MOVE_CURSOR', dr: 1, dc: 1, rows: 0, cols: 0 });
    expect(next.cursor).toEqual({ r: 0, c: 0 });
  });
});

describe('labReducer ESCAPE', () => {
  it('clears every range and fixed value in one action', () => {
    const before = state({ filter: filter({ ranges: { a: [1, 2], b: [3, 4] }, values: { c: 5 }, scope: 'long', pass: ['p'], status: ['done'] }), maximized: true });
    const next = labReducer(before, { type: 'ESCAPE' });
    expect(next.filter.ranges).toEqual({});
    expect(next.filter.values).toEqual({});
    expect(next.filter.scope).toBe('long');
    expect(next.filter.pass).toEqual(['p']);
    expect(next.filter.status).toEqual(['done']);
    expect(next.maximized).toBe(true);
  });

  it('clears when only fixed values exist', () => {
    const next = labReducer(state({ filter: filter({ values: { c: 5 } }) }), { type: 'ESCAPE' });
    expect(next.filter.values).toEqual({});
  });

  it('un-maximizes when there is nothing to clear', () => {
    const next = labReducer(state({ maximized: true }), { type: 'ESCAPE' });
    expect(next.maximized).toBe(false);
  });

  // Review Focus 5: Esc with nothing to clear is a no-op, never a navigation.
  it('ESCAPE with nothing to clear is identity', () => {
    const before = state({ selected: { trials: ['t1'] }, pins: { A: 't1' } });
    expect(labReducer(before, { type: 'ESCAPE' })).toBe(before);
    expect(labReducer(initialLabState, { type: 'ESCAPE' })).toBe(initialLabState);
  });

  it('a scope, pass or status filter alone is not something ESCAPE clears', () => {
    const before = state({ filter: filter({ scope: 'short', pass: ['p'], status: ['done'] }) });
    expect(labReducer(before, { type: 'ESCAPE' })).toBe(before);
  });
});

describe('labReducer SET_MAXIMIZED and ROWS_REFRESHED', () => {
  it('SET_MAXIMIZED sets the flag', () => {
    expect(labReducer(initialLabState, { type: 'SET_MAXIMIZED', maximized: true }).maximized).toBe(true);
    expect(labReducer(state({ maximized: true }), { type: 'SET_MAXIMIZED', maximized: false }).maximized).toBe(false);
  });

  // Review Focus 3: a running experiment refreshes its rows; the selection and pins survive.
  it('ROWS_REFRESHED keeps selection and pins', () => {
    const before = state({ source: EXP, selected: { trials: ['t1', 't2'] }, pins: { A: 't1', C: 't2' }, cursor: { r: 2, c: 1 } });
    const next = labReducer(before, { type: 'ROWS_REFRESHED' });
    expect(next).toBe(before);
    expect(next.selected).toEqual({ trials: ['t1', 't2'] });
    expect(next.pins).toEqual({ A: 't1', C: 't2' });
  });
});

describe('canonicalFilter and filterHash', () => {
  it('filterHash is the same whatever order the ranges were set in', () => {
    const one = filter({ ranges: { a: [1, 2], b: [3, 4] } });
    const two = filter({ ranges: { b: [3, 4], a: [1, 2] } });
    expect(canonicalFilter(one)).toBe(canonicalFilter(two));
    expect(filterHash(one)).toBe(filterHash(two));
  });

  it('filterHash differs once a bound changes', () => {
    const one = filter({ ranges: { a: [1, 2], b: [3, 4] } });
    const two = filter({ ranges: { a: [1, 2], b: [3, 5] } });
    expect(filterHash(one)).not.toBe(filterHash(two));
  });

  it('filterHash differs for a range versus a fixed value, a scope, a pass and a status', () => {
    const hashes = new Set([
      filterHash(filter()),
      filterHash(filter({ ranges: { a: [1, 1] } })),
      filterHash(filter({ values: { a: 1 } })),
      filterHash(filter({ scope: 'long' })),
      filterHash(filter({ pass: ['p'] })),
      filterHash(filter({ status: ['p'] })),
    ]);
    expect(hashes.size).toBe(6);
  });

  it('pass and status are compared as sets', () => {
    expect(filterHash(filter({ pass: ['b', 'a'], status: ['y', 'x'] }))).toBe(filterHash(filter({ pass: ['a', 'b'], status: ['x', 'y'] })));
  });

  it('canonicalFilter does not reorder the caller\'s arrays', () => {
    const f = filter({ pass: ['b', 'a'] });
    canonicalFilter(f);
    expect(f.pass).toEqual(['b', 'a']);
  });

  it('filterHash is 8 lowercase hex characters', () => {
    expect(filterHash(initialLabState.filter)).toMatch(/^[0-9a-f]{8}$/);
    expect(filterHash(filter({ ranges: { a: [0.5, 1e9] }, scope: 'short', pass: ['é'] }))).toMatch(/^[0-9a-f]{8}$/);
  });

  it('filterHash is FNV-1a 32-bit over the canonical text', () => {
    const fnv = (text: string): string => {
      let h = 0x811c9dc5;
      for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
      }
      return h.toString(16).padStart(8, '0');
    };
    const f = filter({ ranges: { a: [1, 2] }, values: { b: 3 }, scope: 'long', pass: ['p'] });
    expect(filterHash(f)).toBe(fnv(canonicalFilter(f)));
  });
});

describe('activeFilterCount', () => {
  it('is 0 for the initial filter', () => {
    expect(activeFilterCount(initialLabState.filter)).toBe(0);
  });

  it('counts one range and a long scope as 2', () => {
    expect(activeFilterCount(filter({ ranges: { a: [1, 2] }, scope: 'long' }))).toBe(2);
  });

  it('counts ranges, fixed values, a non-combined scope, pass and status', () => {
    const f = filter({ ranges: { a: [1, 2], b: [3, 4] }, values: { c: 5 }, scope: 'short', pass: ['p', 'q'], status: ['done'] });
    expect(activeFilterCount(f)).toBe(2 + 1 + 1 + 2 + 1);
  });
});
