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
