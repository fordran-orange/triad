/** The preview's lines for a reading (Mission 14 spec §4.4): who read it and, for an AI reading,
 * the rewrite the phrase reader read and anything that could not be expressed. */
import type { Reading } from './apply';

/** Core's usage names the provider by company; the builder names it by the tool you chose. */
const NAMES: Record<string, string> = { anthropic: 'Claude', openai: 'Codex', CLAUDE: 'Claude', CODEX: 'Codex' };

export function providerName(provider: string | null | undefined): string {
  return (provider && NAMES[provider]) || provider || 'the AI';
}

export interface ReadingLines {
  rewrite: string | null;
  readBy: string;
  unsupported: string | null;
}

export function readingLines(reading: Reading): ReadingLines {
  if (reading.read_by !== 'ai') return { rewrite: null, readBy: 'Read by the phrase reader', unsupported: null };
  const p = reading.provenance ?? {};
  const tokens = p.input_tokens != null && p.output_tokens != null ? ` · ${p.input_tokens}+${p.output_tokens} tokens` : '';
  const model = p.model ? ` · ${p.model}` : '';
  return {
    rewrite: reading.rewrite ?? null,
    readBy: `Read by ${providerName(p.provider as string | undefined)}${model}${tokens}`,
    unsupported: reading.unsupported && reading.unsupported.trim() ? reading.unsupported : null,
  };
}
