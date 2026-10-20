import { describe, expect, it } from 'vitest';
import { formatSeconds } from './components/OptimizePopover';
import { axisChoices, axisLength, needsConfirm, squareTitle, tooManySquares } from './optimizer';
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

  it('axisLength counts the values of a parameter as the grid expands them', () => {
    const job = {
      side: 'short',
      strategy: { long_side: { optimization: [] }, short_side: { optimization: [{ path: 'indicators.ema.length', start: 5, stop: 50, step: 5, enabled: true }] } },
    } as unknown as JobStatus;
    expect(axisLength(job, 'indicators.ema.length')).toBe(10);
    expect(axisLength(job, 'indicators.sma.length')).toBe(0);
  });

  it('tooManySquares stops a matrix the page cannot draw and says what to do instead', () => {
    expect(tooManySquares(50, 50)).toBeNull();
    expect(tooManySquares(400, 250)).toBe('400 × 250 = 100,000 squares is more than the matrix draws (2,500): choose other parameters or a coarser step; the table lists every cell');
    expect(tooManySquares(3000, 0)).toBe('3,000 × 1 = 3,000 squares is more than the matrix draws (2,500): choose other parameters or a coarser step; the table lists every cell');
  });

  it('formatSeconds never reads 60 of a smaller unit', () => {
    expect(formatSeconds(7199)).toBe('2 h 0 min');
    expect(formatSeconds(119.6)).toBe('2 min 0 s');
  });
});
