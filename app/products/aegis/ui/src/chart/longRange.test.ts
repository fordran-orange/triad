import { describe, expect, it } from 'vitest';
import type { Marker } from './adapter';
import { MAX_DISPLAY_BARS, coarserRequest, inWindow, isLongRange, nextRequest, placeMarkers, shownAs, viewWindow } from './longRange';

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
    expect(ask).toEqual({ from: 4_050 * H, to: 6_900 * H, maxBars: 1_500, atLeast: '1h' }); // never finer
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
    expect(nextRequest({ from: 100 * H, to: 200 * H }, selection, native, C)).toEqual({ from: 0, to: 300 * H, maxBars: 1_500, atLeast: '1m' });
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

describe('coarserRequest (QA D1: zooming out of native candles)', () => {
  const C = 1_000;
  const M = 60_000;
  const selection = { from: 0, to: 10_000 * H };

  it('asks for candles coarser than the loaded ones even when a wider window holds nothing new', () => {
    // one session of native 1m candles, all visible: the overnight gap leaves a wider window empty
    const session = Array.from({ length: 372 }, (_, i) => 5_000 * H + i * M);
    const view = { window: { from: session[0], to: session[371] }, displayTimeframe: '1m', nativeTimeframe: '1m', barTimes: session };
    const ask = coarserRequest({ from: session[0], to: session[371] }, selection, view, C);
    expect(ask?.atLeast).toBe('15m'); // the next coarser timeframe, however few candles that is
    expect(ask?.maxBars).toBe(1_500);
    expect(ask!.from).toBeLessThan(session[0]);
    expect(ask!.to).toBeGreaterThan(session[371]);
  });

  it('at the chart limit with more candles loaded than shown, asks for at most 1.5 x capacity', () => {
    const minutes = Array.from({ length: 5_000 }, (_, i) => i * M);
    const view = { window: { from: 0, to: 4_999 * M }, displayTimeframe: '1m', nativeTimeframe: '1m', barTimes: minutes };
    const ask = coarserRequest({ from: 2_000 * M, to: 3_249 * M }, { from: 0, to: 4_999 * M }, view, C);
    expect(ask).toEqual({ from: 751 * M, to: 4_498 * M, maxBars: 1_500, atLeast: '15m' });
  });

  it('at daily candles asks for more of the selection, or nothing once it is all loaded', () => {
    const D = 24 * H;
    const days = Array.from({ length: 400 }, (_, i) => i * D);
    const daily = { window: { from: 0, to: 399 * D }, displayTimeframe: '1D', nativeTimeframe: '1m', barTimes: days };
    expect(coarserRequest({ from: 0, to: 399 * D }, { from: 0, to: 399 * D }, daily, C)).toBeNull();
    const part = { ...daily, window: { from: 100 * D, to: 399 * D }, barTimes: days.slice(100) };
    expect(coarserRequest({ from: 100 * D, to: 399 * D }, { from: 0, to: 2_000 * D }, part, C)).toEqual({ from: 0, to: 698 * D, maxBars: 1_500, atLeast: '1D' });
  });

  it('after a coarser swap, asks for finer candles only once the operator zooms in again', () => {
    const hours = { window: selection, displayTimeframe: '1h', nativeTimeframe: '1m', barTimes: Array.from({ length: 10_000 }, (_, i) => i * H), finerBlocked: true };
    expect(nextRequest({ from: 5_000 * H, to: 5_149 * H }, selection, hours, C)).toBeNull(); // would fit, but blocked
    expect(nextRequest({ from: 5_000 * H, to: 5_149 * H }, selection, { ...hours, finerBlocked: false }, C)).not.toBeNull();
  });
});

describe('nextRequest order (QA D1)', () => {
  it('asks for finer candles before more of the same when a narrow view reaches an end', () => {
    const selection = { from: 0, to: 10_000 * H };
    const loaded = Array.from({ length: 1_001 }, (_, i) => (5_000 + i) * H);
    const hours = { window: { from: 5_000 * H, to: 6_000 * H }, displayTimeframe: '1h', nativeTimeframe: '1m', barTimes: loaded };
    const ask = nextRequest({ from: 5_000 * H, to: 5_100 * H }, selection, hours, 1_000);
    expect(ask).toEqual({ from: 4_900 * H, to: 5_200 * H, maxBars: 1_500 }); // no atLeast: finer may come
  });
});

