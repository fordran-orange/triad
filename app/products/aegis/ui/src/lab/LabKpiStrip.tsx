import { useEffect, useRef, useState, type ReactNode } from 'react';
import { errorMessage } from '../api/client';
import { profitKind } from '../components/Heatmap';
import { DASH, money, num, pct } from '../format';
import { PERCENT_OBJECTIVES, type LabEnvelope, type Objective } from '../results';
import { KPI_LABELS, KPI_ORDER, type KpiKey } from './labKpiLabels';
import { kpiTrialsText, SHARPE } from './labQuery';
import { useLab } from './labState';
import { activeFilterCount, filterHash } from './labStore';
import { LabError } from './NotBuilt';
import type { LabQueryData, Stamped } from './useLabQuery';

interface Kpi {
  key: KpiKey;
  value: ReactNode;
  /** Why the value is a dash, or what a shown value is; every dash has one. */
  title: string;
  sub?: string | null;
  tone?: 'loss' | 'gain';
}

const count = (n: number) => n.toLocaleString('en-US');

/** An objective's value as the reports print it: money for P&L and expectancy, a percentage for the shares, two
 *  decimals for the ratios and the trade Sharpe, whole trades. */
export function objectiveText(objective: string, value: number | null): string {
  if (value === null) return DASH;
  if (PERCENT_OBJECTIVES.has(objective as Objective)) return pct(value);
  if (objective === 'net_pnl' || objective === 'expectancy') return money(value);
  if (objective === SHARPE) return num(value, 2);
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

const dash = (key: KpiKey, title: string): Kpi => ({ key, value: DASH, title });

/** The Best KPI: the latest report's recommended plateau centre (a grid job has no report). */
function bestKpi(data: LabQueryData): Kpi {
  const { loaded } = data;
  if (loaded === null) return dash('best', data.loading ? 'loading the source' : 'no source open');
  if (loaded.kind === 'opt') return dash('best', 'not in this job: a grid job has no report');
  const { report } = loaded;
  if (!report) return dash('best', 'no report yet');
  const rec = report.recommendation;
  if (rec === null) return dash('best', 'the latest report has no recommendation');
  return {
    key: 'best',
    value: objectiveText(report.objective, rec.centre.objective),
    title: `${KPI_LABELS.best.title}: cell ${rec.centre.cell} (${report.objective})`,
    sub: `cell ${rec.centre.cell} · ${report.objective}`,
    tone: lossTone(report.objective, rec.centre.objective),
  };
}

function kpis(data: LabQueryData, filtered: number | null, filtersActive: number): Kpi[] {
  const { loaded, loading, summary } = data;
  const best = bestKpi(data);
  if (loaded === null || summary === null) {
    const why = loaded === null ? (loading ? 'loading the source' : 'no source open') : data.summaryError ? 'the summary is unavailable' : 'loading the summary';
    return KPI_ORDER.map((key) => (key === 'best' ? best : dash(key, why)));
  }
  const c = summary.counts;
  const trials = kpiTrialsText(c.completed, filtered ?? c.completed, filtered === null ? 0 : filtersActive);
  const error = loaded.kind === 'exp' ? loaded.document.error : loaded.job.error;
  const skipped = loaded.kind === 'opt' && loaded.job.skipped_cells ? `${count(loaded.job.skipped_cells)} skipped` : null;
  const byKey: Record<KpiKey, Kpi> = {
    trials: { key: 'trials', value: trials.primary, title: KPI_LABELS.trials.title, sub: trials.sub },
    valid: { key: 'valid', value: count(c.valid), title: KPI_LABELS.valid.title },
    planned: { key: 'planned', value: count(c.scheduled), title: KPI_LABELS.planned.title, sub: skipped },
    coverage: c.valid > 0 ? { key: 'coverage', value: pct(c.unique / c.valid, 1), title: KPI_LABELS.coverage.title } : dash('coverage', 'nothing valid to cover'),
    best,
    failed: {
      key: 'failed',
      value: count(c.failed),
      title: error ? `${KPI_LABELS.failed.title}; the run itself recorded an error: ${error}` : KPI_LABELS.failed.title,
      sub: error ? 'the run recorded an error' : null,
      tone: c.failed > 0 || error ? 'loss' : undefined,
    },
  };
  return KPI_ORDER.map((key) => byKey[key]);
}

/** Six counts across the top of the Lab, from the source's summary (§6.4); with a filter active the Trials KPI also
 *  counts what the filter keeps (its own `counts` query). Every dash says why; a failed query shows its X state. */
export function LabKpiStrip({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const filtersActive = activeFilterCount(lab.filter);
  const source = data.loaded ? `${data.loaded.kind}:${data.loaded.id}` : null;
  const hash = filterHash(lab.filter);
  const scopeKey = source === null ? null : `${source}|${hash}`;
  const [retry, setRetry] = useState(0);
  const [counted, setCounted] = useState<{ key: string; envelope: Stamped<LabEnvelope<{}>> } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  const want = scopeKey !== null && filtersActive > 0 && data.summary !== null ? `${scopeKey}|${data.tick}|${retry}` : null;
  useEffect(() => {
    if (want === null || asked.current === want) return; // nothing to count, or React's development double-run
    asked.current = want;
    const mine = ++seq.current;
    const key = scopeKey as string;
    data
      .query<{}>('counts')
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return;
        setCounted({ key, envelope });
        setFailed(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailed({ key, message: errorMessage(e) }));
    // `want` stands for the source, the filter, the refresh tick and Retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [want]);
  const filtered = filtersActive > 0 && counted !== null && counted.key === scopeKey ? counted.envelope.scope.filtered : null;
  return (
    <div className="lab-kpis" id="lab-kpis">
      {kpis(data, filtered, filtersActive).map((k) => (
        <div className="kpi" data-kpi={k.key} key={k.key} title={k.title}>
          <div className="kpi-label">{KPI_LABELS[k.key].label}</div>
          <div className={'kpi-value' + (k.tone === 'loss' ? ' red' : k.tone === 'gain' ? ' green' : '')}>{k.value}</div>
          {k.sub && <div className="kpi-sub">{k.sub}</div>}
        </div>
      ))}
      {data.summaryError && <LabError message={`Summary unavailable: ${data.summaryError}`} onRetry={data.retrySummary} />}
      {failed !== null && failed.key === scopeKey && filtersActive > 0 && <LabError message={`Filtered count unavailable: ${failed.message}`} onRetry={() => setRetry((n) => n + 1)} />}
    </div>
  );
}
