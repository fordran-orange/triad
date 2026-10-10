// Vela backend for the ChartAdapter (spike result: docs/superpowers/plans/2026-10-09-chart-spike-result.md).
// Overlays are native indicators that plot server-supplied arrays; markers are a legend-less
// native indicator emitting arrow labels. The library's attribution watermark stays enabled.
import { Vela, registerNativeIndicator } from '@luxalgo/vela';
import type { Bar, ChartAdapter, CrosshairPoint, Marker, Overlay } from './adapter';
import type { Timeframe } from '../state/workspace';

const TIMEFRAME_TO_VELA: Record<Timeframe, string> = { '1m': '1', '15m': '15', '30m': '30', '1h': '60', '1D': 'D' };

// Module-level registries read by the native indicator instances (one chart per page in Aegis).
const overlayRegistry = new Map<string, Overlay>();
let markerRegistry: Marker[] = [];
let registered = false;

type Emitter = { emit(out: unknown): void; id: string };

function registerNatives() {
  if (registered) return;
  registered = true;
  registerNativeIndicator({
    type: 'aegis-line',
    title: 'Aegis series',
    paneHint: 'price',
    overlay: true,
    legend: false, // the panel header carries the legend; Vela's rows would only say 'Aegis series'
    multiInstance: true,
    inputsSchema: () => [{ key: 'series', title: 'Series', type: 'string', defval: '' }],
    defaultInputs: () => ({ series: '' }),
    create: () => {
      let ctx: Emitter | null = null;
      let inputs: Record<string, unknown> = {};
      const emit = () => {
        if (!ctx) return;
        const overlay = overlayRegistry.get(String(inputs.series));
        if (!overlay) return;
        ctx.emit({
          series: [
            {
              id: ctx.id + ':' + overlay.id,
              title: overlay.title,
              paneId: '',
              kind: 'line',
              overlay: true,
              points: overlay.points.map((p) => ({ time: p.time, value: p.value })),
              style: { color: overlay.color, width: 2, lineStyle: 'solid' },
            },
          ],
        });
      };
      return {
        start(c: Emitter, i: Record<string, unknown>) {
          ctx = c;
          inputs = i;
          emit();
        },
        onBars: emit,
        onViewport() {},
        setInputs(i: Record<string, unknown>) {
          inputs = i;
          emit();
        },
        suspend() {},
        resume: emit,
        stop() {},
      };
    },
  } as never);
  registerNativeIndicator({
    type: 'aegis-markers',
    title: 'Trades',
    paneHint: 'price',
    overlay: true,
    legend: false,
    inputsSchema: () => [],
    defaultInputs: () => ({}),
    create: () => {
      let ctx: Emitter | null = null;
      const emit = () => {
        if (!ctx) return;
        ctx.emit({
          series: [],
          labels: markerRegistry.map((m, i) => ({
            id: ctx!.id + ':m' + i,
            paneId: '',
            xloc: 'bar_time',
            x: m.time,
            y: m.price,
            yloc: m.kind === 'entry' ? 'belowbar' : 'abovebar',
            text: (m.side === 'LONG' ? 'L' : 'S') + (m.kind === 'entry' ? '' : 'x'),
            style: m.kind === 'entry' ? 'arrowup' : 'arrowdown',
            color: m.side === 'LONG' ? '#39d98a' : '#ff5c67',
            textColor: '#ffffff',
            size: 'small',
            textAlign: 'center',
            fontFamily: 'default',
            overlay: true,
          })),
        });
      };
      return {
        start(c: Emitter) {
          ctx = c;
          emit();
        },
        onBars: emit,
        onViewport() {},
        setInputs: emit,
        suspend() {},
        resume: emit,
        stop() {},
      };
    },
  } as never);
}

type Handle = { id: string; setInputs(i: Record<string, unknown>): void; remove(): void };

export class VelaAdapter implements ChartAdapter {
  private el: HTMLElement | null = null;
  private chart: Vela | null = null;
  private timeframe: Timeframe = '1h';
  private overlayHandles = new Map<string, Handle>();
  private markerHandle: Handle | null = null;
  private crosshair: ((p: CrosshairPoint | null) => void) | null = null;
  private pendingOverlays: Overlay[] = [];
  private pendingMarkers: Marker[] = [];

  mount(el: HTMLElement): void {
    this.el = el;
    registerNatives();
  }

  setBars(bars: Bar[], timeframe: Timeframe): void {
    if (!this.el) throw new Error('mount() before setBars()');
    this.timeframe = timeframe;
    const data = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }));
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
      this.overlayHandles.clear();
      this.markerHandle = null;
    }
    this.el.innerHTML = '';
    const chart = new Vela(this.el, { data, timeframe: TIMEFRAME_TO_VELA[timeframe], theme: 'dark' } as never);
    this.chart = chart;
    const crosshair = this.crosshair;
    if (crosshair) {
      (chart.renderer as unknown as { onCrosshairMove(cb: (e: { time: number | null; price: number | null }) => void): void }).onCrosshairMove((e) =>
        crosshair({ time: e.time, price: e.price }),
      );
    }
    void chart.ready().then(() => {
      if (this.chart !== chart) return;
      this.applyOverlays(this.pendingOverlays);
      this.applyMarkers(this.pendingMarkers);
    });
  }

  setOverlays(series: Overlay[]): void {
    this.pendingOverlays = series;
    if (this.chart) this.applyOverlays(series);
  }

  setMarkers(markers: Marker[]): void {
    this.pendingMarkers = markers;
    if (this.chart) this.applyMarkers(markers);
  }

  private applyOverlays(series: Overlay[]) {
    const chart = this.chart;
    if (!chart) return;
    const wanted = new Set(series.map((s) => s.id));
    for (const [id, handle] of this.overlayHandles) {
      if (!wanted.has(id)) {
        handle.remove();
        this.overlayHandles.delete(id);
        overlayRegistry.delete(id);
      }
    }
    for (const overlay of series) {
      overlayRegistry.set(overlay.id, overlay);
      const existing = this.overlayHandles.get(overlay.id);
      if (existing) existing.setInputs({ series: overlay.id });
      else this.overlayHandles.set(overlay.id, chart.addNativeIndicator('aegis-line', { inputs: { series: overlay.id } }) as unknown as Handle);
    }
  }

  private applyMarkers(markers: Marker[]) {
    const chart = this.chart;
    if (!chart) return;
    markerRegistry = markers;
    if (this.markerHandle) this.markerHandle.setInputs({});
    else this.markerHandle = chart.addNativeIndicator('aegis-markers') as unknown as Handle;
  }

  onCrosshair(cb: (p: CrosshairPoint | null) => void): void {
    this.crosshair = cb;
  }

  resize(): void {
    this.chart?.resize();
  }

  clear(): void {
    this.chart?.destroy();
    this.chart = null;
    this.overlayHandles.clear();
    this.markerHandle = null;
    this.pendingOverlays = [];
    this.pendingMarkers = [];
    if (this.el) this.el.innerHTML = '';
  }

  destroy(): void {
    this.clear();
    this.el = null;
  }

  get currentTimeframe(): Timeframe {
    return this.timeframe;
  }
}
