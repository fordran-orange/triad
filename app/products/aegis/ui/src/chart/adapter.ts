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
  value: number;
}

export interface Overlay {
  id: string;
  title: string;
  color: string;
  points: OverlayPoint[];
}

export interface Marker {
  time: number;
  price: number;
  side: 'LONG' | 'SHORT';
  kind: 'entry' | 'exit';
}

export interface CrosshairPoint {
  time: number | null;
  price: number | null;
}

export interface ChartAdapter {
  mount(el: HTMLElement): void;
  setBars(bars: Bar[], timeframe: Timeframe): void;
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
