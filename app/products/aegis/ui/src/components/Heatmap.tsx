import { DASH } from '../format';

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
}

/** 'sign': below 0 loses money (net P&L, return, CAGR, MAR, expectancy); 'ratio': below 1
 *  loses money (profit factor); null: the metric has no profit sign. */
export type ProfitKind = 'sign' | 'ratio' | null;

const SIGNED = new Set(['net_pnl', 'net_return', 'cagr', 'mar', 'expectancy']);

export function profitKind(metric: string): ProfitKind {
  if (SIGNED.has(metric)) return 'sign';
  return metric === 'profit_factor' ? 'ratio' : null;
}

type Tone = 'empty' | 'hot' | 'gain' | 'mid' | 'cool' | 'loss';

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

export function Heatmap({ title, metric, fast, slow, matrix, format, rowLabel = 'fast↓', colLabel = 'slow→', selected, onSelect, empty, lowerIsBetter = false, profit = null }: HeatmapProps) {
  const grid = cells(fast, slow, matrix, lowerIsBetter, profit);
  const fmt = format ?? ((v: number) => v.toFixed(0));
  return (
    <div className="heatmap">
      <div className="panel-title">
        {title} <span className="small">{metric}</span>
      </div>
      {fast.length === 0 || slow.length === 0 ? (
        <div className="sub">{empty ?? 'Optimization not run — no parameter grid to show.'}</div>
      ) : (
        <div className="heat-grid" style={{ gridTemplateColumns: `48px repeat(${slow.length}, 1fr)` }}>
          <div className="cell h" title={colLabel}>
            {rowLabel}
          </div>
          {slow.map((s) => (
            <div className="cell h" key={'h' + s}>
              {s}
            </div>
          ))}
          {grid.map((row, r) => (
            <div key={'r' + fast[r]} style={{ display: 'contents' }}>
              <div className="cell h">{fast[r]}</div>
              {row.map((cell) => {
                const isSelected = selected?.fast === cell.fast && selected?.slow === cell.slow;
                const className = 'cell ' + (cell.tone === 'mid' ? '' : cell.tone) + (isSelected ? ' selected' : '');
                const label = cell.value === null ? DASH : fmt(cell.value);
                const title = `${rowLabel} ${cell.fast} / ${colLabel} ${cell.slow}${cell.value === null ? ' · skipped or pending' : ''}`;
                return onSelect && cell.value !== null ? (
                  <button type="button" key={`${cell.fast}-${cell.slow}`} className={className} title={title} onClick={() => onSelect(cell.fast, cell.slow)} aria-pressed={isSelected}>
                    {label}
                  </button>
                ) : (
                  <div key={`${cell.fast}-${cell.slow}`} className={className} title={title}>
                    {label}
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
