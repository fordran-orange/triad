import { describe, expect, it } from 'vitest';
import type { LabTask, LabTaskState } from '../results';
import { canRerun, isActive, pollDelay, TASK_POLL_MS, taskLine } from './labTask';

const T0 = Date.parse('2026-10-30T10:00:00Z');
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString();
const STATES: LabTaskState[] = ['queued', 'running', 'done', 'cancelled', 'failed'];

/** A task as the server's status sends it (`tasks.status_json`): a running importance task, no stage delivered yet. */
function task(over: Partial<LabTask> = {}): LabTask {
  return {
    id: 'a1b2c3',
    label: 'importance',
    state: 'running',
    stage: 0,
    stages: 3,
    progress: 0,
    error: null,
    started_at: at(0),
    finished_at: null,
    sharing_cpu: false,
    ...over,
  };
}

describe('taskLine (the task line names the computing task, as the server status does)', () => {
  it('reads the example of the plan: the stage being computed and the shared CPU', () => {
    expect(taskLine(task({ sharing_cpu: true }), T0)).toBe('Importance · stage 1 of 3 · sharing CPU with the running job');
  });

  it('names the stage being computed: one past the stages delivered, never past the last', () => {
    expect(taskLine(task({ stage: 1, progress: 1 / 3 }), T0)).toBe('Importance · stage 2 of 3');
    expect(taskLine(task({ stage: 2 }), T0)).toBe('Importance · stage 3 of 3');
    expect(taskLine(task({ stage: 3 }), T0)).toBe('Importance · stage 3 of 3');
  });

  it('adds the seconds elapsed since the task started, once there is at least one', () => {
    expect(taskLine(task({ stage: 1 }), T0 + 400)).toBe('Importance · stage 2 of 3');
    expect(taskLine(task({ stage: 1 }), T0 + 41_400)).toBe('Importance · stage 2 of 3 · 41 s elapsed');
    expect(taskLine(task({ stage: 2, sharing_cpu: true }), T0 + 83_000)).toBe('Importance · stage 3 of 3 · 1 min 23 s elapsed · sharing CPU with the running job');
  });

  it('shows no elapsed time for a clock that reads before the start, or a start it cannot read', () => {
    expect(taskLine(task(), T0 - 5_000)).toBe('Importance · stage 1 of 3');
    expect(taskLine(task({ started_at: null }), T0 + 90_000)).toBe('Importance · stage 1 of 3');
    expect(taskLine(task({ started_at: 'not a time' }), T0 + 90_000)).toBe('Importance · stage 1 of 3');
  });

  it('says queued while the task waits, and still names the shared CPU', () => {
    expect(taskLine(task({ state: 'queued', started_at: null }), T0 + 9_000)).toBe('Importance · queued');
    expect(taskLine(task({ state: 'queued', started_at: null, sharing_cpu: true }), T0)).toBe('Importance · queued · sharing CPU with the running job');
  });

  it('says how long a finished task took, from its own two stamps', () => {
    expect(taskLine(task({ state: 'done', stage: 3, finished_at: at(83) }), T0 + 500_000)).toBe('Importance · done in 1 min 23 s');
    expect(taskLine(task({ state: 'done', stage: 3, finished_at: at(41) }), T0 + 500_000)).toBe('Importance · done in 41 s');
    expect(taskLine(task({ state: 'done', stage: 3, started_at: null, finished_at: at(41) }), T0)).toBe('Importance · done');
  });

  it('names the stages a cancelled task kept, or that it stopped before the first', () => {
    expect(taskLine(task({ state: 'cancelled', stage: 2, finished_at: at(60) }), T0 + 100_000)).toBe('Importance · cancelled after stage 2 of 3');
    expect(taskLine(task({ state: 'cancelled', stage: 0, finished_at: at(5) }), T0 + 100_000)).toBe('Importance · cancelled before the first stage finished');
  });

  it("gives a failed task's error beside the stages it delivered", () => {
    const failed = task({ state: 'failed', stage: 1, error: 'ValueError: no finite net_pnl', finished_at: at(12) });
    expect(taskLine(failed, T0 + 100_000)).toBe('Importance · failed after stage 1 of 3 · ValueError: no finite net_pnl');
    expect(taskLine({ ...failed, stage: 0, error: null }, T0)).toBe('Importance · failed');
  });

  it('says nothing of the CPU once the task has stopped, whatever its status carries', () => {
    expect(taskLine(task({ state: 'cancelled', stage: 1, sharing_cpu: true }), T0)).toBe('Importance · cancelled after stage 1 of 3');
    expect(taskLine(task({ state: 'done', stage: 3, finished_at: at(5), sharing_cpu: true }), T0)).toBe('Importance · done in 5 s');
  });

  it("names the label the server sent, capitalised, and never the waiting task's", () => {
    expect(taskLine(task({ label: 'pareto sweep' }), T0)).toBe('Pareto sweep · stage 1 of 3');
  });
});

describe('pollDelay (a poll never restarts a stopped task)', () => {
  it('polls every 2,000 ms while the task is queued or running', () => {
    expect(TASK_POLL_MS).toBe(2_000);
    expect(pollDelay(task({ state: 'queued' }))).toBe(2_000);
    expect(pollDelay(task({ state: 'running' }))).toBe(2_000);
  });

  it('stops polling once the task is done, failed or cancelled', () => {
    for (const state of ['done', 'failed', 'cancelled'] as const) expect(pollDelay(task({ state }))).toBeNull();
  });

  it('has nothing to poll without a task (a view that requested none)', () => {
    expect(pollDelay(null)).toBeNull();
  });

  it('polls exactly the states that are active', () => {
    for (const state of STATES) expect(pollDelay(task({ state }))).toBe(isActive(task({ state })) ? TASK_POLL_MS : null);
  });
});

describe('canRerun ("Run again" shows only on a stopped task)', () => {
  it('is true for a cancelled and a failed task only', () => {
    const answer = Object.fromEntries(STATES.map((state) => [state, canRerun(task({ state }))]));
    expect(answer).toEqual({ queued: false, running: false, done: false, cancelled: true, failed: true });
  });

  it('is false while a cancel is pending: the state still reads running, and a rerun would queue a new task', () => {
    expect(canRerun(task({ state: 'running', stage: 1 }))).toBe(false);
  });

  it('is false without a task', () => {
    expect(canRerun(null)).toBe(false);
  });
});
