// Pure helpers for large and multi-variable optimizations (the limits change, 2026-10-20).
import type { Cell, JobStatus } from './results';

/** Start asks first when a run is estimated above ten minutes. */
export const CONFIRM_SECONDS = 600;

export function needsConfirm(estimatedSeconds: number): boolean {
  return estimatedSeconds > CONFIRM_SECONDS;
}

/** The enabled optimization parameters of the job's side, in the order the job planned them. */
export function axisChoices(job: Pick<JobStatus, 'side' | 'strategy'>): string[] {
  const side = job.side === 'long' ? job.strategy.long_side : job.strategy.short_side;
  return (side?.optimization ?? []).filter((p) => p.enabled !== false).map((p) => p.path);
}

/** A matrix square's hover: how many cells it summarises and the other parameters of its best
 *  cell (the square shows the best of them). */
export function squareTitle(count: number, best: Cell | null, axes: [string, string], describe: (params: Record<string, number>) => string): string {
  if (!best) return count ? `${count} cells, none with a value` : 'no cells';
  const others = Object.fromEntries(Object.entries(best.params).filter(([path]) => !axes.includes(path)));
  const rest = Object.keys(others).length ? ` · ${describe(others)}` : '';
  return count > 1 ? `best of ${count}${rest}` : `1 cell${rest}`;
}

/** The most matrix squares the page draws (the worker's MAX_SQUARES); the table carries the rest. */
export const MAX_SQUARES = 2500;

/** How many values a parameter takes in the job's grid (0 when it is not one of them). */
export function axisLength(job: Pick<JobStatus, 'side' | 'strategy'>, path: string): number {
  const side = job.side === 'long' ? job.strategy.long_side : job.strategy.short_side;
  const p = (side?.optimization ?? []).find((o) => o.path === path && o.enabled !== false);
  return p ? Math.floor((p.stop - p.start) / p.step + 1e-9) + 1 : 0;
}

/** Why a matrix is not drawn, or null when it fits (the limits review: a two-parameter grid of
 *  100,000 cells would be 100,000 squares re-rendered every second). */
export function tooManySquares(rows: number, cols: number): string | null {
  const c = Math.max(1, cols);
  const n = rows * c;
  if (n <= MAX_SQUARES) return null;
  const f = (v: number) => v.toLocaleString('en-US');
  return `${f(rows)} × ${f(c)} = ${f(n)} squares is more than the matrix draws (${f(MAX_SQUARES)}): choose other parameters or a coarser step; the table lists every cell`;
}

