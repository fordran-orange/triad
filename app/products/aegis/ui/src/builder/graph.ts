/**
 * The builder's graph (Mission 13 spec §4.5–4.6): a side as blocks and wires. The canvas is a view
 * of the strategy: `graphFromSide` draws a side, `sideFromGraph` reads it back (or names the first
 * problem), `canConnect` says why a wire is refused. No React here; the canvas renders these.
 */
import { INDICATOR_KINDS, type IndicatorSpec, type OptimizationParameter, type RuleSpec, type StrategySide } from '../contracts';
import { BAND_OPERATORS, isConstant, isGroup, membersOf, type Rule } from '../rules';

export type BlockType = 'price' | 'indicator' | 'condition' | 'and' | 'or' | 'stop_loss' | 'take_profit' | 'entry' | 'exit';

/** indicator: the spec; condition: its operator and any number typed into an unwired input;
 * stop_loss / take_profit: the percentage and whether the phrase reader set it as the default. */
export interface BlockSettings {
  indicator?: IndicatorSpec;
  operator?: string;
  left?: string;
  right?: string;
  pct?: number | null;
  badge?: 'default';
}

export interface Block {
  id: string;
  type: BlockType;
  x: number;
  y: number;
  settings: BlockSettings;
}

export interface Wire {
  id: string;
  from: string;
  fromPort: string;
  to: string;
  toPort: string;
}

export interface SideGraph {
  blocks: Block[];
  wires: Wire[];
}

export interface Canvas {
  version: 1;
  long: SideGraph;
  short: SideGraph;
}

export const PRICE_PORTS = ['close', 'open', 'high', 'low'];
const FIXED = new Set(['entry', 'exit', 'price']);
const OPERATOR_LABELS: Record<string, string> = { inside_band: 'inside band', outside_band: 'outside band' };
const COLUMN = 230;
const ROW = 150; // the tallest block (a condition) is about 125 px

type Signal = 'series' | 'band' | 'rule' | 'stop' | 'target';

function kindOutputs(spec: IndicatorSpec | undefined): string[] {
  return INDICATOR_KINDS[(spec?.kind ?? '').toUpperCase()]?.outputs ?? [];
}

function isBandKind(spec: IndicatorSpec | undefined): boolean {
  const outputs = kindOutputs(spec);
  return outputs.includes('upper') && outputs.includes('lower');
}

/** The ports a block offers to wires leaving it. */
export function outputPorts(block: Block): string[] {
  switch (block.type) {
    case 'price':
      return PRICE_PORTS;
    case 'indicator': {
      const outputs = kindOutputs(block.settings.indicator);
      return [...(outputs.length ? outputs : ['value']), ...(isBandKind(block.settings.indicator) ? ['band'] : [])];
    }
    case 'entry':
    case 'exit':
      return [];
    default:
      return ['out'];
  }
}

/** The ports a block takes wires into; AND and OR keep one spare input. */
export function inputPorts(block: Block, graph: SideGraph): string[] {
  switch (block.type) {
    case 'condition':
      return ['left', 'right'];
    case 'and':
    case 'or': {
      const used = graph.wires.filter((w) => w.to === block.id).length;
      return Array.from({ length: used + 1 }, (_, i) => `in${i}`);
    }
    case 'entry':
      return ['rule'];
    case 'exit':
      return ['rule', 'stop', 'target'];
    default:
      return [];
  }
}

function signalOut(block: Block, port: string): Signal {
  if (block.type === 'price' || block.type === 'indicator') return port === 'band' ? 'band' : 'series';
  if (block.type === 'stop_loss') return 'stop';
  if (block.type === 'take_profit') return 'target';
  return 'rule';
}

// -- strategy side → graph ------------------------------------------------------------------------

/** A side drawn as blocks: Price, Entry and Exit always; one block per indicator; conditions and
 * groups as the rules nest; Stop loss / Take profit into Exit. Laid out automatically. */
export function graphFromSide(side: StrategySide): SideGraph {
  const blocks: Block[] = [
    { id: 'price', type: 'price', x: 0, y: 0, settings: {} },
    ...(side.indicators ?? []).map((spec): Block => ({ id: spec.id, type: 'indicator', x: 0, y: 0, settings: { indicator: spec } })),
    { id: 'entry', type: 'entry', x: 0, y: 0, settings: {} },
    { id: 'exit', type: 'exit', x: 0, y: 0, settings: {} },
  ];
  const wires: Wire[] = [];
  const counters: Record<string, number> = {};
  const nextId = (type: string) => `${type}-${(counters[type] = (counters[type] ?? 0) + 1)}`;
  const wire = (from: string, fromPort: string, to: string, toPort: string) => wires.push({ id: `w${wires.length + 1}`, from, fromPort, to, toPort });

  const operand = (value: string, to: string, port: string, band: boolean): string | undefined => {
    if (band) {
      wire(value, 'band', to, port);
      return undefined;
    }
    if (value.startsWith('price.')) {
      wire('price', value.slice('price.'.length), to, port);
      return undefined;
    }
    if (isConstant(value)) return value;
    const [id, output] = value.split('.', 2);
    wire(id, output ?? 'value', to, port);
    return undefined;
  };

  const draw = (rule: Rule): string => {
    if (!isGroup(rule)) {
      const id = nextId('condition');
      const band = BAND_OPERATORS.includes(rule.operator);
      const settings: BlockSettings = { operator: rule.operator };
      blocks.push({ id, type: 'condition', x: 0, y: 0, settings });
      const left = operand(rule.left, id, 'left', false);
      const right = operand(rule.right, id, 'right', band);
      if (left !== undefined) settings.left = left;
      if (right !== undefined) settings.right = right;
      return id;
    }
    const type = rule.any_of !== undefined && rule.any_of !== null ? 'or' : 'and';
    const id = nextId(type);
    blocks.push({ id, type, x: 0, y: 0, settings: {} });
    membersOf(rule).forEach((member, i) => wire(draw(member), 'out', id, `in${i}`));
    return id;
  };

  wire(draw(side.entry), 'out', 'entry', 'rule');
  if (side.exit) wire(draw(side.exit), 'out', 'exit', 'rule');
  if (side.stop_loss_pct != null) {
    const id = nextId('stop_loss');
    blocks.push({ id, type: 'stop_loss', x: 0, y: 0, settings: { pct: side.stop_loss_pct } });
    wire(id, 'out', 'exit', 'stop');
  }
  if (side.take_profit_pct != null) {
    const id = nextId('take_profit');
    blocks.push({ id, type: 'take_profit', x: 0, y: 0, settings: { pct: side.take_profit_pct } });
    wire(id, 'out', 'exit', 'target');
  }
  return autoLayout({ blocks, wires });
}

// -- graph → strategy side ------------------------------------------------------------------------

class Problem extends Error {}

function inputsOf(graph: SideGraph, id: string): Wire[] {
  return graph.wires.filter((w) => w.to === id);
}

function blockOf(graph: SideGraph, id: string): Block {
  const block = graph.blocks.find((b) => b.id === id);
  if (!block) throw new Problem(`${id} is missing`);
  return block;
}

function operandOf(graph: SideGraph, wire: Wire | undefined): string | undefined {
  if (!wire) return undefined;
  const source = blockOf(graph, wire.from);
  if (source.type === 'price') return `price.${wire.fromPort}`;
  if (wire.fromPort === 'value' || wire.fromPort === 'band') return source.id;
  return `${source.id}.${wire.fromPort}`;
}

function ruleOf(graph: SideGraph, id: string): Rule {
  const block = blockOf(graph, id);
  if (block.type === 'condition') {
    const inputs = inputsOf(graph, id);
    const left = operandOf(graph, inputs.find((w) => w.toPort === 'left')) ?? block.settings.left;
    const right = operandOf(graph, inputs.find((w) => w.toPort === 'right')) ?? block.settings.right;
    if (left === undefined || left === '') throw new Problem(`${id}: left input is empty`);
    if (right === undefined || right === '') throw new Problem(`${id}: right input is empty`);
    const condition: RuleSpec = { left, operator: block.settings.operator ?? 'greater_than', right, timing: 'bar_close' };
    return condition;
  }
  if (block.type === 'and' || block.type === 'or') {
    const members = inputsOf(graph, id)
      .sort((a, b) => Number(a.toPort.slice(2)) - Number(b.toPort.slice(2)))
      .map((w) => ruleOf(graph, w.from));
    if (members.length === 0) throw new Problem(`${id} has nothing wired in`);
    if (members.length === 1) return members[0];
    return block.type === 'and' ? { all_of: members } : { any_of: members };
  }
  throw new Problem(`${id} is not a rule`);
}

function levelOf(graph: SideGraph, port: 'stop' | 'target'): number | undefined {
  const wire = inputsOf(graph, 'exit').find((w) => w.toPort === port);
  if (!wire) return undefined;
  const pct = blockOf(graph, wire.from).settings.pct;
  if (pct == null || !(pct > 0)) throw new Problem(`${port === 'stop' ? 'Stop loss' : 'Take profit'} needs a percentage above 0`);
  return pct;
}

const levelPath = (path: string) => path === 'stop_loss_pct' || path === 'take_profit_pct';

/** The side the graph describes, built on `base` (its direction, switch and ranges), or the first
 * problem by name. Loose blocks are ignored; a group with one input counts as that input. */
export function sideFromGraph(graph: SideGraph, base: StrategySide): { side: StrategySide; problem: null } | { side: null; problem: string } {
  try {
    const entryWire = inputsOf(graph, 'entry').find((w) => w.toPort === 'rule');
    if (!entryWire) throw new Problem('Entry has nothing wired in');
    const entry = ruleOf(graph, entryWire.from);
    const exitWire = inputsOf(graph, 'exit').find((w) => w.toPort === 'rule');
    const exit = exitWire ? ruleOf(graph, exitWire.from) : undefined;
    const stop = levelOf(graph, 'stop');
    const target = levelOf(graph, 'target');
    if (exit === undefined && stop === undefined && target === undefined) throw new Problem('Exit has nothing wired in');
    const specs = graph.blocks.filter((b) => b.type === 'indicator').map((b) => ({ ...b.settings.indicator!, id: b.id }));
    const order = (base.indicators ?? []).map((i) => i.id);
    const indicators = [
      ...order.flatMap((id) => specs.filter((s) => s.id === id)),
      ...specs.filter((s) => !order.includes(s.id)),
    ];
    const ids = new Set(indicators.map((i) => i.id));
    const optimization = (base.optimization ?? []).filter((r: OptimizationParameter) =>
      levelPath(r.path) ? (r.path === 'stop_loss_pct' ? stop : target) !== undefined : ids.has(r.path.split('.')[1]),
    );
    const side: StrategySide = { ...base, indicators, entry, optimization };
    delete side.exit;
    delete side.stop_loss_pct;
    delete side.take_profit_pct;
    if (exit !== undefined) side.exit = exit;
    if (stop !== undefined) side.stop_loss_pct = stop;
    if (target !== undefined) side.take_profit_pct = target;
    return { side, problem: null };
  } catch (error) {
    if (error instanceof Problem) return { side: null, problem: error.message };
    throw error;
  }
}

function canonical(value: unknown): string {
  const sort = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sort);
    if (v && typeof v === 'object')
      return Object.fromEntries(
        Object.keys(v as Record<string, unknown>)
          .filter((k) => (v as Record<string, unknown>)[k] !== undefined && (v as Record<string, unknown>)[k] !== null)
          .sort()
          .map((k) => [k, sort((v as Record<string, unknown>)[k])]),
      );
    return v;
  };
  return JSON.stringify(sort(value));
}

/** Whether a saved graph still reads as this side (ranges aside): if not, the side is laid out
 * afresh rather than drawing a canvas that no longer matches the strategy. */
export function readsAs(graph: SideGraph, side: StrategySide): boolean {
  const read = sideFromGraph(graph, side);
  if (read.side === null) return false;
  const strip = (s: StrategySide) => ({ ...s, optimization: undefined });
  return canonical(strip(read.side)) === canonical(strip(side));
}

// -- wiring rules ---------------------------------------------------------------------------------

function feeds(graph: SideGraph, from: string, target: string, seen = new Set<string>()): boolean {
  if (from === target) return true;
  if (seen.has(from)) return false;
  seen.add(from);
  return inputsOf(graph, from).some((w) => feeds(graph, w.from, target, seen));
}

/** null when the wire is allowed; otherwise a short reason for the status line. */
export function canConnect(graph: SideGraph, wire: Omit<Wire, 'id'>): string | null {
  const from = graph.blocks.find((b) => b.id === wire.from);
  const to = graph.blocks.find((b) => b.id === wire.to);
  if (!from || !to) return 'that block is gone';
  if (!outputPorts(from).includes(wire.fromPort) || !inputPorts(to, graph).includes(wire.toPort)) return 'those ports do not connect';
  const signal = signalOut(from, wire.fromPort);
  const wants: Signal =
    to.type === 'condition'
      ? wire.toPort === 'right' && BAND_OPERATORS.includes(to.settings.operator ?? '')
        ? 'band'
        : 'series'
      : to.type === 'exit' && wire.toPort === 'stop'
        ? 'stop'
        : to.type === 'exit' && wire.toPort === 'target'
          ? 'target'
          : 'rule';
  if (signal === 'stop' && wants !== 'stop') return 'a stop goes into Exit';
  if (signal === 'target' && wants !== 'target') return 'a take profit goes into Exit';
  if (signal === 'series' && wants === 'band') return `${OPERATOR_LABELS[to.settings.operator ?? ''] ?? 'that comparison'} needs a band on the right`;
  if (signal === 'band' && wants !== 'band') return wants === 'series' ? 'a band goes into the right of inside or outside' : 'a band goes into a condition';
  if (signal === 'series' && wants !== 'series') return 'a series goes into a condition';
  if (signal === 'rule' && (wants === 'series' || wants === 'band')) return 'a condition goes into AND, OR, Entry or Exit';
  if (signal === 'rule' && (wants === 'stop' || wants === 'target')) return 'a condition goes into the rule input of Exit';
  if (graph.wires.some((w) => w.to === wire.to && w.toPort === wire.toPort)) {
    if (to.type === 'entry') return 'Entry takes one input: join conditions with AND or OR first';
    if (to.type === 'exit' && wire.toPort === 'rule') return 'Exit takes one rule: join conditions with AND or OR first';
    if (to.type === 'exit') return wire.toPort === 'stop' ? 'Exit already has a stop loss' : 'Exit already has a take profit';
    return 'that input is taken';
  }
  if (feeds(graph, wire.from, wire.to)) return 'that would make a loop';
  return null;
}

/** Blocks from which no wire leads to Entry or Exit: greyed on the canvas, ignored by backtests. */
export function looseBlocks(graph: SideGraph): Set<string> {
  const reached = new Set<string>(['entry', 'exit']);
  let grew = true;
  while (grew) {
    grew = false;
    for (const w of graph.wires)
      if (reached.has(w.to) && !reached.has(w.from)) {
        reached.add(w.from);
        grew = true;
      }
  }
  return new Set(graph.blocks.filter((b) => !FIXED.has(b.id) && !reached.has(b.id)).map((b) => b.id));
}

// -- layout ---------------------------------------------------------------------------------------

/** Columns by role, left to right: price and indicators, conditions, groups (innermost first),
 * Stop loss / Take profit, then Entry and Exit; rows in the order the rules are drawn. */
export function autoLayout(graph: SideGraph): SideGraph {
  const height = (id: string, seen = new Set<string>()): number => {
    if (seen.has(id)) return 1;
    seen.add(id);
    const inner = inputsOf(graph, id)
      .map((w) => graph.blocks.find((b) => b.id === w.from))
      .filter((b): b is Block => !!b && (b.type === 'and' || b.type === 'or'))
      .map((b) => height(b.id, seen));
    return 1 + Math.max(0, ...inner);
  };
  const groups = graph.blocks.filter((b) => b.type === 'and' || b.type === 'or');
  const tallest = Math.max(0, ...groups.map((g) => height(g.id)));
  const column = (block: Block): number => {
    switch (block.type) {
      case 'price':
      case 'indicator':
        return 0;
      case 'condition':
        return 1;
      case 'and':
      case 'or':
        return 1 + height(block.id);
      case 'stop_loss':
      case 'take_profit':
        return 2 + tallest;
      default:
        return 3 + tallest;
    }
  };
  const rows: Record<number, number> = {};
  const blocks = graph.blocks.map((block) => {
    const col = column(block);
    const row = (rows[col] = (rows[col] ?? -1) + 1);
    return { ...block, x: col * COLUMN, y: row * ROW };
  });
  return { ...graph, blocks };
}
