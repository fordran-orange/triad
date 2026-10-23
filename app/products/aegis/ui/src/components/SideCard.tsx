import { describeSide } from '../rules';
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
      <div className="logic" style={{ whiteSpace: 'pre-line' }}>
        {describeSide({ ...spec, indicators })}
      </div>
      <button
        type="button"
        className="btn small"
        id={`edit-in-builder-${side}`}
        onClick={() => {
          dispatch({ type: 'SET_BUILDER_SIDE', side });
          dispatch({ type: 'SET_PAGE', page: 'lab' });
        }}
      >
        Edit in builder
      </button>
    </div>
  );
}
