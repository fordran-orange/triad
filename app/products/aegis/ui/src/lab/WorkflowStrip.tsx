import { workflowSteps } from './workflow';

const STATE_TEXT = { live: 'live', done: 'done', disabled: 'not yet available' } as const;

/** Screen H's six-step workflow, every step always visible; a step that is not available yet says why. */
export function WorkflowStrip({ hasExperiment, hasReport }: { hasExperiment: boolean; hasReport: boolean }) {
  const steps = workflowSteps({ hasExperiment, hasReport });
  return (
    <ol className="workflow-strip" id="workflow-strip" aria-label="Variable Intelligence workflow">
      {steps.map((step, i) => (
        <li
          key={step.key}
          className="workflow-step"
          data-key={step.key}
          data-state={step.state}
          aria-disabled={step.state === 'disabled' || undefined}
          title={step.state === 'disabled' ? step.reason : step.state === 'done' ? 'an experiment defines the variables' : 'define the variables with an experiment'}
        >
          <span className="workflow-index">{i + 1}</span> <span className="workflow-label">{step.label}</span> <span className="workflow-state">· {STATE_TEXT[step.state]}</span>
        </li>
      ))}
    </ol>
  );
}
