// The KPI strip's words as data (LabKpiStrip.tsx renders from them), so a node test (labKpiStrip.test.ts) can read
// every label and title: the strip counts trials, never "backtests" (spec §6.4). Not named labKpiStrip.ts: on a
// case-insensitive file system `./LabKpiStrip` would resolve to that file before the component's `.tsx`.

export type KpiKey = 'trials' | 'valid' | 'planned' | 'coverage' | 'best' | 'failed';

/** The strip's order, left to right. */
export const KPI_ORDER: KpiKey[] = ['trials', 'valid', 'planned', 'coverage', 'best', 'failed'];

/** Each KPI's label and the title of its value (what the number is, from the summary's §6.4 counts). */
export const KPI_LABELS: Record<KpiKey, { label: string; title: string }> = {
  trials: { label: 'Trials', title: 'completed trials (status ok, block 0); with a filter active, the sub line counts the ones it keeps' },
  valid: { label: 'Valid', title: 'valid configurations in the search space: the grid without its skipped combinations' },
  planned: { label: 'Planned', title: 'trials scheduled to run: the experiment’s passes, or the grid job’s kept cells' },
  coverage: { label: 'Coverage', title: 'distinct configurations completed ÷ valid configurations' },
  best: { label: 'Best', title: 'the recommended plateau centre of the latest report' },
  failed: { label: 'Failed', title: 'trials whose evaluation raised an error' },
};
