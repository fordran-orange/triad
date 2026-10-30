import type { LabTask } from '../results';
import { canRerun, isActive, taskLine } from './labTask';

/** The task line of the importance analysis with its controls: Cancel while the task is queued or running, and Run again
 *  only once it was cancelled or failed (during a pending cancel the state still reads `running`, so it is not offered
 *  then). Nothing when no task was requested: the panel then prints the server's reason. */
export function TaskBar({
  id,
  task,
  cancelling,
  error,
  onCancel,
  onRerun,
}: {
  id: string;
  task: LabTask | null;
  cancelling: boolean;
  error: string | null;
  onCancel: () => void;
  onRerun: () => void;
}) {
  if (task === null) return null;
  return (
    <div className="lab-task" id={id} data-state={task.state}>
      <span className="lab-task-line">{taskLine(task, Date.now())}</span>
      {isActive(task) && (
        <button type="button" className="btn lab-task-btn" id={`${id}-cancel`} disabled={cancelling} title="stops the whole importance analysis, which the Importance and Interaction tabs share" onClick={onCancel}>
          {cancelling ? 'Cancelling…' : 'Cancel'}
        </button>
      )}
      {canRerun(task) && (
        <button type="button" className="btn lab-task-btn" id={`${id}-rerun`} title="computes the importance again; nothing else ever restarts a stopped task" onClick={onRerun}>
          Run again
        </button>
      )}
      {error !== null && <span className="lab-error-text">Cancel failed: {error}</span>}
    </div>
  );
}
