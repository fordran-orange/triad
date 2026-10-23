import { describe, expect, it } from 'vitest';
import type { RuleSpec, StrategySide } from '../contracts';
import { autoLayout, canConnect, graphFromSide, looseBlocks, readsAs, sideFromGraph, type SideGraph } from './graph';

const rule = (left: string, operator: string, right: string): RuleSpec => ({ left, operator, right, timing: 'bar_close' });
const ema = { id: 'ema', kind: 'EMA', length: 9, source: 'close', overlay: true };
const sma = { id: 'sma', kind: 'SMA', length: 30, source: 'close', overlay: true };
const donchian = { id: 'donchian', kind: 'DONCHIAN', length: 20, source: 'close', overlay: true };
const rsi = { id: 'rsi', kind: 'RSI', length: 14, source: 'close', overlay: true };
const bb = { id: 'bb', kind: 'BB', length: 20, source: 'close', overlay: true };

const reference: StrategySide = {
  direction: 'long',
  enabled: true,
  indicators: [ema, sma],
  entry: rule('ema', 'crosses_above', 'sma'),
  exit: rule('ema', 'crosses_below', 'sma'),
  optimization: [{ path: 'indicators.ema.length', enabled: true, start: 5, stop: 20, step: 1 }],
};
const breakout: StrategySide = {
  direction: 'long',
  enabled: true,
  indicators: [donchian, rsi],
  entry: { all_of: [rule('price.close', 'crosses_above', 'donchian.upper'), rule('rsi', 'less_than', '70')] },
  exit: rule('price.close', 'crosses_below', 'donchian.middle'),
  optimization: [],
};
const nested: StrategySide = {
  direction: 'short',
  enabled: true,
  indicators: [rsi, sma, ema, bb],
  entry: { all_of: [rule('rsi', 'crosses_below', '70'), { any_of: [rule('price.close', 'less_than', 'sma'), rule('price.close', 'outside_band', 'bb'), rule('ema', 'less_than', '100.25')] }] },
  exit: { any_of: [rule('rsi', 'less_than', '30'), { all_of: [rule('price.high', 'greater_than', 'sma'), rule('price.close', 'inside_band', 'bb')] }] },
  optimization: [],
};
const stopOnly: StrategySide = { ...reference, exit: undefined, stop_loss_pct: 2 };
const ruleAndLevels: StrategySide = { ...reference, stop_loss_pct: 1.5, take_profit_pct: 4 };

const without = (graph: SideGraph, match: (w: SideGraph['wires'][number]) => boolean): SideGraph => ({ ...graph, wires: graph.wires.filter((w) => !match(w)) });
const problem = (graph: SideGraph, base: StrategySide) => sideFromGraph(graph, base).problem;

describe('graph ↔ strategy side', () => {
  it.each([
    ['reference', reference],
    ['breakout', breakout],
    ['nested tree', nested],
    ['stop-only exit', stopOnly],
    ['rule exit and both levels', ruleAndLevels],
  ])('round-trips the %s', (_name, side) => {
    const result = sideFromGraph(graphFromSide(side), side);
    expect(result.problem).toBeNull();
    expect(result.side).toEqual(side);
    expect(readsAs(graphFromSide(side), side)).toBe(true);
  });

  it('keeps one block per indicator however many conditions read it', () => {
    const graph = graphFromSide(nested);
    expect(graph.blocks.filter((b) => b.type === 'indicator').map((b) => b.id)).toEqual(['rsi', 'sma', 'ema', 'bb']);
    expect(graph.wires.filter((w) => w.from === 'rsi')).toHaveLength(2);
  });

  it('counts an AND with one wired input as that input, and ignores loose blocks', () => {
    const graph = graphFromSide(reference);
    const into = graph.wires.find((w) => w.to === 'entry')!;
    const and: SideGraph = {
      blocks: [...graph.blocks, { id: 'and-9', type: 'and', x: 0, y: 0, settings: {} }, { id: 'condition-9', type: 'condition', x: 0, y: 0, settings: { operator: 'greater_than', right: '5' } }],
      wires: [
        ...graph.wires.filter((w) => w !== into),
        { id: 'w-a', from: into.from, fromPort: into.fromPort, to: 'and-9', toPort: 'in0' },
        { id: 'w-b', from: 'and-9', fromPort: 'out', to: 'entry', toPort: 'rule' },
      ],
    };
    expect(sideFromGraph(and, reference).side).toEqual(reference);
    expect([...looseBlocks(and)]).toEqual(['condition-9']);
  });
});

describe('problems', () => {
  it('names what is missing, exactly', () => {
    const graph = graphFromSide(reference);
    expect(problem(without(graph, (w) => w.to === 'entry'), reference)).toBe('Entry has nothing wired in');
    expect(problem(without(graph, (w) => w.to === 'exit'), reference)).toBe('Exit has nothing wired in');
    const condition = graph.wires.find((w) => w.to === 'entry')!.from;
    expect(problem(without(graph, (w) => w.to === condition && w.toPort === 'left'), reference)).toBe(`${condition}: left input is empty`);
    const empty: SideGraph = {
      blocks: [
        { id: 'entry', type: 'entry', x: 0, y: 0, settings: {} },
        { id: 'exit', type: 'exit', x: 0, y: 0, settings: {} },
        { id: 'and-1', type: 'and', x: 0, y: 0, settings: {} },
        { id: 'stop_loss-1', type: 'stop_loss', x: 0, y: 0, settings: { pct: null } },
      ],
      wires: [
        { id: 'w1', from: 'and-1', fromPort: 'out', to: 'entry', toPort: 'rule' },
        { id: 'w2', from: 'stop_loss-1', fromPort: 'out', to: 'exit', toPort: 'stop' },
      ],
    };
    expect(problem(empty, reference)).toBe('and-1 has nothing wired in');
    const stopped = graphFromSide(stopOnly);
    const stop = stopped.blocks.find((b) => b.type === 'stop_loss')!;
    stop.settings = { pct: null };
    expect(problem(stopped, stopOnly)).toBe('Stop loss needs a percentage above 0');
  });
});

describe('canConnect', () => {
  const graph = graphFromSide(breakout);
  const condition = graph.wires.find((w) => w.to === 'exit' && w.toPort === 'rule')!.from;
  const withBlocks: SideGraph = {
    blocks: [
      ...graph.blocks,
      { id: 'and-7', type: 'and', x: 0, y: 0, settings: {} },
      { id: 'stop_loss-7', type: 'stop_loss', x: 0, y: 0, settings: { pct: 2 } },
      { id: 'condition-7', type: 'condition', x: 0, y: 0, settings: { operator: 'inside_band' } },
    ],
    wires: graph.wires,
  };

  it('allows a series into a condition and a condition into a group', () => {
    expect(canConnect(withBlocks, { from: 'price', fromPort: 'close', to: 'condition-7', toPort: 'left' })).toBeNull();
    expect(canConnect(withBlocks, { from: condition, fromPort: 'out', to: 'and-7', toPort: 'in0' })).toBeNull();
    expect(canConnect(withBlocks, { from: 'stop_loss-7', fromPort: 'out', to: 'exit', toPort: 'stop' })).toBeNull();
  });

  it('refuses a wire that breaks a rule, saying why', () => {
    expect(canConnect(withBlocks, { from: 'stop_loss-7', fromPort: 'out', to: 'entry', toPort: 'rule' })).toBe('a stop goes into Exit');
    expect(canConnect(withBlocks, { from: 'price', fromPort: 'close', to: 'and-7', toPort: 'in0' })).toBe('a series goes into a condition');
    expect(canConnect(withBlocks, { from: condition, fromPort: 'out', to: 'entry', toPort: 'rule' })).toBe('Entry takes one input: join conditions with AND or OR first');
    expect(canConnect(withBlocks, { from: 'rsi', fromPort: 'value', to: 'condition-7', toPort: 'right' })).toBe('inside band needs a band on the right');
    const looped: SideGraph = {
      ...withBlocks,
      blocks: [...withBlocks.blocks, { id: 'or-8', type: 'or', x: 0, y: 0, settings: {} }],
      wires: [...withBlocks.wires, { id: 'w-x', from: 'and-7', fromPort: 'out', to: 'or-8', toPort: 'in0' }],
    };
    expect(canConnect(looped, { from: 'or-8', fromPort: 'out', to: 'and-7', toPort: 'in0' })).toBe('that would make a loop');
  });
});

describe('readsAs and layout', () => {
  it('is false when the graph names an indicator the side no longer has, or a rule differs', () => {
    const graph = graphFromSide(breakout);
    expect(readsAs(graph, { ...breakout, indicators: [donchian] })).toBe(false);
    expect(readsAs(graph, { ...breakout, exit: rule('price.close', 'crosses_below', 'donchian.lower') })).toBe(false);
  });

  it('lays out price and indicators, then conditions, then groups, then Entry and Exit', () => {
    const graph = autoLayout(graphFromSide(nested));
    const xs = (types: string[]) => graph.blocks.filter((b) => types.includes(b.type)).map((b) => b.x);
    expect(Math.max(...xs(['price', 'indicator']))).toBeLessThan(Math.min(...xs(['condition'])));
    expect(Math.max(...xs(['condition']))).toBeLessThan(Math.min(...xs(['and', 'or'])));
    expect(Math.max(...xs(['and', 'or']))).toBeLessThan(Math.min(...xs(['entry', 'exit'])));
    const places = graph.blocks.map((b) => `${b.x},${b.y}`);
    expect(new Set(places).size).toBe(places.length);
  });
});
