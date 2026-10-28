import { describe, expect, it } from 'vitest';
import type { Parameter, StrategySpec, Surface } from '../contracts';
import { families, parameterCount, parsePath, searchFamilies } from './catalog';

function surfaceOf(...parameters: Array<[string, number, number, number]>): Surface {
  return { parameters: parameters.map(([path, start, stop, step]): Parameter => ({ path, start, stop, step })) };
}

// A minimal spec cast through unknown, as src/state/workspace.test.ts does: only the indicators matter here.
type Indicators = Array<{ id: string; kind: string; length: number }>;

function specWith(long: Indicators, short: Indicators): StrategySpec {
  return {
    id: 'ema9-sma30-cross-v1',
    name: '9 EMA / 30 SMA Cross',
    description: 'test',
    long_side: { direction: 'long', indicators: long },
    short_side: { direction: 'short', indicators: short },
  } as unknown as StrategySpec;
}

const SURFACE = surfaceOf(
  ['long_side.indicators.ema.length', 5, 20, 1],
  ['long_side.indicators.sma.length', 20, 100, 5],
  ['long_side.stop_loss_pct', 1, 5, 0.5],
  ['short_side.indicators.ema.length', 5, 20, 1],
);

describe('parameterCount', () => {
  it('counts the values of a whole-step range, both ends included', () => {
    expect(parameterCount({ start: 2, stop: 10, step: 1 })).toBe(9);
    expect(parameterCount({ start: 5, stop: 20, step: 1 })).toBe(16);
    expect(parameterCount({ start: 20, stop: 100, step: 5 })).toBe(17);
  });

  it('has no floating-point off-by-one on a half step', () => {
    expect(parameterCount({ start: 1, stop: 5, step: 0.5 })).toBe(9);
  });

  it('absorbs the representation error of a tenth step', () => {
    // (0.7 - 0.1) / 0.1 is 5.999999999999999 in doubles; the 1e-9 nudge keeps the sixth step in the count.
    expect(parameterCount({ start: 0.1, stop: 0.7, step: 0.1 })).toBe(7);
    expect(parameterCount({ start: 0, stop: 1, step: 0.1 })).toBe(11);
  });

  it('counts a range whose step does not divide it only up to the last whole step', () => {
    expect(parameterCount({ start: 1, stop: 5, step: 3 })).toBe(2);
  });

  it('counts one value when start equals stop', () => {
    expect(parameterCount({ start: 7, stop: 7, step: 1 })).toBe(1);
  });
});

describe('families', () => {
  it('groups the surface into long ema, sma and levels, then short ema, in first-seen order', () => {
    const list = families(SURFACE, null);
    expect(list.map((f) => f.key)).toEqual(['long:ema', 'long:sma', 'long:levels', 'short:ema']);
    expect(list.map((f) => f.side)).toEqual(['long', 'long', 'long', 'short']);
    expect(list.filter((f) => f.side === 'long')).toHaveLength(3);
    expect(list.filter((f) => f.side === 'short')).toHaveLength(1);
  });

  it('counts each entry from its own range: 16, 17, 9 and 16', () => {
    const list = families(SURFACE, null);
    expect(list.flatMap((f) => f.entries.map((e) => e.count))).toEqual([16, 17, 9, 16]);
  });

  it('carries the path, side, family key, field and range on every entry', () => {
    const list = families(SURFACE, null);
    expect(list[0].entries).toEqual([
      { path: 'long_side.indicators.ema.length', side: 'long', family: 'long:ema', field: 'length', start: 5, stop: 20, step: 1, count: 16 },
    ]);
    expect(list[2].entries).toEqual([
      { path: 'long_side.stop_loss_pct', side: 'long', family: 'long:levels', field: 'stop_loss_pct', start: 1, stop: 5, step: 0.5, count: 9 },
    ]);
    expect(list[3].entries[0].side).toBe('short');
    expect(list[3].entries[0].family).toBe('short:ema');
  });

  it('labels a family with the indicator kind and length when the spec has it', () => {
    const spec = specWith(
      [
        { id: 'ema', kind: 'ema', length: 9 },
        { id: 'sma', kind: 'sma', length: 30 },
      ],
      [{ id: 'ema', kind: 'ema', length: 12 }],
    );
    const list = families(SURFACE, spec);
    expect(list.map((f) => f.label)).toEqual(['long · ema (EMA 9)', 'long · sma (SMA 30)', 'long · levels', 'short · ema (EMA 12)']);
  });

  it('labels a family with the id alone when there is no spec', () => {
    expect(families(SURFACE, null).map((f) => f.label)).toEqual(['long · ema', 'long · sma', 'long · levels', 'short · ema']);
  });

  it('falls back to the id alone for an indicator the spec does not hold or a spec with no indicators', () => {
    const spec = specWith([{ id: 'sma', kind: 'sma', length: 30 }], []);
    expect(families(SURFACE, spec).map((f) => f.label)).toEqual(['long · ema', 'long · sma (SMA 30)', 'long · levels', 'short · ema']);
    const bare = { long_side: {}, short_side: {} } as unknown as StrategySpec;
    expect(families(SURFACE, bare).map((f) => f.label)).toEqual(['long · ema', 'long · sma', 'long · levels', 'short · ema']);
  });

  it('keeps an indicator id on its own side: the same id on both sides makes two families', () => {
    const spec = specWith([{ id: 'ema', kind: 'ema', length: 9 }], [{ id: 'ema', kind: 'ema', length: 21 }]);
    const list = families(SURFACE, spec);
    expect(list.find((f) => f.key === 'long:ema')?.label).toBe('long · ema (EMA 9)');
    expect(list.find((f) => f.key === 'short:ema')?.label).toBe('short · ema (EMA 21)');
  });

  it('puts the length and the params of one indicator in one family, with the field after the id', () => {
    const list = families(
      surfaceOf(
        ['long_side.indicators.bb.length', 10, 30, 2],
        ['long_side.indicators.bb.params.mult', 1, 3, 0.5],
        ['long_side.indicators.ema.length', 5, 20, 1],
      ),
      null,
    );
    expect(list.map((f) => f.key)).toEqual(['long:bb', 'long:ema']);
    expect(list[0].entries.map((e) => e.field)).toEqual(['length', 'params.mult']);
    expect(list[0].entries.map((e) => e.count)).toEqual([11, 5]);
  });

  it('groups stop-loss and take-profit into one levels family per side', () => {
    const list = families(
      surfaceOf(
        ['short_side.stop_loss_pct', 1, 3, 0.5],
        ['short_side.take_profit_pct', 2, 6, 1],
        ['long_side.take_profit_pct', 2, 4, 1],
      ),
      null,
    );
    expect(list.map((f) => f.key)).toEqual(['short:levels', 'long:levels']);
    expect(list[0].entries.map((e) => e.field)).toEqual(['stop_loss_pct', 'take_profit_pct']);
    expect(list[0].label).toBe('short · levels');
    expect(list[1].entries.map((e) => e.field)).toEqual(['take_profit_pct']);
  });

  it('lists the sides in the order the surface first shows them', () => {
    const list = families(
      surfaceOf(
        ['short_side.indicators.ema.length', 5, 20, 1],
        ['long_side.indicators.ema.length', 5, 20, 1],
      ),
      null,
    );
    expect(list.map((f) => f.key)).toEqual(['short:ema', 'long:ema']);
  });

  it('skips a path that does not follow the convention and keeps the rest', () => {
    const list = families(
      surfaceOf(
        ['execution.slippage_bps', 0, 5, 1],
        ['long_side.entry.value', 1, 2, 1],
        ['long_side.indicators.ema', 1, 2, 1],
        ['middle_side.indicators.ema.length', 1, 2, 1],
        ['long_side.indicators.ema.length', 5, 20, 1],
      ),
      null,
    );
    expect(list.map((f) => f.key)).toEqual(['long:ema']);
    expect(list[0].entries).toHaveLength(1);
  });

  it('returns no families for an empty surface', () => {
    expect(families({ parameters: [] }, null)).toEqual([]);
  });
});

describe('searchFamilies', () => {
  const list = families(SURFACE, null);

  it("keeps only the levels family for 'stop', by the field of its entry", () => {
    expect(searchFamilies(list, 'stop').map((f) => f.key)).toEqual(['long:levels']);
  });

  it('returns the list itself for empty or whitespace-only text', () => {
    expect(searchFamilies(list, '')).toBe(list);
    expect(searchFamilies(list, '   ')).toBe(list);
  });

  it('matches case-insensitively and ignores the spaces around the text', () => {
    expect(searchFamilies(list, 'STOP').map((f) => f.key)).toEqual(['long:levels']);
    expect(searchFamilies(list, '  Stop_Loss ').map((f) => f.key)).toEqual(['long:levels']);
  });

  it('matches the family label', () => {
    expect(searchFamilies(list, 'sma').map((f) => f.key)).toEqual(['long:sma']);
    expect(searchFamilies(list, 'short').map((f) => f.key)).toEqual(['short:ema']);
    expect(searchFamilies(list, 'levels').map((f) => f.key)).toEqual(['long:levels']);
  });

  it("matches the label's spec text when the families were built with a spec", () => {
    const spec = specWith([{ id: 'ema', kind: 'ema', length: 9 }], []);
    expect(searchFamilies(families(SURFACE, spec), 'ema 9').map((f) => f.key)).toEqual(['long:ema']);
  });

  it('matches the path of an entry', () => {
    expect(searchFamilies(list, 'short_side.indicators').map((f) => f.key)).toEqual(['short:ema']);
  });

  it('matches the field of an entry', () => {
    expect(searchFamilies(list, 'length').map((f) => f.key)).toEqual(['long:ema', 'long:sma', 'short:ema']);
  });

  it('keeps each matching family whole, with all of its entries', () => {
    const wide = families(
      surfaceOf(
        ['long_side.indicators.bb.length', 10, 30, 2],
        ['long_side.indicators.bb.params.mult', 1, 3, 0.5],
      ),
      null,
    );
    const found = searchFamilies(wide, 'mult');
    expect(found).toHaveLength(1);
    expect(found[0].entries).toHaveLength(2);
  });

  it('returns an empty list when nothing matches', () => {
    expect(searchFamilies(list, 'zzz')).toEqual([]);
  });
});

describe('parameterCount and parsePath guards', () => {
  it('counts no values for a range whose stop is below its start, as surface.py does', () => {
    expect(parameterCount({ start: 10, stop: 5, step: 1 })).toBe(0);
    expect(parameterCount({ start: 1, stop: 0.5, step: 0.1 })).toBe(0);
  });

  it("parsePath('long_side.indicators.ema.params.') is null: a params path needs a name", () => {
    expect(parsePath('long_side.indicators.ema.params.')).toBeNull();
  });

  it('parsePath still reads a named params path, a length and a level field', () => {
    expect(parsePath('long_side.indicators.bb.params.mult')).toEqual({ side: 'long', id: 'bb', field: 'params.mult' });
    expect(parsePath('short_side.indicators.ema.length')).toEqual({ side: 'short', id: 'ema', field: 'length' });
    expect(parsePath('long_side.stop_loss_pct')).toEqual({ side: 'long', id: 'levels', field: 'stop_loss_pct' });
  });
});
