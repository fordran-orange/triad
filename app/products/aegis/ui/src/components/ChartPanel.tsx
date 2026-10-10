import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { createChartAdapter, type ChartAdapter, type CrosshairPoint, type Marker } from '../chart/adapter';
import { syncChart } from '../chart/sync';
import { num } from '../format';
import type { Provenance } from '../results';
import { useDispatch, useWorkspace } from '../state/workspace';
import { sideIndicators } from './StrategyPanel';

const TABS = ['QQQ', 'SPY', 'ITOT'];
const COLORS: Record<string, string> = { ema: '#2da7ff', sma: '#39d98a' };

interface Loaded {
  count: number;
  data: Provenance;
}

export function ChartPanel() {
  const { selection, strategy, lastRun } = useWorkspace();
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
  const markers: Marker[] = lastRun?.markers ?? [];
  const pinnedVintage = lastRun?.data.vintage;

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
        setError(errorMessage(e));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // markers are applied separately below; indicatorKey captures parameter changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adapterReady, selection.symbol, selection.timeframe, selection.start, selection.end, indicatorKey]);

  // A new run only changes the markers; bars and overlays stay as fetched.
  useEffect(() => {
    adapterRef.current?.setMarkers(markers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastRun]);

  const fast = indicators.find((i) => i.kind.toUpperCase() === 'EMA');
  const slow = indicators.find((i) => i.kind.toUpperCase() === 'SMA');

  return (
    <div className="chart-panel">
      <div className="tabs">
        {TABS.map((symbol) => (
          <button
            key={symbol}
            className={'tab' + (symbol === selection.symbol ? ' active' : '')}
            type="button"
            onClick={() => dispatch({ type: 'SET_SELECTION', selection: { symbol } })}
          >
            {symbol}
          </button>
        ))}
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
