import { useDispatch, useWorkspace } from '../state/workspace';
import { ExecutionPanel } from './ExecutionPanel';
import { OptimizationRanges } from './OptimizationRanges';
import { SideCard } from './SideCard';
import { TemporalPanel } from './TemporalPanel';

/** Indicator parameters live on each side (side-owned after Task 3); the panel edits them through paths. */
export function sideIndicators(strategy: unknown, side: 'long_side' | 'short_side'): Array<{ id: string; kind: string; length: number; source?: string }> {
  const s = strategy as Record<string, { indicators?: Array<{ id: string; kind: string; length: number; source?: string }> }> & {
    indicators?: Array<{ id: string; kind: string; length: number; source?: string }>;
  };
  return s[side]?.indicators ?? s.indicators ?? [];
}

export function StrategyPanel() {
  const { strategy, linkSides } = useWorkspace();
  const dispatch = useDispatch();
  const longInd = strategy ? sideIndicators(strategy, 'long_side') : [];
  const fast = longInd.find((i) => i.kind.toUpperCase() === 'EMA');
  const slow = longInd.find((i) => i.kind.toUpperCase() === 'SMA');
  const setLength = (id: string | undefined, value: number) =>
    id && Number.isFinite(value) && value > 0 && dispatch({ type: 'SET_SIDE_PARAM', side: 'long', path: `indicators.${id}.length`, value });

  return (
    <aside className="right-panel">
      <div className="right-tabs">
        <span className="active">Strategy</span>
        <span className="disabled" title="Not yet built">Indicators</span>
        <span className="disabled" title="Not yet built">Objects</span>
      </div>
      <div className="panel-section">
        <div className="panel-title">
          <span id="strategy-name">{strategy?.name ?? '—'}</span>
          <span className="muted">v{strategy?.version ?? '—'}</span>
        </div>
        <div className="sub">{strategy?.description ?? 'Strategy contract not loaded'}</div>
        <div className="pills">
          <div className={'pill' + (strategy?.long_side.enabled ? ' on' : '')}>Long</div>
          <div className={'pill' + (strategy?.short_side.enabled ? ' on' : '')}>Short</div>
        </div>
      </div>
      <div className="panel-section">
        <div className="section-label">
          Indicators
          <button type="button" className={'link-toggle' + (linkSides ? ' on' : '')} onClick={() => dispatch({ type: 'SET_LINK_SIDES', linked: !linkSides })} title="Mirror indicator parameters to both sides">
            {linkSides ? 'linked long/short' : 'independent sides'}
          </button>
        </div>
        <div className="row">
          <label>Fast EMA</label>
          <input id="ema-length" type="number" min={1} value={fast?.length ?? ''} disabled={!fast} onChange={(e) => setLength(fast?.id, Number(e.target.value))} />
        </div>
        <div className="row">
          <label>Slow SMA</label>
          <input id="sma-length" type="number" min={1} value={slow?.length ?? ''} disabled={!slow} onChange={(e) => setLength(slow?.id, Number(e.target.value))} />
        </div>
        <div className="row">
          <label>Price source</label>
          <select value={fast?.source ?? 'close'} disabled>
            <option value="close">Close</option>
          </select>
        </div>
        <div className="section-label">Asymmetric strategy sides</div>
        {strategy ? (
          <>
            <SideCard side="long" />
            <SideCard side="short" />
          </>
        ) : (
          <div className="empty-state">Strategy contract not loaded</div>
        )}
      </div>
      <TemporalPanel />
      <ExecutionPanel />
      <OptimizationRanges />
    </aside>
  );
}
