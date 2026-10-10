import { useWorkspace } from '../state/workspace';

interface Point {
  timestamp: string;
  equity: number;
}

function curves(run: unknown): Array<[string, string, Point[]]> {
  const r = run as { result?: Record<string, { equity?: Point[] }> } | null;
  if (!r?.result) return [];
  return [
    ['combined', '#2da7ff', r.result.combined?.equity ?? []],
    ['long', '#39d98a', r.result.long?.equity ?? []],
    ['short', '#ff5c67', r.result.short?.equity ?? []],
  ];
}

/** Plain SVG polylines; no chart library involved (spec §4.2). */
export function EquityTab() {
  const { lastRun } = useWorkspace();
  const series = curves(lastRun).filter(([, , points]) => points.length > 1);
  if (series.length === 0) {
    return (
      <div className="result-body single">
        <div className="empty-state">No equity curve — no backtest has been run.</div>
      </div>
    );
  }
  const all = series.flatMap(([, , p]) => p.map((x) => x.equity));
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const width = 1000;
  const height = 180;
  const path = (points: Point[]) =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'}${((i / (points.length - 1)) * width).toFixed(1)} ${(height - ((p.equity - min) / span) * height).toFixed(1)}`).join(' ');
  return (
    <div className="result-body single">
      <div className="results-table">
        <div className="legend">
          {series.map(([name, color]) => (
            <b key={name} style={{ color }}>
              {name}
            </b>
          ))}
          <span className="muted">
            min {min.toFixed(0)} · max {max.toFixed(0)}
          </span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height: 170 }} aria-label="equity curve">
          {series.map(([name, color, points]) => (
            <path key={name} d={path(points)} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      </div>
    </div>
  );
}
