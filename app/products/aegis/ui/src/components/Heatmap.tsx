import { DASH } from '../format';
import { heatTemplate } from '../layout';
import { profitKind, type ProfitKind } from '../lab/metricRules';

// The profit sign moved to the Lab's pure metric rules (one place for what loses money); these keep every importer working.
export { profitKind };
export type { ProfitKind };

export interface HeatmapProps {
  title: string;
  metric: string;
  fast: number[];
  slow: number[];
  /** rows = fast lengths ascending, columns = slow lengths ascending, null = skipped or pending */
  matrix: Array<Array<number | null>> | null;
  format?: (v: number) => string;
  rowLabel?: string;
  colLabel?: string;
  selected?: { fast: number; slow: number } | null;
  onSelect?: (fast: number, slow: number) => void;
  empty?: string;
  /** Hot = best; for an objective where lower is better (max_drawdown) the tones flip. */
  lowerIsBetter?: boolean;
  /** The metric whose sign is money: a losing value is red whatever its rank. */
  profit?: ProfitKind;
  /** The full numbers of a cell for its hover title (the cell itself shows a compact value). */
  detail?: (fast: number, slow: number) => string | null;
  /** How many trials (cells) each square holds, in the matrix's shape: each square then carries its `n` badge,
   *  and a square no trial tested is told apart from a tested one without a value. */
  counts?: ReadonlyArray<ReadonlyArray<number>> | null;
  /** Draw the squares no trial tested hatched (needs `counts`): an untested square is never filled. */
  hatchUntested?: boolean;
}

export type Tone = 'empty' | 'hot' | 'gain' | 'mid' | 'cool' | 'loss';

function third(t: number): 'top' | 'middle' | 'bottom' {
  return t >= 0.67 ? 'top' : t <= 0.33 ? 'bottom' : 'middle';
}

/** Maps a metric matrix onto the heat grid. Pure; vitest-covered (heatmap.test.ts). Losing
 *  money is red, always (operator, 2026-10-19): with a profit sign, a losing value is 'loss'
 *  whatever its rank, gains rank among themselves (best third 'hot', the rest 'gain') and break-even
 *  is neutral; without one, the tones rank the whole grid and the middle stays neutral. */
export function cells(fast: number[], slow: number[], matrix: HeatmapProps['matrix'], lowerIsBetter = false, profit: ProfitKind = null) {
  const values = (matrix ?? []).flat().filter((v): v is number => v !== null && Number.isFinite(v));
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 0;
  const even = profit === 'ratio' ? 1 : 0;
  const gains = values.filter((v) => v > even);
  const gainLo = gains.length ? Math.min(...gains) : 0;
  const gainHi = gains.length ? Math.max(...gains) : 0;
  return fast.map((f, r) =>
    slow.map((s, c) => {
      const v = matrix?.[r]?.[c] ?? null;
      let tone: Tone = 'empty';
      if (v !== null && Number.isFinite(v) && profit) {
        if (v < even) tone = 'loss';
        else if (v === even) tone = 'mid';
        else tone = third(gainHi === gainLo ? 1 : (v - gainLo) / (gainHi - gainLo)) === 'top' ? 'hot' : 'gain';
      } else if (v !== null && Number.isFinite(v)) {
        const raw = hi === lo ? 0.5 : (v - lo) / (hi - lo);
        const place = third(lowerIsBetter ? 1 - raw : raw);
        tone = place === 'top' ? 'hot' : place === 'bottom' ? 'cool' : 'mid';
      }
      return { fast: f, slow: s, value: v, tone };
    }),
  );
}

/** A count as a badge fits a square: 3, 999, 1.2k, 12k, 2.5M. */
function countText(n: number): string {
  const short = (v: number) => String(Number(v.toFixed(v < 10 ? 1 : 0)));
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${short(n / 1000)}k`;
  return `${short(n / 1_000_000)}M`;
}

/** A square's `n` badge: its count and the badge text (none for an untested square), and whether it is hatched
 *  (no trial tested it: its tone is 'empty' and its count 0). Without `counts` there is no badge and no hatch.
 *  Pure; vitest-covered (heatmap.test.ts). The tone itself always comes from `cells()`. */
export function badge(counts: ReadonlyArray<ReadonlyArray<number>> | null | undefined, r: number, c: number, tone: Tone): { n: number | null; text: string | null; hatched: boolean } {
  if (!counts) return { n: null, text: null, hatched: false };
  const n = counts[r]?.[c] ?? 0;
  return { n, text: n > 0 ? countText(n) : null, hatched: tone === 'empty' && n === 0 };
}

/** Which squares of a job's own grid were tested, as `counts` for the badges and the hatch: 1 where the trade
 *  count is defined (every evaluated cell has one, zero trades included; a refused or pending cell has none), 0
 *  elsewhere. The status's matrices cover every evaluated cell, while its cell list holds only the best CELLS_SENT,
 *  and a metric can be undefined over a tested square (MAR below a year), so neither of those can say. Null when
 *  the status carries no trade-count matrix for the side: then no badge and no hatch, never a guess. */
export function testedCounts(matrices: Partial<Record<string, Partial<Record<string, ReadonlyArray<ReadonlyArray<number | null>>>>>> | null | undefined, side: string): number[][] | null {
  const grid = matrices?.trade_count?.[side];
  if (!grid) return null;
  return grid.map((row) => row.map((value) => (value !== null && Number.isFinite(value) ? 1 : 0)));
}

/** The legend the dock's basis line carries (spec §5.1): what a square's look means. No robust plateau overlay is
 *  drawn, in the dock or on the Lab's heatmap: the estimators arrived in Phase 3 as the Lab's Robustness (A–D) tab and the
 *  candidate card. */
export function HeatLegend() {
  return (
    <span className="heat-legend">
      <span className="heat-key">
        <i className="swatch tested" />
        Tested
      </span>
      {' · '}
      <span className="heat-key">
        <i className="swatch hatched" />
        Untested (hatched)
      </span>
      {' · '}
      <span className="heat-key">
        <i className="swatch selected" />
        Selected
      </span>
      {' · '}
      <span className="heat-key muted" title="no robust plateau is drawn here or on the Lab's heatmap; the Lab's Robustness (A–D) tab shows how a trial's surroundings hold up">
        <i className="swatch plateau" />
        Robust plateau (not drawn)
      </span>
    </span>
  );
}

export function Heatmap({ title, metric, fast, slow, matrix, format, rowLabel = 'fast↓', colLabel = 'slow→', selected, onSelect, empty, lowerIsBetter = false, profit = null, detail, counts, hatchUntested = false }: HeatmapProps) {
  const grid = cells(fast, slow, matrix, lowerIsBetter, profit);
  const fmt = format ?? ((v: number) => v.toFixed(0));
  return (
    <div className="heatmap">
      <div className="panel-title">
        {title} <span className="small">{metric}</span>
      </div>
      {fast.length > 0 && slow.length > 0 && (
        <div className="sub heat-axes">
          rows {rowLabel} · columns {colLabel} · {fast.length} × {slow.length}
        </div>
      )}
      {fast.length === 0 || slow.length === 0 ? (
        <div className="sub">{empty ?? 'Optimization not run — no parameter grid to show.'}</div>
      ) : (
        <div className="heat-grid" style={{ gridTemplateColumns: heatTemplate(slow.length) }}>
          <div className="cell h corner" title={colLabel}>
            {rowLabel}
          </div>
          {slow.map((s) => (
            <div className="cell h colhead" key={'h' + s}>
              {s}
            </div>
          ))}
          {grid.map((row, r) => (
            <div key={'r' + fast[r]} style={{ display: 'contents' }}>
              <div className="cell h rowhead">{fast[r]}</div>
              {row.map((cell, c) => {
                const isSelected = selected?.fast === cell.fast && selected?.slow === cell.slow;
                const n = badge(counts, r, c, cell.tone);
                const hatched = hatchUntested && n.hatched;
                const className = 'cell ' + (cell.tone === 'mid' ? '' : cell.tone) + (hatched ? ' hatched' : '') + (n.text ? ' has-n' : '') + (isSelected ? ' selected' : '');
                const label = cell.value === null ? DASH : fmt(cell.value);
                const more = cell.value === null ? null : (detail?.(cell.fast, cell.slow) ?? null);
                const state =
                  n.n === null
                    ? cell.value === null
                      ? ' · skipped or pending'
                      : more
                        ? ` · ${more}`
                        : ''
                    : n.n === 0
                      ? ' · untested'
                      : `${cell.value === null ? ' · no value' : more ? ` · ${more}` : ''} · n ${n.n}`;
                const title = `${rowLabel} ${cell.fast} / ${colLabel} ${cell.slow}${state}`;
                // The badge's digits are CSS content (attr(data-n)), so a square's text stays its value alone.
                const mark = n.text ? <span className="cell-n" data-n={n.text} aria-hidden="true" /> : null;
                return onSelect && cell.value !== null ? (
                  <button type="button" key={`${cell.fast}-${cell.slow}`} className={className} title={title} onClick={() => onSelect(cell.fast, cell.slow)} aria-pressed={isSelected}>
                    {label}
                    {mark}
                  </button>
                ) : (
                  <div key={`${cell.fast}-${cell.slow}`} className={className} title={title}>
                    {label}
                    {mark}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
