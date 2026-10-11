import { INDICATOR_KINDS, type IndicatorSpec } from '../contracts';
import { effectiveParams } from '../rules';
import { useDispatch, type Side } from '../state/workspace';

const SOURCES = ['close', 'open', 'high', 'low'] as const;

/**
 * Length, parameters and source of one indicator, edited through `indicators.<id>.…` paths.
 * Rendered by the Strategy and Indicators tabs (only one is mounted at a time, so ids are unique):
 * `#<prefix><id>-length`, `#<prefix><id>-<param>`, `#<prefix><id>-source`.
 */
export function IndicatorInputs({ side, spec, idPrefix, label = '' }: { side: Side; spec: IndicatorSpec; idPrefix: string; label?: string }) {
  const dispatch = useDispatch();
  const info = INDICATOR_KINDS[spec.kind.toUpperCase()];
  const params = effectiveParams(spec);
  const set = (path: string, value: number | string) => dispatch({ type: 'SET_SIDE_PARAM', side, path: `indicators.${spec.id}.${path}`, value });
  const base = `${idPrefix}${spec.id}`;
  return (
    <>
      <div className="row">
        <label htmlFor={`${base}-length`}>
          {label}
          {spec.kind.toUpperCase()} <span className="muted">{spec.id}</span> length
        </label>
        <input
          id={`${base}-length`}
          type="number"
          min={1}
          step={1}
          value={spec.length}
          onChange={(e) => {
            const value = Math.round(Number(e.target.value));
            if (Number.isFinite(value) && value > 0) set('length', value);
          }}
        />
      </div>
      {Object.keys(info?.params ?? {}).map((name) => {
        const whole = info.integer_params.includes(name);
        return (
          <div className="row" key={name}>
            <label htmlFor={`${base}-${name}`}>
              {label}
              <span className="muted">{spec.id}</span> {name}
            </label>
            <input
              id={`${base}-${name}`}
              type="number"
              min={0}
              step={whole ? 1 : 0.1}
              value={params[name]}
              onChange={(e) => {
                const value = Number(e.target.value);
                if (Number.isFinite(value) && value > 0) set(`params.${name}`, whole ? Math.round(value) : value);
              }}
            />
          </div>
        );
      })}
      {info?.requires.includes('source') && (
        <div className="row">
          <label htmlFor={`${base}-source`}>
            {label}
            <span className="muted">{spec.id}</span> source
          </label>
          <select id={`${base}-source`} value={spec.source ?? 'close'} onChange={(e) => set('source', e.target.value)}>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      )}
    </>
  );
}
