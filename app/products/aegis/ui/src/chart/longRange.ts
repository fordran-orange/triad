// The long-range chart's pure decisions (Mission 10 spec §7): where markers sit on aggregated
// candles, which window to ask for after a zoom, and when to ask. No library, no React.
import type { Marker } from './adapter';

/** The candles a selection's first load asks for at most (the worker picks the timeframe). */
export const MAX_DISPLAY_BARS = 20_000;

/** Candles of the next finer standard timeframe per candle, rounded up (RTH 09:30-16:00 has
 *  seven 1h candles), so an estimate never says "fits" where the worker would refuse. */
const FINER_PER_CANDLE: Record<string, number> = { '1D': 7, '1h': 2, '30m': 2, '15m': 15 };
const COARSEST = '1D';
/** The chart cannot zoom out past its capacity (Vela keeps candles at least 0.5 px apart): at
 *  this share of it the view is at the limit and coarser candles let it keep widening. */
const AT_LIMIT = 0.85;
/** Finer candles are asked for only when they would fill at most this share of the capacity,
 *  so a swap in either direction lands between the two thresholds and never swaps back. */
const FINER_FILL = 0.5;

export interface Span {
  from: number; // epoch ms
  to: number;
}

/** Index of the last time at or before `t` in ascending `times`, or -1. */
function lastAtOrBefore(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

/** Each marker on the drawn candle that contains it: the last candle at or before its time. A
 *  marker before the first candle is outside what is drawn and is dropped; one after the last
 *  belongs to the last (callers pass only markers inside the loaded window). Native bars place
 *  every marker on its own bar. */
export function placeMarkers(markers: Marker[], barTimes: number[]): Marker[] {
  const placed: Marker[] = [];
  for (const m of markers) {
    const i = lastAtOrBefore(barTimes, m.time);
    if (i >= 0) placed.push(barTimes[i] === m.time ? m : { ...m, time: barTimes[i] });
  }
  return placed;
}

/** How many of ascending `times` lie in [span.from, span.to]. */
export function inWindow(times: number[], span: Span): number {
  return lastAtOrBefore(times, span.to) - lastAtOrBefore(times, span.from - 1);
}

/** The visible span widened by `margin` spans on each side, clamped to the selection. */
export function viewWindow(visible: Span, selection: Span, margin = 1): Span {
  const width = visible.to - visible.from;
  return { from: Math.max(selection.from, visible.from - margin * width), to: Math.min(selection.to, visible.to + margin * width) };
}

/** Whether a selection of `count` native bars zooms through the worker; one that fits in a first
 *  load is drawn whole and behaves exactly as before Mission 10. */
export function isLongRange(count: number): boolean {
  return count > MAX_DISPLAY_BARS;
}

/** The header's badge: "shown as 1h candles" when aggregated, null for native bars. */
export function shownAs(displayTimeframe: string, nativeTimeframe: string): string | null {
  return displayTimeframe === nativeTimeframe ? null : `shown as ${displayTimeframe} candles`;
}

export interface LoadedView {
  window: Span; // what the worker answered for
  displayTimeframe: string;
  nativeTimeframe: string;
  barTimes: number[]; // the drawn candles' times
}

/** How close to an end of the loaded candles, as a share of their span, counts as reaching it. */
const EDGE = 0.02;

/** A zoom's request: the window and the candles the worker may answer with over it. */
export interface ChartAsk extends Span {
  maxBars: number;
}

/** What a view change asks the worker for, or null to keep what is drawn:
 *  - at the zoom-out limit (`capacity` candles), coarser candles over three visible spans;
 *  - at an end of the loaded candles where the selection goes on, more of it (the chart cannot
 *    pan or zoom past its data);
 *  - finer candles once they would fill at most half the chart.
 *  The worker answers with the finest timeframe holding at most 1.5 x capacity candles over the
 *  three spans, i.e. at most half the chart over the visible one. */
export function nextRequest(visible: Span, selection: Span, view: LoadedView, capacity: number): ChartAsk | null {
  const ask = { ...viewWindow(visible, selection), maxBars: Math.max(1, Math.round(capacity * 3 * FINER_FILL)) };
  const shown = inWindow(view.barTimes, visible);
  if (shown >= capacity * AT_LIMIT && view.displayTimeframe !== COARSEST) return ask;
  const first = view.barTimes.length ? view.barTimes[0] : view.window.from;
  const last = view.barTimes.length ? view.barTimes[view.barTimes.length - 1] : view.window.to;
  const slack = (last - first) * EDGE;
  const moreLeft = view.window.from > selection.from && visible.from <= first + slack;
  const moreRight = view.window.to < selection.to && visible.to >= last - slack;
  if (moreLeft || moreRight) return ask;
  if (view.displayTimeframe === view.nativeTimeframe) return null;
  return shown * (FINER_PER_CANDLE[view.displayTimeframe] ?? Infinity) <= capacity * FINER_FILL ? ask : null;
}
