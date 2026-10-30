// The Robustness tab's decisions (spec §7.6), nothing React and nothing drawn: the peak list and the robust list side
// by side, each row's value (converted back from the worker's ORIENTED numbers, `max_drawdown` negated) beside its
// classification or its reason verbatim, whether the two rankings disagree, and the stable candidate or why there is
// none. The ranking is the worker's (lexicographic over the resolved categories, the metric breaking a tie); a stable
// cell with a lower value can rank above a higher unresolved one, so the value is always printed beside it.
// `RobustnessView` only draws what this returns.
import type { LabRankedEntry, LabRankings } from '../results';
import { orientationOf, realValue, trialLabel } from './candidateModel';
import { lossTone, objectiveText } from './LabKpiStrip';
import { stableEntry } from './labQuery';

export type ClassTone = 'stable' | 'mixed' | 'weak' | 'unresolved';

/** The style family of a classification, by its words: stable local / stable region, mixed, isolated peak / unstable region,
 *  and unresolved. */
export function classTone(state: 'resolved' | 'unresolved', classification: string | null): ClassTone {
  if (state === 'unresolved' || classification === null) return 'unresolved';
  if (classification.startsWith('stable')) return 'stable';
  if (classification === 'mixed') return 'mixed';
  return 'weak';
}

export interface RankedRow {
  trialId: string;
  trialLabel: string;
  /** 1-based place in this list. */
  place: number;
  /** In the metric's real units. */
  value: number;
  valueText: string;
  /** The classification, else the reason it has none: both as the server sent them. */
  classification: string;
  state: 'resolved' | 'unresolved';
  /** Which category placed it, A or B; null when neither resolved. */
  rankedBy: 'A' | 'B' | null;
  /** The value loses money (below its break-even): drawn red, whatever the place. */
  loses: boolean;
  stable: boolean;
}

function row(entry: LabRankedEntry, place: number, metric: string, stable: string | null): RankedRow {
  const orientation = orientationOf(metric);
  const value = realValue(orientation, entry.value) ?? entry.value;
  const resolved = entry.classification !== null;
  return {
    trialId: entry.trial_id,
    trialLabel: trialLabel(entry.trial_id),
    place,
    value,
    valueText: objectiveText(metric, value),
    classification: entry.classification ?? entry.reason ?? '',
    state: resolved ? 'resolved' : 'unresolved',
    rankedBy: entry.ranked_by,
    loses: lossTone(metric, value) === 'loss',
    stable: stable !== null && entry.trial_id === stable,
  };
}

/** One of the two lists. The robust list is `ranked` in the order the worker gave, the peak list `peak_ranked`; values are
 *  converted with the orientation of the metric that was asked (the rankings carry none of their own). */
export function rankingRows(rankings: LabRankings, list: 'peak' | 'robust', metric: string): RankedRow[] {
  const entries = list === 'robust' ? rankings.ranked : rankings.peak_ranked;
  return entries.map((entry, i) => row(entry, i + 1, metric, rankings.stable));
}

export interface RobustSummary {
  disagree: boolean;
  /** Whether the first of each list is one trial, said in a sentence; empty with nothing to rank. */
  agreement: string;
  /** The stable candidate, or why there is none (the server's `stable_reason` verbatim). */
  stable: string;
  /** The stable candidate's id, null when there is none. */
  stableId: string | null;
}

/** The sentences above the lists. `stable` is chosen from the whole pool, so it may name a trial the lists do not show
 *  (said so); when it names none, `stable_reason` is printed as the worker wrote it. */
export function robustSummary(rankings: LabRankings, metric: string): RobustSummary {
  const peak = rankings.peak[0];
  const robust = rankings.robust[0];
  let agreement = '';
  if (peak !== undefined && robust !== undefined)
    agreement = rankings.disagree ? `Peak and robust disagree: the peak is ${trialLabel(peak)}, the most robust is ${trialLabel(robust)}.` : `Peak and robust agree on ${trialLabel(robust)}.`;
  let stable: string;
  if (rankings.stable === null) stable = rankings.stable_reason === null ? 'No stable candidate' : `No stable candidate: ${rankings.stable_reason}`;
  else {
    const found = stableEntry(rankings);
    if (found === null) stable = `Stable candidate: ${trialLabel(rankings.stable)} (outside the rows listed)`;
    else {
      const shown = row(found, 0, metric, rankings.stable);
      stable = `Stable candidate: ${shown.trialLabel} · ${shown.classification} · ${shown.valueText}`;
    }
  }
  return { disagree: rankings.disagree, agreement, stable, stableId: rankings.stable };
}

/** B's axes, or that B is not run for want of a finished importance result. */
export function axesLine(axes: readonly string[]): string {
  return axes.length === 0 ? 'B is not run: it needs a finished importance result for this snapshot' : `B axes: ${axes.join(', ')}`;
}

/** τ and the tolerance it comes from, with the label the worker sends for a default. */
export function toleranceLine(tolerance: number, label: string | null): string {
  const base = `τ = tolerance ${tolerance} × (P90 − P10) of the metric`;
  return label === null ? base : `${base} · ${label}`;
}
