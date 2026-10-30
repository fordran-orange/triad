import { describe, expect, it } from 'vitest';
import { Brush1D, drawWhisker, HitGrid, linearScale, niceTicks, ordinalScale, ScatterHit } from './canvas';

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

describe('ScatterHit', () => {
  const xs = [100, 140, 140.5, 300, Number.NaN];
  const ys = [50, 90, 90, 200, 10];

  it('finds the nearest point within the radius, and nothing outside it', () => {
    const hit = new ScatterHit(xs, ys, 8);
    expect(hit.at(100, 50)).toBe(0);
    expect(hit.at(104, 53)).toBe(0); // inside the 8 px radius
    expect(hit.at(140, 90)).toBe(1);
    expect(hit.at(300, 195)).toBe(3);
    expect(hit.at(120, 70)).toBeNull(); // between two points, near neither
    expect(hit.at(100, 59)).toBeNull(); // 9 px: past the radius
  });

  it('a point at exactly the radius is hit; the nearer of two wins, a tie goes to the lower index', () => {
    const hit = new ScatterHit(xs, ys, 8);
    expect(hit.at(108, 50)).toBe(0); // exactly 8 px away
    expect(hit.at(108.0001, 50)).toBeNull();
    expect(hit.at(140.4, 90)).toBe(2); // nearer to the second of two points a pixel apart
    expect(hit.at(140.25, 90)).toBe(1); // equidistant: the lower index
  });

  it('never hits a point with a non-finite coordinate, and answers null for a bad query or no points', () => {
    const hit = new ScatterHit(xs, ys, 8);
    expect(hit.at(Number.NaN, 10)).toBeNull();
    expect(hit.at(0, Number.POSITIVE_INFINITY)).toBeNull();
    expect(new ScatterHit([], [], 8).at(0, 0)).toBeNull();
    expect(new ScatterHit([1], [1], 0).at(1, 1)).toBeNull(); // no radius, no hit
    expect(new ScatterHit([1, 2], [1], 5).at(1, 1)).toBe(0); // a short y list: the pairs it has
  });

  it('agrees with a brute-force scan over 2,000 points, negative coordinates included', () => {
    let seed = 7;
    const rand = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    const px = Array.from({ length: 2000 }, () => rand() * 600 - 100);
    const py = Array.from({ length: 2000 }, () => rand() * 400 - 50);
    const radius = 6;
    const hit = new ScatterHit(px, py, radius);
    const brute = (x: number, y: number): number | null => {
      let best: number | null = null;
      let bestD = Number.POSITIVE_INFINITY;
      px.forEach((_, i) => {
        const d = Math.hypot(px[i] - x, py[i] - y);
        if (d <= radius && d < bestD) {
          best = i;
          bestD = d;
        }
      });
      return best;
    };
    for (let k = 0; k < 400; k++) {
      const x = rand() * 600 - 100;
      const y = rand() * 400 - 50;
      expect(hit.at(x, y), `${x},${y}`).toBe(brute(x, y));
    }
  });
});

describe('niceTicks', () => {
  it('rounds the step to 1, 2 or 5 times a power of ten and stays inside the domain', () => {
    expect(niceTicks([0, 100], 5)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks([0, 1], 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    expect(niceTicks([-3, 7], 5)).toEqual([-2, 0, 2, 4, 6]);
    expect(niceTicks([0.1, 0.35], 5)).toEqual([0.1, 0.15, 0.2, 0.25, 0.3, 0.35]);
    expect(niceTicks([-1500, 4500], 6)).toEqual([-1000, 0, 1000, 2000, 3000, 4000]);
    for (const [lo, hi, count] of [[0.013, 0.97, 6], [12345, 98765, 7], [-0.5, 0.2, 3]] as const)
      for (const t of niceTicks([lo, hi], count)) {
        expect(t).toBeGreaterThanOrEqual(lo);
        expect(t).toBeLessThanOrEqual(hi);
      }
  });

  it('cleans binary noise: 3 × 0.2 reads 0.6, and no tick is negative zero', () => {
    expect(niceTicks([0, 1], 5)[3]).toBe(0.6);
    const ticks = niceTicks([-1, 1], 4);
    expect(ticks).toEqual([-1, -0.5, 0, 0.5, 1]);
    expect(Object.is(ticks[2], -0)).toBe(false);
  });

  it('is order-free, and a degenerate or unusable domain never gives NaN ticks', () => {
    expect(niceTicks([100, 0], 5)).toEqual(niceTicks([0, 100], 5));
    expect(niceTicks([5, 5], 5)).toEqual([5]);
    expect(niceTicks([Number.NaN, 1], 5)).toEqual([]);
    expect(niceTicks([0, Number.POSITIVE_INFINITY], 5)).toEqual([]);
    expect(niceTicks([0, 10], 0)).toEqual([]);
    expect(niceTicks([0, 10], Number.NaN)).toEqual([]);
    expect(niceTicks([0, 1e12], 1e9).length).toBeLessThanOrEqual(1001); // a huge count is capped
  });

  it('keeps a tick count near the one asked for', () => {
    for (const count of [3, 5, 8, 12]) {
      const n = niceTicks([0, 1234.5], count).length;
      expect(n, `count ${count}`).toBeGreaterThanOrEqual(Math.floor(count / 2));
      expect(n, `count ${count}`).toBeLessThanOrEqual(count * 2 + 1);
    }
  });
});

/** A context that records the path it is asked to stroke and the style it strokes with. */
function recorder() {
  const segments: Array<[string, number, number]> = [];
  const strokes: Array<{ style: unknown; width: unknown; path: Array<[string, number, number]> }> = [];
  let path: Array<[string, number, number]> = [];
  const ctx = {
    strokeStyle: '' as unknown,
    lineWidth: 0 as unknown,
    save: () => undefined,
    restore: () => undefined,
    beginPath: () => {
      path = [];
    },
    moveTo: (x: number, y: number) => path.push(['M', x, y]),
    lineTo: (x: number, y: number) => path.push(['L', x, y]),
    stroke: () => {
      strokes.push({ style: ctx.strokeStyle, width: ctx.lineWidth, path });
      segments.push(...path);
    },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, strokes, segments };
}

describe('drawWhisker', () => {
  const x = linearScale([0, 1], [10, 210]); // 200 px for a share of 1

  it('strokes the interval and a cap at each end, in the colour asked', () => {
    const r = recorder();
    drawWhisker(r.ctx, x, 30, 0.1, 0.4, '#abc', 4);
    expect(r.strokes).toHaveLength(1);
    expect(r.strokes[0].style).toBe('#abc');
    expect(r.strokes[0].path).toEqual([
      ['M', 30, 30],
      ['L', 90, 30], // the interval: x(0.1) = 30 to x(0.4) = 90
      ['M', 30, 26],
      ['L', 30, 34], // the low cap
      ['M', 90, 26],
      ['L', 90, 34], // the high cap
    ]);
  });

  it('is indifferent to the order of the bounds, and a degenerate interval is still a mark', () => {
    const a = recorder();
    const b = recorder();
    drawWhisker(a.ctx, x, 30, 0.4, 0.1, '#abc');
    drawWhisker(b.ctx, x, 30, 0.1, 0.4, '#abc');
    expect(a.strokes[0].path).toEqual(b.strokes[0].path);
    const point = recorder();
    drawWhisker(point.ctx, x, 30, 0.2, 0.2, '#abc', 4);
    expect(point.segments.length).toBeGreaterThan(0);
  });

  it('draws nothing for a bound that is not a number: an interval is never invented', () => {
    for (const [lo, hi] of [[Number.NaN, 0.4], [0.1, Number.POSITIVE_INFINITY]] as const) {
      const r = recorder();
      drawWhisker(r.ctx, x, 30, lo, hi, '#abc');
      expect(r.segments).toEqual([]);
    }
  });
});
