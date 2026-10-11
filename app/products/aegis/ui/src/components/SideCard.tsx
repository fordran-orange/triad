import { describeRule } from '../rules';
import { RuleEditor } from './RuleEditor';
import { useDispatch, useWorkspace, type Side } from '../state/workspace';
import { sideIndicators } from './StrategyPanel';

const KEY: Record<Side, 'long_side' | 'short_side'> = { long: 'long_side', short: 'short_side' };

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
        ENTRY: {describeRule(spec.entry, indicators)}
        <br />
        EXIT: {describeRule(spec.exit, indicators)}
      </div>
      <RuleEditor side={side} which="entry" spec={spec} />
      <RuleEditor side={side} which="exit" spec={spec} />
    </div>
  );
}
