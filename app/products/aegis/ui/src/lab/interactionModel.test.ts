import { describe, expect, it } from 'vitest';
import { IMPORTANCE_CONSTANTS, interactions, pair, PATHS } from './analyticsFixtures';
import { hoverText, intensity, interactionModel, matrixLayout, matrixSummary, truncatedNotice, unresolvedText } from './interactionModel';

describe('the matrix of J', () => {
  const view = interactions();
  const model = interactionModel(view)!;

  it('has no matrix before the first stage was delivered', () => {
    expect(interactionModel(interactions({ computed: null, pairs: [], total_pairs: 0, unresolved_pairs: 0, constants: null }))).toBeNull();
  });

  it('is d × d, with d read from the number of pairs, and names its parameters by their index', () => {
    expect(model.size).toBe(4); // 6 pairs: d = 4
    expect(model.labels).toEqual(PATHS);
    expect(model.cells).toHaveLength(4);
    for (const row of model.cells) expect(row).toHaveLength(4);
  });

  it('puts a pair on both sides of the diagonal, each reading its own direction of Δ, and leaves the diagonal empty', () => {
    const upper = model.cells[0][1]!;
    const lower = model.cells[1][0]!;
    expect(upper.pair).toBe(lower.pair);
    expect(upper.own).toBe('D_ij'); // row 0 is the pair's first parameter: what it adds beyond the second
    expect(lower.own).toBe('D_ji');
    for (let i = 0; i < 4; i++) expect(model.cells[i][i]).toBeNull();
  });

  it('lists the unresolved pairs in the order the server sent them, not re-sorted', () => {
    expect(model.unresolved.map((p) => p.pair)).toEqual([[PATHS[1], PATHS[2]], [PATHS[0], PATHS[3]]]);
    const swapped = interactionModel(interactions({ pairs: [pair(0, 3, { unresolved: true, coverage: 0.1 }), pair(0, 1), pair(1, 2, { unresolved: true, coverage: 0.3 })] }))!;
    expect(swapped.unresolved.map((p) => p.index)).toEqual([[0, 3], [1, 2]]);
  });

  it('shades a resolved pair by J and hatches an unresolved one: no value, however large its J', () => {
    const big = interactionModel(interactions({ pairs: [pair(0, 1, { J: { value: 0.2, lo: 0.1, hi: 0.3 } }), pair(0, 2, { J: { value: 0.1, lo: 0.05, hi: 0.15 } }), pair(1, 2, { unresolved: true, coverage: 0.2, J: { value: 0.9, lo: 0.8, hi: 1 } })], total_pairs: 3, unresolved_pairs: 1 }))!;
    expect(big.maxJ).toBe(0.2); // the resolved pairs' largest: an unresolved J does not stretch the scale
    expect(intensity(big.cells[0][1], big.maxJ)).toBe(1);
    expect(intensity(big.cells[0][2], big.maxJ)).toBe(0.5);
    expect(intensity(big.cells[1][2], big.maxJ)).toBeNull(); // hatched
    expect(intensity(null, big.maxJ)).toBeNull(); // no pair sent for this square
  });

  it('shades a J below zero as zero, and never divides by a zero scale', () => {
    const low = interactionModel(interactions({ pairs: [pair(0, 1, { J: { value: -0.01, lo: -0.03, hi: 0.01 } })], total_pairs: 1, unresolved_pairs: 0 }))!;
    expect(intensity(low.cells[0][1], low.maxJ)).toBe(0);
    expect(Number.isFinite(low.maxJ)).toBe(true);
  });

  it('a truncated answer leaves the pairs it cut as empty squares and says so', () => {
    const cut = interactions({ pairs: [pair(0, 1), pair(0, 2)], total_pairs: 300, unresolved_pairs: 0, truncated: true });
    const m = interactionModel(cut)!;
    expect(m.size).toBe(25); // 300 pairs: d = 25
    expect(m.cells[1][2]).toBeNull();
    expect(truncatedNotice(cut)).toBe('truncated: the first 2 of 300 pairs are shown');
    expect(truncatedNotice(view)).toBeNull();
  });
});

describe('the hover and the lists', () => {
  const v = interactions();
  const model = interactionModel(v)!;

  it('reads J with its interval, the Δ of the hovered direction first, and I as display only', () => {
    const text = hoverText(model.cells[0][1]!, v.constants!);
    expect(text).toContain('ema.length × sma.length');
    expect(text).toContain('J 20.0% [18.0%–22.0%]');
    expect(text.indexOf('Δ ema.length beyond sma.length')).toBeGreaterThan(-1);
    expect(text.indexOf('Δ ema.length beyond sma.length')).toBeLessThan(text.indexOf('Δ sma.length beyond ema.length'));
    expect(text).toContain('(floor 3.0%, detected)'); // 0.10 over the 0.03 floor
    expect(text).toContain('(floor 3.0%, not detected)'); // 0.02 under it
    expect(text).toContain('coverage 0.90');
    expect(text).not.toContain('unbalanced');
    expect(text).not.toContain('unresolved');
  });

  it('the other side of the diagonal reads the other direction first', () => {
    const text = hoverText(model.cells[1][0]!, v.constants!);
    expect(text.indexOf('Δ sma.length beyond ema.length')).toBeLessThan(text.indexOf('Δ ema.length beyond sma.length'));
  });

  it('I has no interval: nothing in brackets follows it, and it says it is display only', () => {
    const text = hoverText(model.cells[0][1]!, v.constants!);
    const at = text.indexOf('I 5.0%');
    expect(at).toBeGreaterThan(-1);
    const tail = text.slice(at, text.indexOf('·', at));
    expect(tail).toContain('display only');
    expect(tail).not.toContain('[');
  });

  it('flags an unbalanced pair, and an unresolved one with its coverage against the constant of the response', () => {
    const unbalanced = hoverText(model.cells[2][3]!, v.constants!);
    expect(unbalanced).toContain('unbalanced');
    const unresolved = hoverText(model.cells[1][2]!, v.constants!);
    expect(unresolved).toContain('unresolved');
    expect(unresolved).toContain('coverage 0.30');
    expect(unresolved).toContain('needs 0.5');
    expect(hoverText(model.cells[1][2]!, { ...IMPORTANCE_CONSTANTS, PAIR_MIN_COVERAGE: 0.7 })).toContain('needs 0.7');
  });

  it('a Δ below zero reads as zero, the stored value untouched', () => {
    const neg = pair(0, 1, { D_ij: { value: -0.004, lo: -0.02, hi: 0.01, floor: 0.03, detected: false } });
    const m = interactionModel(interactions({ pairs: [neg], total_pairs: 1, unresolved_pairs: 0 }))!;
    expect(hoverText(m.cells[0][1]!, IMPORTANCE_CONSTANTS)).toContain('Δ ema.length beyond sma.length 0.0%');
    expect(neg.D_ij.value).toBe(-0.004);
  });

  it('an unresolved line names the pair and its coverage', () => {
    expect(unresolvedText(v.pairs[2], v.constants!)).toBe('sma.length × stop_loss_pct · coverage 0.30 (needs 0.5)');
  });

  it('the summary counts the pairs', () => {
    expect(matrixSummary(v)).toBe('interaction matrix of J: 4 parameters, 6 pairs, 2 unresolved (hatched)');
  });
});

describe('matrixLayout (the width sets the square, the height follows)', () => {
  it('squares grow to the cap on a wide canvas and shrink to fit a narrow one', () => {
    expect(matrixLayout(500, 4)).toEqual({ x0: 130, y0: 118, cell: 40, height: 118 + 4 * 40 + 10 });
    expect(matrixLayout(300, 20)).toEqual({ x0: 130, y0: 118, cell: 8, height: 118 + 20 * 8 + 10 });
  });

  it('a canvas too narrow for the margins, or no parameters, has no square and never a NaN', () => {
    expect(matrixLayout(100, 4).cell).toBe(0);
    expect(matrixLayout(500, 0)).toEqual({ x0: 130, y0: 118, cell: 0, height: 128 });
  });
});
