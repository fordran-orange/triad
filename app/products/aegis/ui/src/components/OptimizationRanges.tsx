import type { OptimizationParameter, StrategySide } from '../contracts';
import { SIDES, SIDE_KEY, useDispatch, useWorkspace, type Side } from '../state/workspace';

function label(range: OptimizationParameter, side: StrategySide): string {
  const [, id, ...rest] = range.path.split('.');
  const field = rest[0] === 'params' ? rest.slice(1).join('.') : rest.join('.');
  const indicator = side.indicators?.find((i) => i.id === id);
  return `${indicator ? `${indicator.kind.toUpperCase()} ${id}` : id} ${field}`;
}

/** Per-side ranges the optimizer expands (spec §2b.1); edits go straight into the strategy document. */
export function OptimizationRanges() {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  if (!strategy) {
    return (
      <div className="panel-section">
        <div className="section-label">Optimization ranges</div>
        <div className="empty-state">Strategy contract not loaded</div>
      </div>
    );
  }
  const setNumber = (side: Side, path: string, field: 'start' | 'stop' | 'step', raw: string) => {
    const value = Number(raw);
    if (Number.isFinite(value) && (field !== 'step' || value > 0)) dispatch({ type: 'SET_RANGE', side, path, field, value });
  };
  return (
    <div className="panel-section">
      <div className="section-label">
        Optimization ranges <span className="muted">start → stop · step</span>
      </div>
      {SIDES.map((side) =>
        (strategy[SIDE_KEY[side]].optimization ?? []).map((r) => (
          <div className="row range" key={side + r.path}>
            <label>
              <input
                type="checkbox"
                checked={r.enabled ?? true}
                aria-label={`${side} ${r.path} enabled`}
                onChange={(e) => dispatch({ type: 'SET_RANGE', side, path: r.path, field: 'enabled', value: e.target.checked })}
              />
              {side.toUpperCase()} · {label(r, strategy[SIDE_KEY[side]])}
            </label>
            <input type="number" value={r.start} aria-label={`${side} ${r.path} start`} onChange={(e) => setNumber(side, r.path, 'start', e.target.value)} />
            <input type="number" value={r.stop} aria-label={`${side} ${r.path} stop`} onChange={(e) => setNumber(side, r.path, 'stop', e.target.value)} />
            <input type="number" value={r.step} min={0} aria-label={`${side} ${r.path} step`} onChange={(e) => setNumber(side, r.path, 'step', e.target.value)} />
          </div>
        )),
      )}
    </div>
  );
}
