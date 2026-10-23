import { describe, expect, it } from 'vitest';
import { exitLabel } from '../format';
import type { Trade } from '../results';

describe('exitLabel (Mission 13)', () => {
  it('names a stop loss and a take profit, and nothing else', () => {
    const trade = (exit_reason?: 'stop_loss' | 'take_profit') => ({ exit_reason }) as Trade;
    expect(exitLabel(trade('stop_loss'))).toBe('stop loss');
    expect(exitLabel(trade('take_profit'))).toBe('take profit');
    expect(exitLabel(trade())).toBe('');
  });
});
