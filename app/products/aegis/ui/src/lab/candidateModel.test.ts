import { describe, expect, it } from 'vitest';
import type { LabCandidateCard, LabTrial, LabTrialMetrics } from '../results';
import { candidateCard, categoryA, categoryB, categoryC, categoryD } from './analyticsFixtures';
import { candidateCardModel, coverageText, realQuartiles, realValue, rowFromTrial, trialLabel, type CardModel, type CategoryView } from './candidateModel';
import { objectiveText } from './metricRules';

const input = (view: CategoryView, label: string) => view.inputs.find((i) => i.label === label)?.text;
const category = (model: CardModel, name: 'A' | 'B' | 'C' | 'D') => model.categories.find((c) => c.name === name)!;

/** The four categories, resolved, for the all-tested case. */
function allResolved(): LabCandidateCard {
  return candidateCard({
    categories: {
      A: categoryA(),
      B: categoryB({ resolved: true, classification: 'stable region', reason: null }),
      C: categoryC({ resolved: true, classification: 'consistent', reason: null }),
      D: categoryD({ resolved: true, classification: 'holds', reason: null }),
    },
    tested: ['A', 'B', 'C', 'D'],
    unknown: [],
  });
}

describe('candidateCard.testedUnknown', () => {
  it('has the four categories in order, tested or unknown by what the server resolved', () => {
    const model = candidateCardModel(candidateCard());
    expect(model.categories.map((c) => c.name)).toEqual(['A', 'B', 'C', 'D']);
    expect(model.categories.map((c) => c.state)).toEqual(['resolved', 'unresolved', 'unresolved', 'unresolved']);
    expect(model.categories.map((c) => c.stateText)).toEqual(['tested', 'unknown', 'unknown', 'unknown']);
  });

  it('shows a classification verbatim when resolved and the reason verbatim when not', () => {
    const model = candidateCardModel(candidateCard());
    expect(category(model, 'A').verdict).toBe('stable local');
    expect(category(model, 'B').verdict).toBe('too few sampled trials in the region (n 12 of 30)');
    expect(category(model, 'C').verdict).toBe('no blocks or folds');
    expect(category(model, 'D').verdict).toBe('no replay yet (stage 2)');
  });

  it('every category can be tested: the verdicts are the classifications and every state is resolved', () => {
    const model = candidateCardModel(allResolved());
    expect(model.categories.map((c) => c.verdict)).toEqual(['stable local', 'stable region', 'consistent', 'holds']);
    expect(model.categories.every((c) => c.state === 'resolved' && c.stateText === 'tested')).toBe(true);
    expect(model.summary).toBe('Tested: A, B, C, D · Unknown: none');
  });

  it('every category can be unknown: each shows its own reason, and none is shown as tested', () => {
    const none = candidateCard({
      categories: {
        A: categoryA({ resolved: false, classification: null, reason: 'untested surroundings (coverage 0.25 of 0.5)' }),
        B: categoryB(),
        C: categoryC(),
        D: categoryD(),
      },
      tested: [],
      unknown: ['A', 'B', 'C', 'D'],
    });
    const model = candidateCardModel(none);
    expect(model.categories.map((c) => c.stateText)).toEqual(['unknown', 'unknown', 'unknown', 'unknown']);
    expect(category(model, 'A').verdict).toBe('untested surroundings (coverage 0.25 of 0.5)');
    expect(model.summary).toBe('Tested: none · Unknown: A, B, C, D');
  });

  it('lists the tested and the unknown as the server names them', () => {
    expect(candidateCardModel(candidateCard()).summary).toBe('Tested: A · Unknown: B, C, D');
  });

  it('the state of a category is the category’s own, not the summary lists’', () => {
    const odd = candidateCard({ tested: ['A', 'B'], unknown: ['C', 'D'] }); // the lists disagree with `resolved` on B
    expect(category(candidateCardModel(odd), 'B').state).toBe('unresolved');
  });

  it('has no score and no overall label: four categories, never summed', () => {
    const model = candidateCardModel(allResolved());
    const keys = [...Object.keys(model), ...model.categories.flatMap((c) => Object.keys(c))];
    for (const key of keys) expect(key, key).not.toMatch(/score|overall|total|grade|rating|rank|aggregate/i);
    expect(model.categories).toHaveLength(4);
  });
});

describe('what the card prints for C: the server’s words, and the diagnostic apart', () => {
  const diagnostic = (classification: 'consistent' | 'inconsistent' | null) => ({
    name: 'selection-period consistency',
    classification,
    reason: classification === null ? 'no block has a defined net P&L' : null,
    inputs: { full: null, block_figures: [], ratio_band: [0.5, 2] as [number, number], drawdown_factor: 1.5 },
  });

  it('without blocks C reads what the server sent', () => {
    expect(category(candidateCardModel(candidateCard()), 'C').verdict).toBe('no blocks or folds');
  });

  it('with blocks C reads what the server sent, unresolved · selection-period only', () => {
    const withBlocks = candidateCard({ categories: { ...candidateCard().categories, C: categoryC({ reason: 'unresolved · selection-period only' }) }, findings: [diagnostic('consistent')] });
    const model = candidateCardModel(withBlocks);
    expect(category(model, 'C').verdict).toBe('unresolved · selection-period only');
    expect(category(model, 'C').state).toBe('unresolved');
  });

  it('shows the selection-period finding beside C, named and labelled informational', () => {
    const withBlocks = candidateCard({ categories: { ...candidateCard().categories, C: categoryC({ reason: 'unresolved · selection-period only' }) }, findings: [diagnostic('consistent')] });
    const c = category(candidateCardModel(withBlocks), 'C');
    expect(c.findings).toHaveLength(1);
    expect(c.findings[0].name).toBe('selection-period consistency');
    expect(c.findings[0].verdict).toBe('consistent');
    expect(category(candidateCardModel(withBlocks), 'A').findings).toEqual([]);
  });

  it('a finding with no verdict prints its reason verbatim', () => {
    const c = category(candidateCardModel(candidateCard({ findings: [diagnostic(null)] })), 'C');
    expect(c.findings[0].verdict).toBe('no block has a defined net P&L');
  });

  it('changing the finding changes nothing about C itself', () => {
    const base = candidateCard({ categories: { ...candidateCard().categories, C: categoryC({ reason: 'unresolved · selection-period only' }) } });
    const a = category(candidateCardModel({ ...base, findings: [diagnostic('consistent')] }), 'C');
    const b = category(candidateCardModel({ ...base, findings: [diagnostic('inconsistent')] }), 'C');
    expect({ ...a, findings: [] }).toEqual({ ...b, findings: [] });
    expect(a.findings[0].verdict).not.toBe(b.findings[0].verdict);
  });

  it('prints the folds C needs and the blocks it was given', () => {
    const c = category(candidateCardModel(candidateCard()), 'C');
    expect(input(c, 'folds')).toBe('0 (needs 3, each with ≥ 30 trades)');
    expect(input(c, 'blocks')).toBe('0');
    expect(input(c, 'fold ratio')).toBe('within 0.5×–2× of the full range, drawdown ≤ 1.5×');
  });
});

describe('what the card prints for A and B', () => {
  it('A prints n and what it needs, coverage, P25, P75, IQR, τ and the valid basis', () => {
    const a = category(candidateCardModel(candidateCard()), 'A');
    expect(input(a, 'n')).toBe('7 (needs 7)');
    expect(input(a, 'coverage')).toBe('0.87 (needs 0.5)');
    expect(input(a, 'P25')).toBe(objectiveText('mar', 1.39));
    expect(input(a, 'P75')).toBe(objectiveText('mar', 1.73));
    expect(input(a, 'IQR')).toBe(objectiveText('mar', 0.34));
    expect(input(a, 'τ')).toBe(objectiveText('mar', 0.69));
    expect(input(a, 'valid basis')).toBe('the frame: 8 valid positions, none ruled out');
  });

  it('coverage is cut to two decimals, never rounded up to the threshold it missed', () => {
    expect(coverageText(0.496)).toBe('0.49');
    expect(coverageText(0.875)).toBe('0.87');
    expect(coverageText(0.29)).toBe('0.29');
    expect(coverageText(1)).toBe('1.00');
    expect(coverageText(0)).toBe('0.00');
    const near = candidateCard({ categories: { ...candidateCard().categories, A: categoryA({ inputs: { ...categoryA().inputs, coverage: 0.496 } }) } });
    expect(input(category(candidateCardModel(near), 'A'), 'coverage')).toBe('0.49 (needs 0.5)');
  });

  it('an undefined input prints a dash, never a number', () => {
    const empty = candidateCard({ categories: { ...candidateCard().categories, A: categoryA({ inputs: { ...categoryA().inputs, p25: null, p75: null, iqr: null } }) } });
    const a = category(candidateCardModel(empty), 'A');
    expect(input(a, 'P25')).toBe('—');
    expect(input(a, 'IQR')).toBe('—');
  });

  it('B prints the radius, n against its need, the density, and the region’s axes', () => {
    const b = category(candidateCardModel(candidateCard()), 'B');
    expect(input(b, 'radius')).toBe('0.15 of each axis range');
    expect(input(b, 'n')).toBe('12 (needs 30)');
    expect(input(b, 'density')).toBe('0.80× a uniform draw');
    expect(input(b, 'axes')).toBe('ema.length, sma.length');
  });

  it('B names the unresolved A beside its own result, and says nothing when A was resolved', () => {
    const sparse = candidateCard({ categories: { ...candidateCard().categories, B: categoryB({ inputs: { ...categoryB().inputs, a_unresolved: 'untested surroundings (coverage 0.25 of 0.5)' } }) } });
    const notes = category(candidateCardModel(sparse), 'B').notes;
    expect(notes).toContain('A unresolved · untested surroundings (coverage 0.25 of 0.5)');
    expect(category(candidateCardModel(candidateCard()), 'B').notes).toEqual([]);
    const nulled = candidateCard({ categories: { ...candidateCard().categories, B: categoryB({ inputs: { ...categoryB().inputs, a_unresolved: null } }) } });
    expect(category(candidateCardModel(nulled), 'B').notes).toEqual([]);
  });

  it('B with no density prints a dash for it', () => {
    const none = candidateCard({ categories: { ...candidateCard().categories, B: categoryB({ inputs: { ...categoryB().inputs, density: null } }) } });
    expect(input(category(candidateCardModel(none), 'B'), 'density')).toBe('—');
  });

  it('D says it has no scenario yet, and C and D keep their constants from the response', () => {
    const d = category(candidateCardModel(candidateCard()), 'D');
    expect(input(d, 'scenarios')).toBe('none yet');
    expect(input(d, 'holds when')).toBe('stressed net P&L ≥ 70% of base, drawdown ≤ 1.3×');
    const custom = candidateCard({ categories: { ...candidateCard().categories, D: categoryD({ inputs: { ...categoryD().inputs, stress_keep: 0.8, drawdown_factor: 1.2, scenarios: ['base', 'slippage×1.5'] } }) } });
    const d2 = category(candidateCardModel(custom), 'D');
    expect(input(d2, 'scenarios')).toBe('base, slippage×1.5');
    expect(input(d2, 'holds when')).toBe('stressed net P&L ≥ 80% of base, drawdown ≤ 1.2×');
  });
});

describe('a negated metric prints in real units (orientation −1)', () => {
  // max_drawdown is negated: the oriented value −0.15 is a real drawdown of 0.15; the oriented lower quartile −0.20 is
  // the real upper one (0.20), and the oriented upper quartile −0.10 the real lower one (0.10).
  const drawdown = candidateCard({
    metric: 'max_drawdown',
    orientation: -1,
    value: -0.15,
    tau: 0.05,
    categories: {
      A: categoryA({ inputs: { ...categoryA().inputs, orientation: -1, value: -0.15, p25: -0.2, p75: -0.1, iqr: 0.1, tau: 0.05, distance: 0.05 } }),
      B: categoryB({ inputs: { ...categoryB().inputs, orientation: -1, value: -0.15, p25: -0.25, p75: -0.08, iqr: 0.17, tau: 0.05 } }),
      C: categoryC(),
      D: categoryD(),
    },
  });
  const model = candidateCardModel(drawdown);

  it('the card’s value and band are real', () => {
    expect(model.value).toBe(objectiveText('max_drawdown', 0.15));
    expect(model.tau).toBe(objectiveText('max_drawdown', 0.05));
  });

  it('P25 and P75 swap places and change sign; IQR and τ keep theirs', () => {
    const a = category(model, 'A');
    expect(input(a, 'P25')).toBe(objectiveText('max_drawdown', 0.1));
    expect(input(a, 'P75')).toBe(objectiveText('max_drawdown', 0.2));
    expect(input(a, 'IQR')).toBe(objectiveText('max_drawdown', 0.1));
    expect(input(a, 'τ')).toBe(objectiveText('max_drawdown', 0.05));
    const b = category(model, 'B');
    expect(input(b, 'P25')).toBe(objectiveText('max_drawdown', 0.08));
    expect(input(b, 'P75')).toBe(objectiveText('max_drawdown', 0.25));
  });

  it('says which quartile the rule reads, so the swap is not a surprise', () => {
    expect(category(model, 'A').notes.join(' ')).toContain('lower is better');
    expect(category(candidateCardModel(candidateCard()), 'A').notes).toEqual([]);
  });

  it('realValue and realQuartiles convert and never return negative zero', () => {
    expect(realValue(-1, -0.15)).toBe(0.15);
    expect(realValue(1, 3)).toBe(3);
    expect(Object.is(realValue(-1, 0), 0)).toBe(true);
    expect(realValue(-1, null)).toBeNull();
    expect(realQuartiles(-1, -0.2, -0.1)).toEqual({ p25: 0.1, p75: 0.2 });
    expect(realQuartiles(1, 1.39, 1.73)).toEqual({ p25: 1.39, p75: 1.73 });
    expect(realQuartiles(-1, null, -0.1)).toEqual({ p25: 0.1, p75: null });
  });

});

describe('the header of the card', () => {
  it('names the trial, its value and the band, and the default tolerance’s label as sent', () => {
    const model = candidateCardModel(candidateCard());
    expect(model.trialLabel).toBe('trial 5');
    expect(model.value).toBe(objectiveText('mar', 1.26));
    expect(model.tolerance).toBe('0.15');
    expect(model.toleranceLabel).toBeNull();
    expect(candidateCardModel(candidateCard({ tolerance_label: 'default tolerance 0.15' })).toleranceLabel).toBe('default tolerance 0.15');
  });

  it('a candidate that loses money is flagged, and a drawdown never is', () => {
    expect(candidateCardModel(candidateCard({ metric: 'net_pnl', value: -5 })).valueLoses).toBe(true);
    expect(candidateCardModel(candidateCard({ metric: 'net_pnl', value: 0 })).valueLoses).toBe(false);
    expect(candidateCardModel(candidateCard({ metric: 'mar', value: 1.26 })).valueLoses).toBe(false);
    expect(candidateCardModel(candidateCard({ metric: 'max_drawdown', orientation: -1, value: -0.4 })).valueLoses).toBe(false);
  });

  it('trialLabel reads the number after the hash', () => {
    expect(trialLabel('exp:e1#5')).toBe('trial 5');
    expect(trialLabel('opt:j9#120')).toBe('trial 120');
    expect(trialLabel('odd')).toBe('odd');
  });
});

describe('rowFromTrial (a trial picked from a chart becomes the row the rail reads)', () => {
  const metrics = (net_pnl: number): LabTrialMetrics => ({
    net_pnl, net_return: null, cagr: null, max_drawdown: 0.1, mar: null, win_rate: null, expectancy: null, profit_factor: null, trade_count: 12, exposure: null, sharpe_trade: null, low_n: true,
  });
  const trial = (id: string, params: Record<string, number>): LabTrial => ({
    trial_id: id,
    trial_no: 7,
    cell: 7,
    params,
    pos: [],
    param_key: null,
    status: 'ok',
    attempt: 1,
    block: 0,
    pass: null,
    design: null,
    metrics: { combined: metrics(500), long: metrics(300), short: metrics(200) },
    elapsed_ms: null,
    engine: null,
    chunk: null,
    finished_at: null,
    identity: { inputs_key: null, strategy_hash: null },
  });

  it('an experiment’s trial carries every scope’s columns and its own parameter paths', () => {
    const row = rowFromTrial(trial('exp:e1#7', { 'indicators.ema.length': 20 }), 'exp', 'combined');
    expect(row.id).toBe('exp:e1#7');
    expect(row.label).toBe('trial 7');
    expect(row.params).toEqual({ 'indicators.ema.length': 20 });
    expect(row.values['combined.net_pnl']).toBe(500);
    expect(row.values['short.net_pnl']).toBe(200);
    expect(row.values['combined.low_n']).toBeUndefined(); // a flag, not a metric
    expect(row.values['combined.cagr']).toBeNull();
    expect(row.valid).toBeNull();
  });

  it('a grid job’s trial drops the side prefix and reads the side’s metrics by name', () => {
    const row = rowFromTrial(trial('opt:j1#7', { 'long_side.indicators.ema.length': 20 }), 'opt', 'long');
    expect(row.id).toBe('opt:j1#7');
    expect(row.label).toBe('#7');
    expect(row.params).toEqual({ 'indicators.ema.length': 20 });
    expect(row.values.net_pnl).toBe(300);
    expect(row.values['long.net_pnl']).toBeUndefined();
  });
});
