import { describe, expect, it } from 'vitest';
import { Brush1D, HitGrid, linearScale, ordinalScale } from './canvas';

describe('linearScale', () => {
  it('round trip: invert(scale(v)) is v, and the domain ends land on the range ends', () => {
    const y = linearScale([10, 60], [300, 20]); // a vertical axis: the low value at the bottom
    expect(y(10)).toBe(300);
    expect(y(60)).toBe(20);
    expect(y(35)).toBe(160);
    for (const v of [10, 12.5, 35, 59.9, 60]) expect(y.invert(y(v))).toBeCloseTo(v, 10);
    for (const px of [20, 77, 300]) expect(y(y.invert(px))).toBeCloseTo(px, 10);
    expect(y.domain).toEqual([10, 60]);
    expect(y.range).toEqual([300, 20]);
  });

  it('a degenerate domain maps to the range midpoint, never NaN', () => {
    const one = linearScale([5, 5], [0, 100]);
    expect(one(5)).toBe(50);
    expect(one(7)).toBe(50);
    expect(one.invert(30)).toBe(5);
    expect(Number.isNaN(one(5)) || Number.isNaN(one.invert(30))).toBe(false);
    // A degenerate range (a zero-height axis) is no NaN either: every value at that pixel, the pixel at the
    // domain's middle.
    const flat = linearScale([0, 10], [40, 40]);
    expect(flat(3)).toBe(40);
    expect(flat.invert(40)).toBe(5);
  });
});

describe('ordinalScale', () => {
  it('index at band edges: a band holds its start and not its end', () => {
    const x = ordinalScale([10, 20, 30, 40], [0, 100]);
    expect(x.band).toBe(25);
    expect(x(10)).toBe(0);
    expect(x(30)).toBe(50);
    expect(x.index(0)).toBe(0);
    expect(x.index(24.999)).toBe(0);
    expect(x.index(25)).toBe(1);
    expect(x.index(50)).toBe(2);
    expect(x.index(75)).toBe(3);
    expect(x.index(99.999)).toBe(3);
    expect(x.index(100)).toBe(-1);
    expect(x.index(-0.001)).toBe(-1);
  });

  it('no values: no band and no index', () => {
    const none = ordinalScale([], [0, 100]);
    expect(none.band).toBe(0);
    expect(none.index(10)).toBe(-1);
  });
});

describe('HitGrid', () => {
  // 3 rows × 4 columns of 20 × 15 squares from (50, 10).
  const grid = new HitGrid(3, 4, 50, 10, 20, 15);

  it('at() inside gives the row and the column', () => {
    expect(grid.at(50, 10)).toEqual({ r: 0, c: 0 });
    expect(grid.at(69.9, 24.9)).toEqual({ r: 0, c: 0 });
    expect(grid.at(70, 25)).toEqual({ r: 1, c: 1 });
    expect(grid.at(129.9, 54.9)).toEqual({ r: 2, c: 3 });
  });

  it('at() outside is null', () => {
    expect(grid.at(49.9, 30)).toBeNull();
    expect(grid.at(130, 30)).toBeNull();
    expect(grid.at(60, 9.9)).toBeNull();
    expect(grid.at(60, 55)).toBeNull();
    expect(new HitGrid(0, 0, 0, 0, 0, 0).at(0, 0)).toBeNull();
  });
});

describe('Brush1D', () => {
  const axis = linearScale([0, 100], [200, 0]); // a vertical axis 200 px tall

  it('a drag gives an ordered range in the axis values, whichever way it went', () => {
    const seen: Array<[number, number] | null> = [];
    const down = new Brush1D(axis, (range) => seen.push(range));
    down.down(150);
    down.move(120);
    down.move(50);
    expect(down.range).toEqual([25, 75]); // live while the drag goes on
    expect(seen).toEqual([]); // the filter is written once, on release
    down.up();
    expect(seen).toEqual([[25, 75]]);
    expect(down.range).toEqual([25, 75]);
    const up = new Brush1D(axis, (range) => seen.push(range));
    up.down(50);
    up.move(150);
    up.up();
    expect(seen[1]).toEqual([25, 75]);
  });

  it('a click without a drag is null: the axis brush clears', () => {
    const seen: Array<[number, number] | null> = [];
    const click = new Brush1D(axis, (range) => seen.push(range));
    click.down(80);
    click.up();
    expect(seen).toEqual([null]);
    expect(click.range).toBeNull();
    const jitter = new Brush1D(axis, (range) => seen.push(range));
    jitter.down(80);
    jitter.move(81);
    jitter.up();
    expect(seen).toEqual([null, null]);
  });

  it('a drag past the axis ends stops at them; a release without a press does nothing', () => {
    const seen: Array<[number, number] | null> = [];
    const brush = new Brush1D(axis, (range) => seen.push(range));
    brush.up();
    brush.move(10);
    expect(seen).toEqual([]);
    brush.down(-40);
    brush.move(260);
    brush.up();
    expect(seen).toEqual([[0, 100]]);
  });
});
