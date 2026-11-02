import { xState } from './labQuery';

/** An honest placeholder for a Lab panel or view a later phase builds: it names what is missing and when it
 *  arrives, and shows nothing that looks like data. */
export function NotBuilt({ what, phase }: { what: string; phase: number }) {
  return (
    <div className="not-built" role="note">
      {what}: arrives in Phase {phase} (plan §11)
    </div>
  );
}

/** A panel's X state (spec:390): the failed query's message and a Retry that re-issues that one query; the other
 *  panels are not touched. A worker's refusal passes no `onRetry`: asking again cannot change its answer, so it has the message
 *  alone. */
export function LabError({ message, onRetry, id }: { message: string; onRetry?: () => void; id?: string }) {
  const x = xState(message);
  return (
    <div className="lab-error" role="alert" id={id}>
      <span className="lab-error-text">{x.message}</span>
      {onRetry !== undefined && (
        <button type="button" className="btn lab-retry" onClick={onRetry}>
          {x.retryLabel}
        </button>
      )}
    </div>
  );
}
