import { describe, expect, it } from 'vitest';
import type { RuleSpec, StrategySide, StrategySpec } from '../contracts';
import { defaultRanges } from '../state/workspace';
import { applyReading, levelRange } from './apply';

const rule = (left: string, operator: string, right: string): RuleSpec => ({ left, operator, right, timing: 'bar_close' });
const indicator = (id: string, kind: string, length: number) => ({ id, kind, length, source: 'close', overlay: true });
const side = (direction: 'long' | 'short'): StrategySide => ({
  direction,
  enabled: true,
  indicators: [indicator('ema', 'EMA', 9), indicator('sma', 'SMA', 30)],
  entry: rule('ema', direction === 'long' ? 'crosses_above' : 'crosses_below', 'sma'),
  exit: rule('ema', direction === 'long' ? 'crosses_below' : 'crosses_above', 'sma'),
  optimization: [
    { path: 'indicators.ema.length', enabled: true, start: 5, stop: 20, step: 1 },
    { path: 'indicators.sma.length', enabled: true, start: 20, stop: 100, step: 5 },
  ],
});
const reference = { id: 'ref', name: 'ref', version: 1, description: '', long_side: side('long'), short_side: side('short') } as unknown as StrategySpec;

describe('applyReading', () => {
  it("replaces the sentence's side, gives each new indicator its default ranges and badges the default levels", () => {
    const long: StrategySide = {
      direction: 'long',
      enabled: true,
      indicators: [indicator('ema', 'EMA', 9), indicator('sma30', 'SMA', 30), indicator('sma200', 'SMA', 200)],
      entry: { all_of: [rule('ema', 'crosses_above', 'sma30'), rule('price.close', 'greater_than', 'sma200')] },
      optimization: [],
      stop_loss_pct: 2,
      take_profit_pct: 5,
    };
    const { strategy, graphs } = applyReading(reference, { sides: { long_side: long }, reading: '', defaults: ['long_side.stop_loss_pct', 'long_side.take_profit_pct'] });
    const ranges = strategy.long_side.optimization!;
    for (const spec of long.indicators!) for (const range of defaultRanges(spec)) expect(ranges).toContainEqual(range);
    expect(ranges.filter((r) => r.path === 'stop_loss_pct' || r.path === 'take_profit_pct').every((r) => r.enabled === false)).toBe(true);
    expect(strategy.short_side).toBe(reference.short_side);
    expect(Object.keys(graphs)).toEqual(['long']);
    const levels = graphs.long!.blocks.filter((b) => b.type === 'stop_loss' || b.type === 'take_profit');
    expect(levels.map((b) => [b.type, b.settings.pct, b.settings.badge])).toEqual([
      ['stop_loss', 2, 'default'],
      ['take_profit', 5, 'default'],
    ]);
  });

  it('keeps the ranges of a reused indicator and adds them for a new one', () => {
    const long: StrategySide = { ...reference.long_side, indicators: [...reference.long_side.indicators!, indicator('rsi', 'RSI', 14)], exit: rule('rsi', 'greater_than', '70') };
    const { strategy, graphs } = applyReading(reference, { sides: { long_side: long }, reading: '', defaults: [] });
    const paths = strategy.long_side.optimization!.map((r) => r.path);
    expect(paths.slice(0, 2)).toEqual(['indicators.ema.length', 'indicators.sma.length']);
    expect(strategy.long_side.optimization!.slice(0, 2)).toEqual(reference.long_side.optimization);
    expect(paths).toContain('indicators.rsi.length');
    expect(graphs.long!.blocks.some((b) => b.settings.badge)).toBe(false);
  });
});

describe('levelRange (Mission 13 review I1)', () => {
  const LEVELS = ['stop_loss_pct', 'take_profit_pct'] as const;

  it.each([0.05, 0.1, 0.2, 0.25, 2, 60])('gives a %s%% stop or target a range the server accepts: start ≤ stop, step > 0', (pct) => {
    for (const path of LEVELS) {
      const range = levelRange(path, pct);
      expect(range.enabled).toBe(false);
      expect(range.start).toBeGreaterThan(0);
      expect(range.start).toBeLessThanOrEqual(range.stop);
      expect(range.step).toBeGreaterThan(0);
      if (path === 'stop_loss_pct') expect(range.stop).toBeLessThan(100);
    }
  });

  it('mirrors defaultRanges: half the value to twice it in quarter steps, a stop loss clamped below 100', () => {
    expect(levelRange('stop_loss_pct', 0.2)).toEqual({ path: 'stop_loss_pct', enabled: false, start: 0.1, stop: 0.4, step: 0.05 });
    expect(levelRange('take_profit_pct', 60)).toEqual({ path: 'take_profit_pct', enabled: false, start: 30, stop: 120, step: 15 });
    expect(levelRange('stop_loss_pct', 60)).toEqual({ path: 'stop_loss_pct', enabled: false, start: 30, stop: 99, step: 15 });
  });
});
