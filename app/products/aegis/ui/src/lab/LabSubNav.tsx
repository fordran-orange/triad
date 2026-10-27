import { useLab, useLabDispatch } from './labState';
import type { LabView } from './labStore';

/** The Lab's views in the plan's order (§5.2): Run Monitor (D), Trial Lab (B), Parameter Families (E),
 *  Variable Intelligence (H), Walk-Forward (F), History & Lineage (G), Compare (C). */
export const LAB_VIEWS: Array<{ view: LabView; label: string }> = [
  { view: 'monitor', label: 'Run Monitor' },
  { view: 'trials', label: 'Trial Lab' },
  { view: 'families', label: 'Parameter Families' },
  { view: 'variables', label: 'Variable Intelligence' },
  { view: 'walkforward', label: 'Walk-Forward' },
  { view: 'lineage', label: 'History & Lineage' },
  { view: 'compare', label: 'Compare' },
];

/** The left sub-nav: switching views changes only the view, so the filter, the selection and the pins stay. */
export function LabSubNav() {
  const { view } = useLab();
  const dispatch = useLabDispatch();
  return (
    <nav className="lab-subnav" id="lab-subnav" aria-label="Optimization Lab views">
      <div className="lab-subnav-title">Optimization Lab</div>
      {LAB_VIEWS.map((item) => (
        <button
          type="button"
          key={item.view}
          id={`lab-view-${item.view}`}
          className={'nav' + (view === item.view ? ' active' : '')}
          aria-current={view === item.view ? 'page' : undefined}
          onClick={() => dispatch({ type: 'SET_VIEW', view: item.view })}
        >
          <span className="dot" />
          {item.label}
        </button>
      ))}
    </nav>
  );
}
