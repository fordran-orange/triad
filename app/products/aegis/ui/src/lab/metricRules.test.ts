import { describe, expect, it } from 'vitest';
import { breakEven, lossTone, losesMoney, lowerIsBetter, objectiveText, orientationOf, profitKind } from './metricRules';

describe('profitKind and breakEven (where a metric stops losing money)', () => {
  it('the money-signed metrics break even at 0 and the profit factor at 1', () => {
    for (const metric of ['net_pnl', 'net_return', 'cagr', 'mar', 'expectancy', 'sharpe_trade']) {
      expect(profitKind(metric), metric).toBe('sign');
      expect(breakEven(metric), metric).toBe(0);
    }
    expect(profitKind('profit_factor')).toBe('ratio');
    expect(breakEven('profit_factor')).toBe(1);
  });

  it('a metric with no profit sign has no break-even', () => {
    for (const metric of ['max_drawdown', 'win_rate', 'trade_count', 'exposure', 'nonsense']) {
      expect(profitKind(metric), metric).toBeNull();
      expect(breakEven(metric), metric).toBeNull();
    }
  });
});

describe('losesMoney and lossTone are one rule (a loss is red, break-even is neutral, a gain is a gain)', () => {
  const CASES: Array<[string, number | null, 'loss' | 'gain' | undefined]> = [
    ['net_pnl', -0.01, 'loss'],
    ['net_pnl', 0, undefined],
    ['net_pnl', 12, 'gain'],
    ['mar', -1, 'loss'],
    ['sharpe_trade', -0.1, 'loss'],
    ['profit_factor', 0.99, 'loss'],
    ['profit_factor', 1, undefined],
    ['profit_factor', 1.5, 'gain'],
    ['max_drawdown', 0.9, undefined],
    ['max_drawdown', -0.9, undefined],
    ['trade_count', 0, undefined],
    ['net_pnl', null, undefined],
    ['unknown_metric', -5, undefined],
  ];

  it('the tone of every case is what the Lab has always drawn', () => {
    for (const [metric, value, tone] of CASES) expect(lossTone(metric, value), `${metric} ${value}`).toBe(tone);
  });

  it('a value loses money exactly when its tone is loss', () => {
    for (const [metric, value, tone] of CASES) expect(losesMoney(metric, value), `${metric} ${value}`).toBe(tone === 'loss');
  });
});

describe('orientation (which way a metric reads)', () => {
  it('only max drawdown is lower-is-better', () => {
    expect(lowerIsBetter('max_drawdown')).toBe(true);
    expect(orientationOf('max_drawdown')).toBe(-1);
    for (const metric of ['net_pnl', 'mar', 'trade_count', 'profit_factor', 'sharpe_trade', 'exposure']) {
      expect(lowerIsBetter(metric), metric).toBe(false);
      expect(orientationOf(metric), metric).toBe(1);
    }
  });
});

describe('objectiveText (a metric as the Lab prints it)', () => {
  it('prints money, shares, ratios and counts each their own way, and a dash for no value', () => {
    expect(objectiveText('net_pnl', 120)).toBe('$120');
    expect(objectiveText('net_pnl', -120)).toBe('-$120');
    expect(objectiveText('expectancy', 12)).toBe('$12');
    expect(objectiveText('max_drawdown', 0.1234)).toBe('12.34%');
    expect(objectiveText('win_rate', 0.5)).toBe('50.00%');
    expect(objectiveText('mar', 1.5)).toBe('1.50');
    expect(objectiveText('sharpe_trade', 0.456)).toBe('0.46');
    expect(objectiveText('trade_count', 12)).toBe('12');
    expect(objectiveText('mar', null)).toBe('—');
  });
});
