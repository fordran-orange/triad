// Pure orchestration between fetched data and the chart adapter; no library, no React.
import type { IndicatorSpec } from '../contracts';
import type { Timeframe } from '../state/workspace';
import type { Bar, ChartAdapter, Marker, Overlay } from './adapter';

/** How one series is drawn: its legend title, colour, pane, pane group and style. */
export interface OverlayMeta {
  title: string;
  color: string;
  pane: 'price' | 'own';
  group: string;
  style: 'line' | 'columns';
}

export interface ChartPayload {
  bars: Bar[];
  timeframe: Timeframe;
  times: number[];
  series: Record<string, Array<number | null>>;
  meta: Record<string, OverlayMeta>;
  markers: Marker[];
}

// The reference crossover keeps the colours it has had since Mission 3; other series take the
// rest of the palette in order, one colour per series.
const FIXED: Record<string, string> = { ema: '#2da7ff', sma: '#39d98a' };
const PALETTE = ['#f5a524', '#c084fc', '#ff8fab', '#5eead4', '#fde047', '#93c5fd', '#fb923c', '#a3e635', '#f472b6', '#67e8f9'];

/** Title, colour, pane and style for every series the series route returns for these indicators. */
export function chartMeta(
  indicators: IndicatorSpec[],
  outputs: Record<string, string[]>,
  pane: Record<string, 'price' | 'own'>,
): Record<string, OverlayMeta> {
  const meta: Record<string, OverlayMeta> = {};
  let next = 0;
  for (const spec of indicators) {
    const names = outputs[spec.id] ?? [];
    const keys = names.length ? names.map((o) => [`${spec.id}.${o}`, o] as const) : [[spec.id, ''] as const];
    for (const [key, output] of keys) {
      meta[key] = {
        title: `${spec.kind.toUpperCase()} ${spec.length}${output ? ' ' + output : ''}`,
        color: FIXED[key] ?? PALETTE[next++ % PALETTE.length],
        pane: pane[spec.id] ?? 'price',
        group: spec.id,
        style: output === 'histogram' ? 'columns' : 'line',
      };
    }
  }
  return meta;
}

export function overlaysFromSeries(times: number[], series: Record<string, Array<number | null>>, meta: Record<string, OverlayMeta>): Overlay[] {
  return Object.entries(series).map(([id, values]) => {
    const m = meta[id] ?? { title: id, color: '#9db1bf', pane: 'price' as const, group: id, style: 'line' as const };
    return {
      id,
      title: m.title,
      color: m.color,
      pane: m.pane,
      group: m.group,
      style: m.style,
      points: values.flatMap((value, i) => (value === null || value === undefined ? [] : [{ time: times[i], value }])),
    };
  });
}

/** Bars first, then overlays, then markers: the order the chart needs to size its scales. */
export function syncChart(adapter: ChartAdapter, payload: ChartPayload): void {
  adapter.setBars(payload.bars, payload.timeframe);
  adapter.setOverlays(overlaysFromSeries(payload.times, payload.series, payload.meta));
  adapter.setMarkers(payload.markers);
}
