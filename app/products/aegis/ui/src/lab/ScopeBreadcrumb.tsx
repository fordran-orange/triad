// Screen E's scope breadcrumb (spec §5.5): completed → valid unique → filtered → brushed, each step the trials (or
// configurations) the source holds at that point. "Completed" and "valid unique" are the source's own counts (the summary);
// "filtered" is the Lab's filter without its brushes (a side, fixed values, pass and status chips) and "brushed" adds the
// brushed ranges, each the worker's `counts` of that filter. A step the filter does not change is the step before it, said so,
// and asks nothing. A count not yet answered is a dash, never a zero. The decisions are `familiesModel.ts`'s.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import { DASH } from '../format';
import type { LabCounts, LabEnvelope } from '../results';
import { breadcrumbPlan, breadcrumbSteps, type CrumbStep } from './familiesModel';
import { useLab } from './labState';
import { filterHash, type LabFilter } from './labStore';
import { LabError } from './NotBuilt';
import type { LabQueryData, Stamped } from './useLabQuery';

/** The counts of `filter`, asked of the worker on its `counts` view and again on every refresh tick; `null` asks nothing. A
 *  stale answer is dropped (a newer ask owns the count), and an answer for another source or filter is never shown. */
function useCounts(data: LabQueryData, filter: LabFilter | null) {
  const { loaded, query, tick } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const key = source === null || filter === null ? null : `${source}|${filterHash(filter)}`;
  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<{ key: string; envelope: Stamped<LabEnvelope<{}>> } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = key === null ? null : `${key}|${tick}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (key === null || filter === null) return;
    query<{}>('counts', { filter })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer ask owns the count, or the filter moved on
        setAnswer({ key, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailure({ key, message: errorMessage(e) }));
    // The key stands for the source and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, retry]);
  return {
    counts: (answer !== null && answer.key === key ? answer.envelope.scope : null) as LabCounts | null,
    error: failure !== null && failure.key === key ? failure.message : null,
    retry: () => setRetry((n) => n + 1),
  };
}

/** The four steps, each with its exact count as `data-n` (empty while it is not known) for the walk. */
export function CrumbSteps({ steps }: { steps: CrumbStep[] }) {
  return (
    <nav className="breadcrumb-steps" aria-label="Scope">
      {steps.map((step, i) => (
        <Fragment key={step.key}>
          {i > 0 && (
            <span className="breadcrumb-arrow" aria-hidden="true">
              →
            </span>
          )}
          <span className="breadcrumb-step" id={`lab-families-crumb-${step.key}`} data-n={step.n ?? ''} title={step.note}>
            <b>{step.n === null ? DASH : step.n.toLocaleString('en-US')}</b> {step.label}
            <span className="sub breadcrumb-note">
              {step.unit} · {step.note}
            </span>
          </span>
        </Fragment>
      ))}
    </nav>
  );
}

export function ScopeBreadcrumb({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const plan = useMemo(() => breadcrumbPlan(lab.filter), [lab.filter]);
  const filtered = useCounts(data, plan.filtered);
  const brushed = useCounts(data, plan.brushed);
  const steps = breadcrumbSteps(data.summary?.counts ?? null, filtered.counts, brushed.counts, plan);
  return (
    <div className="lab-breadcrumb" id="lab-families-breadcrumb" data-filtered={plan.filtered === null ? 'none' : 'filter'} data-brushed={plan.brushed === null ? 'none' : 'brush'}>
      <CrumbSteps steps={steps} />
      {data.summary === null && data.summaryError === null && (
        <span className="sub lab-loading" id="lab-families-breadcrumb-loading">
          {data.loaded === null ? 'loading the source…' : 'loading the counts…'}
        </span>
      )}
      {filtered.error !== null && <LabError message={`Filtered count unavailable: ${filtered.error}`} onRetry={filtered.retry} />}
      {brushed.error !== null && <LabError message={`Brushed count unavailable: ${brushed.error}`} onRetry={brushed.retry} />}
    </div>
  );
}
