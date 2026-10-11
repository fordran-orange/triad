import { useEffect, useState } from 'react';
import { api } from './api/client';
import { ChartPanel } from './components/ChartPanel';
import { LabPage } from './components/LabPage';
import { JobPoller } from './components/JobPoller';
import { ResultsTabs } from './components/ResultsTabs';
import { RunsDrawer } from './components/RunsDrawer';
import { SideNav } from './components/SideNav';
import { StatusStrip } from './components/StatusStrip';
import { StrategyPanel } from './components/StrategyPanel';
import { TopBar } from './components/TopBar';
import { TERMINAL_JOB_STATES } from './results';
import { useDocumentSync } from './state/documents';
import { useDispatch, useWorkspace } from './state/workspace';

export function App() {
  const dispatch = useDispatch();
  const { page } = useWorkspace();
  useDocumentSync();
  const [apiState, setApiState] = useState<string>('loading strategy contract…');
  const [runsOpen, setRunsOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // The workspace starts on the built-in reference document (spec §8).
    api
      .strategyDocument('ema9-sma30-cross-v1')
      .then((document) => {
        if (cancelled) return;
        dispatch({ type: 'SET_DOCUMENT', document });
        setApiState('strategy contract loaded');
      })
      .catch((error: Error) => !cancelled && setApiState('strategy API unavailable: ' + error.message));
    // The symbol menu reflects what is on disk; absent archives are absent, not errors on click.
    api
      .symbols()
      .then((body) => !cancelled && dispatch({ type: 'SET_SYMBOLS', symbols: body.symbols }))
      .catch(() => !cancelled && dispatch({ type: 'SET_SYMBOLS', symbols: [] }));
    api
      .status()
      .then((status) => !cancelled && dispatch({ type: 'SET_STATUS', status }))
      .catch(() => !cancelled && dispatch({ type: 'SET_STATUS', status: null }));
    // A job started before this page loaded (or in another tab) is adopted, not hidden behind a 409.
    api
      .optimizations()
      .then(async (jobs) => {
        for (const summary of jobs) {
          if (cancelled || TERMINAL_JOB_STATES.has(summary.status) || !summary.side) continue;
          try {
            const job = await api.job(summary.job_id);
            if (!cancelled) dispatch({ type: 'JOB_UPDATED', side: summary.side, job });
          } catch {
            /* the job vanished between list and fetch; nothing to adopt */
          }
        }
      })
      .catch(() => undefined);
    api
      .walkforwards()
      .then(async (jobs) => {
        for (const summary of jobs) {
          if (cancelled || TERMINAL_JOB_STATES.has(summary.status) || !summary.side) continue;
          try {
            const job = await api.walkforwardJob(summary.job_id);
            if (!cancelled) dispatch({ type: 'WALKFORWARD_UPDATED', side: summary.side, job });
          } catch {
            /* vanished between list and fetch */
          }
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  return (
    <div className="app">
      <TopBar runsOpen={runsOpen} onToggleRuns={() => setRunsOpen((v) => !v)} />
      <SideNav />
      <main className="main">
        {page === 'lab' ? (
          <section className="workspace">
            <LabPage />
            <StrategyPanel />
          </section>
        ) : (
          <>
            <section className="workspace">
              <ChartPanel />
              <StrategyPanel />
            </section>
            <ResultsTabs />
          </>
        )}
      </main>
      <RunsDrawer open={runsOpen} onClose={() => setRunsOpen(false)} />
      <JobPoller />
      <StatusStrip apiState={apiState} />
    </div>
  );
}
