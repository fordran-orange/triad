import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LabTask, LabTaskState } from '../results';
import { canRerun, cancelPending, followTask, isActive, noteDone, NO_DONE, pollDelay, pollStopped, sameWatch, TASK_POLL_MS, taskLine, watchTaskStatus } from './labTask';

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

describe('noteDone (a finished importance task refreshes what reads its result, once)', () => {
  const run = (tasks: Array<LabTask | null>) => tasks.reduce(noteDone, NO_DONE);

  it('a transition to done counts once, and every later look at the same done task does not', () => {
    const sequence = [task({ state: 'queued' }), task({ state: 'running', stage: 1 }), task({ state: 'running', stage: 2 }), task({ state: 'done', stage: 3 }), task({ state: 'done', stage: 3 }), task({ state: 'done', stage: 3 })];
    expect(sequence.map((_, i) => run(sequence.slice(0, i + 1)).count)).toEqual([0, 0, 0, 1, 1, 1]);
  });

  it('hands back the same counter when nothing changed, so a state update does not render', () => {
    const once = run([task({ state: 'done', stage: 3 })]);
    expect(noteDone(once, task({ state: 'done', stage: 3 }))).toBe(once);
    expect(noteDone(once, null)).toBe(once);
    expect(noteDone(once, task({ state: 'running' }))).toBe(once);
  });

  it('only done counts: a cancelled or failed task, or none, is no new result', () => {
    for (const state of ['queued', 'running', 'cancelled', 'failed'] as const) expect(noteDone(NO_DONE, task({ state })).count).toBe(0);
    expect(noteDone(NO_DONE, null)).toBe(NO_DONE);
  });

  it('a task run again counts when it is done in its turn: a new id, not the old one twice', () => {
    const first = task({ id: 'first', state: 'done', stage: 3 });
    const second = task({ id: 'second', state: 'done', stage: 3 });
    expect(run([first, task({ id: 'second', state: 'running' }), second, second]).count).toBe(2);
  });

  it('a task first seen already done counts (its result may be newer than what the readers asked)', () => {
    expect(run([task({ state: 'done', stage: 3 })]).count).toBe(1);
  });
});

describe('sameWatch (a background watch belongs to the source it was handed from)', () => {
  const watch = { source: 'exp:e1', taskId: 'a1b2c3' };

  it('holds only while that source is the one open', () => {
    expect(sameWatch(watch, 'exp:e1')).toBe(true);
    expect(sameWatch(watch, 'exp:e2')).toBe(false);
    expect(sameWatch(watch, 'opt:e1')).toBe(false);
  });

  it('never holds without a watch, or without an open source', () => {
    expect(sameWatch(null, 'exp:e1')).toBe(false);
    expect(sameWatch(watch, null)).toBe(false);
    expect(sameWatch(null, null)).toBe(false);
  });
});

describe('cancelPending (Cancel is a request about one task of one view key)', () => {
  const asked = { key: 'importance|exp:e1|net_pnl|f1', id: 'a1b2c3' };

  it('holds while the task asked about is still active under the same key', () => {
    expect(cancelPending(asked, asked.key, task({ state: 'running' }))).toBe(true);
    expect(cancelPending(asked, asked.key, task({ state: 'queued' }))).toBe(true);
  });

  it('is reset by a new key (another source, metric or filter) and by another task', () => {
    expect(cancelPending(asked, 'importance|exp:e2|net_pnl|f1', task({ state: 'running' }))).toBe(false);
    expect(cancelPending(asked, null, task({ state: 'running' }))).toBe(false);
    expect(cancelPending(asked, asked.key, task({ id: 'other', state: 'running' }))).toBe(false);
  });

  it('ends once the task has stopped, and never holds without a request or a task', () => {
    for (const state of ['done', 'cancelled', 'failed'] as const) expect(cancelPending(asked, asked.key, task({ state }))).toBe(false);
    expect(cancelPending(null, asked.key, task({ state: 'running' }))).toBe(false);
    expect(cancelPending(asked, asked.key, null)).toBe(false);
  });
});

describe('pollStopped (a failed poll says that the polling stopped)', () => {
  it('says so while the last answer shows a task that is still active', () => {
    expect(pollStopped('503 Service Unavailable', task({ state: 'running' }))).toBe('polling has stopped and the task may still be running: Retry asks again');
    expect(pollStopped('boom', task({ state: 'queued' }))).not.toBeNull();
  });

  it('says nothing without an error, or when the task had already stopped', () => {
    expect(pollStopped(null, task({ state: 'running' }))).toBeNull();
    expect(pollStopped('boom', task({ state: 'done' }))).toBeNull();
    expect(pollStopped('boom', null)).toBeNull();
  });
});

describe('followTask (a watch is bound to the task it was handed and stops when that task ended)', () => {
  it('keeps watching while the task is queued or running, and counts nothing yet', () => {
    for (const state of ['queued', 'running'] as const) {
      const step = followTask(NO_DONE, task({ state }));
      expect(step.watching, state).toBe(true);
      expect(step.counter).toBe(NO_DONE);
    }
  });

  it('stops at every ended state, and counts a done task exactly once', () => {
    const done = followTask(NO_DONE, task({ state: 'done', stage: 3 }));
    expect(done.watching).toBe(false);
    expect(done.counter.count).toBe(1);
    // The same ended task seen again (a second look before the watch was dropped) counts nothing more.
    const again = followTask(done.counter, task({ state: 'done', stage: 3 }));
    expect(again.watching).toBe(false);
    expect(again.counter.count).toBe(1);
  });

  it('counts nothing for a cancelled or a failed task, and stops', () => {
    for (const state of ['cancelled', 'failed'] as const) {
      const step = followTask(NO_DONE, task({ state, stage: 1 }));
      expect(step.watching, state).toBe(false);
      expect(step.counter.count, state).toBe(0);
    }
  });

  it('is of the task it was handed: a different task reading done is no business of the watch', () => {
    const next = followTask(NO_DONE, task({ id: 'next', state: 'done', stage: 3 }), 'handed');
    expect(next.watching).toBe(false); // the watch ends: its own task is not the one it sees
    expect(next.counter.count).toBe(0);
    const own = followTask(NO_DONE, task({ id: 'handed', state: 'done', stage: 3 }), 'handed');
    expect(own.counter.count).toBe(1);
  });

  it('a task that was not found (404) or a look that failed stops the watch quietly, counting nothing', () => {
    const gone = followTask(NO_DONE, null);
    expect(gone.watching).toBe(false);
    expect(gone.counter).toBe(NO_DONE);
  });
});

describe('watchTaskStatus (the background watch reads one task’s status and nothing else)', () => {
  const handed = { source: 'exp:e1', taskId: 'T1' };

  /** A watch over a scripted list of statuses (the last repeats), with the real stop rule and counter. */
  function scripted(statuses: Array<LabTask | 'unknown'>) {
    const reads: Array<[string, string]> = [];
    let counter = NO_DONE;
    let ended = 0;
    let asked = 0;
    const stop = watchTaskStatus(handed, {
      read: async (source, taskId) => {
        reads.push([source, taskId]);
        const next = statuses[Math.min(asked++, statuses.length - 1)];
        if (next === 'unknown') throw new Error('404: unknown task');
        return next;
      },
      seen: (status) => {
        const step = followTask(counter, status, handed.taskId);
        counter = step.counter;
        return step.watching;
      },
      end: () => {
        ended += 1;
      },
    });
    return { reads, stop, count: () => counter.count, ended: () => ended };
  }

  const running = task({ id: 'T1', state: 'running', stage: 1 });
  const done = task({ id: 'T1', state: 'done', stage: 3 });

  afterEach(() => vi.useRealTimers());

  it('reads the handed task every poll while it runs, then notes the one done and stops', async () => {
    vi.useFakeTimers();
    const w = scripted([running, running, done]);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 2 + 10);
    expect(w.reads).toHaveLength(2);
    expect(w.count()).toBe(0);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS);
    expect(w.reads).toHaveLength(3);
    expect(w.count()).toBe(1);
    expect(w.ended()).toBe(1);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 5); // nothing more is asked once it ended
    expect(w.reads).toHaveLength(3);
    for (const read of w.reads) expect(read).toEqual(['exp:e1', 'T1']); // only ever the handed task, only its status
  });

  it('never follows the key’s next task: another id ends the watch and counts nothing', async () => {
    vi.useFakeTimers();
    const w = scripted([running, task({ id: 'T2', state: 'done', stage: 3 })]);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 4);
    expect(w.reads).toHaveLength(2);
    expect(w.count()).toBe(0);
    expect(w.ended()).toBe(1);
  });

  it('a task that ended cancelled or failed stops the watch and counts nothing', async () => {
    vi.useFakeTimers();
    for (const state of ['cancelled', 'failed'] as const) {
      const w = scripted([running, task({ id: 'T1', state, stage: 1 })]);
      await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 4);
      expect(w.reads, state).toHaveLength(2);
      expect(w.count(), state).toBe(0);
      expect(w.ended(), state).toBe(1);
    }
  });

  it('an unknown task (404) or a failed read ends it quietly, counting nothing', async () => {
    vi.useFakeTimers();
    const w = scripted([running, 'unknown']);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 4);
    expect(w.reads).toHaveLength(2);
    expect(w.count()).toBe(0);
    expect(w.ended()).toBe(1);
  });

  it('stopping it clears its timer, and a read that lands after the stop is ignored', async () => {
    vi.useFakeTimers();
    const early = scripted([running]);
    early.stop();
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 3);
    expect(early.reads).toHaveLength(0);
    let answer: (status: LabTask) => void = () => undefined;
    const seen: Array<LabTask | null> = [];
    let ended = 0;
    const stop = watchTaskStatus(handed, {
      read: () => new Promise<LabTask>((resolve) => (answer = resolve)), // held: the read is in flight
      seen: (status) => {
        seen.push(status);
        return true;
      },
      end: () => {
        ended += 1;
      },
    });
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS); // the first read is issued
    stop(); // ... and answered after the stop
    answer(done);
    await vi.advanceTimersByTimeAsync(TASK_POLL_MS * 3);
    expect(seen).toEqual([]);
    expect(ended).toBe(0);
  });
});
