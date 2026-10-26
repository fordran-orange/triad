import { describe, expect, it } from 'vitest';
import type { StrategySide, StrategySpec } from '../contracts';
import { applyReading, type Reading } from './apply';
import { readingLines } from './reading';

const side = {
  direction: 'long',
  enabled: true,
  indicators: [{ id: 'ema', kind: 'EMA', length: 9, source: 'close', overlay: true }],
  entry: { left: 'ema', operator: 'crosses_above', right: '30', timing: 'bar_close' },
  optimization: [],
  stop_loss_pct: 2,
} as StrategySide;

const phraseReading: Reading = { sides: { long_side: side }, reading: 'Long entry: EMA 9 crosses above 30.', defaults: [], read_by: 'phrases' };
const aiReading: Reading = {
  ...phraseReading,
  read_by: 'ai',
  rewrite: 'buy when 9 ema crosses above 30',
  substitutions: [{ from: 'crosses up', to: 'crosses above' }],
  unsupported: '',
  provenance: { provider: 'anthropic', model: 'claude-sonnet-5', input_tokens: 900, output_tokens: 60, run_id: 'run-1' },
};

describe('readingLines (Mission 14)', () => {
  it('says the phrase reader read it, with no rewrite line', () => {
    expect(readingLines(phraseReading)).toEqual({ rewrite: null, readBy: 'Read by the phrase reader', unsupported: null });
  });

  it('names the provider, model and tokens of an AI reading, and its rewrite', () => {
    expect(readingLines(aiReading)).toEqual({
      rewrite: 'buy when 9 ema crosses above 30',
      readBy: 'Read by Claude · claude-sonnet-5 · 900+60 tokens',
      unsupported: null,
    });
    expect(readingLines({ ...aiReading, provenance: { ...aiReading.provenance, provider: 'openai', model: 'gpt-6-astra' } }).readBy).toBe(
      'Read by Codex · gpt-6-astra · 900+60 tokens',
    );
  });

  it('shows what could not be expressed, and Apply applies only what was read (Review Focus 5)', () => {
    const partial = { ...aiReading, unsupported: 'stop out at 3% down' };
    expect(readingLines(partial).unsupported).toBe('stop out at 3% down');
    const strategy = { long_side: { ...side, stop_loss_pct: undefined }, short_side: side } as unknown as StrategySpec;
    const applied = applyReading(strategy, partial);
    expect(applied.strategy.long_side.stop_loss_pct).toBe(2); // the read side as given, nothing invented
  });
});
