// Pure orchestration between fetched data and the chart adapter; no library, no React.
import type { Bar, ChartAdapter, Marker, Overlay } from './adapter';
import type { Timeframe } from '../state/workspace';

export interface ChartPayload {
  bars: Bar[];
  timeframe: Timeframe;
  times: number[];
  series: Record<string, Array<number | null>>;
  colors: Record<string, string>;
  titles: Record<string, string>;
  markers: Marker[];
}

export function overlaysFromSeries(
  times: number[],
  series: Record<string, Array<number | null>>,
  colors: Record<string, string>,
  titles: Record<string, string>,
): Overlay[] {
  return Object.entries(series).map(([id, values]) => ({
    id,
    title: titles[id] ?? id,
    color: colors[id] ?? '#9db1bf',
    points: values.flatMap((value, i) => (value === null || value === undefined ? [] : [{ time: times[i], value }])),
  }));
}

/** Bars first, then overlays, then markers: the order the chart needs to size its scales. */
export function syncChart(adapter: ChartAdapter, payload: ChartPayload): void {
  adapter.setBars(payload.bars, payload.timeframe);
  adapter.setOverlays(overlaysFromSeries(payload.times, payload.series, payload.colors, payload.titles));
  adapter.setMarkers(payload.markers);
}
