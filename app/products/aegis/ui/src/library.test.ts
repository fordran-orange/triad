import { describe, expect, it } from 'vitest';
import { comparable, headlineText, kindLabel, markText, queryString } from './library';
import type { LibraryEntry, LibraryFilters } from './results';

function entry(kind: LibraryEntry['kind'], headline: Record<string, unknown>, id = 'x'): LibraryEntry {
  return {
    kind,
    id,
    name: 'n',
    label: '',
    notes: '',
    starred: false,
    symbols: ['QQQ'],
    timeframe: '1h',
    start: '2024-01-01',
    end: '2024-12-31',
    strategy_id: null,
    strategy_name: null,
    created_at: null,
    status: 'done',
    decision: null,
    headline,
    links: {},
  };
}

const FILTERS: LibraryFilters = {
  kinds: [],
  symbol: '',
  timeframe: '',
  strategy: '',
  starred: false,
  decision: '',
  q: '',
  sort: 'created',
  offset: 0,
  limit: 50,
  deleted: false,
};

describe('library helpers', () => {
  it('headlineText speaks each kind, with a dash for what is missing', () => {
    expect(headlineText(entry('backtest', { net_pnl: 1234.5, net_return: 0.0123, mar: 0.61, max_drawdown: 0.08, trade_count: 12 }))).toBe(
      'Net $1,235 · MAR 0.61 · DD 8.00% · 12 trades',
    );
    expect(headlineText(entry('backtest', { net_pnl: -50, net_return: -0.01, mar: null, max_drawdown: 0.02, trade_count: 3 }))).toBe(
      'Net -$50 · MAR — · DD 2.00% · 3 trades',
    );
    expect(headlineText(entry('optimization', { side: 'long', cells_run: 271, cells_total: 271, objective: 'net_pnl', best: 56801 }))).toBe(
      'LONG · 271/271 cells · best net P&L $56,801',
    );
    expect(headlineText(entry('optimization', { side: 'short', cells_run: 9, cells_total: 12, objective: 'mar', best: null }))).toBe(
      'SHORT · 9/12 cells · best MAR —',
    );
    expect(headlineText(entry('walkforward', { side: 'long', windows: 9, net_pnl: 23042.29, mar: 1.2 }))).toBe('LONG · 9 windows · Net $23,042 · MAR 1.20');
    expect(headlineText(entry('experiment', { mode: 'exhaustive', cells_done: 252, cells_planned: 252, objective: 'mar', recommended: true }))).toBe(
      'exhaustive · 252/252 cells · MAR · recommends a plateau',
    );
    expect(headlineText(entry('experiment', { mode: 'sampled', cells_done: 10, cells_planned: 2000, objective: 'net_pnl', recommended: null }))).toBe(
      'sampled · 10/2,000 cells · net P&L · no report',
    );
    expect(headlineText(entry('study', { symbols: ['QQQ', 'SPY'], windows: 32, summary_line: 'plateau rule ahead of the peak rule on 2 of 2 symbols by MAR' }))).toBe(
      'plateau rule ahead of the peak rule on 2 of 2 symbols by MAR · 32 windows',
    );
    expect(headlineText(entry('backtest', {}))).toBe('preparing…');
  });

  it('queryString drops empty filters and repeats kinds', () => {
    expect(queryString(FILTERS)).toBe('limit=50');
    expect(queryString({ ...FILTERS, kinds: ['backtest', 'study'], q: 'walk break', starred: true, sort: 'mar', offset: 50, deleted: true })).toBe(
      'kind=backtest&kind=study&starred=true&q=walk+break&sort=mar&offset=50&limit=50&deleted=true',
    );
  });

  it('comparable needs exactly two backtests and says why otherwise', () => {
    expect(comparable([entry('backtest', {}, 'a'), entry('backtest', {}, 'b')])).toEqual({ ok: true, reason: '' });
    expect(comparable([entry('backtest', {}, 'a')])).toEqual({ ok: false, reason: 'tick exactly two backtests to compare' });
    expect(comparable([entry('backtest', {}, 'a'), entry('optimization', {}, 'b')])).toEqual({
      ok: false,
      reason: 'only backtests compare in this version',
    });
  });

  it('markText and kindLabel', () => {
    expect(markText('better')).toBe('▲ better');
    expect(markText('worse')).toBe('▼ worse');
    expect(markText(null)).toBe('');
    expect(kindLabel('walkforward')).toBe('Walk-forward');
  });
});
