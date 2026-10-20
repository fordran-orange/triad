import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { createChartAdapter, type ChartAdapter, type Marker } from '../chart/adapter';
import { chartMeta, syncChart, type OverlayMeta } from '../chart/sync';
import type { RunEnvelope } from '../results';
import { selectionFromData, type Selection } from '../state/workspace';

/** A saved run's chart on the Library page: the run's archive bars, its indicators and its trade
 *  markers. It mounts its own adapter (the Library and Charts pages are never shown together) and
 *  never reads or writes the workspace (spec §5.1). */
export function LibraryChart({ run }: { run: RunEnvelope }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<ChartAdapter | null>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<{ kind: 'loading' | 'ok' | 'error' | 'drifted'; text?: string; count?: number }>({ kind: 'loading' });
  const [meta, setMeta] = useState<Record<string, OverlayMeta>>({});

  const selection: Selection | null = run.data.source === 'raw_archive' ? selectionFromData(run.data, null) : null;
  const side = run.strategy.long_side.enabled || !run.strategy.short_side.enabled ? 'long_side' : 'short_side';
  const indicators = run.strategy[side].indicators ?? [];
  const unavailable = run.state === 'source_unavailable';

  useEffect(() => {
    let cancelled = false;
    createChartAdapter().then((adapter) => {
      if (cancelled || !mountRef.current) return;
      adapter.mount(mountRef.current);
      adapterRef.current = adapter;
      setReady(true);
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

  useEffect(() => {
    const adapter = adapterRef.current;
    if (!adapter || !ready || !selection || unavailable) return;
    let cancelled = false;
    setState({ kind: 'loading' });
    Promise.all([api.bars(selection), api.indicators(selection, indicators)])
      .then(([bars, series]) => {
        if (cancelled) return;
        if (run.data.vintage !== undefined && bars.data.vintage !== run.data.vintage) {
          adapter.clear(); // the archive moved since the run: different data is never drawn under the run's markers
          setState({ kind: 'drifted', text: `the run is pinned to vintage ${run.data.vintage}; the archive is now ${bars.data.vintage ?? 'unknown'}` });
          return;
        }
        const drawn = chartMeta(indicators, series.outputs, series.pane);
        setMeta(drawn);
        syncChart(adapter, { bars: bars.bars, timeframe: selection.timeframe, times: series.times, series: series.series, meta: drawn, markers: (run.markers ?? []) as Marker[] });
        setState({ kind: 'ok', count: bars.count });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        adapter.clear();
        setState({ kind: 'error', text: errorMessage(e) });
      });
    return () => {
      cancelled = true;
    };
    // the run identifies everything fetched here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, run.run_id]);

  const blocked = !selection ? 'This run was made from supplied bars; it has no archive chart.' : unavailable ? `This run's pinned archive is no longer available; its saved results are shown below. ${run.state_detail ?? ''}` : null;

  return (
    <div className="library-chart chart" id="library-chart">
      <div className="chart-header">
        <div className="instrument">
          {run.data.symbol ?? '—'} · {run.data.timeframe ?? '—'} <span className="badge raw">RAW ARCHIVE · NOT RESEARCH-ELIGIBLE</span>
          {run.data.vintage && <span className="badge">vintage {run.data.vintage}</span>}
        </div>
        <div className="legend">
          <span className="muted">{side === 'long_side' ? 'LONG' : 'SHORT'}</span>
          {Object.entries(meta).map(([key, m]) => (
            <b key={key} style={{ color: m.color }}>
              {m.title}
            </b>
          ))}
          {state.kind === 'ok' && <span className="muted">{state.count?.toLocaleString()} bars · {(run.markers ?? []).length} markers</span>}
        </div>
      </div>
      <div className="chart-mount" ref={mountRef} />
      {(blocked || state.kind !== 'ok') && (
        <div className="chart-empty">
          {blocked ? (
            <span className="notice warn">{blocked}</span>
          ) : state.kind === 'drifted' ? (
            <span className="notice warn">Source unavailable: {state.text}. The saved results are shown below.</span>
          ) : state.kind === 'error' ? (
            <span className="error">{state.text}</span>
          ) : (
            'Loading bars…'
          )}
        </div>
      )}
    </div>
  );
}
