import { useEffect, useRef, useState } from 'react';
import { createChartAdapter, type ChartAdapter, type Marker } from '../chart/adapter';
import { shownAs } from '../chart/longRange';
import { useLongRange } from '../chart/useLongRange';
import type { RunEnvelope } from '../results';
import { selectionFromData, type Selection } from '../state/workspace';

/** A saved run's chart on the Library page: the run's archive bars, its indicators and its trade
 *  markers. It mounts its own adapter (the Library and Charts pages are never shown together) and
 *  never reads or writes the workspace (spec §5.1). */
export function LibraryChart({ run }: { run: RunEnvelope }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<ChartAdapter | null>(null);
  const [ready, setReady] = useState(false);
  const [drift, setDrift] = useState<string | null>(null);

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

  // Mission 10: the same long-range loader as the Charts page.
  const markers = (run.markers ?? []) as Marker[];
  const range = useLongRange(ready && !unavailable ? adapterRef.current : null, selection, indicators, markers, {
    markerKey: `${run.run_id}:${markers.length}`,
    onLoaded: (bars) => {
      if (run.data.vintage !== undefined && bars.data.vintage !== run.data.vintage) {
        // the archive moved since the run: different data is never drawn under the run's markers
        setDrift(`the run is pinned to vintage ${run.data.vintage}; the archive is now ${bars.data.vintage ?? 'unknown'}`);
        return false;
      }
      setDrift(null);
    },
  });
  const meta = range.meta;
  const state: { kind: 'loading' | 'ok' | 'error' | 'drifted'; text?: string } = drift
    ? { kind: 'drifted', text: drift }
    : range.error
      ? { kind: 'error', text: range.error }
      : range.count !== null
        ? { kind: 'ok' }
        : { kind: 'loading' };
  const badge = range.displayTimeframe && selection ? shownAs(range.displayTimeframe, selection.timeframe) : null;

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
          {state.kind === 'ok' && (
            <span className="muted">
              {range.count?.toLocaleString()} bars · {(run.markers ?? []).length} markers
            </span>
          )}
          {state.kind === 'ok' && badge && (
            <span className="badge" id="library-shown-as">
              {badge}
            </span>
          )}
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
