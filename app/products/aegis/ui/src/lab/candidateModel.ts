// The candidate card's decisions (spec §7.6), nothing React and nothing drawn: a tested trial's four robustness
// categories as the rail prints them, side by side and never summed, each tested or unknown with its classification or
// its reason verbatim and the inputs that decided it. `CandidateCard` only renders what this returns. The orientation
// helpers at the top are the Robustness tab's and the Pareto panel's too: the worker sends A's and B's numbers and the
// rankings' values ORIENTED (higher is better, so `max_drawdown` is negated) and everything printed is converted back.
import { DASH, num, pct } from '../format';
import type { LabCandidateCard, LabCategoryName, LabFigures, LabFinding, LabNumber, LabTrial } from '../results';
import { lossTone, objectiveText } from './LabKpiStrip';
import type { LabScope } from './labStore';
import type { TrialRow } from './useLabSource';

/** Which way a metric reads: `max_drawdown` is the one metric where lower is better (the worker's `LOWER_IS_BETTER`).
 *  The card carries its own `orientation`; the rankings do not, so they read the asked metric's. */
export function orientationOf(metric: string): 1 | -1 {
  return metric === 'max_drawdown' ? -1 : 1;
}

/** An oriented value in the metric's real units (`orientation * value`); never negative zero, an undefined value stays
 *  undefined. */
export function realValue(orientation: 1 | -1, value: LabNumber): LabNumber {
  if (value === null) return null;
  const real = orientation * value;
  return real === 0 ? 0 : real;
}

/** The neighbours' quartiles in real units. Negating a metric reverses its order, so the oriented lower quartile is
 *  the real upper one: with `orientation` -1, P25 and P75 swap places as they change sign. */
export function realQuartiles(orientation: 1 | -1, p25: LabNumber, p75: LabNumber): { p25: LabNumber; p75: LabNumber } {
  return orientation === 1 ? { p25, p75 } : { p25: realValue(-1, p75), p75: realValue(-1, p25) };
}

/** `trial 5` for `exp:e1#5` (a grid job's `opt:j1#5` too); an id with no number after its `#` is kept as it is. */
export function trialLabel(id: string): string {
  const found = /#(\d+)$/.exec(id);
  return found ? `trial ${found[1]}` : id;
}

/** A coverage cut to two decimals, never rounded up: 0.496 prints 0.49, so it never reads as the 0.5 it missed (the
 *  worker's own reason texts do the same). */
export function coverageText(coverage: number): string {
  return (Math.floor(coverage * 100 + 1e-9) / 100).toFixed(2);
}

export interface CardInput {
  label: string;
  text: string;
}

/** An informational result beside a category (the blocks' `selection-period consistency`): never part of the category. */
export interface FindingView {
  name: string;
  verdict: string;
  lines: CardInput[];
}

export interface CategoryView {
  name: LabCategoryName;
  title: string;
  /** `resolved`: the server gave a classification; `unresolved`: it gave a reason. */
  state: 'resolved' | 'unresolved';
  /** `tested` for a resolved category, `unknown` for the rest. */
  stateText: 'tested' | 'unknown';
  /** The classification when resolved, else the reason, both as the server sent them. */
  verdict: string;
  inputs: CardInput[];
  notes: string[];
  /** Only C carries any. */
  findings: FindingView[];
}

export interface CardModel {
  trialId: string;
  trialLabel: string;
  /** The candidate's value and τ, in real units. */
  value: string;
  /** The value is below its metric's break-even: shown red, whatever its categories say. */
  valueLoses: boolean;
  tau: string;
  tolerance: string;
  toleranceLabel: string | null;
  /** `Tested: A · Unknown: B, C, D`, from the lists the server sent. */
  summary: string;
  /** Exactly four, A to D. */
  categories: CategoryView[];
}

const TITLES: Record<LabCategoryName, string> = {
  A: 'local parameter robustness',
  B: 'sampled-region robustness',
  C: 'temporal robustness',
  D: 'execution robustness',
};

const names = (list: readonly LabCategoryName[]) => (list.length === 0 ? 'none' : list.join(', '));

/** One evaluation's per-unit-time figures on one line. */
function figuresText(figures: LabFigures): string {
  return `${num(figures.net_pnl_per_1000_bars, 2)} net P&L per 1,000 bars · ${figures.trades} trades · max drawdown ${pct(figures.max_drawdown)}`;
}

const ratioText = (ratio: LabNumber) => (ratio === null ? DASH : num(ratio, 2));

function finding(f: LabFinding): FindingView {
  return {
    name: f.name,
    verdict: f.classification ?? f.reason ?? 'no verdict',
    lines: [
      ...(f.inputs.full ? [{ label: 'full range', text: figuresText(f.inputs.full) }] : []),
      ...f.inputs.block_figures.map((b) => ({ label: `block ${b.block}`, text: `${figuresText(b)} · ratio ${ratioText(b.ratio)}` })),
    ],
  };
}

/** A card as the rail prints it. Everything about a category comes from that category: the lists `tested` and
 *  `unknown` only feed the summary line, and the findings are shown beside C without touching it. */
export function candidateCardModel(card: LabCandidateCard): CardModel {
  const fmt = (value: LabNumber) => objectiveText(card.metric, value);
  const { A, B, C, D } = card.categories;
  const view = (c: { name: LabCategoryName; resolved: boolean; classification: string | null; reason: string | null }, inputs: CardInput[], notes: string[] = [], findings: FindingView[] = []): CategoryView => ({
    name: c.name,
    title: TITLES[c.name],
    state: c.resolved ? 'resolved' : 'unresolved',
    stateText: c.resolved ? 'tested' : 'unknown',
    verdict: c.classification ?? c.reason ?? '',
    inputs,
    notes,
    findings,
  });
  const reading = (orientation: 1 | -1) => (orientation === -1 ? ['lower is better: the rule reads the neighbours’ worse quartile, shown here as P75'] : []);

  const a = A.inputs;
  const qa = realQuartiles(a.orientation, a.p25, a.p75);
  const b = B.inputs;
  const qb = realQuartiles(b.orientation, b.p25, b.p75);
  const c = C.inputs;
  const d = D.inputs;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

  const categories = [
    view(
      A,
      [
        { label: 'n', text: `${a.n} (needs ${a.required_n})` },
        { label: 'coverage', text: `${coverageText(a.coverage)} (needs ${a.min_coverage})` },
        { label: 'P25', text: fmt(qa.p25) },
        { label: 'P75', text: fmt(qa.p75) },
        { label: 'IQR', text: fmt(a.iqr) },
        { label: 'τ', text: fmt(a.tau) },
        { label: 'reach', text: `${plural(a.r, 'step')} in at most ${plural(a.m, 'parameter')}` },
        { label: 'valid basis', text: a.valid_basis },
      ],
      reading(a.orientation),
    ),
    view(
      B,
      [
        { label: 'radius', text: `${b.radius} of each axis range` },
        { label: 'n', text: `${b.n} (needs ${b.min_n})` },
        { label: 'density', text: b.density === null ? DASH : `${b.density.toFixed(2)}× a uniform draw` },
        { label: 'axes', text: b.axes.length === 0 ? DASH : b.axes.join(', ') },
        { label: 'P25', text: fmt(qb.p25) },
        { label: 'P75', text: fmt(qb.p75) },
        { label: 'IQR', text: fmt(b.iqr) },
        { label: 'τ', text: fmt(b.tau) },
      ],
      [...(b.a_unresolved ? [`A unresolved · ${b.a_unresolved}`] : []), ...reading(b.orientation)],
    ),
    view(
      C,
      [
        { label: 'folds', text: `${c.folds} (needs ${c.folds_min}, each with ≥ ${c.fold_min_trades} trades)` },
        ...(c.blocks !== undefined ? [{ label: 'blocks', text: String(c.blocks) }] : []),
        { label: 'fold ratio', text: `within ${c.ratio_band[0]}×–${c.ratio_band[1]}× of the full range, drawdown ≤ ${c.drawdown_factor}×` },
        ...(c.full ? [{ label: 'full range', text: figuresText(c.full) }] : []),
        ...(c.fold_figures ?? []).map((f, k) => ({ label: `fold ${k + 1}`, text: `${figuresText(f)} · ratio ${ratioText(f.ratio)}` })),
      ],
      [],
      card.findings.map(finding),
    ),
    view(D, [
      { label: 'scenarios', text: d.scenarios.length === 0 ? 'none yet' : d.scenarios.join(', ') },
      { label: 'holds when', text: `stressed net P&L ≥ ${Math.round(d.stress_keep * 100)}% of base, drawdown ≤ ${d.drawdown_factor}×` },
      ...(d.base ? [{ label: 'base', text: figuresText(d.base) }] : []),
      ...(d.stressed ? [{ label: 'stressed', text: figuresText(d.stressed) }] : []),
    ]),
  ];
  return {
    trialId: card.trial_id,
    trialLabel: trialLabel(card.trial_id),
    value: fmt(realValue(card.orientation, card.value)),
    valueLoses: lossTone(card.metric, realValue(card.orientation, card.value)) === 'loss',
    tau: fmt(card.tau),
    tolerance: String(card.tolerance),
    toleranceLabel: card.tolerance_label,
    summary: `Tested: ${names(card.tested)} · Unknown: ${names(card.unknown)}`,
    categories,
  };
}

/** A trial picked from a chart as the row the rail's trial card reads: the parameters and every metric column. An
 *  experiment's row holds every scope as `<scope>.<metric>`; a grid job's, whose `/lab` paths carry its side, drops
 *  that prefix and holds the side's metrics by name (as `optRowFromLab` does). */
export function rowFromTrial(trial: LabTrial, kind: 'exp' | 'opt', scope: LabScope): TrialRow {
  const metricsOf = (s: LabScope) => Object.entries(trial.metrics[s]).filter(([name]) => name !== 'low_n') as Array<[string, number | null]>;
  if (kind === 'opt') {
    const prefix = `${scope}_side.`;
    return {
      id: trial.trial_id,
      label: `#${trial.trial_no}`,
      params: Object.fromEntries(Object.entries(trial.params).map(([path, v]) => [path.startsWith(prefix) ? path.slice(prefix.length) : path, v])),
      values: Object.fromEntries(metricsOf(scope)),
      valid: null,
    };
  }
  return {
    id: trial.trial_id,
    label: `trial ${trial.trial_no}`,
    params: { ...trial.params },
    values: Object.fromEntries((['combined', 'long', 'short'] as const).flatMap((s) => metricsOf(s).map(([name, v]) => [`${s}.${name}`, v] as const))),
    valid: null,
  };
}
