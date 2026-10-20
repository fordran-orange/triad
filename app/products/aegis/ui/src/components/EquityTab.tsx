import { timeLabel } from '../format';
import type { EquityPoint } from '../results';
import { useWorkspace, type RunRecord } from '../state/workspace';
import { StaleNotice } from './RunContext';

/** Plain SVG polylines; no chart library involved (spec §4.2). */
export function EquityTab() {
  const { lastRun } = useWorkspace();
  return <EquityView run={lastRun} stale />;
}

/** One run's view; the Library feeds it a saved run without touching the workspace (Mission 9). */
export function EquityView({ run: lastRun, stale = false }: { run: RunRecord | null; stale?: boolean }) {
  const result = lastRun?.result;
  const series: Array<[string, string, EquityPoint[]]> = result
    ? [
        ['combined', '#2da7ff', result.combined.equity],
        ['long', '#39d98a', result.long.equity],
        ['short', '#ff5c67', result.short.equity],
      ]
    : [];
  const drawn = series.filter(([, , points]) => points.length > 1);
  if (drawn.length === 0) {
    return (
      <div className="result-body single">
        <div className="empty-state">{result ? 'The last run produced no equity path with more than one point.' : 'No equity curve — no backtest has been run.'}</div>
      </div>
    );
  }
  const all = drawn.flatMap(([, , p]) => p.map((x) => x.equity));
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const width = 1000;
  const height = 180;
  const path = (points: EquityPoint[]) =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'}${((i / (points.length - 1)) * width).toFixed(1)} ${(height - ((p.equity - min) / span) * height).toFixed(1)}`).join(' ');
  const longest = drawn.reduce((a, b) => (a[2].length >= b[2].length ? a : b));
  return (
    <div className="result-body single">
      <div className="results-table">
        {stale && <StaleNotice />}
        <div className="legend">
          {drawn.map(([name, color, points]) => (
            <b key={name} style={{ color }}>
              {name} ({points.length})
            </b>
          ))}
          <span className="muted">
            min {min.toFixed(0)} · max {max.toFixed(0)}
          </span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height: 170 }} aria-label="equity curve">
          {drawn.map(([name, color, points]) => (
            <path key={name} d={path(points)} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        <div className="legend muted small">
          <span>{timeLabel(longest[2][0]?.timestamp)}</span>
          <span style={{ marginLeft: 'auto' }}>{timeLabel(longest[2][longest[2].length - 1]?.timestamp)}</span>
        </div>
        <div className="muted small">Combined equity is realized at each exit; per-side equity is marked to market per bar. Different x scales.</div>
      </div>
    </div>
  );
}
