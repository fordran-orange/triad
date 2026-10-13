import { DASH, num } from '../format';
import type { MainEffectPoint } from '../results';

/** One small SVG per parameter: the median of the objective at each value with its p25–p75 band. */
export function MainEffects({ effects, objective }: { effects: Record<string, MainEffectPoint[]>; objective: string }) {
  const entries = Object.entries(effects);
  if (entries.length === 0) return <div className="empty-state">No main effects: no valid cells.</div>;
  return (
    <div className="effects">
      {entries.map(([path, points]) => (
        <Effect key={path} path={path} points={points} objective={objective} />
      ))}
    </div>
  );
}

function Effect({ path, points, objective }: { path: string; points: MainEffectPoint[]; objective: string }) {
  const drawn = points.filter((p) => p.median !== null);
  const width = 300;
  const height = 100;
  const pad = 8;
  if (drawn.length === 0) {
    return (
      <div className="effect">
        <div className="small">{path}</div>
        <div className="empty-state">{DASH}</div>
      </div>
    );
  }
  const lows = drawn.map((p) => (p.p25 ?? p.median) as number);
  const highs = drawn.map((p) => (p.p75 ?? p.median) as number);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / Math.max(points.length - 1, 1)) * (width - 2 * pad);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - 2 * pad);
  const index = (p: MainEffectPoint) => points.indexOf(p);
  const band = [...drawn.map((p) => `${x(index(p)).toFixed(1)},${y((p.p75 ?? p.median) as number).toFixed(1)}`), ...[...drawn].reverse().map((p) => `${x(index(p)).toFixed(1)},${y((p.p25 ?? p.median) as number).toFixed(1)}`)].join(' ');
  const line = drawn.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(index(p)).toFixed(1)} ${y(p.median as number).toFixed(1)}`).join(' ');
  const best = drawn.reduce((a, b) => ((b.median as number) > (a.median as number) ? b : a));
  return (
    <div className="effect" id={`effect-${path.replace(/\./g, '-')}`}>
      <div className="small">
        <b>{path}</b> <span className="muted">median {objective}; best at {num(best.value, 4)} ({num(best.median, 4)})</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label={`main effect of ${path}`}>
        <polygon points={band} fill="#2da7ff" fillOpacity={0.15} stroke="none" />
        <path d={line} fill="none" stroke="#2da7ff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {drawn.map((p) => (
          <circle key={p.value} cx={x(index(p))} cy={y(p.median as number)} r={2} fill="#2da7ff" />
        ))}
      </svg>
      <div className="legend muted small">
        <span>{num(points[0].value, 4)}</span>
        <span style={{ marginLeft: 'auto' }}>{num(points[points.length - 1].value, 4)}</span>
      </div>
    </div>
  );
}
