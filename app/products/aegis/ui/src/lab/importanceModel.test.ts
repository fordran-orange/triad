import { describe, expect, it } from 'vitest';
import type { LabImportance } from '../results';
import { CAVEAT_TEXT, importanceResult, IMPORTANCE_CONSTANTS, parameterStatus, task } from './analyticsFixtures';
import {
  availabilityText,
  axisMax,
  caveatOf,
  constantsLine,
  IMPORTANCE_CAVEAT,
  importanceRows,
  marksText,
  partialLabel,
  sampleLine,
  stateNotice,
  statusKind,
} from './importanceModel';

const view = (over: Partial<LabImportance> = {}): LabImportance => ({ task: task(), reason: null, snapshot_label: null, importance: null, ...over });

describe('the order of the rows (unresolved last, the rest by share)', () => {
  it('ranks the Measured parameters by their share and puts Insufficient coverage last, whatever its share', () => {
    // Shares: ema 0.10, sma 0.45, stop 0.02, take 0.30 — but take has insufficient coverage.
    const rows = importanceRows(importanceResult());
    expect(rows.map((r) => r.path)).toEqual(['sma.length', 'ema.length', 'stop_loss_pct', 'take_profit_pct']);
    expect(rows.map((r) => r.index)).toEqual([0, 1, 2, 3]);
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3, null]);
    expect(rows.map((r) => r.resolved)).toEqual([true, true, true, false]);
    expect(rows.map((r) => r.paramIndex)).toEqual([1, 0, 2, 3]);
  });

  it('ranks by the share as sent: a share below zero ranks below zero, not tied with it', () => {
    const base = importanceResult();
    const result = importanceResult({ fine: { ...base.fine, S: [-0.004, 0.0, 0.0, 0.3] } });
    // ema −0.004 < sma 0 = stop 0: sma and stop tie, the lower parameter index first, ema after them.
    expect(importanceRows(result).map((r) => r.path)).toEqual(['sma.length', 'stop_loss_pct', 'ema.length', 'take_profit_pct']);
  });

  it('a Measured parameter whose share is undefined ranks after the defined ones, before the unresolved', () => {
    const base = importanceResult();
    const result = importanceResult({ fine: { ...base.fine, S: [null, 0.45, 0.02, 0.3] } });
    expect(importanceRows(result).map((r) => r.path)).toEqual(['sma.length', 'stop_loss_pct', 'ema.length', 'take_profit_pct']);
  });

  it('several unresolved parameters keep the path order they came in', () => {
    const base = importanceResult();
    const result = importanceResult({
      labels: ['Insufficient coverage', 'Measured', 'Insufficient coverage', 'Insufficient coverage'],
      statuses: [
        parameterStatus('sma.length', 'Active · detected'),
        parameterStatus('ema.length', 'Insufficient coverage · unresolved'),
        parameterStatus('stop_loss_pct', 'Insufficient coverage · unresolved'),
        parameterStatus('take_profit_pct', 'Insufficient coverage · unresolved'),
      ],
      fine: { ...base.fine, S: [0.9, 0.1, 0.8, 0.7] },
    });
    expect(importanceRows(result).map((r) => r.path)).toEqual(['sma.length', 'ema.length', 'stop_loss_pct', 'take_profit_pct']);
  });
});

describe('the labels, statuses and marks of a row (read from the response, never recomputed)', () => {
  const rows = importanceRows(importanceResult());
  const byPath = Object.fromEntries(rows.map((r) => [r.path, r]));

  it('prints the coverage label and the status as the server sends them', () => {
    expect(byPath['sma.length'].label).toBe('Measured');
    expect(byPath['sma.length'].status).toBe('Investigate · interaction not ruled out');
    expect(byPath['take_profit_pct'].label).toBe('Insufficient coverage');
    expect(byPath['take_profit_pct'].status).toBe('Insufficient coverage · unresolved');
    expect(byPath['ema.length'].status).toBe('Active · detected');
    expect(byPath['sma.length'].reason).toBe('reason of sma.length');
  });

  it('shows the failing text on a parameter that is not proposable, and nothing on one that is', () => {
    expect(byPath['sma.length'].failing).toBe('failing of sma.length');
    const proposable = importanceRows(importanceResult({ statuses: [parameterStatus('ema.length', 'Deprioritized · proposable'), ...importanceResult().statuses.slice(1)] }));
    expect(proposable.find((r) => r.path === 'ema.length')?.failing).toBeNull();
    expect(proposable.find((r) => r.path === 'ema.length')?.proposable).toBe(true);
  });

  it('carries the flags of the status verbatim', () => {
    const flagged = importanceRows(importanceResult({ statuses: [parameterStatus('ema.length', 'Active · detected', { flags: ['credit shared with sma.length'] }), ...importanceResult().statuses.slice(1)] }));
    expect(flagged.find((r) => r.path === 'ema.length')?.flags).toEqual(['credit shared with sma.length']);
  });

  it('maps a status to a style family by its words alone', () => {
    expect(statusKind('Active · detected')).toBe('active');
    expect(statusKind('Active · not detected')).toBe('active');
    expect(statusKind('Investigate · period-dependent')).toBe('investigate');
    expect(statusKind('Investigate · interaction not ruled out')).toBe('investigate');
    expect(statusKind('Investigate · three-way effect not ruled out')).toBe('investigate');
    expect(statusKind('Deprioritized · proposable')).toBe('deprioritized');
    expect(statusKind('Insufficient coverage · unresolved')).toBe('unresolved');
    expect(statusKind('')).toBe('unresolved'); // no status sent: nothing is claimed
  });

  it('a parameter with no status row gets an empty status, not an invented one', () => {
    const rows2 = importanceRows(importanceResult({ statuses: [] }));
    expect(rows2).toHaveLength(4);
    expect(rows2.every((r) => r.status === '' && r.failing === null && r.flags.length === 0)).toBe(true);
  });

  it('the three marks of a Measured row sit side by side: whisker, block range and floor tick', () => {
    const sma = byPath['sma.length'].marks;
    expect(sma).toEqual({ share: 0.45, lo: 0.38, hi: 0.52, floor: 0.03, tick: 0.02, block: [0.3, 0.6] });
  });

  it('an unresolved row has no marks and no numbers: a share on too little data is not shown', () => {
    expect(byPath['take_profit_pct'].marks).toBeNull();
    expect(byPath['take_profit_pct'].text).toBe('');
  });

  it('a block range of null (K = 0 or not measured) stays null, never zero', () => {
    const none = importanceRows(importanceResult({ block_range: null }));
    expect(none.every((r) => r.marks === null || r.marks.block === null)).toBe(true);
  });

  it('keeps the stored share as sent, and clamps only the text', () => {
    const base = importanceResult();
    const rows3 = importanceRows(importanceResult({ fine: { ...base.fine, S: [-0.004, 0.45, 0.02, 0.3], lo: { ...base.fine.lo, S: [-0.03, 0.38, -0.01, 0.2] } } }));
    const ema = rows3.find((r) => r.path === 'ema.length')!;
    expect(ema.marks?.share).toBe(-0.004);
    expect(ema.marks?.lo).toBe(-0.03);
    expect(ema.text).toContain('share 0.0%');
    expect(ema.text).not.toContain('-');
  });
});

describe('the text of a row', () => {
  it('prints the share, the interval with its coverage, the block range and both floors', () => {
    const text = marksText({ share: 0.45, lo: 0.38, hi: 0.52, floor: 0.03, tick: 0.02, block: [0.3, 0.6] }, IMPORTANCE_CONSTANTS);
    expect(text).toBe('share 45.0% · 90 % interval 38.0%–52.0% · block range 30.0%–60.0% · detection floor 3.0% · null 95th percentile 2.0%');
  });

  it('says plainly what was not measured', () => {
    const text = marksText({ share: 0.1, lo: null, hi: null, floor: null, tick: null, block: null }, IMPORTANCE_CONSTANTS);
    expect(text).toBe('share 10.0% · no interval · block range not measured · no detection floor');
  });

  it('reads the interval and the floor quantile from the constants of the response', () => {
    const marks = { share: 0.1, lo: 0.05, hi: 0.2, floor: 0.02, tick: 0.01, block: null };
    expect(marksText(marks, { ...IMPORTANCE_CONSTANTS, INTERVAL: 0.8, FLOOR_QUANTILE: 0.99 })).toContain('80 % interval');
    expect(marksText(marks, { ...IMPORTANCE_CONSTANTS, INTERVAL: 0.8, FLOOR_QUANTILE: 0.99 })).toContain('null 99th percentile');
  });
});

describe('the shared axis of the marks', () => {
  it('reaches the largest mark of the resolved rows and rounds to a tick', () => {
    expect(axisMax(importanceRows(importanceResult()))).toBeCloseTo(0.6, 12); // the sma block range ends at 0.6
  });

  it('rounds up, never down past a mark', () => {
    const base = importanceResult();
    const result = importanceResult({ fine: { ...base.fine, hi: { ...base.fine.hi, S: [0.15, 0.55, 0.05, 0.4] } }, block_range: [[0, 0.1], [0.3, 0.4], [0, 0.04], null] });
    expect(axisMax(importanceRows(result))).toBeGreaterThanOrEqual(0.55);
    expect(axisMax(importanceRows(result))).toBeCloseTo(0.6, 12);
  });

  it('ignores an unresolved row, and falls back to a whole share when nothing is drawn', () => {
    const base = importanceResult();
    const huge = importanceResult({ fine: { ...base.fine, hi: { ...base.fine.hi, S: [0.15, 0.52, 0.05, 5] } } });
    expect(axisMax(importanceRows(huge))).toBeLessThan(1);
    expect(axisMax([])).toBe(1);
  });
});

describe('what the panel says around the rows', () => {
  it('the caveat is printed verbatim, from the response, and is the spec text when none came', () => {
    const spec = 'conditional on these ranges, this data, this sampler and this partition; a share is evidence about where exploration pays, not proof that a parameter is irrelevant';
    expect(CAVEAT_TEXT).toBe(spec);
    expect(IMPORTANCE_CAVEAT).toBe(spec);
    expect(caveatOf(importanceResult())).toBe(spec);
    expect(caveatOf(importanceResult({ caveat: 'the server may reword it' }))).toBe('the server may reword it');
    expect(caveatOf(null)).toBe(spec); // the caveat is always on the panel, a result or not
  });

  it('a partial stage is labelled partial, a whole one is not', () => {
    expect(partialLabel(importanceResult())).toBe('PARTIAL · stage 2 of 3');
    expect(partialLabel(importanceResult({ partial: false, stage: 3 }))).toBeNull();
  });

  it('the availability line is the server message verbatim, else says the rule is available', () => {
    expect(availabilityText(importanceResult())).toBe('empirical deprioritization unavailable: inputs are not a product design (12 % of the grid is invalid)');
    const base = importanceResult();
    const available = importanceResult({ availability: { ...base.availability, available: true, reason: null, reasons: [], hint: null, message: null } });
    expect(availabilityText(available)).toBe('empirical deprioritization available');
  });

  it('the constants line is read from the response and changes with it', () => {
    const line = constantsLine(IMPORTANCE_CONSTANTS);
    expect(line).toContain('θ_min 0.01');
    expect(line).toContain('90 % intervals');
    expect(line).toContain('bootstrap B = 200');
    expect(line).toContain('permutation P = 200');
    expect(line).toContain('≥ 30 × its values');
    expect(line).toContain('≥ 20 rows per value');
    expect(line).toContain('V > 0.3');
    const other = constantsLine({ ...IMPORTANCE_CONSTANTS, THETA_MIN: 0.02, BOOTSTRAP_B: 500, ALIAS_V: 0.4 });
    expect(other).toContain('θ_min 0.02');
    expect(other).toContain('B = 500');
    expect(other).toContain('V > 0.4');
  });

  it('states a subsample, and says nothing when every row was read', () => {
    expect(sampleLine(importanceResult({ sampled_from: 120000 }))).toBe('bootstrap and null read a seeded subsample of 50,000 of 120,000 rows');
    expect(sampleLine(importanceResult())).toBe('');
  });
});

describe('the notice for a view with no stage yet', () => {
  it('shows nothing once a stage was delivered', () => {
    expect(stateNotice(view({ importance: importanceResult() }))).toBeNull();
  });

  it('prints the reason verbatim when no task was requested (a grid job still running)', () => {
    const reason = 'importance is available when the optimization finishes';
    expect(stateNotice(view({ task: null, reason }))).toEqual({ kind: 'reason', text: reason });
  });

  it('waits for the first stage while the task runs or queues', () => {
    expect(stateNotice(view({ task: task({ state: 'running', stage: 0 }) }))).toEqual({ kind: 'waiting', text: 'waiting for stage 1 of 3' });
    expect(stateNotice(view({ task: task({ state: 'queued', stage: 0 }) }))?.kind).toBe('waiting');
  });

  it('says a stopped task delivered nothing, and an unrequested view was not asked', () => {
    expect(stateNotice(view({ task: task({ state: 'cancelled', stage: 0 }) }))?.kind).toBe('stopped');
    expect(stateNotice(view({ task: task({ state: 'failed', stage: 0, error: 'boom' }) }))?.kind).toBe('stopped');
    expect(stateNotice(view({ task: null, reason: null }))?.kind).toBe('none');
  });
});
