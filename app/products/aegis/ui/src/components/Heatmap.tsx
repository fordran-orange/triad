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
}

/** Maps a metric matrix onto the heat grid. Pure; vitest-covered (heatmap.test.ts). */
export function cells(fast: number[], slow: number[], matrix: HeatmapProps['matrix']) {
  const values = (matrix ?? []).flat().filter((v): v is number => v !== null && Number.isFinite(v));
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 0;
  return fast.map((f, r) =>
    slow.map((s, c) => {
      const v = matrix?.[r]?.[c] ?? null;
      let tone: 'empty' | 'hot' | 'cool' | 'mid' = 'empty';
      if (v !== null && Number.isFinite(v)) {
        const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
        tone = t >= 0.67 ? 'hot' : t <= 0.33 ? 'cool' : 'mid';
      }
      return { fast: f, slow: s, value: v, tone };
    }),
  );
}

export function Heatmap({ title, metric, fast, slow, matrix, format, rowLabel = 'fast↓', colLabel = 'slow→', selected, onSelect, empty }: HeatmapProps) {
  const grid = cells(fast, slow, matrix);
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
