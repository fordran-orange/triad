import { useWorkspace } from '../state/workspace';

interface Range {
  path: string;
  enabled?: boolean;
  start: number;
  stop: number;
  step: number;
}

/** Ranges live on each side (side-owned after Task 3); read either shape. */
function ranges(strategy: unknown, side: 'long_side' | 'short_side'): Range[] {
  const s = strategy as Record<string, { optimization?: Range[] }> & { optimization?: Range[] };
  return s[side]?.optimization ?? s.optimization ?? [];
}

const label = (path: string) => path.replace(/^indicators\./, '').replace(/\.length$/, '').toUpperCase();

export function OptimizationRanges() {
  const { strategy } = useWorkspace();
  if (!strategy) {
    return (
      <div className="panel-section">
        <div className="section-label">Optimization range</div>
        <div className="empty-state">Strategy contract not loaded</div>
      </div>
    );
  }
  const long = ranges(strategy, 'long_side');
  const short = ranges(strategy, 'short_side');
  const shared = long === short; // pre-Task-3 contract: one top-level list
  const groups: Array<[string, Range[]]> = shared ? [['', long]] : [['LONG · ', long], ['SHORT · ', short]];
  return (
    <div className="panel-section">
      <div className="section-label">Optimization range</div>
      {groups.map(([prefix, list]) =>
        list.map((r) => (
          <div className="row" key={prefix + r.path}>
            <label>
              {prefix}
              {label(r.path)}
            </label>
            <input value={`${r.start} → ${r.stop} · step ${r.step}`} readOnly title="Range editing connects in the optimizer phase" />
          </div>
        )),
      )}
    </div>
  );
}
