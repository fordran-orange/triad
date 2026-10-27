import { describe, expect, it } from 'vitest';
import type { StrategySide, StrategySpec } from '../contracts';
import { applyReading, type Reading } from './apply';
import { readerSelection, readingLines } from './reading';

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
    expect(readingLines({ ...aiReading, provenance: { ...aiReading.provenance, provider: 'xai', model: 'grok-4.7' } }).readBy).toBe(
      'Read by Grok · grok-4.7 · 900+60 tokens',
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

describe('readerSelection (operator, 2026-10-27: each provider only while Core can route to it)', () => {
  const choices = (available: string[]) =>
    (['CLAUDE', 'CODEX', 'GROK'] as const).map((id) => ({ id, name: id[0] + id.slice(1).toLowerCase(), available: available.includes(id) }));

  it('offers only the providers Core can route now, Grok among them when it can', () => {
    expect(readerSelection(choices(['CLAUDE', 'GROK']), 'CLAUDE').options.map((c) => c.id)).toEqual(['CLAUDE', 'GROK']);
    expect(readerSelection(choices(['CLAUDE', 'CODEX']), 'CLAUDE').options.map((c) => c.id)).toEqual(['CLAUDE', 'CODEX']);
  });

  it('keeps the remembered provider when it is offered', () => {
    expect(readerSelection(choices(['CLAUDE', 'CODEX', 'GROK']), 'GROK').selected).toBe('GROK');
  });

  it('shows the first one offered when the remembered provider is not', () => {
    expect(readerSelection(choices(['CODEX', 'GROK']), 'CLAUDE').selected).toBe('CODEX');
  });

  it('offers none, selects none and asks no AI when Core can route to none', () => {
    expect(readerSelection(choices([]), 'CLAUDE')).toEqual({ options: [], selected: null, ai: false });
  });

  it('offers none while the list has not arrived, but a read may still ask the remembered provider', () => {
    expect(readerSelection(null, 'CODEX')).toEqual({ options: [], selected: null, ai: true });
  });

  it('asks the AI whenever a provider is offered', () => {
    expect(readerSelection(choices(['GROK']), 'CLAUDE').ai).toBe(true);
  });
});
