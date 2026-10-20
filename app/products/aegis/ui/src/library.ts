// Pure helpers for the Results library (Mission 9 spec §4, §7–8); no React, no fetch.
import { DASH, money, num, pct } from './format';
import type { CompareMark, LibraryEntry, LibraryFilters, LibraryKind } from './results';

const KIND_LABELS: Record<LibraryKind, string> = {
  backtest: 'Backtest',
  optimization: 'Optimization',
  walkforward: 'Walk-forward',
  experiment: 'Experiment',
  study: 'Study',
};

const OBJECTIVE_LABELS: Record<string, string> = {
  net_pnl: 'net P&L',
  net_return: 'return',
  cagr: 'CAGR',
  max_drawdown: 'max drawdown',
  mar: 'MAR',
  win_rate: 'win rate',
  expectancy: 'expectancy',
  profit_factor: 'profit factor',
  trade_count: 'trades',
  exposure: 'exposure',
};

const n = (value: unknown) => (typeof value === 'number' ? value.toLocaleString('en-US') : DASH);
const value = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function kindLabel(kind: LibraryKind): string {
  return KIND_LABELS[kind];
}

export function objectiveLabel(objective: unknown): string {
  return typeof objective === 'string' ? (OBJECTIVE_LABELS[objective] ?? objective) : DASH;
}

/** An objective's value as the rest of the app writes it. */
export function objectiveValue(objective: unknown, v: unknown): string {
  const x = value(v);
  if (objective === 'net_pnl' || objective === 'expectancy') return money(x);
  if (objective === 'max_drawdown' || objective === 'net_return' || objective === 'cagr' || objective === 'win_rate' || objective === 'exposure') return pct(x);
  if (objective === 'trade_count') return num(x, 0);
  return num(x, 2);
}

/** One line of each kind's headline numbers; "preparing…" until the worker has computed them,
 *  and a dash when it has but the document gave nothing to show. */
export function headlineText(entry: LibraryEntry): string {
  if (entry.ready === false) return 'preparing…';
  const h = entry.headline;
  if (!h || Object.keys(h).length === 0) return DASH;
  const side = typeof h.side === 'string' ? h.side.toUpperCase() : DASH;
  switch (entry.kind) {
    case 'backtest':
      return `Net ${money(value(h.net_pnl))} · MAR ${num(value(h.mar), 2)} · DD ${pct(value(h.max_drawdown))} · ${n(h.trade_count)} trades`;
    case 'optimization':
      return `${side} · ${n(h.cells_run)}/${n(h.cells_total)} cells · best ${objectiveLabel(h.objective)} ${objectiveValue(h.objective, h.best)}`;
    case 'walkforward':
      return `${side} · ${n(h.windows)} windows · Net ${money(value(h.net_pnl))} · MAR ${num(value(h.mar), 2)}`;
    case 'experiment': {
      const verdict = h.recommended === true ? 'recommends a plateau' : h.recommended === false ? 'no plateau' : 'no report';
      return `${typeof h.mode === 'string' ? h.mode : DASH} · ${n(h.cells_done)}/${n(h.cells_planned)} cells · ${objectiveLabel(h.objective)} · ${verdict}`;
    }
    case 'study':
      return `${typeof h.summary_line === 'string' ? h.summary_line : DASH} · ${n(h.windows)} windows`;
    default:
      return DASH;
  }
}

const MONEY_OBJECTIVES = new Set(['net_pnl', 'net_return', 'cagr', 'expectancy']);

/** Whether the headline lost money (red is reserved for that; operator, 2026-10-19). */
export function losing(entry: LibraryEntry): boolean {
  const h = entry.headline ?? {};
  const pnl = value(h.net_pnl);
  if (pnl !== null) return pnl < 0;
  const best = value(h.best);
  return MONEY_OBJECTIVES.has(String(h.objective)) && best !== null && best < 0;
}

/** GET /library's query: empty filters are left out; kinds repeat. */
export function queryString(filters: LibraryFilters): string {
  const q = new URLSearchParams();
  for (const kind of filters.kinds) q.append('kind', kind);
  if (filters.symbol) q.set('symbol', filters.symbol);
  if (filters.timeframe) q.set('timeframe', filters.timeframe);
  if (filters.strategy) q.set('strategy', filters.strategy);
  if (filters.starred) q.set('starred', 'true');
  if (filters.decision) q.set('decision', filters.decision);
  if (filters.q.trim()) q.set('q', filters.q.trim());
  if (filters.sort !== 'created') q.set('sort', filters.sort);
  if (filters.offset > 0) q.set('offset', String(filters.offset));
  q.set('limit', String(filters.limit));
  if (filters.deleted) q.set('deleted', 'true');
  return q.toString();
}

/** The entry the view shows: the list's copy while the page lists it, else the copy fetched
 *  by id (an item opened from a deep link, or one a new label or star took off the page). */
export function openedEntry(
  entries: LibraryEntry[],
  selected: { kind: LibraryKind; id: string } | null,
  fetched: LibraryEntry | null,
): LibraryEntry | null {
  if (!selected) return null;
  const listed = entries.find((e) => e.kind === selected.kind && e.id === selected.id);
  if (listed) return listed;
  return fetched && fetched.kind === selected.kind && fetched.id === selected.id ? fetched : null;
}

/** Whether the ticked entries can be compared (exactly two backtests in this version). */
export function comparable(selected: LibraryEntry[]): { ok: boolean; reason: string } {
  if (selected.length !== 2) return { ok: false, reason: 'tick exactly two backtests to compare' };
  if (selected.some((e) => e.kind !== 'backtest')) return { ok: false, reason: 'only backtests compare in this version' };
  return { ok: true, reason: '' };
}

/** A difference's direction in words: never red or green (red is reserved for losing money). */
export function markText(mark: CompareMark): string {
  return mark === 'better' ? '▲ better' : mark === 'worse' ? '▼ worse' : '';
}
