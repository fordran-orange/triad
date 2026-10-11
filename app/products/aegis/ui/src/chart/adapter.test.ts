import { describe, expect, it } from 'vitest';
import type { Bar, ChartAdapter, CrosshairPoint, Marker, Overlay } from './adapter';
import type { IndicatorSpec } from '../contracts';
import { chartMeta, overlaysFromSeries, syncChart } from './sync';

class MockAdapter implements ChartAdapter {
  calls: string[] = [];
  bars: Bar[] = [];
  overlays: Overlay[] = [];
  markers: Marker[] = [];
  mount() {
    this.calls.push('mount');
  }
  setBars(bars: Bar[]) {
    this.calls.push('setBars');
    this.bars = bars;
  }
  setOverlays(series: Overlay[]) {
    this.calls.push('setOverlays');
    this.overlays = series;
  }
  setMarkers(markers: Marker[]) {
    this.calls.push('setMarkers');
    this.markers = markers;
  }
  onCrosshair(_cb: (p: CrosshairPoint | null) => void) {
    this.calls.push('onCrosshair');
  }
  clear() {
    this.calls.push('clear');
    this.bars = [];
  }
  resize() {
    this.calls.push('resize');
  }
  destroy() {
    this.calls.push('destroy');
  }
}

const bars: Bar[] = [1, 2, 3].map((i) => ({ time: i * 60_000, open: i, high: i + 1, low: i - 1, close: i, volume: 10 }));

const spec = (id: string, kind: string, length: number, params?: Record<string, number>): IndicatorSpec => ({ id, kind, length, source: 'close', overlay: true, ...(params ? { params } : {}) });
const reference = [spec('ema', 'EMA', 9), spec('sma', 'SMA', 30)];
const referenceMeta = chartMeta(reference, { ema: [], sma: [] }, { ema: 'price', sma: 'price' });

describe('chart sync', () => {
  it('calls setBars then setOverlays then setMarkers', () => {
    const adapter = new MockAdapter();
    syncChart(adapter, { bars, timeframe: '1h', times: bars.map((b) => b.time), series: { ema: [null, 2, 3], sma: [null, null, 3] }, meta: referenceMeta, markers: [] });
    expect(adapter.calls).toEqual(['setBars', 'setOverlays', 'setMarkers']);
    expect(adapter.bars).toHaveLength(3);
    expect(adapter.overlays.map((o) => o.id)).toEqual(['ema', 'sma']);
  });

  it("keeps the reference strategy's ids, titles and colours on the price pane", () => {
    const overlays = overlaysFromSeries([60_000, 120_000, 180_000], { ema: [null, 2, 3] }, referenceMeta);
    expect(overlays).toEqual([
      { id: 'ema', title: 'EMA 9', color: '#2da7ff', pane: 'price', group: 'ema', style: 'line', points: [{ time: 120_000, value: 2 }, { time: 180_000, value: 3 }] },
    ]);
    expect(referenceMeta.sma).toMatchObject({ title: 'SMA 30', color: '#39d98a', pane: 'price', group: 'sma' });
  });

  it('puts price kinds on the price pane and oscillators in one pane per indicator', () => {
    const indicators = [...reference, spec('donchian', 'DONCHIAN', 20), spec('rsi', 'RSI', 14), spec('macd', 'MACD', 12, { slow: 26, signal: 9 })];
    const meta = chartMeta(
      indicators,
      { ema: [], sma: [], donchian: ['upper', 'lower', 'middle'], rsi: [], macd: ['line', 'signal', 'histogram'] },
      { ema: 'price', sma: 'price', donchian: 'price', rsi: 'own', macd: 'own' },
    );
    expect(Object.keys(meta)).toEqual(['ema', 'sma', 'donchian.upper', 'donchian.lower', 'donchian.middle', 'rsi', 'macd.line', 'macd.signal', 'macd.histogram']);
    expect(['donchian.upper', 'donchian.lower', 'donchian.middle'].map((k) => meta[k].pane)).toEqual(['price', 'price', 'price']);
    expect(meta['donchian.upper']).toMatchObject({ title: 'DONCHIAN 20 upper', group: 'donchian', style: 'line' });
    expect(meta.rsi).toMatchObject({ title: 'RSI 14', pane: 'own', group: 'rsi' });
    expect(meta['macd.histogram']).toMatchObject({ pane: 'own', group: 'macd', style: 'columns' });
    expect(meta['macd.line'].style).toBe('line');
    const colors = Object.values(meta).map((m) => m.color);
    expect(new Set(colors).size).toBe(colors.length);

    const adapter = new MockAdapter();
    syncChart(adapter, { bars, timeframe: '1h', times: bars.map((b) => b.time), series: { rsi: [null, 40, 60], 'macd.histogram': [null, null, 0.5] }, meta, markers: [] });
    expect(adapter.overlays.map((o) => [o.id, o.pane, o.group, o.style])).toEqual([
      ['rsi', 'own', 'rsi', 'line'],
      ['macd.histogram', 'own', 'macd', 'columns'],
    ]);
  });
});
