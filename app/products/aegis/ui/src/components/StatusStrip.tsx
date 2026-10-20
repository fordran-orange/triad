import { useState } from 'react';
import { CHART_LIBRARY, VELA_NOTICE } from '../about';
import { api, errorMessage } from '../api/client';
import { DASH, money, num, pct, shortHash } from '../format';
import { runStaleness, useDispatch, useWorkspace } from '../state/workspace';

export function StatusStrip({ apiState }: { apiState: string }) {
  const state = useWorkspace();
  const dispatch = useDispatch();
  const [keeping, setKeeping] = useState(false);
  const [keepError, setKeepError] = useState<string | null>(null);
  const keep = (runId: string) => {
    setKeeping(true);
    setKeepError(null);
    api
      .keepRun(runId)
      .then(() => dispatch({ type: 'RUN_KEPT', run_id: runId }))
      .catch((e: unknown) => setKeepError(errorMessage(e)))
      .finally(() => setKeeping(false));
  };
  const { selection, strategy, lastRun, running, runError } = state;
  const m = lastRun?.result.combined.metrics ?? null;
  const stale = runStaleness(state);
  return (
    <div className="status-strip">
      <span title={lastRun ? 'The symbol the shown KPIs were computed on' : 'Current selection'}>
        <b>{lastRun ? (lastRun.data.symbol ?? selection.symbol) : selection.symbol}</b> · {strategy?.name ?? DASH}
      </span>
      <span>
        CAGR <b>{m ? pct(m.cagr) : DASH}</b>
      </span>
      <span>
        Net P&L <b>{m ? money(m.net_pnl) : DASH}</b>
      </span>
      <span>
        Max DD <b>{m ? pct(m.max_drawdown) : DASH}</b>
      </span>
      <span>
        MAR <b>{m ? num(m.mar) : DASH}</b>
      </span>
      <span>
        Expectancy <b>{m ? money(m.expectancy) : DASH}</b>
      </span>
      <span>
        Exposure <b>{m ? pct(m.exposure) : DASH}</b>
      </span>
      <span className="mono" title="SHA-256 of the canonical result payload">
        hash <b id="result-hash">{shortHash(lastRun?.result_hash)}</b>
      </span>
      <span id="run-state">
        {running && <span className="badge">running backtest…</span>}
        {!running && runError && (
          <span className="badge error" title={runError}>
            run failed: {runError}
          </span>
        )}
        {!running && !runError && lastRun?.state === 'source_unavailable' && (
          <span className="badge raw" title={lastRun.state_detail ?? 'pinned archive unavailable'}>
            SOURCE UNAVAILABLE
          </span>
        )}
        {!running && !runError && lastRun?.state === 'ok' && (
          <span className="muted">run {lastRun.run_id.slice(0, 8)} · {lastRun.elapsed_ms} ms</span>
        )}
        {!running && lastRun?.saved === false && (
          <>
            <span className="badge raw" title="Held in memory only: the worker forgets unsaved runs on restart">
              NOT KEPT
            </span>
            <button id="keep-run" type="button" className="btn" disabled={keeping} onClick={() => keep(lastRun.run_id)} title={keepError ?? 'Save this run'}>
              {keeping ? 'Keeping…' : 'Keep'}
            </button>
            {keepError && <span className="badge error">{keepError}</span>}
          </>
        )}
        {!running && stale.any && (
          <span className="badge raw" id="stale-badge" title="The selection, strategy or settings changed since this run; the KPIs describe the run, not the screen">
            STALE
          </span>
        )}
      </span>
      <span className="about">
        <span id="api-state">{apiState}</span>
        {' · '}
        <a href={CHART_LIBRARY.homepage} target="_blank" rel="noreferrer" title={VELA_NOTICE}>
          charts by {CHART_LIBRARY.name} {CHART_LIBRARY.version} ({CHART_LIBRARY.license})
        </a>
      </span>
    </div>
  );
}
