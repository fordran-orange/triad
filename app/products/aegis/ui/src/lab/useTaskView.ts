// The importance task's views (`importance`, `interactions`) behind one hook: the Phase 2 per-panel pattern (a view key,
// a sequence number so a newer ask owns the panel, the discard of an answer whose filter moved on) plus what a task adds
// (spec §9.4). While the computing task is queued or running the view is asked again every `TASK_POLL_MS`; once it is
// done, failed or cancelled the polling stops, and so it does on unmount and on a new source (the timer belongs to the
// answer for the view in hand). A poll never restarts a stopped task: only the operator's "Run again" sends `rerun`, and
// nothing else does. Cancel stops the whole analysis the two tabs share, not one tab's task.
//
// What the rest of the Lab reads of the task is told to `data` (`useLabQuery`'s `noteTask` and `watchTask`): every answer's
// task goes to the done counter that the Robustness tab and the rail's card re-ask on, and a tab left while the task still
// runs hands the task's id to a background watch, which reads that task's status (never a view) until it ends, so its
// finishing is seen with this tab gone and no work is created by leaving.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { LabEnvelope, LabTaskView } from '../results';
import { answered } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { cancelPending, isActive, pollDelay, pollStopped, type TaskWatch } from './labTask';
import type { LabQueryData, Stamped } from './useLabQuery';

export type TaskViewName = 'importance' | 'interactions';

/** An answered view and what it was asked for: the panel describes it until the next one lands. */
export interface TaskAnswer<T extends LabTaskView> {
  key: string;
  source: string;
  envelope: Stamped<LabEnvelope<T>>;
}

export function useTaskView<T extends LabTaskView>(data: LabQueryData, view: TaskViewName) {
  const lab = useLab();
  const { loaded, query, tick, noteTask, watchTask } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  // The importance ignores the filter (§7.3), but the store's filter is part of the key all the same: an answer that
  // lands after the filter moved is discarded by `query`, and the key moving is what asks again.
  const viewKey = source === null ? null : [view, source, lab.metric, filterHash(lab.filter)].join('|');

  const [retry, setRetry] = useState(0);
  const [poll, setPoll] = useState(0);
  const [answer, setAnswer] = useState<TaskAnswer<T> | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [stopAsk, setStopAsk] = useState<{ key: string; id: string } | null>(null);
  const [stopFailure, setStopFailure] = useState<{ key: string; message: string } | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  const rerun = useRef(false);

  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${tick}|${retry}|${poll}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null || source === null) return;
    const again = rerun.current; // the operator's "Run again" is consumed by the ask it started
    rerun.current = false;
    if (again) setRerunning(true);
    query<T>(view, again ? { rerun: true } : {})
      .then((envelope) => {
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        noteTask(envelope.task); // a task that finished is news to the readers of its result, whichever ask learned it
        if (mine !== seq.current) return; // a newer ask owns the view
        setAnswer({ key: viewKey, source, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setFailure({ key: viewKey, message: errorMessage(e) });
      })
      .finally(() => {
        if (again) setRerunning(false);
      });
    // The key stands for the view, the source, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry, poll]);

  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;

  // Poll while the computing task is active. The timer is the answer's: a new answer re-arms it, a new key or an unmount
  // clears it, and a task that has stopped (or none was requested) arms nothing.
  const delay = current === null ? null : pollDelay(current.envelope.task);
  useEffect(() => {
    if (delay === null) return;
    const timer = setTimeout(() => setPoll((n) => n + 1), delay);
    return () => clearTimeout(timer);
  }, [delay, current]);

  // A tab left while its task still runs hands the task's id to the background watch (and takes it back when it is opened
  // again), so the Robustness tab and the card learn that it finished. What is running is remembered as it is answered.
  const running = useRef<TaskWatch | null>(null);
  const task = current?.envelope.task ?? null;
  useEffect(() => {
    running.current = source !== null && task !== null && isActive(task) ? { source, taskId: task.id } : null;
  }, [source, task]);
  useEffect(() => {
    watchTask(null);
    return () => {
      if (running.current !== null) watchTask(running.current);
    };
  }, [watchTask]);

  const cancel = useCallback(async () => {
    if (task === null || source === null || viewKey === null) return;
    setStopAsk({ key: viewKey, id: task.id });
    setStopFailure(null);
    try {
      await api.labCancelTask(source, task.id);
    } catch (e) {
      setStopFailure({ key: viewKey, message: errorMessage(e) });
      setStopAsk(null);
      return;
    }
    setPoll((n) => n + 1); // ask again at once: the status reads `cancelled` from the task's next checkpoint
  }, [task, source, viewKey]);

  const runAgain = useCallback(() => {
    if (rerun.current) return; // one "Run again" at a time: a second click before the ask went out is not a second task
    rerun.current = true;
    setRetry((n) => n + 1);
  }, []);
  const retryAsk = useCallback(() => setRetry((n) => n + 1), []);

  return {
    source,
    viewKey,
    current,
    shown,
    error,
    /** What a failed poll adds: the polling stopped while the task the last answer showed may still run. */
    pollStopped: pollStopped(error, shown?.envelope.task ?? null),
    /** No answer for the view in hand yet (a refresh of the same key keeps its answer drawn and is not pending). */
    pending: loaded === null ? data.loading : viewKey !== null && error === null && current === null,
    retry: retryAsk,
    runAgain,
    /** The "Run again" ask is on its way: the button is not offered again until it is answered. */
    rerunning,
    cancel,
    /** A cancel was asked of this task under this key and it still reads queued or running: Run again is not offered then. */
    cancelling: cancelPending(stopAsk, viewKey, task),
    stopError: stopFailure !== null && stopFailure.key === viewKey ? stopFailure.message : null,
  };
}
