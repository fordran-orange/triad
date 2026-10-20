// Vela backend for the ChartAdapter (spike result: docs/superpowers/plans/2026-10-09-chart-spike-result.md).
// Overlays are native indicators that plot server-supplied arrays; markers are a legend-less
// native indicator emitting arrow labels. The library's attribution watermark stays enabled.
import { Vela, registerNativeIndicator } from '@luxalgo/vela';
import type { Bar, ChartAdapter, CrosshairPoint, Marker, Overlay, VisibleSpan } from './adapter';
import type { Timeframe } from '../state/workspace';
import { SeriesMap } from './seriesMap';

const TIMEFRAME_TO_VELA: Record<Timeframe, string> = { '1m': '1', '15m': '15', '30m': '30', '1h': '60', '1D': 'D' };
// Vela keeps candles at least MIN_BAR_SPACING px apart (its own constant), so a chart shows at
// most its plot width / 0.5 candles; the price scale takes about PRICE_SCALE_PX of the mount.
const MIN_BAR_SPACING = 0.5;
const PRICE_SCALE_PX = 64;

// Module-level registries read by the native indicator instances (one chart per page in Aegis).
const overlayRegistry = new Map<string, Overlay>();
const groupRegistry = new Map<string, Overlay[]>(); // own-pane series by indicator id
const seriesToOverlay = new SeriesMap(); // emitted series id → overlay id (crosshair values)
let markerRegistry: Marker[] = [];
let registered = false;

const lineSeries = (ctxId: string, overlay: Overlay, overlay_: boolean) => {
  const id = ctxId + ':' + overlay.id;
  seriesToOverlay.set(id, overlay.id);
  return {
    id,
    title: overlay.title,
    paneId: '',
    kind: overlay.style === 'columns' ? 'columns' : 'line',
    overlay: overlay_,
    points: overlay.points.map((p) => ({ time: p.time, value: p.value })),
    style: { color: overlay.color, width: overlay.style === 'columns' ? 1 : 2, lineStyle: 'solid', ...(overlay.style === 'columns' ? { base: 0 } : {}) },
  };
};

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
        ctx.emit({ series: [lineSeries(ctx.id, overlay, true)] });
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
  // One study pane per oscillator indicator: every own-pane series of a group in one instance.
  registerNativeIndicator({
    type: 'aegis-pane',
    title: 'Aegis study',
    paneHint: 'new',
    overlay: false,
    legend: false,
    multiInstance: true,
    inputsSchema: () => [{ key: 'group', title: 'Group', type: 'string', defval: '' }],
    defaultInputs: () => ({ group: '' }),
    create: () => {
      let ctx: Emitter | null = null;
      let inputs: Record<string, unknown> = {};
      const emit = () => {
        if (!ctx) return;
        const overlays = groupRegistry.get(String(inputs.group)) ?? [];
        ctx.emit({ series: overlays.map((o) => lineSeries(ctx!.id, o, false)) });
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
  private paneHandles = new Map<string, Handle>();
  private markerHandle: Handle | null = null;
  private crosshair: ((p: CrosshairPoint | null) => void) | null = null;
  private pendingOverlays: Overlay[] = [];
  private pendingMarkers: Marker[] = [];
  private viewport: ((span: VisibleSpan) => void) | null = null;
  private stopViewport: (() => void) | null = null;
  private swapping: Promise<void> | null = null; // an in-place swap of candles in flight

  mount(el: HTMLElement): void {
    this.el = el;
    registerNatives();
  }

  setBars(bars: Bar[], timeframe: Timeframe): void {
    if (!this.el) throw new Error('mount() before setBars()');
    this.timeframe = timeframe;
    const data = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }));
    if (this.chart) {
      this.stopViewport?.();
      this.stopViewport = null;
      this.chart.destroy();
      this.chart = null;
      this.forgetAll();
    }
    this.el.innerHTML = '';
    const chart = new Vela(this.el, { data, timeframe: TIMEFRAME_TO_VELA[timeframe], theme: 'dark' } as never);
    this.chart = chart;
    const crosshair = this.crosshair;
    if (crosshair) {
      type Move = { time: number | null; price: number | null; paneKind?: 'price' | 'study' | null; values?: ReadonlyMap<string, number> };
      (chart.renderer as unknown as { onCrosshairMove(cb: (e: Move) => void): void }).onCrosshairMove((e) => {
        const values: Record<string, number> = {};
        for (const [seriesId, value] of e.values ?? new Map<string, number>()) {
          const overlayId = seriesToOverlay.overlayOf(seriesId);
          if (overlayId !== undefined) values[overlayId] = value;
        }
        crosshair({ time: e.time, price: e.price, paneKind: e.paneKind ?? null, values });
      });
    }
    this.swapping = null;
    this.listenViewport();
    void chart.ready().then(() => {
      if (this.chart !== chart) return;
      this.applyOverlays(this.pendingOverlays);
      this.applyMarkers(this.pendingMarkers);
    });
  }

  replaceBars(bars: Bar[], timeframe: Timeframe, visible: VisibleSpan): void {
    const chart = this.chart;
    if (!chart) return this.setBars(bars, timeframe);
    this.timeframe = timeframe;
    const data = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }));
    // setMarket keeps panes, handles and subscriptions; the native indicators restart and read
    // the registries, which setOverlays/setMarkers refresh meanwhile (see `refresh`).
    const swap: Promise<void> = chart
      .setMarket({ timeframe: TIMEFRAME_TO_VELA[timeframe], data, visibleRange: { from: visible.from, to: visible.to } } as never)
      .then(() => {
        if (this.chart !== chart || this.swapping !== swap) return;
        this.swapping = null;
        this.applyOverlays(this.pendingOverlays);
        this.applyMarkers(this.pendingMarkers);
      });
    this.swapping = swap;
  }

  capacity(): number {
    return Math.max(100, Math.floor(((this.el?.clientWidth ?? 0) - PRICE_SCALE_PX) / MIN_BAR_SPACING));
  }

  onViewport(cb: (span: VisibleSpan) => void): void {
    this.viewport = cb;
    this.listenViewport();
  }

  private listenViewport() {
    this.stopViewport?.();
    this.stopViewport = null;
    const chart = this.chart;
    const cb = this.viewport;
    if (!chart || !cb) return;
    const on = (chart as unknown as { on(event: 'viewport:changed', handler: (r: VisibleSpan) => void): () => void }).on;
    this.stopViewport = on.call(chart, 'viewport:changed', (r) => cb({ from: r.from, to: r.to }));
  }

  setOverlays(series: Overlay[]): void {
    this.pendingOverlays = series;
    if (this.chart && this.swapping) this.refresh(series);
    else if (this.chart) this.applyOverlays(series);
  }

  setMarkers(markers: Marker[]): void {
    this.pendingMarkers = markers;
    if (this.chart && this.swapping) markerRegistry = markers;
    else if (this.chart) this.applyMarkers(markers);
  }

  /** During a swap: the registries the restarting native indicators read hold the new points. */
  private refresh(series: Overlay[]) {
    for (const s of series) if (s.pane === 'price' && overlayRegistry.has(s.id)) overlayRegistry.set(s.id, s);
    const groups = new Map<string, Overlay[]>();
    for (const s of series) if (s.pane === 'own') groups.set(s.group, [...(groups.get(s.group) ?? []), s]);
    for (const [group, overlays] of groups) if (groupRegistry.has(group)) groupRegistry.set(group, overlays);
  }

  private applyOverlays(series: Overlay[]) {
    const chart = this.chart;
    if (!chart) return;
    const priced = series.filter((s) => s.pane === 'price');
    const groups = new Map<string, Overlay[]>();
    for (const s of series) if (s.pane === 'own') groups.set(s.group, [...(groups.get(s.group) ?? []), s]);

    const wanted = new Set(priced.map((s) => s.id));
    for (const [id, handle] of this.overlayHandles) {
      if (!wanted.has(id)) {
        handle.remove();
        this.overlayHandles.delete(id);
        overlayRegistry.delete(id);
        seriesToOverlay.forget([id]);
      }
    }
    for (const overlay of priced) {
      overlayRegistry.set(overlay.id, overlay);
      const existing = this.overlayHandles.get(overlay.id);
      if (existing) existing.setInputs({ series: overlay.id });
      else this.overlayHandles.set(overlay.id, chart.addNativeIndicator('aegis-line', { inputs: { series: overlay.id } }) as unknown as Handle);
    }

    for (const [group, handle] of this.paneHandles) {
      if (!groups.has(group)) {
        handle.remove(); // the indicator's study pane goes with it
        this.paneHandles.delete(group);
        seriesToOverlay.forget((groupRegistry.get(group) ?? []).map((o) => o.id));
        groupRegistry.delete(group);
      }
    }
    for (const [group, overlays] of groups) {
      groupRegistry.set(group, overlays);
      const existing = this.paneHandles.get(group);
      if (existing) existing.setInputs({ group });
      else this.paneHandles.set(group, chart.addNativeIndicator('aegis-pane', { inputs: { group } }) as unknown as Handle);
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

  /** Handles and the module registries go with the chart; a rebuilt chart re-registers what it shows. */
  private forgetAll() {
    this.overlayHandles.clear();
    this.paneHandles.clear();
    this.markerHandle = null;
    overlayRegistry.clear();
    groupRegistry.clear();
    seriesToOverlay.clear();
  }

  clear(): void {
    this.stopViewport?.();
    this.stopViewport = null;
    this.swapping = null;
    this.chart?.destroy();
    this.chart = null;
    this.forgetAll();
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
