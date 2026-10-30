// What the Lab outside the importance tabs reads of the importance task. The Robustness tab and the rail's candidate card
// take B's axes from the finished importance, so when the task finishes they must ask again, whichever tab the operator
// was on. This hook lives above the tabs (in `useLabQuery`, which the page owns) for that reason:
// - `importanceDone` counts the importance tasks seen finished (`noteDone`); every answer a tab gets is told to `noteTask`,
//   and the readers add the count to the mark of their ask.
// - A tab that is left while its task still runs polls no more (its timer is its answer's), so it hands that task to
//   `watchTask`. The watch is bound to the task it was handed (its id) and reads the task's status from the read-only status
//   route (Ruling P21) every `TASK_POLL_MS` until the task is no longer queued or running (`followTask`). It asks no view:
//   a view's poll requests a task, and on a running experiment a poll at a new chunk would queue another, so leaving a tab
//   would chain importance tasks beside the job. It therefore creates no work, never follows the key's next task, and a task
//   the worker does not know (a 404) ends it quietly. A watch belongs to the source it was handed from and is dropped when
//   the Lab opens another.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { LabTask } from '../results';
import { followTask, NO_DONE, noteDone, sameWatch, watchTaskStatus, type DoneCounter, type TaskWatch } from './labTask';

/** `source` is the open source once it opened, else null. */
export function useTaskWatch(source: string | null) {
  const counter = useRef<DoneCounter>(NO_DONE);
  const [count, setCount] = useState(0);
  const [watch, setWatch] = useState<TaskWatch | null>(null);
  const apply = useCallback((next: DoneCounter) => {
    if (next === counter.current) return; // nothing was news: no render
    counter.current = next;
    setCount(next.count);
  }, []);
  const noteTask = useCallback((task: LabTask | null) => apply(noteDone(counter.current, task)), [apply]);
  const watchTask = useCallback((next: TaskWatch | null) => setWatch(next), []);

  const following = sameWatch(watch, source);
  useEffect(() => {
    if (!following || watch === null) return;
    // A 404 (the worker knows no such task) or a failed read ends the watch; the readers ask again on their own marks.
    return watchTaskStatus(watch, {
      read: api.labTaskStatus,
      seen: (task) => {
        const step = followTask(counter.current, task, watch.taskId);
        apply(step.counter);
        return step.watching;
      },
      end: () => setWatch(null),
    });
    // The handed task and the source stand for the watch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [following, watch?.source, watch?.taskId, apply]);

  // A watch the Lab has moved away from (another source) is of no use.
  useEffect(() => {
    if (watch !== null && !following) setWatch(null);
  }, [watch, following]);

  return { importanceDone: count, noteTask, watchTask };
}
