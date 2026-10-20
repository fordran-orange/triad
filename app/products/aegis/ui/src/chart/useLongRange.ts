// The long-range chart loader the Charts page and the Library's run view share (Mission 10 spec
// §7): the selection is asked for as at most MAX_DISPLAY_BARS candles; a zoom or pan asks again
// for the visible window at the detail the chart can show (see nextRequest) and swaps the candles
// in place. A selection that fits draws as before.
import { useEffect, useRef, useState } from 'react';
import { api, errorMessage, type BarsResponse, type IndicatorsResponse } from '../api/client';
import type { IndicatorSpec } from '../contracts';
import type { Provenance } from '../results';
import type { Selection, Timeframe } from '../state/workspace';
import type { ChartAdapter, Marker, VisibleSpan } from './adapter';
import { MAX_DISPLAY_BARS, isLongRange, nextRequest, placeMarkers, type LoadedView, type Span } from './longRange';
import { chartMeta, overlaysFromSeries, syncChart, type OverlayMeta } from './sync';

const DEBOUNCE_MS = 400;

export interface LongRange {
  loading: boolean;
  error: string | null;
  count: number | null; // the native bars of the whole selection
  shown: number | null; // the candles drawn now
  displayTimeframe: string | null;
  data: Provenance | null;
  meta: Record<string, OverlayMeta>;
}

export interface LongRangeOptions {
  /** The selection's first answer; returning false keeps it off the chart (the caller says why). */
  onLoaded?: (bars: BarsResponse, series: IndicatorsResponse) => boolean | void;
  onFailed?: (message: string) => void;
  markerKey?: string; // what identifies the markers (default: their count)
}

interface View extends LoadedView {
  selection: Span;
  meta: Record<string, OverlayMeta>;
  zooms: boolean; // a long selection: views ask the worker again (isLongRange)
}

const IDLE: LongRange = { loading: false, error: null, count: null, shown: null, displayTimeframe: null, data: null, meta: {} };

function inside(markers: Marker[], window: Span): Marker[] {
  return markers.filter((m) => m.time >= window.from && m.time <= window.to);
}

export function useLongRange(
  adapter: ChartAdapter | null,
  selection: Selection | null,
  indicators: IndicatorSpec[],
  markers: Marker[],
  options: LongRangeOptions = {},
): LongRange {
  const [state, setState] = useState<LongRange>(IDLE);
  const view = useRef<View | null>(null);
  const generation = useRef(0); // a new selection or indicator set
  const zoom = useRef(0); // the latest zoom request
  const asked = useRef('');
  const visibleNow = useRef<VisibleSpan | null>(null);
  const latest = useRef({ selection, indicators, markers, options });
  latest.current = { selection, indicators, markers, options };

  const selectionKey = selection ? `${selection.symbol}|${selection.timeframe}|${selection.start}|${selection.end}` : '';
  const indicatorKey = JSON.stringify(indicators.map((i) => [i.id, i.kind, i.length, i.source ?? 'close', i.params ?? {}]));
  const markerKey = options.markerKey ?? String(markers.length);

  // The whole selection, at most MAX_DISPLAY_BARS candles.
  useEffect(() => {
    if (!adapter || !selection) return;
    const gen = ++generation.current;
    view.current = null;
    asked.current = '';
    setState((s) => ({ ...s, loading: true, error: null, count: null, shown: null, displayTimeframe: null, data: null }));
    const ask = { maxBars: MAX_DISPLAY_BARS };
    Promise.all([api.bars(selection, ask), api.indicators(selection, indicators, ask)])
      .then(([bars, series]) => {
        if (gen !== generation.current) return;
        if (latest.current.options.onLoaded?.(bars, series) === false) {
          adapter.clear();
          setState(IDLE);
          return;
        }
        const meta = chartMeta(indicators, series.outputs, series.pane);
        const barTimes = bars.bars.map((b) => b.time);
        const whole = { from: bars.window.from_ms ?? 0, to: bars.window.to_ms ?? 0 };
        if (barTimes.length) {
          view.current = {
            window: whole,
            selection: whole,
            displayTimeframe: bars.display_timeframe,
            nativeTimeframe: selection.timeframe,
            barTimes,
            meta,
            zooms: isLongRange(bars.count),
          };
        }
        syncChart(adapter, {
          bars: bars.bars,
          timeframe: bars.display_timeframe as Timeframe,
          times: series.times,
          series: series.series,
          meta,
          markers: placeMarkers(latest.current.markers, barTimes),
        });
        setState({ loading: false, error: null, count: bars.count, shown: bars.shown, displayTimeframe: bars.display_timeframe, data: bars.data, meta });
      })
      .catch((e: unknown) => {
        if (gen !== generation.current) return;
        adapter.clear(); // never leave a previous selection's candles under a header that names the new one
        view.current = null;
        const message = errorMessage(e);
        latest.current.options.onFailed?.(message);
        setState({ ...IDLE, error: message });
      });
    // the keys capture every input of the fetch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adapter, selectionKey, indicatorKey]);

  // A pan or zoom: ask for the visible window when it fits finer candles or leaves what is loaded.
  useEffect(() => {
    if (!adapter) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reload = () => {
      const v = view.current;
      const visible = visibleNow.current;
      const { selection: sel, indicators: specs } = latest.current;
      if (!v || !v.zooms || !visible || !sel) return;
      const window = nextRequest(visible, v.selection, v, adapter.capacity());
      if (!window) return;
      const tag = `${window.from}:${window.to}:${window.maxBars}`;
      if (tag === asked.current) return; // the worker already answered this request
      asked.current = tag;
      const gen = generation.current;
      const mine = ++zoom.current;
      const ask = { maxBars: window.maxBars, from: window.from, to: window.to };
      Promise.all([api.bars(sel, ask), api.indicators(sel, specs, ask)])
        .then(([bars, series]) => {
          const current = view.current;
          if (gen !== generation.current || mine !== zoom.current || !current) return;
          const barTimes = bars.bars.map((b) => b.time);
          const loaded = { from: bars.window.from_ms ?? window.from, to: bars.window.to_ms ?? window.to };
          view.current = { ...current, window: loaded, displayTimeframe: bars.display_timeframe, barTimes };
          adapter.replaceBars(bars.bars, bars.display_timeframe as Timeframe, visibleNow.current ?? visible);
          adapter.setOverlays(overlaysFromSeries(series.times, series.series, current.meta));
          adapter.setMarkers(placeMarkers(inside(latest.current.markers, loaded), barTimes));
          setState((s) => ({ ...s, shown: bars.shown, displayTimeframe: bars.display_timeframe }));
        })
        .catch(() => {
          asked.current = ''; // a failed zoom keeps what is drawn; the next view change asks again
        });
    };
    adapter.onViewport((span) => {
      visibleNow.current = span;
      clearTimeout(timer);
      timer = setTimeout(reload, DEBOUNCE_MS);
    });
    return () => {
      clearTimeout(timer);
      adapter.onViewport(() => {});
    };
  }, [adapter]);

  // New markers (a new run, or a selection that no longer matches it) only move the markers.
  useEffect(() => {
    const v = view.current;
    if (!adapter || !v) return; // a load in flight places the latest markers itself
    adapter.setMarkers(placeMarkers(inside(markers, v.window), v.barTimes));
    // markerKey identifies the markers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adapter, markerKey]);

  return state;
}
