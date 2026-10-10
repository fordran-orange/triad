import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { DASH, shortHash, timeLabel } from '../format';
import type { RunSummary } from '../results';
import { useDispatch, useWorkspace } from '../state/workspace';

/** Persisted runs from GET /aegis/api/runs; loading one restores its selection, strategy and results. */
export function RunsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { lastRun } = useWorkspace();
  const dispatch = useDispatch();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    api
      .runs()
      .then((list) => !cancelled && setRuns(list))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [open, lastRun?.run_id]);

  if (!open) return null;

  const load = async (id: string) => {
    setLoadingId(id);
    setError(null);
    try {
      dispatch({ type: 'LOAD_RUN', run: await api.run(id) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <aside className="drawer" aria-label="Saved runs">
      <div className="drawer-head">
        <b>Saved runs</b>
        <button type="button" className="btn" onClick={onClose} aria-label="Close saved runs">
          ✕
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {lastRun?.state === 'source_unavailable' && (
        <div className="notice warn">
          Loaded run {lastRun.run_id.slice(0, 8)} is pinned to an archive that is no longer available; its saved results are shown but cannot be reproduced.
          <div className="small">{lastRun.state_detail}</div>
        </div>
      )}
      {runs === null && !error && <div className="empty-state">Loading saved runs…</div>}
      {runs !== null && runs.length === 0 && <div className="empty-state">No saved runs yet.</div>}
      {runs?.map((r) => (
        <div key={r.run_id} className={'run-row' + (lastRun?.run_id === r.run_id ? ' current' : '')}>
          <div>
            <b>
              {r.data?.symbol ?? DASH} · {r.data?.timeframe ?? DASH}
            </b>{' '}
            <span className="muted">
              {r.data?.start ?? DASH} → {r.data?.end ?? DASH}
            </span>
            <div className="small muted">
              {r.strategy?.name ?? DASH} · {timeLabel(r.created_at)} · hash {shortHash(r.result_hash)} · vintage {r.data?.vintage ?? DASH}
            </div>
          </div>
          <button type="button" className="btn btn-primary" disabled={loadingId !== null} onClick={() => load(r.run_id)}>
            {loadingId === r.run_id ? 'Loading…' : 'Load'}
          </button>
        </div>
      ))}
    </aside>
  );
}
