// The importance task's views (`importance`, `interactions`) behind one hook: the Phase 2 per-panel pattern (a view key,
// a sequence number so a newer ask owns the panel, the discard of an answer whose filter moved on) plus what a task adds
// (spec §9.4). While the computing task is queued or running the view is asked again every `TASK_POLL_MS`; once it is
// done, failed or cancelled the polling stops, and so it does on unmount and on a new source (the timer belongs to the
// answer for the view in hand). A poll never restarts a stopped task: only the operator's "Run again" sends `rerun`, and
// nothing else does. Cancel stops the whole analysis the two tabs share, not one tab's task.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { LabEnvelope, LabTaskView } from '../results';
import { answered } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { isActive, pollDelay } from './labTask';
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
  const { loaded, query, tick } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  // The importance ignores the filter (§7.3), but the store's filter is part of the key all the same: an answer that
  // lands after the filter moved is discarded by `query`, and the key moving is what asks again.
  const viewKey = source === null ? null : [view, source, lab.metric, filterHash(lab.filter)].join('|');

  const [retry, setRetry] = useState(0);
  const [poll, setPoll] = useState(0);
  const [answer, setAnswer] = useState<TaskAnswer<T> | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [stopping, setStopping] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
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
    query<T>(view, again ? { rerun: true } : {})
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the view
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setFailure({ key: viewKey, message: errorMessage(e) });
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

  const task = current?.envelope.task ?? null;
  const cancel = useCallback(async () => {
    if (task === null || source === null) return;
    setStopping(task.id);
    setStopError(null);
    try {
      await api.labCancelTask(source, task.id);
    } catch (e) {
      setStopError(errorMessage(e));
      setStopping(null);
      return;
    }
    setPoll((n) => n + 1); // ask again at once: the status reads `cancelled` from the task's next checkpoint
  }, [task, source]);

  const retryAsk = useCallback(() => setRetry((n) => n + 1), []);
  const runAgain = useCallback(() => {
    rerun.current = true;
    setRetry((n) => n + 1);
  }, []);

  return {
    source,
    viewKey,
    current,
    shown,
    error,
    /** No answer for the view in hand yet (a refresh of the same key keeps its answer drawn and is not pending). */
    pending: loaded === null ? data.loading : viewKey !== null && error === null && current === null,
    retry: retryAsk,
    runAgain,
    cancel,
    /** A cancel was asked and the task still reads queued or running: Run again is not offered then. */
    cancelling: stopping !== null && task !== null && task.id === stopping && isActive(task),
    stopError,
  };
}
