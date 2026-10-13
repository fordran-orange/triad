// Rule and indicator helpers shared by the side cards, the Indicators tab, the rule editors and the
// walk-forward window proposal. Kind metadata comes from INDICATOR_KINDS, generated from the
// Python registry (app/products/aegis/kinds.py), so warm-up and outputs agree with the engine.
import { INDICATOR_KINDS, type IndicatorKind, type IndicatorSpec, type RuleGroup, type RuleSpec, type StrategySide } from './contracts';

export type Rule = RuleSpec | RuleGroup;

export const PRICE_OPERANDS = ['price.close', 'price.open', 'price.high', 'price.low'] as const;
export const OPERATORS = ['crosses_above', 'crosses_below', 'greater_than', 'less_than', 'inside_band', 'outside_band'] as const;
export const BAND_OPERATORS = ['inside_band', 'outside_band'];
export type Operator = (typeof OPERATORS)[number];
export const NO_BAND_TITLE = 'needs a band indicator (one with upper and lower outputs) on this side';

const CONSTANT = /^-?\d+(\.\d+)?$/;

export function isConstant(operand: string): boolean {
  return CONSTANT.test(operand);
}

export function kindOf(spec: Pick<IndicatorSpec, 'kind'>): IndicatorKind | undefined {
  return INDICATOR_KINDS[spec.kind.toUpperCase()];
}

/** The series names rules and the chart use for an indicator: `id`, or `id.output` per output. */
export function referencesOf(spec: Pick<IndicatorSpec, 'id' | 'kind'>): string[] {
  const outputs = kindOf(spec)?.outputs ?? [];
  return outputs.length ? outputs.map((o) => `${spec.id}.${o}`) : [spec.id];
}

/** The side's band indicators: kinds with both an upper and a lower output. */
export function bandIndicators(indicators: IndicatorSpec[] | null | undefined): IndicatorSpec[] {
  return (indicators ?? []).filter((i) => {
    const outputs = kindOf(i)?.outputs ?? [];
    return outputs.includes('upper') && outputs.includes('lower');
  });
}

/** The operator menu: the band operators are disabled, with the reason, until the side has a band (P14 item 4). */
export function operatorChoices(hasBand: boolean): { operator: Operator; disabled: boolean; title: string | undefined }[] {
  return OPERATORS.map((operator) => {
    const disabled = !hasBand && BAND_OPERATORS.includes(operator);
    return { operator, disabled, title: disabled ? NO_BAND_TITLE : undefined };
  });
}

export function effectiveParams(spec: Pick<IndicatorSpec, 'kind' | 'params'>): Record<string, number> {
  return { ...(kindOf(spec)?.params ?? {}), ...(spec.params ?? {}) };
}

function warmupFrom(kind: string, length: number, params: Record<string, number>): number {
  const info = INDICATOR_KINDS[kind.toUpperCase()];
  if (!info) return length;
  const values: Record<string, number> = { length, ...params };
  return Math.round(info.warmup_terms.reduce((sum, term) => sum + (values[term] ?? 0), 0)) + info.warmup_offset;
}

/** Bars after which every output of the indicator has a value (kinds.warmup). */
export function warmupOf(spec: Pick<IndicatorSpec, 'kind' | 'length' | 'params'> & Partial<IndicatorSpec>): number {
  return warmupFrom(spec.kind, spec.length, effectiveParams(spec));
}

/** strategy.side_warmup with ranges: each indicator at the far end of its enabled ranges. */
export function warmupBars(side: StrategySide | undefined): number {
  if (!side) return 0;
  let longest = 0;
  for (const spec of side.indicators ?? []) {
    let length = spec.length;
    const params = effectiveParams(spec);
    for (const range of side.optimization ?? []) {
      if (range.enabled === false) continue;
      const parts = range.path.split('.');
      if (parts[0] !== 'indicators' || parts[1] !== spec.id) continue;
      if (parts.length === 3 && parts[2] === 'length') length = Math.max(length, Math.ceil(range.stop));
      else if (parts.length === 4 && parts[2] === 'params' && parts[3] in params) params[parts[3]] = Math.max(params[parts[3]], range.stop);
    }
    longest = Math.max(longest, warmupFrom(spec.kind, length, params));
  }
  return longest;
}

export function isGroup(rule: Rule): rule is RuleGroup {
  return !('left' in rule);
}

export function conditionsOf(rule: Rule): RuleSpec[] {
  if (!isGroup(rule)) return [rule];
  return rule.all_of ?? rule.any_of ?? [];
}

const VERBS: Record<string, string> = {
  crosses_above: 'crosses ABOVE',
  crosses_below: 'crosses BELOW',
  greater_than: '>',
  less_than: '<',
  inside_band: 'inside',
  outside_band: 'outside',
};

function operandLabel(operand: string, indicators: IndicatorSpec[]): string {
  const [id, output] = operand.split('.', 2);
  const spec = indicators.find((i) => i.id === id);
  if (!spec) return operand; // price fields and constants read as written
  const name = `${spec.kind.toUpperCase()}(${spec.length})`;
  return output ? `${name}.${output}` : name;
}

/** A rule in words, e.g. `price.close crosses ABOVE DONCHIAN(20).upper AND RSI(14) < 70`. */
export function describeRule(rule: Rule, indicators: IndicatorSpec[]): string {
  const one = (r: RuleSpec) => `${operandLabel(r.left, indicators)} ${VERBS[r.operator] ?? r.operator} ${operandLabel(r.right, indicators)}`;
  const parts = conditionsOf(rule).map(one);
  return parts.join(isGroup(rule) && rule.any_of ? ' OR ' : ' AND ');
}

function reads(condition: RuleSpec, id: string): boolean {
  return [condition.left, condition.right].some((o) => o === id || o.startsWith(id + '.'));
}

/** The side's rules that read an indicator ("entry rule", "exit rule"); removal is refused while any do. */
export function ruleReferences(side: StrategySide, id: string): string[] {
  const names: string[] = [];
  if (conditionsOf(side.entry).some((c) => reads(c, id))) names.push('entry rule');
  if (conditionsOf(side.exit).some((c) => reads(c, id))) names.push('exit rule');
  return names;
}
