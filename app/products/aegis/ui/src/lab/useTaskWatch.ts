// What the Lab outside the importance tabs reads of the importance task. The Robustness tab and the rail's candidate card
// take B's axes from the finished importance, so when the task finishes they must ask again, whichever tab the operator
// was on. This hook lives above the tabs (in `useLabQuery`, which the page owns) for that reason:
// - `importanceDone` counts the importance tasks seen finished (`noteDone`); every answer a tab gets is told to `noteTask`,
//   and the readers add the count to the mark of their ask.
// - A tab that is left while its task still runs polls no more (its timer is its answer's), so it hands the task to
//   `watchTask`. The watch asks the importance view every `TASK_POLL_MS` as the tab did, with no `rerun` (it never starts or
//   restarts anything), until the task has stopped, and tells each answer to the counter. It belongs to one source, metric
//   and scope: asking under another would request another task, so a watch the Lab has moved away from is dropped.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { LabTask } from '../results';
import { useLab } from './labState';
import { NO_DONE, noteDone, pollDelay, sameWatch, TASK_POLL_MS, type DoneCounter, type TaskWatch } from './labTask';

/** `look` asks the importance view once: its task, or undefined when the answer was discarded (the filter or the source moved
 *  on). `source` is the open source once it opened, else null. */
export function useTaskWatch(look: () => Promise<LabTask | null | undefined>, source: string | null) {
  const lab = useLab();
  const [done, setDone] = useState<DoneCounter>(NO_DONE);
  const [watch, setWatch] = useState<TaskWatch | null>(null);
  const noteTask = useCallback((task: LabTask | null) => setDone((counter) => noteDone(counter, task)), []);
  const watchTask = useCallback((next: TaskWatch | null) => setWatch(next), []);
  const lookRef = useRef(look);
  lookRef.current = look;

  const metric = lab.metric;
  const scope = lab.filter.scope;
  const following = sameWatch(watch, source === null ? null : { source, metric, scope });

  useEffect(() => {
    if (!following) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const again = () => {
      lookRef
        .current()
        .then((task) => {
          if (stopped) return;
          if (task !== undefined) noteTask(task);
          const delay = task === undefined ? TASK_POLL_MS : pollDelay(task);
          if (delay === null) setWatch(null);
          else timer = setTimeout(again, delay);
        })
        .catch(() => {
          if (!stopped) setWatch(null); // a failed look ends the watch: the readers ask again on their own marks
        });
    };
    timer = setTimeout(again, TASK_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [following, noteTask]);

  // A watch the Lab has moved away from (another source, metric or scope) is of no use.
  useEffect(() => {
    if (watch !== null && !following) setWatch(null);
  }, [watch, following]);

  return { importanceDone: done.count, noteTask, watchTask };
}
