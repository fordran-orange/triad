// The Importance panel's decisions (spec §7.3, §7.4a), nothing React and nothing drawn: the order of the rows (the
// Measured parameters by their share, the unresolved ones last), what each row prints from the response, the lines
// around them, and the notice for a view with no stage yet. The worker decides everything statistical: statuses, labels,
// the availability of the rule, the veto and the constants all arrive in the response and are printed as sent, never
// recomputed (`Investigate · …` and `Insufficient coverage · unresolved` come from `statuses`). A share is shown at 0 or
// above (`displayShare`) while the stored value stays as sent. `ImportanceView` only draws what this returns.
import type { LabCoverageLabel, LabImportance, LabImportanceConstants, LabImportanceResult } from '../results';
import { niceTicks } from './charts/canvas';
import { pct } from '../format';
import { displayShare } from './labQuery';

/** §7.3's caveat, always on the panel. The response carries it (`caveat`) and is printed in preference; this is the spec's
 *  text for a panel with no result yet. */
export const IMPORTANCE_CAVEAT =
  'conditional on these ranges, this data, this sampler and this partition; a share is evidence about where exploration pays, not proof that a parameter is irrelevant';

export function caveatOf(result: LabImportanceResult | null): string {
  return result?.caveat ?? IMPORTANCE_CAVEAT;
}

/** The style family of a status, from its words alone. */
export type StatusKind = 'active' | 'investigate' | 'deprioritized' | 'unresolved';

export function statusKind(status: string): StatusKind {
  if (status.startsWith('Active')) return 'active';
  if (status.startsWith('Investigate')) return 'investigate';
  if (status.startsWith('Deprioritized')) return 'deprioritized';
  return 'unresolved';
}

/** What a Measured row draws, as the worker sent it (unclamped: the drawing clamps). `block` is the `[min, max]` of the
 *  per-block share estimates, null when no block measured it. */
export interface RowMarks {
  share: number | null;
  lo: number | null;
  hi: number | null;
  /** The family-wise detection floor: `Detected` means the share exceeds it. */
  floor: number | null;
  /** The 95th percentile (the floor quantile) of this share's permutation null. */
  tick: number | null;
  block: [number, number] | null;
}

export interface ImportanceRow {
  /** The place in the list, from 0. */
  index: number;
  /** The parameter's place in the response's `paths`. */
  paramIndex: number;
  /** 1-based among the Measured parameters; null for an unresolved one, which is not ranked. */
  rank: number | null;
  path: string;
  label: LabCoverageLabel;
  resolved: boolean;
  /** The status and its reason, verbatim; empty when the response sent none for this parameter. */
  status: string;
  statusKind: StatusKind;
  reason: string;
  flags: string[];
  proposable: boolean;
  /** Why the rule would not propose this parameter; null when it would, or when none was sent. */
  failing: string | null;
  /** Null for an unresolved row: a share on too little data is not drawn. */
  marks: RowMarks | null;
  text: string;
}

const ordinal = (n: number) => {
  const tail = n % 100;
  if (tail >= 11 && tail <= 13) return 'th';
  return ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
};

const share = (v: number | null) => (v === null ? '—' : pct(displayShare(v), 1));

/** A row's numbers on one line: the share, the interval, the block range and the floors. The text clamps at 0 (display
 *  only); the interval and the quantile are named from the constants of the response. */
export function marksText(marks: RowMarks, constants: LabImportanceConstants): string {
  const interval = `${Math.round(constants.INTERVAL * 100)} % interval`;
  const quantile = Math.round(constants.FLOOR_QUANTILE * 100);
  const parts = [
    `share ${share(marks.share)}`,
    marks.lo !== null && marks.hi !== null ? `${interval} ${share(marks.lo)}–${share(marks.hi)}` : 'no interval',
    marks.block !== null ? `block range ${share(marks.block[0])}–${share(marks.block[1])}` : 'block range not measured',
    marks.floor !== null ? `detection floor ${share(marks.floor)}` : 'no detection floor',
  ];
  if (marks.tick !== null) parts.push(`null ${quantile}${ordinal(quantile)} percentile ${share(marks.tick)}`);
  return parts.join(' · ');
}

/** The rows in the order they are listed: the Measured parameters by their share, largest first (a tie by parameter
 *  order; a share the worker could not compute after the ones it could), then the Insufficient-coverage ones, unresolved
 *  and unranked, in parameter order. */
export function importanceRows(result: LabImportanceResult): ImportanceRow[] {
  const status = new Map(result.statuses.map((s) => [s.path, s]));
  const d = result.paths.length;
  const labelOf = (i: number): LabCoverageLabel => result.labels[i] ?? 'Insufficient coverage';
  const shareOf = (i: number) => result.fine.S[i] ?? null;
  const all = Array.from({ length: d }, (_, i) => i);
  const measured = all
    .filter((i) => labelOf(i) === 'Measured')
    .sort((a, b) => {
      const x = shareOf(a);
      const y = shareOf(b);
      if (x === null || y === null) return x === y ? a - b : x === null ? 1 : -1;
      return y - x || a - b;
    });
  const unresolved = all.filter((i) => labelOf(i) !== 'Measured');
  const block = result.block_range;
  const rows: ImportanceRow[] = [...measured, ...unresolved].map((paramIndex, index) => {
    const path = result.paths[paramIndex];
    const found = status.get(path);
    const resolved = labelOf(paramIndex) === 'Measured';
    const marks: RowMarks | null = resolved
      ? {
          share: shareOf(paramIndex),
          lo: result.fine.lo.S[paramIndex] ?? null,
          hi: result.fine.hi.S[paramIndex] ?? null,
          floor: result.fine.floor.S[paramIndex] ?? null,
          tick: result.fine.tick.S[paramIndex] ?? null,
          block: block?.[paramIndex] ?? null,
        }
      : null;
    return {
      index,
      paramIndex,
      rank: resolved ? index + 1 : null,
      path,
      label: labelOf(paramIndex),
      resolved,
      status: found?.status ?? '',
      statusKind: statusKind(found?.status ?? ''),
      reason: found?.reason ?? '',
      flags: found?.flags ?? [],
      proposable: found?.proposable ?? false,
      failing: found?.failing ?? null,
      marks,
      text: marks === null ? '' : marksText(marks, result.constants),
    };
  });
  return rows;
}

/** The shared horizontal extent of the rows' marks: the largest resolved mark rounded up to a tick, so every row is read
 *  on one scale. 1 when nothing is drawn. */
export function axisMax(rows: readonly ImportanceRow[]): number {
  const marks = rows.flatMap((r) => (r.marks === null ? [] : [r.marks]));
  const reached = marks.flatMap((m) => [m.share, m.hi, m.floor, m.tick, m.block?.[1] ?? null]).filter((v): v is number => v !== null && Number.isFinite(v));
  const most = Math.max(0, ...reached.map((v) => displayShare(v)));
  if (!(most > 0)) return 1;
  const ticks = niceTicks([0, most], 5);
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : most;
  return Number((Math.ceil(most / step - 1e-9) * step).toPrecision(12));
}

/** `PARTIAL · stage 2 of 3` for a stage that is not the last; null for the last. */
export function partialLabel(result: LabImportanceResult): string | null {
  return result.partial ? `PARTIAL · stage ${result.stage} of ${result.stages}` : null;
}

/** The availability line: the worker's `empirical deprioritization unavailable: <reason>` verbatim, else that it is available. */
export function availabilityText(result: LabImportanceResult): string {
  return result.availability.message ?? 'empirical deprioritization available';
}

/** The constants the rule and this panel use, read from the response. */
export function constantsLine(c: LabImportanceConstants): string {
  return [
    `θ_min ${c.THETA_MIN}`,
    `${Math.round(c.INTERVAL * 100)} % intervals`,
    `bootstrap B = ${c.BOOTSTRAP_B}`,
    `permutation P = ${c.PERMUTATION_P}`,
    `Measured needs n ≥ ${c.IMPORTANCE_MIN_N_FACTOR} × its values and ≥ ${c.IMPORTANCE_MIN_PER_VALUE} rows per value`,
    `aliased above Cramér's V > ${c.ALIAS_V}`,
  ].join(' · ');
}

/** The subsample line (§7.3: a seeded subsample, stated), empty when every row was read. */
export function sampleLine(result: LabImportanceResult): string {
  if (result.sampled_from === null) return '';
  return `bootstrap and null read a seeded subsample of ${result.constants.IMPORTANCE_ROWS.toLocaleString('en-US')} of ${result.sampled_from.toLocaleString('en-US')} rows`;
}

/** What a view with no stage says: the worker's reason verbatim when it requested no task (a grid job still running), that
 *  the first stage is awaited while the task runs, that a stopped task delivered nothing, or that nothing was asked. Null
 *  once a stage was delivered. */
export function stateNotice(view: Pick<LabImportance, 'importance' | 'task' | 'reason'>): { kind: 'reason' | 'waiting' | 'stopped' | 'none'; text: string } | null {
  if (view.importance !== null) return null;
  if (view.reason !== null) return { kind: 'reason', text: view.reason };
  const { task } = view;
  if (task === null) return { kind: 'none', text: 'importance has not been requested for this source' };
  if (task.state === 'queued' || task.state === 'running') return { kind: 'waiting', text: `waiting for stage ${Math.min(task.stage + 1, task.stages)} of ${task.stages}` };
  return { kind: 'stopped', text: 'the task stopped before its first stage was delivered' };
}
