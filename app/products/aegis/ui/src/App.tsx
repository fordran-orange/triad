import { useEffect, useState } from 'react';
import { api } from './api/client';
import { ChartPanel } from './components/ChartPanel';
import { JobPoller } from './components/JobPoller';
import { ResultsTabs } from './components/ResultsTabs';
import { RunsDrawer } from './components/RunsDrawer';
import { SideNav } from './components/SideNav';
import { StatusStrip } from './components/StatusStrip';
import { StrategyPanel } from './components/StrategyPanel';
import { TopBar } from './components/TopBar';
import { useDispatch } from './state/workspace';

export function App() {
  const dispatch = useDispatch();
  const [apiState, setApiState] = useState<string>('loading strategy contract…');
  const [runsOpen, setRunsOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .defaultStrategy()
      .then((strategy) => {
        if (cancelled) return;
        dispatch({ type: 'SET_STRATEGY', strategy });
        setApiState('strategy contract loaded');
      })
      .catch((error: Error) => !cancelled && setApiState('strategy API unavailable: ' + error.message));
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  return (
    <div className="app">
      <TopBar runsOpen={runsOpen} onToggleRuns={() => setRunsOpen((v) => !v)} />
      <SideNav />
      <main className="main">
        <section className="workspace">
          <ChartPanel />
          <StrategyPanel />
        </section>
        <ResultsTabs />
      </main>
      <RunsDrawer open={runsOpen} onClose={() => setRunsOpen(false)} />
      <JobPoller />
      <StatusStrip apiState={apiState} />
    </div>
  );
}
