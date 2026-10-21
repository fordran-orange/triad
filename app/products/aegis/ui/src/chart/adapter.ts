// The only thing panels know about charts. No strategy, result, temporal or UI state logic may
// depend on a chart library; backends implement this interface (Vela first, lightweight-charts
// as the agreed fallback). See docs/superpowers/plans/2026-10-09-chart-spike-result.md.
import type { Timeframe } from '../state/workspace';

export interface Bar {
  time: number; // epoch ms, bar open time
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OverlayPoint {
  time: number;
  value: number | null; // null: the bar is inside the indicator's warm-up
}

export interface Overlay {
  id: string; // the series' reference spelling: `id` or `id.output`
  title: string;
  color: string;
  points: OverlayPoint[];
  pane: 'price' | 'own'; // price-scale kinds overlay the candles; oscillators get a pane per group
  group: string; // the indicator id: own-pane series of one group share one pane
  style: 'line' | 'columns';
}

export interface Marker {
  time: number;
  price: number;
  side: 'LONG' | 'SHORT';
  kind: 'entry' | 'exit';
}

export interface CrosshairPoint {
  time: number | null;
  price: number | null; // on the hovered pane's scale: a price, or a study value
  paneKind: 'price' | 'study' | null;
  values: Record<string, number>; // series values under the cursor, keyed by overlay id
}

/** A visible time range, epoch ms. */
export interface VisibleSpan {
  from: number;
  to: number;
}

export interface ChartAdapter {
  mount(el: HTMLElement): void;
  setBars(bars: Bar[], timeframe: Timeframe): void;
  /** Swap the candles in place keeping `visible` in view (Mission 10: a zoom's finer or coarser
   *  candles); overlays and markers set meanwhile are applied over the new candles. */
  replaceBars(bars: Bar[], timeframe: Timeframe, visible: VisibleSpan): void;
  /** Called on every applied pan or zoom (not debounced). */
  onViewport(cb: (span: VisibleSpan) => void): void;
  /** How many candles the chart can show at once at its widest zoom. */
  capacity(): number;
  /** Called with the visible span when a wheel-out leaves the view unchanged: the chart is at its
   *  zoom-out limit for the candles it holds (QA D1). */
  onZoomOutLimit(cb: (span: VisibleSpan) => void): void;
  /** Called when the operator wheels in (zooms in) over the chart. */
  onZoomIn(cb: () => void): void;
  setOverlays(series: Overlay[]): void;
  setMarkers(markers: Marker[]): void;
  onCrosshair(cb: (p: CrosshairPoint | null) => void): void;
  /** Remove the chart but keep the mount; the next setBars() draws fresh. Used when a fetch fails. */
  clear(): void;
  resize(): void;
  destroy(): void;
}

export type ChartBackend = 'vela' | 'lightweight';

/** Decided by the Task 1 spike: Vela passed overlays, markers, CSP and attribution. */
export const CHART_BACKEND: ChartBackend = 'vela';

export async function createChartAdapter(): Promise<ChartAdapter> {
  // Lazy import keeps the chart library out of the initial bundle and off vitest's node runs.
  const module = await import('./vela');
  return new module.VelaAdapter();
}
