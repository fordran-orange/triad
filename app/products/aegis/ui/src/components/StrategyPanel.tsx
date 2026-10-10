import type { IndicatorSpec, StrategySpec } from '../contracts';
import { useDispatch, useWorkspace, type Side } from '../state/workspace';
import { ExecutionPanel } from './ExecutionPanel';
import { OptimizationRanges } from './OptimizationRanges';
import { SideCard } from './SideCard';
import { TemporalPanel } from './TemporalPanel';

const KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

/** Indicator parameters are side-owned (spec §2b.1); the panel edits them through `indicators.<id>.<field>` paths. */
export function sideIndicators(strategy: StrategySpec, side: 'long_side' | 'short_side'): IndicatorSpec[] {
  return strategy[side].indicators ?? [];
}

function LengthInputs({ side, prefix }: { side: Side; prefix: string }) {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  const list = strategy ? sideIndicators(strategy, KEY[side]) : [];
  const fast = list.find((i) => i.kind.toUpperCase() === 'EMA');
  const slow = list.find((i) => i.kind.toUpperCase() === 'SMA');
  const idPrefix = side === 'long' ? '' : 'short-';
  const setLength = (id: string | undefined, value: number) => {
    if (id && Number.isFinite(value) && value > 0) dispatch({ type: 'SET_SIDE_PARAM', side, path: `indicators.${id}.length`, value });
  };
  return (
    <>
      <div className="row">
        <label htmlFor={`${idPrefix}ema-length`}>{prefix}Fast EMA</label>
        <input id={`${idPrefix}ema-length`} type="number" min={1} value={fast?.length ?? ''} disabled={!fast} onChange={(e) => setLength(fast?.id, Number(e.target.value))} />
      </div>
      <div className="row">
        <label htmlFor={`${idPrefix}sma-length`}>{prefix}Slow SMA</label>
        <input id={`${idPrefix}sma-length`} type="number" min={1} value={slow?.length ?? ''} disabled={!slow} onChange={(e) => setLength(slow?.id, Number(e.target.value))} />
      </div>
    </>
  );
}

export function StrategyPanel() {
  const { strategy, linkSides } = useWorkspace();
  const dispatch = useDispatch();
  const source = strategy ? sideIndicators(strategy, 'long_side')[0]?.source ?? 'close' : 'close';

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
        {linkSides ? (
          <LengthInputs side="long" prefix="" />
        ) : (
          <>
            <LengthInputs side="long" prefix="Long · " />
            <LengthInputs side="short" prefix="Short · " />
          </>
        )}
        <div className="row">
          <label>Price source</label>
          <select value={source} disabled title="Only close is supported in this slice">
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
