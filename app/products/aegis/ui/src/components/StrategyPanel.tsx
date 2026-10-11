import type { IndicatorSpec, StrategySpec } from '../contracts';
import { useDispatch, useWorkspace, type Side } from '../state/workspace';
import { ExecutionPanel } from './ExecutionPanel';
import { IndicatorInputs } from './IndicatorInputs';
import { IndicatorsTab } from './IndicatorsTab';
import { OptimizationRanges } from './OptimizationRanges';
import { SideCard } from './SideCard';
import { TemporalPanel } from './TemporalPanel';

const KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

/** Indicator parameters are side-owned (spec §2b.1); the panel edits them through `indicators.<id>.<field>` paths. */
export function sideIndicators(strategy: StrategySpec, side: 'long_side' | 'short_side'): IndicatorSpec[] {
  return strategy[side].indicators ?? [];
}

/** Every indicator of a side, generic per kind (`#<id>-length` for long or linked, `#short-<id>-length`). */
function SideInputs({ side, prefix }: { side: Side; prefix: string }) {
  const { strategy } = useWorkspace();
  const list = strategy ? sideIndicators(strategy, KEY[side]) : [];
  const idPrefix = side === 'long' ? '' : 'short-';
  if (list.length === 0) return <div className="empty-state">No indicators on the {side} side</div>;
  return (
    <>
      {list.map((spec) => (
        <IndicatorInputs key={spec.id} side={side} spec={spec} idPrefix={idPrefix} label={prefix} />
      ))}
    </>
  );
}

export function StrategyPanel() {
  const { rightTab } = useWorkspace();
  const dispatch = useDispatch();

  return (
    <aside className="right-panel">
      <div className="right-tabs">
        <button type="button" id="right-tab-strategy" className={rightTab === 'strategy' ? 'active' : ''} onClick={() => dispatch({ type: 'SET_RIGHT_TAB', tab: 'strategy' })}>
          Strategy
        </button>
        <button type="button" id="right-tab-indicators" className={rightTab === 'indicators' ? 'active' : ''} onClick={() => dispatch({ type: 'SET_RIGHT_TAB', tab: 'indicators' })}>
          Indicators
        </button>
        <span className="disabled" title="Not yet built">Objects</span>
      </div>
      {rightTab === 'indicators' ? (
        <IndicatorsTab />
      ) : (
        <StrategyTab />
      )}
    </aside>
  );
}

function StrategyTab() {
  const { strategy, linkSides } = useWorkspace();
  const dispatch = useDispatch();
  return (
    <>
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
          <SideInputs side="long" prefix="" />
        ) : (
          <>
            <SideInputs side="long" prefix="Long · " />
            <SideInputs side="short" prefix="Short · " />
          </>
        )}
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
    </>
  );
}
