import { describe, expect, it } from 'vitest';
import type { ExperimentDocument } from '../contracts';
import type { Cell } from '../results';
import { effectiveOptAxes, isCurrent, isLive, jobPaths, matrixKeyOf, optMetric, optRow, sourceFamilies, statusOf, type LoadedSource, type OptJob } from './useLabSource';

const FAST = 'indicators.fast.length';
const SLOW = 'indicators.slow.length';
const RSI = 'indicators.rsi.length';

type Range = { path: string; start: number; stop: number; step: number };
const FAST_RANGE: Range = { path: FAST, start: 5, stop: 9, step: 1 };
const SLOW_RANGE: Range = { path: SLOW, start: 20, stop: 40, step: 5 };
const RSI_RANGE: Range = { path: RSI, start: 7, stop: 21, step: 7 };

/** A grid job cast through unknown, as optimizer.test.ts does: only the fields the helpers read are filled. The
 *  ranges are the plan of the job's side. */
function job(over: Record<string, unknown> = {}, ranges: Range[] = [FAST_RANGE, SLOW_RANGE]): OptJob {
  const side = (over.side as string | undefined) ?? 'long';
  return {
    job_id: 'j1',
    status: 'done',
    side,
    objective: 'net_pnl',
    cells: [],
    fast_path: FAST,
    slow_path: SLOW,
    fast_values: [5, 6, 7, 8, 9],
    slow_values: [20, 25, 30, 35, 40],
    strategy: { long_side: { optimization: side === 'long' ? ranges : [] }, short_side: { optimization: side === 'short' ? ranges : [] } },
    ...over,
  } as unknown as OptJob;
}

const cell = (params: Record<string, number>, metrics: Record<string, number | null>): Cell =>
  ({ params, fast: null, slow: null, metrics }) as unknown as Cell;

const expSource = (status: string): LoadedSource => ({
  kind: 'exp',
  id: 'e1',
  document: { status } as unknown as ExperimentDocument,
  report: null,
  strategyName: '9 EMA / 30 SMA Cross',
});
const optSource = (status: string): LoadedSource => ({ kind: 'opt', id: 'j1', job: job({ status }) });

describe('isLive', () => {
  it('is true for queued and running, and false for done, paused, cancelled and failed', () => {
    expect(isLive('queued')).toBe(true);
    expect(isLive('running')).toBe(true);
    for (const status of ['done', 'paused', 'cancelled', 'failed']) expect(isLive(status), status).toBe(false);
  });
});

describe('statusOf', () => {
  it("reads an experiment's status and an opt job's status alike", () => {
    for (const status of ['running', 'paused', 'done']) {
      expect(statusOf(expSource(status))).toBe(status);
      expect(statusOf(optSource(status))).toBe(status);
    }
  });
});

describe('isCurrent', () => {
  it('is true for the source the loaded one answers, and false when the source text differs', () => {
    const loaded = optSource('done'); // opt:j1
    expect(isCurrent(loaded, { kind: 'opt', id: 'j1' })).toBe(true);
    expect(isCurrent(loaded, { kind: 'opt', id: 'j2' })).toBe(false); // another id
    expect(isCurrent(loaded, { kind: 'exp', id: 'j1' })).toBe(false); // another kind
  });

  it('is false when either side is null', () => {
    expect(isCurrent(optSource('done'), null)).toBe(false);
    expect(isCurrent(null, { kind: 'opt', id: 'j1' })).toBe(false);
  });
});

describe('optRow', () => {
  const cells = [
    cell({ [FAST]: 5, [SLOW]: 20 }, { net_pnl: 120.5, mar: 1.5, max_drawdown: 0.1, trade_count: 4 }),
    cell({ [FAST]: 6, [SLOW]: 25 }, { net_pnl: NaN, mar: Infinity, max_drawdown: null, trade_count: 3 }),
  ];

  it('builds opt:<job>#<k> with the #k label, a copy of the params and the finite metrics', () => {
    const row = optRow(job({ cells }), 0);
    expect(row).toEqual({
      id: 'opt:j1#0',
      label: '#0',
      params: { [FAST]: 5, [SLOW]: 20 },
      values: { net_pnl: 120.5, mar: 1.5, max_drawdown: 0.1, trade_count: 4 },
      valid: null,
    });
    expect(row.params).not.toBe(cells[0].params);
  });

  it('keeps a null metric null and nulls a non-finite one', () => {
    const row = optRow(job({ cells }), 1);
    expect(row.id).toBe('opt:j1#1');
    expect(row.label).toBe('#1');
    expect(row.values).toEqual({ net_pnl: null, mar: null, max_drawdown: null, trade_count: 3 });
  });
});

describe('jobPaths', () => {
  it("lists the job side's planned parameters in plan order", () => {
    expect(jobPaths(job({}, [FAST_RANGE, SLOW_RANGE, RSI_RANGE]))).toEqual([FAST, SLOW, RSI]);
  });

  it('falls back to [fast_path, slow_path] when the plan holds one path', () => {
    expect(jobPaths(job({ fast_path: RSI }, [FAST_RANGE]))).toEqual([RSI, SLOW]);
  });
});

describe('effectiveOptAxes', () => {
  const three = job({}, [FAST_RANGE, SLOW_RANGE, RSI_RANGE]);

  it('keeps distinct store axes that both belong to the job', () => {
    expect(effectiveOptAxes(three, [RSI, FAST])).toEqual([RSI, FAST]);
  });

  it("otherwise falls back to the job's fast and slow paths", () => {
    expect(effectiveOptAxes(three, null)).toEqual([FAST, SLOW]);
    expect(effectiveOptAxes(three, [RSI, RSI])).toEqual([FAST, SLOW]); // not distinct
    expect(effectiveOptAxes(three, [RSI, 'indicators.other.length'])).toEqual([FAST, SLOW]); // one is not the job's
  });

  it("and, when those are not both the job's, to its first two paths", () => {
    const odd = job({ fast_path: RSI, slow_path: 'indicators.gone.length' }, [FAST_RANGE, SLOW_RANGE, RSI_RANGE]);
    expect(effectiveOptAxes(odd, null)).toEqual([FAST, SLOW]);
  });

  it('is null for a one-parameter job', () => {
    expect(effectiveOptAxes(job({ slow_path: '' }, [FAST_RANGE]), [FAST, SLOW])).toBeNull();
  });
});

describe('optMetric', () => {
  it('keeps one of the four optimizer metrics and clamps an unknown metric to job.objective', () => {
    const j = job({ objective: 'mar' });
    expect(optMetric(j, 'max_drawdown')).toBe('max_drawdown');
    expect(optMetric(j, 'trade_count')).toBe('trade_count');
    expect(optMetric(j, 'win_rate')).toBe('mar');
    expect(optMetric(j, '')).toBe('mar');
  });
});

describe('sourceFamilies', () => {
  it('of an opt job yields one family for its side, labelled with the parameter count', () => {
    for (const side of ['long', 'short'] as const) {
      const list = sourceFamilies({ kind: 'opt', id: 'j1', job: job({ side }) });
      expect(list).toHaveLength(1);
      expect(list[0].label).toBe(`${side} · grid job (2 parameters)`);
      expect(list[0].key).toBe(`${side}:job`);
      expect(list[0].entries.map((e) => [e.path, e.count])).toEqual([
        [FAST, 5],
        [SLOW, 5],
      ]);
    }
  });
});

describe('matrixKeyOf', () => {
  it('names the job, the pair and the metric, and is null without a pair or a metric', () => {
    expect(matrixKeyOf('j1', [FAST, SLOW], 'mar')).toBe(`j1|${FAST}|${SLOW}|mar`);
    expect(matrixKeyOf('j1', [SLOW, FAST], 'mar')).not.toBe(matrixKeyOf('j1', [FAST, SLOW], 'mar'));
    expect(matrixKeyOf('j1', null, 'mar')).toBeNull();
    expect(matrixKeyOf('j1', [FAST, SLOW], null)).toBeNull();
  });
});
