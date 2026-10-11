import type { RuleSpec, StrategySide } from '../contracts';
import { BAND_OPERATORS, conditionsOf, isConstant, isGroup, kindOf, OPERATORS, PRICE_OPERANDS, referencesOf, type Rule } from '../rules';
import { useDispatch, type Side } from '../state/workspace';

const CONSTANT = '__constant__';
const LABELS: Record<string, string> = {
  crosses_above: 'crosses above',
  crosses_below: 'crosses below',
  greater_than: 'greater than',
  less_than: 'less than',
  inside_band: 'inside band',
  outside_band: 'outside band',
};

/** Entry or exit of one side: one condition, or two joined by AND / OR (spec §6). */
export function RuleEditor({ side, which, spec }: { side: Side; which: 'entry' | 'exit'; spec: StrategySide }) {
  const dispatch = useDispatch();
  const rule = spec[which];
  const conditions = conditionsOf(rule);
  const any = isGroup(rule) && rule.any_of !== undefined && rule.any_of !== null;
  const series = [...(spec.indicators ?? []).flatMap((i) => referencesOf(i)), ...PRICE_OPERANDS];
  const bands = (spec.indicators ?? []).filter((i) => {
    const outputs = kindOf(i)?.outputs ?? [];
    return outputs.includes('upper') && outputs.includes('lower');
  });
  const base = `${side}-${which}`;

  const write = (next: RuleSpec[], joinAny = any) => {
    const value: Rule = next.length === 1 ? next[0] : joinAny ? { any_of: next } : { all_of: next };
    dispatch({ type: 'SET_RULE', side, which, rule: value });
  };
  const update = (index: number, patch: Partial<RuleSpec>) => {
    const next = conditions.map((c, i) => (i === index ? { ...c, ...patch } : c));
    write(next);
  };
  const setOperator = (index: number, operator: string) => {
    const current = conditions[index];
    const band = BAND_OPERATORS.includes(operator);
    let right = current.right;
    if (band && !bands.some((b) => b.id === right)) right = bands[0]?.id ?? right;
    if (!band && bands.some((b) => b.id === right)) right = '50';
    update(index, { operator, right });
  };

  return (
    <div className="rule-editor" id={`${base}-editor`}>
      <div className="small muted">{which.toUpperCase()}</div>
      {conditions.map((c, i) => {
        const band = BAND_OPERATORS.includes(c.operator);
        const rightIsConstant = !band && isConstant(c.right);
        return (
          <div className="row rule-row" key={i}>
            {i === 1 && (
              <select id={`${base}-join`} value={any ? 'any' : 'all'} onChange={(e) => write(conditions, e.target.value === 'any')} aria-label={`${side} ${which} join`}>
                <option value="all">AND</option>
                <option value="any">OR</option>
              </select>
            )}
            <select id={`${base}-left-${i}`} value={c.left} onChange={(e) => update(i, { left: e.target.value })} aria-label={`${side} ${which} condition ${i + 1} left`}>
              {!series.includes(c.left) && <option value={c.left}>{c.left}</option>}
              {series.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select id={`${base}-operator-${i}`} value={c.operator} onChange={(e) => setOperator(i, e.target.value)} aria-label={`${side} ${which} condition ${i + 1} operator`}>
              {OPERATORS.map((o) => (
                <option key={o} value={o}>
                  {LABELS[o]}
                </option>
              ))}
            </select>
            <select
              id={`${base}-right-${i}`}
              value={rightIsConstant ? CONSTANT : c.right}
              onChange={(e) => update(i, { right: e.target.value === CONSTANT ? '50' : e.target.value })}
              aria-label={`${side} ${which} condition ${i + 1} right`}
            >
              {band
                ? bands.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.id}
                    </option>
                  ))
                : [
                    ...(!series.includes(c.right) && !rightIsConstant ? [<option key="current" value={c.right}>{c.right}</option>] : []),
                    ...series.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    )),
                    <option key={CONSTANT} value={CONSTANT}>
                      constant…
                    </option>,
                  ]}
            </select>
            {rightIsConstant && (
              <input
                id={`${base}-constant-${i}`}
                type="number"
                step="any"
                value={c.right}
                aria-label={`${side} ${which} condition ${i + 1} constant`}
                onChange={(e) => {
                  if (isConstant(e.target.value)) update(i, { right: e.target.value });
                }}
              />
            )}
            {i === 1 && (
              <button type="button" className="btn" id={`${base}-remove-1`} onClick={() => write([conditions[0]])} title="Remove the second condition">
                ×
              </button>
            )}
          </div>
        );
      })}
      {conditions.length === 1 && (
        <button type="button" className="btn small" id={`${base}-add-condition`} onClick={() => write([conditions[0], { ...conditions[0] }], false)}>
          + condition
        </button>
      )}
    </div>
  );
}
