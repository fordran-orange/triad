import { useState } from 'react';
import { INDICATOR_KINDS } from '../contracts';
import { DASH, num } from '../format';
import { referencesOf, ruleReferences } from '../rules';
import { currentLatest, SIDES, SIDE_KEY, useDispatch, useWorkspace } from '../state/workspace';
import { IndicatorInputs } from './IndicatorInputs';

/** The focused side's indicators: kind, parameters, source, pane and latest value; add and remove. */
export function IndicatorsTab() {
  const state = useWorkspace();
  const { strategy, focusSide, linkSides } = state;
  const latest = currentLatest(state);
  const dispatch = useDispatch();
  const [kind, setKind] = useState('RSI');
  const [error, setError] = useState<string | null>(null);
  if (!strategy) return <div className="empty-state">Strategy contract not loaded</div>;
  const side = strategy[SIDE_KEY[focusSide]];
  const indicators = side.indicators ?? [];
  const idPrefix = focusSide === 'short' && !linkSides ? 'short-' : '';

  const remove = (id: string) => {
    const readers = ruleReferences(side, id);
    if (readers.length > 0) {
      setError(`${id} is read by the ${focusSide} ${readers.join(' and ')}; change that rule before removing it`);
      return;
    }
    setError(null);
    dispatch({ type: 'REMOVE_INDICATOR', side: focusSide, id });
  };

  return (
    <div className="panel-section" id="indicators-tab">
      <div className="section-label">
        Side
        <div className="pills">
          {SIDES.map((s) => (
            <button key={s} id={`focus-${s}`} type="button" className={'pill btn' + (focusSide === s ? ' on' : '')} aria-pressed={focusSide === s} onClick={() => dispatch({ type: 'SET_FOCUS_SIDE', side: s })}>
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="small muted">The chart draws this side's indicators. Adding or removing acts on this side only.</div>
      {indicators.length === 0 && <div className="empty-state">No indicators on the {focusSide} side</div>}
      {indicators.map((spec) => {
        const info = INDICATOR_KINDS[spec.kind.toUpperCase()];
        return (
          <div className="indicator-card" id={`indicator-${spec.id}`} key={spec.id}>
            <div className="side-head">
              <span>
                {spec.kind.toUpperCase()} <span className="muted">{spec.id}</span> · {info?.pane === 'own' ? 'own pane' : 'price pane'}
              </span>
              <button type="button" className="btn" id={`remove-${spec.id}`} onClick={() => remove(spec.id)} title="Remove this indicator from the side">
                Remove
              </button>
            </div>
            <IndicatorInputs side={focusSide} spec={spec} idPrefix={idPrefix} />
            <div className="small" title="Last value in the loaded range, from the chart's fetch">
              {referencesOf(spec).map((key) => (
                <span key={key} className="latest" style={{ marginRight: 8 }}>
                  {key} <b>{latest[key] === undefined || latest[key] === null ? DASH : num(latest[key] as number)}</b>
                </span>
              ))}
            </div>
          </div>
        );
      })}
      {error && (
        <div className="notice warn" id="indicator-error" role="status">
          {error}
        </div>
      )}
      <div className="row">
        <label htmlFor="add-indicator-kind">Add indicator</label>
        <select id="add-indicator-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.keys(INDICATOR_KINDS).map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn"
          id="add-indicator"
          onClick={() => {
            setError(null);
            dispatch({ type: 'ADD_INDICATOR', side: focusSide, kind });
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}
