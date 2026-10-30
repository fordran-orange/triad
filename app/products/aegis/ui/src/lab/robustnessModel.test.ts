import { describe, expect, it } from 'vitest';
import { rankings } from './analyticsFixtures';
import { objectiveText } from './LabKpiStrip';
import { axesLine, classTone, rankingRows, robustSummary, toleranceLine } from './robustnessModel';

describe('rankingRows (the peak list and the robust list, side by side)', () => {
  const r = rankings();

  it('lists the robust rows in the server order, each with its value beside its classification', () => {
    const rows = rankingRows(r, 'robust', 'mar');
    expect(rows.map((x) => x.trialId)).toEqual(['exp:e1#710', 'exp:e1#223']);
    expect(rows.map((x) => x.place)).toEqual([1, 2]);
    expect(rows[0]).toMatchObject({ trialLabel: 'trial 710', value: 5.9, valueText: objectiveText('mar', 5.9), classification: 'stable local', rankedBy: 'A', state: 'resolved' });
  });

  it('lists the peak rows in their own order, from the peak list', () => {
    const rows = rankingRows(r, 'peak', 'mar');
    expect(rows.map((x) => x.trialId)).toEqual(['exp:e1#223', 'exp:e1#710']);
    expect(rows[0].value).toBe(6.7);
  });

  it('an unresolved row prints its reason verbatim in place of a classification, and is placed by neither', () => {
    const row = rankingRows(r, 'robust', 'mar')[1];
    expect(row.state).toBe('unresolved');
    expect(row.classification).toBe('untested surroundings (n 3 of 7)');
    expect(row.rankedBy).toBeNull();
    expect(classTone(row.state, null)).toBe('unresolved');
  });

  it('marks the stable candidate where it is listed', () => {
    expect(rankingRows(r, 'robust', 'mar').map((x) => x.stable)).toEqual([true, false]);
    expect(rankingRows(r, 'peak', 'mar').map((x) => x.stable)).toEqual([false, true]);
    expect(rankingRows(rankings({ stable: null, stable_reason: 'none' }), 'robust', 'mar').some((x) => x.stable)).toBe(false);
  });

  it('a stable cell with a lower value can rank above a higher unresolved one, and the values show it', () => {
    const rows = rankingRows(r, 'robust', 'mar');
    expect(rows[0].value).toBeLessThan(rows[1].value);
    expect(rows[0].state).toBe('resolved');
  });

  it('prints a negated metric in real units: the oriented −0.12 is a drawdown of 0.12', () => {
    const dd = rankings({
      ranked: [{ trial_id: 'exp:e1#4', value: -0.12, ranked_by: 'A', classification: 'mixed', reason: null }],
      peak_ranked: [{ trial_id: 'exp:e1#9', value: -0.05, ranked_by: null, classification: null, reason: 'untested surroundings (n 1 of 7)' }],
    });
    expect(rankingRows(dd, 'robust', 'max_drawdown')[0].value).toBe(0.12);
    expect(rankingRows(dd, 'robust', 'max_drawdown')[0].valueText).toBe(objectiveText('max_drawdown', 0.12));
    expect(rankingRows(dd, 'peak', 'max_drawdown')[0].value).toBe(0.05);
    // The same oriented numbers on a metric that is not negated are printed as they are.
    expect(rankingRows(dd, 'robust', 'net_pnl')[0].value).toBe(-0.12);
  });

  it('a zero is a plain zero, never negative zero', () => {
    const zero = rankings({ ranked: [{ trial_id: 'exp:e1#4', value: 0, ranked_by: 'A', classification: 'mixed', reason: null }] });
    expect(Object.is(rankingRows(zero, 'robust', 'max_drawdown')[0].value, 0)).toBe(true);
  });

  it('a row that loses money is flagged, whatever its place; a drawdown never is', () => {
    const loss = rankings({ ranked: [{ trial_id: 'exp:e1#4', value: -5, ranked_by: 'A', classification: 'stable local', reason: null }] });
    expect(rankingRows(loss, 'robust', 'net_pnl')[0].loses).toBe(true);
    const zero = rankings({ ranked: [{ trial_id: 'exp:e1#4', value: 0, ranked_by: 'A', classification: 'stable local', reason: null }] });
    expect(rankingRows(zero, 'robust', 'net_pnl')[0].loses).toBe(false);
    const dd = rankings({ ranked: [{ trial_id: 'exp:e1#4', value: -0.5, ranked_by: 'A', classification: 'stable local', reason: null }] });
    expect(rankingRows(dd, 'robust', 'max_drawdown')[0].loses).toBe(false);
    const factor = rankings({ ranked: [{ trial_id: 'exp:e1#4', value: 0.8, ranked_by: 'A', classification: 'stable local', reason: null }] });
    expect(rankingRows(factor, 'robust', 'profit_factor')[0].loses).toBe(true); // a profit factor under 1 loses money
  });

  it('classTone sorts the classifications into four families by their words', () => {
    expect(classTone('resolved', 'stable local')).toBe('stable');
    expect(classTone('resolved', 'stable region')).toBe('stable');
    expect(classTone('resolved', 'mixed')).toBe('mixed');
    expect(classTone('resolved', 'isolated peak')).toBe('weak');
    expect(classTone('resolved', 'unstable region')).toBe('weak');
    expect(classTone('unresolved', null)).toBe('unresolved');
  });
});

describe('robustSummary (the disagreement named, the stable candidate, or why there is none)', () => {
  it('says the two rankings disagree and names the first of each', () => {
    const s = robustSummary(rankings(), 'mar');
    expect(s.disagree).toBe(true);
    expect(s.agreement).toBe('Peak and robust disagree: the peak is trial 223, the most robust is trial 710.');
  });

  it('says they agree when the first of each is one trial', () => {
    const s = robustSummary(rankings({ disagree: false, peak: ['exp:e1#710', 'exp:e1#223'] }), 'mar');
    expect(s.disagree).toBe(false);
    expect(s.agreement).toBe('Peak and robust agree on trial 710.');
  });

  it('says nothing when there is nothing to rank', () => {
    expect(robustSummary(rankings({ peak: [], robust: [], disagree: false, ranked: [], peak_ranked: [], stable: null, stable_reason: null }), 'mar').agreement).toBe('');
  });

  it('names the stable candidate with its classification and value', () => {
    const s = robustSummary(rankings(), 'mar');
    expect(s.stable).toBe(`Stable candidate: trial 710 · stable local · ${objectiveText('mar', 5.9)}`);
    expect(s.stableId).toBe('exp:e1#710');
  });

  it('prints the stable reason verbatim when there is no stable candidate', () => {
    const reason = 'the most robust candidates are tied on net_pnl';
    const s = robustSummary(rankings({ stable: null, stable_reason: reason }), 'net_pnl');
    expect(s.stable).toBe(`No stable candidate: ${reason}`);
    expect(s.stableId).toBeNull();
    expect(robustSummary(rankings({ stable: null, stable_reason: null }), 'net_pnl').stable).toBe('No stable candidate');
  });

  it('tolerates a stable candidate chosen from the pool but outside the rows listed', () => {
    const s = robustSummary(rankings({ stable: 'exp:e1#999', ranked: [], peak_ranked: [] }), 'mar');
    expect(s.stable).toBe('Stable candidate: trial 999 (outside the rows listed)');
    expect(s.stableId).toBe('exp:e1#999');
  });

  it('finds a stable candidate that is listed among the peak rows alone', () => {
    const peakOnly = rankings({ ranked: [], stable: 'exp:e1#710' });
    expect(robustSummary(peakOnly, 'mar').stable).toBe(`Stable candidate: trial 710 · stable local · ${objectiveText('mar', 5.9)}`);
  });

  it('prints the stable candidate’s value in real units', () => {
    const dd = rankings({
      stable: 'exp:e1#4',
      ranked: [{ trial_id: 'exp:e1#4', value: -0.12, ranked_by: 'A', classification: 'stable local', reason: null }],
      peak_ranked: [],
    });
    expect(robustSummary(dd, 'max_drawdown').stable).toContain(objectiveText('max_drawdown', 0.12));
  });
});

describe('the lines around the lists', () => {
  it('names B’s axes, or says B is not run without a finished importance result', () => {
    expect(axesLine(['ema.length', 'sma.length'])).toBe('B axes: ema.length, sma.length');
    expect(axesLine([])).toBe('B is not run: it needs a finished importance result for this snapshot');
  });

  it('prints the tolerance, with the label the server sends for a default', () => {
    expect(toleranceLine(0.15, null)).toBe('τ = tolerance 0.15 × (P90 − P10) of the metric');
    expect(toleranceLine(0.15, 'default tolerance 0.15')).toBe('τ = tolerance 0.15 × (P90 − P10) of the metric · default tolerance 0.15');
  });
});
