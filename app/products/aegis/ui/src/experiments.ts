// Pure helpers for the Experiments page (Mission 6 spec §8.2); no React, no fetch.
import { formatSeconds } from './components/OptimizePopover';
import type { StrategySpec } from './contracts';
import type { ExperimentLever, ExperimentReport, Recommendation } from './results';
import { setPath } from './state/workspace';

export interface SurfaceLike {
  parameters: Array<{ path: string; start: number; stop: number; step: number }>;
}

export interface PlanLike {
  mode: 'exhaustive' | 'sampled';
  valid_cells: number;
  planned_runs: number;
  sampled_fraction: number;
}

const n = (value: number) => value.toLocaleString('en-US');

/** "4 parameters · 252 cells · exhaustive" or "… · sampled 1.3% (2,000 runs)". */
export function surfaceLine(surface: SurfaceLike, plan: PlanLike | null): string {
  const count = surface.parameters.length;
  const head = `${count} parameter${count === 1 ? '' : 's'}`;
  if (!plan) return `${head} · plan pending`;
  if (plan.mode === 'exhaustive') return `${head} · ${n(plan.valid_cells)} cells · exhaustive`;
  return `${head} · ${n(plan.valid_cells)} cells · sampled ${(plan.sampled_fraction * 100).toFixed(1)}% (${n(plan.planned_runs)} runs)`;
}

/** Side-prefixed parameter paths applied to a strategy, each side through setPath (plan ruling P8). */
export function applyCellToStrategy(spec: StrategySpec, params: Record<string, number>): StrategySpec {
  let next = spec;
  for (const [path, value] of Object.entries(params)) {
    const dot = path.indexOf('.');
    const side = path.slice(0, dot) as 'long_side' | 'short_side';
    if (side !== 'long_side' && side !== 'short_side') continue;
    next = { ...next, [side]: setPath(next[side], path.slice(dot + 1), value) };
  }
  return next;
}

export interface CellRow {
  cell: number;
  valid: boolean;
  plateau?: number | null;
  [column: string]: unknown;
}

/** Sort rows by a column (nulls last whichever way) and keep one plateau's cells when asked. */
export function cellsView<T extends CellRow>(rows: T[], view: { sort: string; descending: boolean; plateau?: number | null }): T[] {
  const kept = view.plateau === undefined || view.plateau === null ? rows : rows.filter((r) => r.plateau === view.plateau);
  const value = (r: T) => r[view.sort];
  return [...kept].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const xNull = x === null || x === undefined;
    const yNull = y === null || y === undefined;
    if (xNull && yNull) return a.cell - b.cell;
    if (xNull) return 1;
    if (yNull) return -1;
    const order = (x as number) < (y as number) ? -1 : (x as number) > (y as number) ? 1 : a.cell - b.cell;
    return view.descending ? -order : order;
  });
}

export function paramsText(params: Record<string, number>): string {
  return Object.entries(params)
    .map(([path, value]) => `${path} ${value}`)
    .join(', ');
}

/** The one honest sentence for the recommendation card. */
export function recommendationText(report: Pick<ExperimentReport, 'recommendation' | 'statement'>): string {
  const rec: Recommendation | null = report.recommendation;
  if (!rec) return `No recommendation: ${report.statement}`;
  const supported = rec.supported_peak ? `supported peak at cell ${rec.supported_peak.cell}` : 'no supported peak';
  const fragile = rec.fragile_peaks.length;
  return `Plateau ${rec.plateau}: use cell ${rec.centre.cell} (${paramsText(rec.centre.params)}); ${supported}; ${fragile} fragile peak${fragile === 1 ? '' : 's'} marked`;
}

export function leverLabel(lever: Pick<ExperimentLever, 'label' | 'valid_cells' | 'estimate_seconds' | 'fits'> & Partial<ExperimentLever>): string {
  return `${lever.label} → ${n(lever.valid_cells)} cells, ${lever.fits ? 'fits' : formatSeconds(lever.estimate_seconds)}`;
}
