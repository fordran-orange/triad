// The interaction matrix's decisions (spec §7.4), nothing React and nothing drawn: the d × d grid of the joint shares J
// the `interactions` view sends, which pair sits where and which direction of Δ a square reads, how strongly a square is
// shaded (an unresolved pair is hatched, never shaded), and the hover and list texts. `I` has no interval: it is
// display only and no rule reads it, while the rules read Δ. `InteractionMatrix` only draws what this returns. The
// shares arrive unclamped and are shown at 0 or above through `displayShare`.
import { DASH, pct } from '../format';
import type { LabImportanceConstants, LabInteractionPair, LabInteractions, LabIncrement } from '../results';
import { coverageText } from './candidateModel';
import { displayShare } from './labQuery';
import { metricName } from './metricRules';

/** The pair a square shows and which of its two increments the square's row reads: `D_ij` for the pair's first parameter
 *  as the row (what it adds beyond the second), `D_ji` for the second. */
export interface PairCell {
  pair: LabInteractionPair;
  r: number;
  c: number;
  own: 'D_ij' | 'D_ji';
}

export interface InteractionModel {
  size: number;
  /** The parameter paths by index, as the pairs name them; empty where no pair sent that parameter. */
  labels: string[];
  /** `cells[r][c]`: the pair of parameters r and c; null on the diagonal and where the pair was not sent. */
  cells: Array<Array<PairCell | null>>;
  /** The largest J among the resolved pairs, at 0 or above: the scale of the shading. */
  maxJ: number;
  /** The unresolved pairs in the order the server sent them. */
  unresolved: LabInteractionPair[];
}

/** The number of parameters d from the number of pairs d(d − 1)/2, and at least the largest index a pair names + 1. */
function sizeOf(view: LabInteractions): number {
  const fromTotal = Math.round((1 + Math.sqrt(1 + 8 * view.total_pairs)) / 2);
  const fromPairs = view.pairs.reduce((most, p) => Math.max(most, p.index[0] + 1, p.index[1] + 1), 0);
  return Math.max(fromTotal, fromPairs);
}

/** The matrix of an `interactions` answer; null before the first stage was delivered. */
export function interactionModel(view: LabInteractions): InteractionModel | null {
  if (view.computed === null) return null;
  const size = sizeOf(view);
  const labels = Array.from({ length: size }, () => '');
  const cells: Array<Array<PairCell | null>> = Array.from({ length: size }, () => Array.from({ length: size }, () => null));
  let maxJ = 0;
  for (const pair of view.pairs) {
    const [i, j] = pair.index;
    labels[i] = pair.pair[0];
    labels[j] = pair.pair[1];
    cells[i][j] = { pair, r: i, c: j, own: 'D_ij' };
    cells[j][i] = { pair, r: j, c: i, own: 'D_ji' };
    if (!pair.unresolved && pair.J.value !== null) maxJ = Math.max(maxJ, displayShare(pair.J.value));
  }
  return { size, labels, cells, maxJ, unresolved: view.pairs.filter((p) => p.unresolved) };
}

/** How strongly a square is shaded, from 0 to 1 by its J against the largest resolved J; null where nothing is shaded: a
 *  square with no pair, an unresolved pair (hatched), or a J that is undefined. */
export function intensity(cell: PairCell | null, maxJ: number): number | null {
  if (cell === null || cell.pair.unresolved || cell.pair.J.value === null) return null;
  return maxJ > 0 ? Math.min(1, displayShare(cell.pair.J.value) / maxJ) : 0;
}

/** What a square looks like: hatched only when its pair is unresolved (coverage under the constant), shaded by J when the pair
 *  is resolved and has a J, and an outline otherwise: the diagonal, a pair the worker did not send, and a resolved pair whose
 *  J is undefined (hatching it would call it low coverage, and it is not in the unresolved list). */
export type SquareLook = { kind: 'hatch' } | { kind: 'outline' } | { kind: 'shade'; t: number };

export function squareLook(cell: PairCell | null, maxJ: number): SquareLook {
  if (cell === null) return { kind: 'outline' };
  if (cell.pair.unresolved) return { kind: 'hatch' };
  const t = intensity(cell, maxJ);
  return t === null ? { kind: 'outline' } : { kind: 'shade', t };
}

const share = (v: number | null) => (v === null ? DASH : pct(displayShare(v), 1));
const span = (v: { lo: number | null; hi: number | null }) => (v.lo === null || v.hi === null ? 'no interval' : `[${share(v.lo)}–${share(v.hi)}]`);

/** One direction of Δ: what `own` adds beyond `other`, its 90 % bounds and its family floor (`detected` when it exceeds it). */
function delta(own: string, other: string, d: LabIncrement): string {
  const verdict = d.floor === null ? 'no floor' : `floor ${share(d.floor)}, ${d.detected ? 'detected' : 'not detected'}`;
  return `Δ ${own} beyond ${other} ${share(d.value)} ${span(d)} (${verdict})`;
}

/** A square's hover text: the pair, J with its interval, both increments (the square's own direction first), I as display
 *  only, and the pair's coverage and balance. */
export function hoverText(cell: PairCell, constants: LabImportanceConstants): string {
  const { pair } = cell;
  const [a, b] = pair.pair;
  const forward = delta(a, b, pair.D_ij);
  const backward = delta(b, a, pair.D_ji);
  const parts = [
    `${a} × ${b}`,
    `J ${share(pair.J.value)} ${span(pair.J)}`,
    ...(cell.own === 'D_ij' ? [forward, backward] : [backward, forward]),
    `I ${share(pair.I)} (display only, no interval)`,
    `coverage ${coverageText(pair.coverage)}`,
  ];
  if (pair.unresolved) parts.push(`unresolved: coverage is below the minimum (needs ${constants.PAIR_MIN_COVERAGE})`);
  if (pair.unbalanced) parts.push('unbalanced: its cells are far from uniform');
  return parts.join(' · ');
}

/** An unresolved pair's line under the matrix: the pair and its coverage against the constant of the response. */
export function unresolvedText(pair: LabInteractionPair, constants: LabImportanceConstants): string {
  return `${pair.pair[0]} × ${pair.pair[1]} · coverage ${coverageText(pair.coverage)} (needs ${constants.PAIR_MIN_COVERAGE})`;
}

/** What the matrix's shares are shares of: the metric and scope the answer was computed for (not the one now in view) and its
 *  seed; empty before the first stage was delivered. */
export function jBasisLine(view: LabInteractions): string {
  const c = view.computed;
  return c === null ? '' : `J is a share of the variance of ${metricName(c.metric)} · ${c.scope} scope · seed ${c.seed}`;
}

/** `truncated: the first n of N pairs are shown` when the worker cut the list; null otherwise. */
export function truncatedNotice(view: LabInteractions): string | null {
  return view.truncated ? `truncated: the first ${view.pairs.length.toLocaleString('en-US')} of ${view.total_pairs.toLocaleString('en-US')} pairs are shown` : null;
}

/** The canvas's text twin. */
export function matrixSummary(view: LabInteractions): string {
  const model = interactionModel(view);
  if (model === null) return '';
  return `interaction matrix of J: ${model.size} parameters, ${view.total_pairs.toLocaleString('en-US')} pairs, ${view.unresolved_pairs.toLocaleString('en-US')} unresolved (hatched)`;
}

/** The matrix's margins: room for the row names on the left and the column names, turned upright, above. */
export const MATRIX_MARGIN = { left: 130, top: 118, right: 10, bottom: 10 };
/** A square never grows past this. */
export const MATRIX_MAX_CELL = 40;

/** Where the grid sits on a canvas `width` wide and how big a square is: the width sets the square, the height follows
 *  (the panel scrolls), so twenty parameters stay readable. A canvas too narrow for the margins has no square (size 0). */
export function matrixLayout(width: number, size: number): { x0: number; y0: number; cell: number; height: number } {
  const room = Math.max(0, width - MATRIX_MARGIN.left - MATRIX_MARGIN.right);
  const cell = size > 0 ? Math.min(MATRIX_MAX_CELL, room / size) : 0;
  return { x0: MATRIX_MARGIN.left, y0: MATRIX_MARGIN.top, cell, height: MATRIX_MARGIN.top + size * cell + MATRIX_MARGIN.bottom };
}
