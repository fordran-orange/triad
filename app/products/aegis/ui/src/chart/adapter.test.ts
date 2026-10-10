import { describe, expect, it } from 'vitest';
import type { Bar, ChartAdapter, CrosshairPoint, Marker, Overlay } from './adapter';
import { overlaysFromSeries, syncChart } from './sync';

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

describe('chart sync', () => {
  it('calls setBars then setOverlays when the selection changes', () => {
    const adapter = new MockAdapter();
    syncChart(adapter, {
      bars,
      timeframe: '1h',
      times: bars.map((b) => b.time),
      series: { ema: [null, 2, 3], sma: [null, null, 3] },
      colors: { ema: '#2da7ff', sma: '#39d98a' },
      titles: { ema: 'EMA 9', sma: 'SMA 30' },
      markers: [],
    });
    expect(adapter.calls).toEqual(['setBars', 'setOverlays', 'setMarkers']);
    expect(adapter.bars).toHaveLength(3);
    expect(adapter.overlays.map((o) => o.id)).toEqual(['ema', 'sma']);
  });

  it('overlay points drop null values', () => {
    const overlays = overlaysFromSeries(
      [60_000, 120_000, 180_000],
      { ema: [null, 2, 3] },
      { ema: '#2da7ff' },
      { ema: 'EMA 9' },
    );
    expect(overlays).toEqual([
      { id: 'ema', title: 'EMA 9', color: '#2da7ff', points: [{ time: 120_000, value: 2 }, { time: 180_000, value: 3 }] },
    ]);
  });
});
