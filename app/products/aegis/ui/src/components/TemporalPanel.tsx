import type { WindowMode } from '../contracts';
import { useDispatch, useWorkspace } from '../state/workspace';

const MODES: WindowMode[] = ['analyze', 'allow', 'block'];

export function TemporalPanel() {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  const t = strategy?.temporal;
  return (
    <div className="panel-section">
      <div className="section-label">Temporal context</div>
      {!t && <div className="empty-state">Strategy contract not loaded</div>}
      {t?.clock_windows.map((w) => (
        <div className="window" key={w.id}>
          <span>{w.label}</span>
          <span className="badge">
            {w.start}–{w.end}
          </span>
          <select
            value={w.mode ?? 'analyze'}
            aria-label={`${w.label} mode`}
            title="BLOCK wins over ALLOW; ANALYZE only tags trades"
            onChange={(e) => dispatch({ type: 'SET_WINDOW_MODE', id: w.id, mode: e.target.value as WindowMode })}
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m.toUpperCase()}
              </option>
            ))}
            <option value="modify_risk" disabled>
              MODIFY_RISK (not supported)
            </option>
          </select>
        </div>
      ))}
      {t?.market_crossovers.map((c) => (
        <div className="window" key={c.id}>
          <span>{c.label}</span>
          <span className="badge">
            {c.start}–{c.end}
          </span>
          <span className="badge" title="Clock-derived session overlap; tags trades, never gates them">
            {c.enabled ? (c.mode ?? 'analyze').toUpperCase() : 'OFF'}
          </span>
        </div>
      ))}
      {t?.event_windows.map((e) => (
        <div className="window" key={e.event_type}>
          <span>{e.event_type.replace('_', ' / ')}</span>
          <span className="badge">± event</span>
          <span className="badge" title="No event feed is connected; event windows cannot match anything yet">
            feed unavailable
          </span>
        </div>
      ))}
    </div>
  );
}
