import { useDispatch, useWorkspace, type Side } from '../state/workspace';
import { sideIndicators } from './StrategyPanel';

const KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

function describe(indicators: Array<{ id: string; kind: string; length: number }>, rule: { left: string; operator: string; right: string }): string {
  const name = (id: string) => {
    const i = indicators.find((x) => x.id === id);
    return i ? `${i.kind.toUpperCase()}(${i.length})` : id;
  };
  const verb = rule.operator === 'crosses_above' ? 'crosses ABOVE' : rule.operator === 'crosses_below' ? 'crosses BELOW' : rule.operator;
  return `${name(rule.left)} ${verb} ${name(rule.right)}`;
}

export function SideCard({ side }: { side: Side }) {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  if (!strategy) return null;
  const spec = strategy[KEY[side]];
  const indicators = sideIndicators(strategy, KEY[side]);
  return (
    <div className={`side-card ${side}${spec.enabled ? '' : ' off'}`}>
      <div className="side-head">
        <span>{side.toUpperCase()} SIDE</span>
        <button
          type="button"
          className={'toggle' + (spec.enabled ? ' on' : '')}
          aria-label={`${side} side enabled`}
          aria-pressed={spec.enabled}
          onClick={() => dispatch({ type: 'SET_SIDE_PARAM', side, path: 'enabled', value: !spec.enabled })}
        />
      </div>
      <div className="logic">
        ENTRY: {describe(indicators, spec.entry)}
        <br />
        EXIT: {describe(indicators, spec.exit)}
      </div>
    </div>
  );
}
