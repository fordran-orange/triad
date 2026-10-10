import { useEffect } from 'react';
import { ApiError, api } from '../api/client';
import { TERMINAL_JOB_STATES } from '../results';
import { SIDES, useDispatch, useWorkspace, type Side } from '../state/workspace';

type Kind = 'optimization' | 'walkforward';

/** Polls every unfinished job of either kind once a second (spec §4.2), whichever tab is open. Renders nothing. */
export function JobPoller() {
  const { optimization, walkforward } = useWorkspace();
  const dispatch = useDispatch();
  const entries: string[] = [];
  for (const s of SIDES) {
    if (optimization[s] && !TERMINAL_JOB_STATES.has(optimization[s]!.status)) entries.push(`optimization:${s}:${optimization[s]!.job_id}`);
    if (walkforward[s] && !TERMINAL_JOB_STATES.has(walkforward[s]!.status)) entries.push(`walkforward:${s}:${walkforward[s]!.job_id}`);
  }
  const key = entries.join('|');

  useEffect(() => {
    if (!key) return;
    const targets = key.split('|').map((p) => p.split(':') as [Kind, Side, string]);
    let stopped = false;
    const tick = async () => {
      for (const [kind, side, id] of targets) {
        try {
          if (kind === 'optimization') {
            const job = await api.job(id);
            if (!stopped) dispatch({ type: 'JOB_UPDATED', side, job });
          } else {
            const job = await api.walkforwardJob(id);
            if (!stopped) dispatch({ type: 'WALKFORWARD_UPDATED', side, job });
          }
        } catch (error) {
          // The worker no longer knows the job (restarted before it finished): it is lost, stop polling.
          if (error instanceof ApiError && error.status === 404 && !stopped) {
            dispatch(kind === 'optimization' ? { type: 'JOB_LOST', side, job_id: id } : { type: 'WALKFORWARD_LOST', side, job_id: id });
          }
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
