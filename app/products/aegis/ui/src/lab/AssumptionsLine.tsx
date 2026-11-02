// Spec §7.11: every analytic panel states its assumptions. One line, four clauses in a fixed order, on the heatmap (an experiment's
// and a grid job's), the trellis, the neighbourhood map, the drill-down, the convergence chart, the parallel coordinates, the
// importance, the interactions, the robustness rankings, the Pareto front, the rail's candidate card and findings, and the Variables
// screen (which has no view of its own yet: one line for the screen). The clauses are static for Phase 3: every source is a discrete grid, partitions arrive
// in Phase 5 (until then the metrics are in-sample), and the data are raw archives. The uniform-design clause is stated only where
// the panel's numbers rest on the uniform rows (importance, the interactions, and the trellis that ranks its pairs by them).
// The clause strings live here and nowhere else.

export const ASSUMPTION_CLAUSES = {
  grid: 'Discrete grids: every parameter has a step',
  uniform: 'Uniform-design rows',
  inSample: 'Metrics are in-sample on the selection partition',
  raw: 'Raw archives, not research-eligible',
} as const;

/** The panels that carry the line: the id is `lab-assumptions-<panel>`. */
export type AssumptionsPanel =
  | 'heatmap'
  | 'trellis'
  | 'neighbourhood'
  | 'drill'
  | 'convergence'
  | 'parallel'
  | 'importance'
  | 'interactions'
  | 'robustness'
  | 'pareto'
  | 'candidate'
  | 'findings'
  | 'variables';

/** The line's text: the clauses in order, the uniform-design one only for a panel that rests on the uniform rows. */
export function assumptionsText(uniform: boolean): string {
  return [ASSUMPTION_CLAUSES.grid, ...(uniform ? [ASSUMPTION_CLAUSES.uniform] : []), ASSUMPTION_CLAUSES.inSample, ASSUMPTION_CLAUSES.raw].join(' · ');
}

export function AssumptionsLine({ panel, uniform = false }: { panel: AssumptionsPanel; uniform?: boolean }) {
  return (
    <p className="lab-assumptions" id={`lab-assumptions-${panel}`} data-panel={panel}>
      {assumptionsText(uniform)}
    </p>
  );
}
