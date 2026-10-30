// The Lab's side of the importance task (Phase 3, spec §9.4): pure helpers over the task status a view sends
// (`LabTask`, `tasks.status_json`), nothing React and nothing fetched. The panels poll while a task is active, say
// what it is doing in one line, and offer "Run again" only once it has stopped.
import type { LabTask } from '../results';

/** How often an active task's view is asked again (spec §9.4). */
export const TASK_POLL_MS = 2_000;

/** A task that is still to finish: waiting, or computing. */
export function isActive(task: LabTask | null): boolean {
  return task !== null && (task.state === 'queued' || task.state === 'running');
}

/** The wait before the next poll of a task's view: `TASK_POLL_MS` while it is queued or running, null once it is
 *  done, failed or cancelled (and when no task was requested). A poll never restarts a stopped task; the operator's
 *  "Run again" is the only request that sets `rerun`. */
export function pollDelay(task: LabTask | null): number | null {
  return isActive(task) ? TASK_POLL_MS : null;
}

/** Whether "Run again" shows: only a `cancelled` or `failed` task. During a pending cancel the status still reads
 *  `running`, and a request with `rerun` then would queue a new task beside it. */
export function canRerun(task: LabTask | null): boolean {
  return task !== null && (task.state === 'cancelled' || task.state === 'failed');
}

/** Whole seconds as `41 s`, or `1 min 23 s` from a minute on. */
function duration(seconds: number): string {
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** Whole seconds from one ISO time to a millisecond clock; null when either is not a time, or the end precedes the start. */
function secondsBetween(from: string | null, to: string | number | null): number | null {
  if (from === null || to === null) return null;
  const start = Date.parse(from);
  const end = typeof to === 'number' ? to : Date.parse(to);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return Math.floor((end - start) / 1000);
}

const SHARING = 'sharing CPU with the running job';

/** The task line a panel prints, from the status of the computing task (the server names it, never the waiter behind
 *  it). `now` is the client's clock in milliseconds. Examples:
 *  - `Importance · stage 1 of 3 · sharing CPU with the running job`: the stage being computed, one past those
 *    delivered; from the first second on, the time elapsed since it started goes before the CPU clause;
 *  - `Importance · queued`;
 *  - `Importance · done in 1 min 23 s`;
 *  - `Importance · cancelled after stage 2 of 3`: the stages it kept stay readable, labelled partial;
 *  - `Importance · failed after stage 1 of 3 · <error>`. */
export function taskLine(task: LabTask, now: number): string {
  const parts = [task.label.charAt(0).toUpperCase() + task.label.slice(1)];
  const delivered = `stage ${task.stage} of ${task.stages}`;
  switch (task.state) {
    case 'queued':
      parts.push('queued');
      break;
    case 'running': {
      parts.push(`stage ${Math.min(task.stage + 1, task.stages)} of ${task.stages}`);
      const elapsed = secondsBetween(task.started_at, now);
      if (elapsed !== null && elapsed >= 1) parts.push(`${duration(elapsed)} elapsed`);
      break;
    }
    case 'done': {
      const took = secondsBetween(task.started_at, task.finished_at);
      parts.push(took === null ? 'done' : `done in ${duration(took)}`);
      break;
    }
    case 'cancelled':
      parts.push(task.stage > 0 ? `cancelled after ${delivered}` : 'cancelled before the first stage finished');
      break;
    case 'failed':
      parts.push(task.stage > 0 ? `failed after ${delivered}` : 'failed');
      if (task.error) parts.push(task.error);
      break;
  }
  if (isActive(task) && task.sharing_cpu) parts.push(SHARING);
  return parts.join(' · ');
}

// --- what the panels share of one importance analysis beyond one tab ---------------------------------------------------

/** How many importance tasks have been seen finished, and which one was counted last. The Robustness tab and the rail's
 *  candidate card read B from the finished importance, so each asks again when this count moves: a result that appeared
 *  after they asked is what they were missing. */
export interface DoneCounter {
  count: number;
  id: string | null;
}

export const NO_DONE: DoneCounter = { count: 0, id: null };

/** The counter after one more look at the computing task: a task seen `done` counts once, and every later look at the same
 *  done task counts nothing (the same counter object comes back, so a state update that changes nothing renders nothing).
 *  A task run again has a new id and counts in its turn; one that is queued, running, cancelled or failed delivers no
 *  result of its own, and a view that requested no task (null) has nothing to count. */
export function noteDone(counter: DoneCounter, task: LabTask | null): DoneCounter {
  if (task === null || task.state !== 'done' || task.id === counter.id) return counter;
  return { count: counter.count + 1, id: task.id };
}

/** The task a background watch follows: the analysis of one source, metric and side scope (its coalescing key's parts the
 *  Lab chooses). A tab that was left while the task still ran hands it over, so its finishing is seen. */
export interface TaskWatch {
  source: string;
  metric: string;
  scope: string;
}

/** Whether the watch is of the task the Lab is looking at now. A watch asks the importance view with the Lab's own metric
 *  and scope, so it may continue only while they are the watch's: asking under another would request another task. */
export function sameWatch(watch: TaskWatch | null, now: TaskWatch | null): boolean {
  return watch !== null && now !== null && watch.source === now.source && watch.metric === now.metric && watch.scope === now.scope;
}

/** Whether a Cancel the operator asked is still pending: it named one task under one view key, and holds while that task
 *  still reads queued or running under that key. A new key (another source, metric or filter) or another task ends it. */
export function cancelPending(asked: { key: string; id: string } | null, key: string | null, task: LabTask | null): boolean {
  return asked !== null && key !== null && asked.key === key && task !== null && task.id === asked.id && isActive(task);
}

/** What a failed poll adds to its error: that the polling stopped while the task the last answer showed may still run.
 *  Null with no error, or when that task had already stopped. */
export function pollStopped(error: string | null, task: LabTask | null): string | null {
  return error !== null && isActive(task) ? 'polling has stopped and the task may still be running: Retry asks again' : null;
}
