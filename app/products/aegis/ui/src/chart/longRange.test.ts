import { describe, expect, it } from 'vitest';
import type { Marker } from './adapter';
import { MAX_DISPLAY_BARS, inWindow, isLongRange, nextRequest, placeMarkers, shownAs, viewWindow } from './longRange';

const H = 3_600_000;
const marker = (time: number, kind: Marker['kind'] = 'entry'): Marker => ({ time, price: 100, side: 'LONG', kind });

describe('placeMarkers (Review Focus 4)', () => {
  const candles = [0, H, 2 * H, 3 * H];

  it('puts each marker on the drawn candle that contains it', () => {
    const placed = placeMarkers([marker(H), marker(H + 15 * 60_000, 'exit'), marker(3 * H + 59 * 60_000)], candles);
    expect(placed.map((m) => m.time)).toEqual([H, H, 3 * H]);
    expect(placed[1]).toEqual({ ...marker(H, 'exit'), time: H }); // price, side and kind unchanged
  });

  it('drops a marker before the first candle and keeps one after the last on the last', () => {
    expect(placeMarkers([marker(-1), marker(10 * H)], candles).map((m) => m.time)).toEqual([3 * H]);
  });

  it('is the identity on native bars', () => {
    const native = [marker(0), marker(2 * H, 'exit')];
    expect(placeMarkers(native, candles)).toEqual(native);
    expect(placeMarkers([marker(5)], [])).toEqual([]);
  });
});

describe('viewWindow', () => {
  it('widens the visible span by a span each side, clamped to the selection', () => {
    expect(viewWindow({ from: 40, to: 50 }, { from: 0, to: 100 })).toEqual({ from: 30, to: 60 });
    expect(viewWindow({ from: 5, to: 50 }, { from: 0, to: 100 })).toEqual({ from: 0, to: 95 });
    expect(viewWindow({ from: 60, to: 95 }, { from: 0, to: 100 }, 2)).toEqual({ from: 0, to: 100 });
  });
});

describe('shownAs', () => {
  it('names an aggregated display and says nothing for native bars', () => {
    expect(shownAs('1h', '1m')).toBe('shown as 1h candles');
    expect(shownAs('1m', '1m')).toBeNull();
  });
});

describe('nextRequest', () => {
  const C = 1_000; // the chart shows at most 1,000 candles at once
  const selection = { from: 0, to: 10_000 * H };
  const hourly = (n: number, from = 0) => Array.from({ length: n }, (_, i) => from + i * H);
  const hours = { window: selection, displayTimeframe: '1h', nativeTimeframe: '1m', barTimes: hourly(10_000) };

  it('asks for coarser candles at the zoom-out limit, at most 1.5 x capacity over three spans', () => {
    const ask = nextRequest({ from: 5_000 * H, to: 5_950 * H }, selection, hours, C); // 951 of 1,000 shown
    expect(ask).toEqual({ from: 4_050 * H, to: 6_900 * H, maxBars: 1_500 });
    const daily = { ...hours, displayTimeframe: '1D' };
    expect(nextRequest({ from: 5_000 * H, to: 5_950 * H }, selection, daily, C)).toBeNull(); // nothing coarser
  });

  it('asks for finer candles only when they fill at most half the chart', () => {
    expect(nextRequest({ from: 5_000 * H, to: 5_249 * H }, selection, hours, C)).toEqual({ from: 4_751 * H, to: 5_498 * H, maxBars: 1_500 });
    expect(nextRequest({ from: 5_000 * H, to: 5_300 * H }, selection, hours, C)).toBeNull(); // 301 x 2 > 500
    const native = { ...hours, displayTimeframe: '1m', nativeTimeframe: '1m' };
    expect(nextRequest({ from: 5_000 * H, to: 5_010 * H }, selection, native, C)).toBeNull(); // nothing finer
  });

  it('never swaps back and forth: a swap lands between the two thresholds', () => {
    // 1h at the limit becomes 1D with at most 500 shown; 1D at 300 x 7 never asks for finer.
    const days = { window: selection, displayTimeframe: '1D', nativeTimeframe: '1m', barTimes: Array.from({ length: 400 }, (_, i) => i * 24 * H) };
    expect(nextRequest({ from: 0, to: 299 * 24 * H }, selection, days, C)).toBeNull();
  });

  it('asks again when the view reaches an end of the loaded candles where the selection goes on', () => {
    const native = { window: { from: 100 * H, to: 200 * H }, displayTimeframe: '1m', nativeTimeframe: '1m', barTimes: hourly(101, 100 * H) };
    expect(nextRequest({ from: 150 * H, to: 190 * H }, selection, native, C)).toBeNull();
    expect(nextRequest({ from: 100 * H, to: 200 * H }, selection, native, C)).toEqual({ from: 0, to: 300 * H, maxBars: 1_500 });
    expect(nextRequest({ from: 140 * H, to: 199 * H }, selection, native, C)).not.toBeNull(); // panned to its right end
    const atEnd = { ...native, window: { from: 100 * H, to: 10_000 * H }, barTimes: [100 * H, 10_000 * H] };
    expect(nextRequest({ from: 5_000 * H, to: 10_000 * H }, selection, atEnd, C)).toBeNull(); // the selection ends there
  });

  it('keeps the first load at most MAX_DISPLAY_BARS (20,000) and counts candles in a span', () => {
    expect(MAX_DISPLAY_BARS).toBe(20_000);
    expect(inWindow([0, 1, 2, 3, 4], { from: 1, to: 3 })).toBe(3);
  });
});

describe('isLongRange', () => {
  it('leaves a selection that fits exactly as before: only a longer one zooms through the worker', () => {
    expect(isLongRange(20_000)).toBe(false);
    expect(isLongRange(20_001)).toBe(true);
  });
});
