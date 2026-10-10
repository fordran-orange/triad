import { useEffect } from 'react';
import { ApiError, api } from '../api/client';
import { TERMINAL_JOB_STATES } from '../results';
import { SIDES, useDispatch, useWorkspace, type Side } from '../state/workspace';

/** Polls every unfinished optimization once a second (spec §4.2), whichever tab is open. Renders nothing. */
export function JobPoller() {
  const { optimization } = useWorkspace();
  const dispatch = useDispatch();
  const key = SIDES.filter((s) => optimization[s] && !TERMINAL_JOB_STATES.has(optimization[s]!.status))
    .map((s) => `${s}:${optimization[s]!.job_id}`)
    .join('|');

  useEffect(() => {
    if (!key) return;
    const pairs = key.split('|').map((p) => p.split(':') as [Side, string]);
    let stopped = false;
    const tick = async () => {
      for (const [side, id] of pairs) {
        try {
          const job = await api.job(id);
          if (!stopped) dispatch({ type: 'JOB_UPDATED', side, job });
        } catch (error) {
          // The worker no longer knows the job (restarted before it finished): it is lost, stop polling.
          if (error instanceof ApiError && error.status === 404 && !stopped) dispatch({ type: 'JOB_LOST', side, job_id: id });
          // Any other failure is transient; the next tick retries.
        }
      }
    };
    const timer = setInterval(tick, 1000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [key, dispatch]);

  return null;
}
