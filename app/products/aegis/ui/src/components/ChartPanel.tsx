import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { createChartAdapter, type ChartAdapter, type CrosshairPoint, type Marker } from '../chart/adapter';
import { syncChart } from '../chart/sync';
import { num } from '../format';
import type { Provenance } from '../results';
import { runStaleness, useDispatch, useWorkspace } from '../state/workspace';
import { sideIndicators } from './StrategyPanel';

const COLORS: Record<string, string> = { ema: '#2da7ff', sma: '#39d98a' };

interface Loaded {
  count: number;
  data: Provenance;
}

export function ChartPanel() {
  const state = useWorkspace();
  const { selection, strategy, lastRun, symbols } = state;
  const dispatch = useDispatch();
  const mountRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<ChartAdapter | null>(null);
  const [adapterReady, setAdapterReady] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CrosshairPoint | null>(null);
  const [loading, setLoading] = useState(false);

  const indicators = strategy ? sideIndicators(strategy, 'long_side') : [];
  const indicatorKey = indicators.map((i) => `${i.id}:${i.kind}:${i.length}:${i.source ?? 'close'}`).join('|');
  const pinnedVintage = lastRun?.data.vintage;
  const stale = runStaleness(state);
  // Markers belong to the run's selection and archive; on any other chart they would be a lie.
  const vintageDrift = loaded !== null && pinnedVintage !== undefined && pinnedVintage !== loaded.data.vintage;
  const markers: Marker[] = !stale.selection && !vintageDrift ? (lastRun?.markers ?? []) : [];
  const markerKey = `${lastRun?.run_id ?? ''}:${markers.length}`;

  // Mount the chart backend once; the adapter owns the library from here on.
  useEffect(() => {
    let cancelled = false;
    createChartAdapter().then((adapter) => {
      if (cancelled || !mountRef.current) return;
      adapter.mount(mountRef.current);
      adapter.onCrosshair(setCursor);
      adapterRef.current = adapter;
      setAdapterReady(true);
    });
    const onResize = () => adapterRef.current?.resize();
    window.addEventListener('resize', onResize);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', onResize);
      adapterRef.current?.destroy();
      adapterRef.current = null;
    };
  }, []);

  // Selection or indicator parameters changed: fetch bars and series, then sync the chart.
  useEffect(() => {
    const adapter = adapterRef.current;
    if (!adapter || !adapterReady || indicators.length === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setLoaded(null); // the header must not pair the new selection with the previous fetch's count
    Promise.all([api.bars(selection), api.indicators(selection, indicators)])
      .then(([bars, series]) => {
        if (cancelled) return;
        setLoaded({ count: bars.count, data: bars.data });
        dispatch({ type: 'BARS_LOADED', bars: { count: bars.count, vintage: String(bars.data.vintage ?? '') } });
        syncChart(adapter, {
          bars: bars.bars,
          timeframe: selection.timeframe,
          times: series.times,
          series: series.series,
          colors: COLORS,
          titles: Object.fromEntries(indicators.map((i) => [i.id, `${i.kind.toUpperCase()} ${i.length}`])),
          markers,
        });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        adapter.clear(); // never leave a previous selection's candles under a header that names the new one
        setLoaded(null);
        dispatch({ type: 'BARS_LOADED', bars: null });
        setError(errorMessage(e));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // markers are applied separately below; indicatorKey captures parameter changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adapterReady, selection.symbol, selection.timeframe, selection.start, selection.end, indicatorKey]);

  // A new run (or a selection that no longer matches it) only changes the markers; bars and overlays stay as fetched.
  useEffect(() => {
    adapterRef.current?.setMarkers(markers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markerKey]);

  const fast = indicators.find((i) => i.kind.toUpperCase() === 'EMA');
  const slow = indicators.find((i) => i.kind.toUpperCase() === 'SMA');

  return (
    <div className="chart-panel">
      <div className="tabs">
        {(symbols ?? []).map((info) => (
          <button
            key={info.symbol}
            className={'tab' + (info.symbol === selection.symbol ? ' active' : '')}
            type="button"
            title={`vintage ${info.vintage} · ${String(info.first_bar).slice(0, 10)} → ${String(info.last_bar).slice(0, 10)} · ${info.row_count.toLocaleString()} 1m rows · coverage ${info.coverage_pct == null ? '—' : info.coverage_pct.toFixed(1) + '%'} · sources ${(info.vendor_sources ?? []).join(', ') || '—'}`}
            onClick={() => dispatch({ type: 'SET_SELECTION', selection: { symbol: info.symbol } })}
          >
            {info.symbol}
          </button>
        ))}
        {symbols !== null && symbols.length === 0 && <span className="tab muted">no raw archives on disk</span>}
        {symbols === null && <span className="tab muted">{selection.symbol}</span>}
        <button className="tab" type="button" disabled title="Not yet built">
          ＋
        </button>
      </div>
      <div className="chart">
        <div className="chart-header">
          <div className="instrument">
            {selection.symbol} · {selection.timeframe} <span className="badge raw">RAW ARCHIVE · NOT RESEARCH-ELIGIBLE</span>
            {loaded && <span className="badge" title={`archive ${loaded.data.vintage}`}>vintage {loaded.data.vintage}</span>}
            {loaded && pinnedVintage && pinnedVintage !== loaded.data.vintage && (
              <span className="badge raw" title={lastRun?.state_detail ?? `the last run is pinned to vintage ${pinnedVintage}`}>
                RUN PINNED TO VINTAGE {pinnedVintage} · CHART SHOWS CURRENT ARCHIVE
              </span>
            )}
          </div>
          <div className="ohlc">
            {cursor?.price != null ? (
              <>
                cursor {num(cursor.price)} <span className="muted">{cursor.time ? new Date(cursor.time).toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : ''}</span>
              </>
            ) : loaded ? (
              <>
                {loaded.count.toLocaleString()} bars · {selection.start} → {selection.end}
              </>
            ) : (
              <>
                O — &nbsp; H — &nbsp; L — &nbsp; C — <span className="muted">{loading ? 'loading…' : 'not loaded'}</span>
              </>
            )}
          </div>
          <div className="legend">
            <b className="accent">EMA {fast?.length ?? '—'}</b>
            <b className="green">SMA {slow?.length ?? '—'}</b>
            <span>Volume</span>
            {markers.length > 0 && <span className="muted">{markers.length} markers</span>}
            {lastRun && markers.length === 0 && (lastRun.markers?.length ?? 0) > 0 && (
              <span className="muted" title="The last run was made on another selection or archive; its markers are not drawn here">
                markers hidden (run is for {lastRun.data.symbol} · {lastRun.data.timeframe})
              </span>
            )}
          </div>
        </div>
        <div className="chart-mount" ref={mountRef} id="chart-mount" />
        {!loaded && (
          <div className="chart-empty">
            {error ? <span className="error">{error}</span> : loading ? 'Loading bars…' : 'No bars loaded'}
          </div>
        )}
        {loaded && error && <div className="chart-empty error">{error}</div>}
      </div>
    </div>
  );
}
