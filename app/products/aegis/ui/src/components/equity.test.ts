import { describe, expect, it } from 'vitest';
import { sideCurveNote } from './EquityTab';

describe('the equity view (Mission 10: slim saved runs)', () => {
  it('says when a stored side curve stands for more bars than it draws', () => {
    expect(sideCurveNote(undefined, 3_000, 3_000)).toBe('per-side equity is marked to market per bar');
    expect(sideCurveNote({ format: 2, equity_points: { long: 10_000, short: 0 } }, 2_000, 0)).toBe(
      'per-side equity is marked to market per bar, drawn from 2,000 of 10,000 points',
    );
    expect(sideCurveNote({ format: 2, equity_points: { long: 1_500, short: 1_500 } }, 1_500, 1_500)).toBe(
      'per-side equity is marked to market per bar',
    );
  });
});
