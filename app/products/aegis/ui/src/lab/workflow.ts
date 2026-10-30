// The Variable Intelligence workflow strip: which of the six steps is live, done or not yet available.
// Pure state, nothing React; the strip component renders what this returns.

export type StepState = 'live' | 'done' | 'disabled';

export interface WorkflowStep {
  key: 'define' | 'screen' | 'evaluate' | 'propose' | 'approve' | 'monitor';
  label: string;
  state: StepState;
  /** Why a disabled step is not available yet; absent on a live or done step. */
  reason?: string;
}

/** The six steps' labels, in strip order. */
export const WORKFLOW_LABELS: Readonly<Record<WorkflowStep['key'], string>> = Object.freeze({
  define: 'Define variables',
  screen: 'Run screening',
  evaluate: 'Evaluate importance and interactions',
  propose: 'Review search-space proposal',
  approve: 'Approve large sweep',
  monitor: 'Monitor results',
});

/** Phase 1: only Define works. It is done once an experiment exists, live until then. Every later step stays
 *  disabled, with the phase it arrives in as its reason. `hasReport` is accepted now so the signature does not
 *  change when the Phase 3 screening report starts to move steps. Returns new objects on every call. */
export function workflowSteps(input: { hasExperiment: boolean; hasReport: boolean }): WorkflowStep[] {
  const step = (key: WorkflowStep['key'], state: StepState, reason?: string): WorkflowStep =>
    reason === undefined
      ? { key, label: WORKFLOW_LABELS[key], state }
      : { key, label: WORKFLOW_LABELS[key], state, reason };
  const afterPhase4 = 'available after Phase 4';
  return [
    step('define', input.hasExperiment ? 'done' : 'live'),
    step('screen', 'disabled', 'screening blocks are on the experiment planner; this step arrives in Phase 4'),
    step('evaluate', 'disabled', afterPhase4),
    step('propose', 'disabled', afterPhase4),
    step('approve', 'disabled', afterPhase4),
    step('monitor', 'disabled', 'the Run Monitor arrives in Phase 5'),
  ];
}
