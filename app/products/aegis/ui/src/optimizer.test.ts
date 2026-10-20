import { describe, expect, it } from 'vitest';
import { formatSeconds } from './components/OptimizePopover';
import { axisChoices, needsConfirm, squareTitle } from './optimizer';
import type { Cell, JobStatus } from './results';

const describe_ = (params: Record<string, number>) =>
  Object.entries(params)
    .map(([path, v]) => `${path.split('.')[1].toUpperCase()} ${v}`)
    .join(' / ');

const cell = (params: Record<string, number>): Cell => ({ params, fast: null, slow: null, metrics: { net_pnl: 1, mar: null, max_drawdown: 0.1, trade_count: 3 } }) as unknown as Cell;

describe('optimizer helpers (the limits change)', () => {
  it('needsConfirm asks above ten minutes', () => {
    expect(needsConfirm(600)).toBe(false);
    expect(needsConfirm(601)).toBe(true);
  });

  it('axisChoices lists the enabled parameters of the job side, in plan order', () => {
    const job = {
      side: 'long',
      strategy: {
        long_side: {
          optimization: [
            { path: 'indicators.ema.length', start: 5, stop: 9, step: 1, enabled: true },
            { path: 'indicators.sma.length', start: 20, stop: 40, step: 5, enabled: false },
            { path: 'indicators.rsi.length', start: 7, stop: 21, step: 7, enabled: true },
          ],
        },
        short_side: { optimization: [] },
      },
    } as unknown as JobStatus;
    expect(axisChoices(job)).toEqual(['indicators.ema.length', 'indicators.rsi.length']);
  });

  it('squareTitle names how many cells a square holds and the rest of its best cell', () => {
    const best = cell({ 'indicators.ema.length': 5, 'indicators.sma.length': 20, 'indicators.rsi.length': 14 });
    const axes: [string, string] = ['indicators.ema.length', 'indicators.sma.length'];
    expect(squareTitle(9, best, axes, describe_)).toBe('best of 9 · RSI 14');
    expect(squareTitle(1, best, axes, describe_)).toBe('1 cell · RSI 14');
    expect(squareTitle(3, null, axes, describe_)).toBe('3 cells, none with a value');
    expect(squareTitle(0, null, axes, describe_)).toBe('no cells');
  });

  it('formatSeconds reads hours once a run passes an hour', () => {
    expect(formatSeconds(59)).toBe('59 s');
    expect(formatSeconds(125)).toBe('2 min 5 s');
    expect(formatSeconds(7380)).toBe('2 h 3 min');
  });
});
