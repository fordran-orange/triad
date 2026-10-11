import { describe, expect, it } from 'vitest';
import type { IndicatorSpec, RuleGroup, RuleSpec, StrategySide } from './contracts';
import { conditionsOf, describeRule, referencesOf, ruleReferences, warmupBars, warmupOf } from './rules';

const rule = (left: string, operator: string, right: string): RuleSpec => ({ left, operator, right, timing: 'bar_close' });

const reference: StrategySide = {
  direction: 'long',
  enabled: true,
  indicators: [
    { id: 'ema', kind: 'EMA', length: 9, source: 'close', overlay: true },
    { id: 'sma', kind: 'SMA', length: 30, source: 'close', overlay: true },
  ],
  entry: rule('ema', 'crosses_above', 'sma'),
  exit: rule('ema', 'crosses_below', 'sma'),
  optimization: [
    { path: 'indicators.ema.length', enabled: true, start: 5, stop: 20, step: 1 },
    { path: 'indicators.sma.length', enabled: true, start: 20, stop: 100, step: 5 },
  ],
};

const breakout: StrategySide = {
  ...reference,
  indicators: [
    { id: 'donchian', kind: 'DONCHIAN', length: 20, source: 'close', overlay: true },
    { id: 'rsi', kind: 'RSI', length: 14, source: 'close', overlay: true },
    { id: 'macd', kind: 'MACD', length: 12, source: 'close', overlay: true },
  ],
  entry: { all_of: [rule('price.close', 'crosses_above', 'donchian.upper'), rule('rsi', 'less_than', '70')] } as RuleGroup,
  exit: rule('price.close', 'crosses_below', 'donchian.middle'),
  optimization: [{ path: 'indicators.macd.params.slow', enabled: true, start: 20, stop: 40, step: 5 }],
};

describe('rule helpers', () => {
  it('names an indicator\'s series the way rules and the chart do', () => {
    expect(referencesOf(breakout.indicators![0] as IndicatorSpec)).toEqual(['donchian.upper', 'donchian.lower', 'donchian.middle']);
    expect(referencesOf(breakout.indicators![1] as IndicatorSpec)).toEqual(['rsi']);
  });

  it('computes warm-up per kind and over the ranges, as the Python side does', () => {
    expect(warmupOf({ id: 'r', kind: 'RSI', length: 14, source: 'close', overlay: true })).toBe(15);
    expect(warmupOf({ id: 'm', kind: 'macd', length: 12, source: 'close', overlay: true })).toBe(34);
    expect(warmupBars(reference)).toBe(100);
    expect(warmupBars(breakout)).toBe(40 + 9 - 1);
    expect(warmupBars(undefined)).toBe(0);
  });

  it('describes single rules and groups in words', () => {
    expect(describeRule(reference.entry, reference.indicators!)).toBe('EMA(9) crosses ABOVE SMA(30)');
    expect(describeRule(breakout.entry, breakout.indicators!)).toBe('price.close crosses ABOVE DONCHIAN(20).upper AND RSI(14) < 70');
    expect(describeRule({ any_of: [rule('rsi', 'greater_than', '30'), rule('price.close', 'outside_band', 'donchian')] } as RuleGroup, breakout.indicators!)).toBe(
      'RSI(14) > 30 OR price.close outside DONCHIAN(20)',
    );
    expect(conditionsOf(breakout.entry)).toHaveLength(2);
  });

  it('finds the rules that read an indicator', () => {
    expect(ruleReferences(breakout, 'donchian')).toEqual(['entry rule', 'exit rule']);
    expect(ruleReferences(breakout, 'rsi')).toEqual(['entry rule']);
    expect(ruleReferences(breakout, 'macd')).toEqual([]);
    expect(ruleReferences(reference, 'ema')).toEqual(['entry rule', 'exit rule']);
  });
});
