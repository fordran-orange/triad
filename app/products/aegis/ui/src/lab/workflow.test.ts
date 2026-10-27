import { describe, expect, it } from 'vitest';
import { WORKFLOW_LABELS, workflowSteps } from './workflow';

describe('WORKFLOW_LABELS', () => {
  it('names the six steps in the fixed order', () => {
    expect(Object.keys(WORKFLOW_LABELS)).toEqual(['define', 'screen', 'evaluate', 'propose', 'approve', 'monitor']);
    expect(WORKFLOW_LABELS).toEqual({
      define: 'Define variables',
      screen: 'Run screening',
      evaluate: 'Evaluate importance and interactions',
      propose: 'Review search-space proposal',
      approve: 'Approve large sweep',
      monitor: 'Monitor results',
    });
  });

  it('is frozen, so no caller can rename a step for everyone', () => {
    expect(Object.isFrozen(WORKFLOW_LABELS)).toBe(true);
  });
});

describe('workflowSteps', () => {
  it('returns exactly six steps in the fixed order, each carrying its label', () => {
    const steps = workflowSteps({ hasExperiment: false, hasReport: false });
    expect(steps.map((s) => s.key)).toEqual(['define', 'screen', 'evaluate', 'propose', 'approve', 'monitor']);
    for (const s of steps) expect(s.label).toBe(WORKFLOW_LABELS[s.key]);
  });

  it('with no experiment, makes Define live and every later step disabled with a Phase reason', () => {
    const steps = workflowSteps({ hasExperiment: false, hasReport: false });
    expect(steps[0]).toEqual({ key: 'define', label: 'Define variables', state: 'live' });
    for (const s of steps.slice(1)) {
      expect(s.state, s.key).toBe('disabled');
      expect(s.reason, s.key).toContain('Phase');
    }
  });

  it('with an experiment, marks Define done and leaves the rest disabled', () => {
    const steps = workflowSteps({ hasExperiment: true, hasReport: false });
    expect(steps[0].state).toBe('done');
    expect(steps[0].reason).toBeUndefined();
    for (const s of steps.slice(1)) expect(s.state, s.key).toBe('disabled');
  });

  it('gives each disabled step the phase it arrives in', () => {
    const reasons = Object.fromEntries(
      workflowSteps({ hasExperiment: true, hasReport: false }).map((s) => [s.key, s.reason]),
    );
    expect(reasons.screen).toBe('screening experiments arrive in Phase 3');
    expect(reasons.evaluate).toBe('available after Phase 4');
    expect(reasons.propose).toBe('available after Phase 4');
    expect(reasons.approve).toBe('available after Phase 4');
    expect(reasons.monitor).toBe('the Run Monitor arrives in Phase 5');
  });

  it('keeps every later step disabled in Phase 1 even when a report exists', () => {
    const steps = workflowSteps({ hasExperiment: true, hasReport: true });
    expect(steps[0].state).toBe('done');
    for (const s of steps.slice(1)) expect(s.state, s.key).toBe('disabled');
  });

  it('returns fresh objects on every call, so a caller that edits a step cannot change the next result', () => {
    const first = workflowSteps({ hasExperiment: false, hasReport: false });
    first[0].state = 'done';
    first[1].reason = 'changed';
    const second = workflowSteps({ hasExperiment: false, hasReport: false });
    expect(second).not.toBe(first);
    expect(second[0].state).toBe('live');
    expect(second[1].reason).toBe('screening experiments arrive in Phase 3');
  });
});
