import type { Trade } from './results';
// Honest formatting: a missing value is an em dash, never a fabricated number.
export const DASH = '—';

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return (value * 100).toFixed(digits) + '%';
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const sign = value < 0 ? '-' : '';
  return sign + '$' + Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function shortHash(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 12) : DASH;
}

export function timeLabel(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return iso.replace('T', ' ').slice(0, 16);
}

/** How a trade closed when a level closed it (Mission 13): "stop loss", "take profit", or "". */
export function exitLabel(trade: Pick<Trade, 'exit_reason'>): string {
  if (trade.exit_reason === 'stop_loss') return 'stop loss';
  if (trade.exit_reason === 'take_profit') return 'take profit';
  return '';
}

