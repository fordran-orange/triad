import { describe, expect, it } from 'vitest';
import type { WindowRecord } from '../results';
import { defaultWindowBars, finalChoice, stitchedPoints } from './WalkForwardTab';

const record = (index: number, status: WindowRecord['status'], equities: number[], params: Record<string, number> | null): WindowRecord =>
  ({
    index,
    status,
    is_start: `is${index}`,
    is_end: `ie${index}`,
    oos_start: `os${index}`,
    oos_end: `oe${index}`,
    is_bars: 10,
    oos_bars: equities.length,
    cells_evaluated: 4,
    best: params ? { params, metrics: {} } : null,
    oos: status === 'done' ? { trades: [], equity: equities.map((e, i) => ({ timestamp: `t${index}-${i}`, equity: e, drawdown: 0 })), metrics: {} } : null,
    efficiency: null,
  }) as unknown as WindowRecord;

describe('walk-forward helpers', () => {
  it('defaultWindowBars proposes 40% / 10% of the loaded bars with the spec floors', () => {
    expect(defaultWindowBars(502, 30)).toEqual({ inSample: 201, outOfSample: 50 });
    expect(defaultWindowBars(null, 30)).toEqual({ inSample: 250, outOfSample: 63 });
    expect(defaultWindowBars(100, 100)).toEqual({ inSample: 135, outOfSample: 20 }); // floors: 35 + longest, 20
  });

  it('stitchedPoints concatenates done windows in order and marks window starts', () => {
    const records = [record(0, 'done', [1, 2, 3], { a: 1 }), record(1, 'pending', [9, 9], null), record(2, 'done', [4, 5], { a: 2 })];
    const { points, boundaries } = stitchedPoints(records);
    expect(points.map((p) => p.equity)).toEqual([1, 2, 3, 4, 5]);
    expect(boundaries).toEqual([0, 3]);
    expect(stitchedPoints([]).points).toEqual([]);
  });

  it('finalChoice is the last done window\'s configuration, null when none', () => {
    const records = [record(0, 'done', [1], { a: 1 }), record(1, 'done', [1], { a: 7 }), record(2, 'pending', [1], null)];
    expect(finalChoice(records)).toEqual({ a: 7 });
    expect(finalChoice([record(0, 'no_valid_cell', [], null)])).toBeNull();
  });
});
