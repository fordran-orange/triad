import type { ReactNode } from 'react';
import { profitKind } from '../components/Heatmap';
import { DASH, money, num, pct } from '../format';
import { PERCENT_OBJECTIVES, type ExperimentProgress, type Objective } from '../results';
import type { LabData } from './useLabSource';

interface Kpi {
  key: 'trials' | 'valid' | 'planned' | 'coverage' | 'best' | 'failed';
  label: string;
  value: ReactNode;
  /** Why the value is a dash, or what a shown value is; every dash has one. */
  title: string;
  sub?: string;
  tone?: 'loss' | 'gain';
}

const count = (n: number) => n.toLocaleString('en-US');

/** An objective's value as the reports print it: money for P&L and expectancy, a percentage for the shares. */
export function objectiveText(objective: string, value: number | null): string {
  if (value === null) return DASH;
  if (PERCENT_OBJECTIVES.has(objective as Objective)) return pct(value);
  if (objective === 'net_pnl' || objective === 'expectancy') return money(value);
  return num(value, objective === 'trade_count' ? 0 : 2);
}

/** The Heatmap's profit sign (`profitKind`): below break-even loses money and shows red, above it gains, break-even
 *  itself is neutral; profit factor breaks even at 1, the other money-signed objectives at 0. */
export function lossTone(objective: string, value: number | null): 'loss' | 'gain' | undefined {
  if (value === null) return undefined;
  const kind = profitKind(objective);
  if (!kind) return undefined;
  const even = kind === 'ratio' ? 1 : 0;
  return value < even ? 'loss' : value > even ? 'gain' : undefined;
}

function dash(key: Kpi['key'], label: string, title: string): Kpi {
  return { key, label, value: DASH, title };
}

function kpis(data: LabData): Kpi[] {
  const { loaded, loading } = data;
  if (loaded === null) {
    const why = loading ? 'loading the source' : 'no source open';
    return [dash('trials', 'Trials', why), dash('valid', 'Valid', why), dash('planned', 'Planned', why), dash('coverage', 'Coverage', why), dash('best', 'Best', why), dash('failed', 'Failed', why)];
  }
  if (loaded.kind === 'opt') {
    const { job } = loaded;
    const done = job.cells_done ?? job.progress.done;
    const planned = job.total_cells ?? job.progress.total;
    return [
      { key: 'trials', label: 'Trials', value: count(done), title: 'cells the job has evaluated' },
      dash('valid', 'Valid', 'not in this job'),
      { key: 'planned', label: 'Planned', value: count(planned), title: 'cells in the job’s grid', sub: job.skipped_cells ? `${count(job.skipped_cells)} skipped` : undefined },
      dash('coverage', 'Coverage', 'not in this job'),
      dash('best', 'Best', 'not in this job'),
      { key: 'failed', label: 'Failed', value: job.error ? '1' : '0', title: job.error ? `the job failed: ${job.error}` : 'the job recorded no error', tone: job.error ? 'loss' : undefined },
    ];
  }
  const { document, report } = loaded;
  const progress = document.progress as unknown as ExperimentProgress;
  const done = typeof progress.cells_done === 'number' ? progress.cells_done : null;
  const planned = typeof progress.cells_planned === 'number' ? progress.cells_planned : null;
  const noReport = 'no report yet';
  const trials: Kpi = done === null ? dash('trials', 'Trials', 'the experiment reports no progress') : { key: 'trials', label: 'Trials', value: count(done), title: 'cells evaluated so far' };
  const plannedKpi: Kpi = planned === null ? dash('planned', 'Planned', 'the experiment reports no plan') : { key: 'planned', label: 'Planned', value: count(planned), title: 'cells the plan runs' };
  const valid: Kpi = report
    ? { key: 'valid', label: 'Valid', value: count(report.valid_cells), title: 'valid cells in the latest report', sub: `${count(report.null_objective_cells)} without an objective value` }
    : dash('valid', 'Valid', noReport);
  const coverage: Kpi = !report
    ? dash('coverage', 'Coverage', noReport)
    : !planned
      ? dash('coverage', 'Coverage', 'nothing planned')
      : { key: 'coverage', label: 'Coverage', value: pct(report.valid_cells / planned, 1), title: 'valid cells in the report ÷ planned cells' };
  const rec = report?.recommendation ?? null;
  const best: Kpi = !report
    ? dash('best', 'Best', noReport)
    : rec === null
      ? dash('best', 'Best', 'the latest report has no recommendation')
      : {
          key: 'best',
          label: 'Best',
          value: objectiveText(report.objective, rec.centre.objective),
          title: `the recommended plateau centre, cell ${rec.centre.cell} (${report.objective})`,
          sub: `cell ${rec.centre.cell} · ${report.objective}`,
          tone: lossTone(report.objective, rec.centre.objective),
        };
  const failed: Kpi = {
    key: 'failed',
    label: 'Failed',
    value: document.error ? '1' : '0',
    title: document.error ? `the experiment recorded an error: ${document.error}` : 'the experiment recorded no error',
    tone: document.error ? 'loss' : undefined,
  };
  return [trials, valid, plannedKpi, coverage, best, failed];
}

/** Six counts across the top of the Lab, every one from the open source or a dash that says why. */
export function LabKpiStrip({ data }: { data: LabData }) {
  return (
    <div className="lab-kpis" id="lab-kpis">
      {kpis(data).map((k) => (
        <div className="kpi" data-kpi={k.key} key={k.key} title={k.title}>
          <div className="kpi-label">{k.label}</div>
          <div className={'kpi-value' + (k.tone === 'loss' ? ' red' : k.tone === 'gain' ? ' green' : '')}>{k.value}</div>
          {k.sub && <div className="kpi-sub">{k.sub}</div>}
        </div>
      ))}
    </div>
  );
}
