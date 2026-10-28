import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { DASH } from '../format';
import { METRIC_LABELS, OBJECTIVE_LABELS, type LabBuild } from '../results';
import { datasetLabel, failedSource, metricList, SHARPE, SHARPE_LABEL, statusLabel } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { parseSource, sourceText, type LabScope } from './labStore';
import { LinkedChip } from './LinkedChip';
import { LabError } from './NotBuilt';
import type { LabQueryData } from './useLabQuery';
import { isLive, statusOf } from './useLabSource';

const SCOPES: Array<{ key: 'long' | 'short' | 'both'; scope: LabScope; label: string }> = [
  { key: 'long', scope: 'long', label: 'Long' },
  { key: 'short', scope: 'short', label: 'Short' },
  { key: 'both', scope: 'combined', label: 'Both' },
];

const metricLabel = (metric: string) =>
  metric === SHARPE ? SHARPE_LABEL : ((OBJECTIVE_LABELS as Record<string, string>)[metric] ?? (METRIC_LABELS as Record<string, string>)[metric] ?? metric);

/** The Lab's context toolbar: what is open (source, strategy, parent, data), the direction and metric the panels
 *  read, the states the strategy and the data do not carry yet, the run status and the linked filter. */
export function LabContextBar({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { experiments, listError, reloadList, loaded, loading, refreshError, optSources, summary } = data;
  const value = lab.source ? sourceText(lab.source) : '';
  const kind = loaded?.kind ?? lab.source?.kind ?? 'exp';
  const listed = value === '' || optSources.some((id) => `opt:${id}` === value) || (experiments ?? []).some((e) => `exp:${e.id}` === value);
  // The data root's free space, asked once as the Lab opens: below the worker's threshold it says so.
  const [disk, setDisk] = useState<LabBuild['disk'] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .labBuild()
      .then((build) => !cancelled && setDisk(build.disk))
      .catch(() => undefined); // the warning is advisory: without the build route there is nothing to warn about
    return () => {
      cancelled = true;
    };
  }, []);

  const open = (text: string) => {
    if (text === '') return;
    const source = parseSource(text);
    if (source === null) {
      dispatch({ type: 'SOURCE_FAILED', message: `${text}: not a Lab source (exp:<id> or opt:<id>)` });
      return;
    }
    const summary = source.kind === 'exp' ? experiments?.find((e) => e.id === source.id) : undefined;
    dispatch({ type: 'OPEN_SOURCE', source, metric: summary?.objective });
  };

  const job = loaded?.kind === 'opt' ? loaded.job : null;
  const doc = loaded?.kind === 'exp' ? loaded.document : null;
  const strategy = loaded?.kind === 'exp' ? loaded.strategyName : job ? job.strategy.name : null;
  const range = doc ? doc.data : job ? job.data : null;
  const dataset = range ? [range.symbol, range.timeframe, range.start, '→', range.end].map((part) => part ?? DASH).join(' ') : null;
  const provenance = datasetLabel(summary);
  const status = loaded ? statusOf(loaded) : null;
  const live = status !== null && isLive(status);
  const scopeShown: LabScope = job ? job.side : lab.filter.scope; // a grid job evaluates its own side only
  const retryOpen = failedSource(lab.sourceError);
  // The open experiment's option follows its live status, so `running` never sticks once it finished.
  const statusOfListed = (id: string, listedStatus: string) => (value === `exp:${id}` ? (summary?.status ?? doc?.status ?? listedStatus) : listedStatus);

  return (
    <div className="lab-context" id="lab-context">
      <label className="lab-field">
        Source
        <select id="lab-source" value={value} aria-label="Source" onChange={(e) => open(e.target.value)}>
          <option value="" disabled>
            {experiments === null ? (listError ? 'Experiments unavailable' : 'Loading experiments…') : 'Choose an experiment'}
          </option>
          {!listed && <option value={value}>{value}</option>}
          {optSources.map((id) => (
            <option key={id} value={`opt:${id}`}>
              Grid job {id.slice(0, 8)} (from the dock)
            </option>
          ))}
          {(experiments ?? []).map((e) => (
            <option key={e.id} value={`exp:${e.id}`}>
              {e.name} · {statusOfListed(e.id, e.status)}
            </option>
          ))}
        </select>
      </label>
      {lab.sourceError &&
        (retryOpen !== null ? (
          <LabError id="lab-source-error" message={`Could not open ${lab.sourceError}`} onRetry={() => open(retryOpen)} />
        ) : (
          <span className="error" id="lab-source-error" role="alert">
            Could not open {lab.sourceError}
          </span>
        ))}
      {listError && <LabError message={`Experiments unavailable: ${listError}`} onRetry={reloadList} />}
      {disk?.low && (
        <span className="error" id="lab-disk-warning" role="status">
          low disk: {disk.free_gb.toFixed(1)} GB free on {disk.root}
        </span>
      )}
      <span className="lab-field" id="lab-strategy" title={job ? 'the strategy the job was planned from' : 'the strategy document the experiment pinned'}>
        Strategy <b>{strategy ?? (loading ? 'loading…' : DASH)}</b>
      </span>
      {doc?.parent && (
        <button type="button" className="chip" id="lab-parent" title="Open the experiment this one refines" onClick={() => open(`exp:${doc.parent}`)}>
          refines {doc.parent}
        </button>
      )}
      <span className="lab-field" id="lab-dataset" title={provenance === '' ? undefined : 'the pinned data: the archive’s sha256 prefix and vintage'}>
        Data <b>{dataset ?? (loading ? 'loading…' : DASH)}</b>
        {provenance !== '' && <span className="muted">· {provenance}</span>}
      </span>
      <span className="lab-scope" role="group" aria-label="Direction">
        {SCOPES.map((s) => (
          <button
            type="button"
            key={s.key}
            id={`lab-scope-${s.key}`}
            className={'chip' + (scopeShown === s.scope ? ' active' : '')}
            aria-pressed={scopeShown === s.scope}
            disabled={kind === 'opt'}
            title={kind === 'opt' ? `a grid job evaluates its ${job?.side ?? 'one'} side only` : s.scope === 'combined' ? 'both sides together' : `the ${s.label.toLowerCase()} side's metrics`}
            onClick={() => dispatch({ type: 'SET_SCOPE', scope: s.scope })}
          >
            {s.label}
          </button>
        ))}
      </span>
      <span className="lab-field muted" id="lab-independent">
        Long and short: evaluated independently
      </span>
      <label className="lab-field">
        Metric
        <select id="lab-metric" value={lab.metric} aria-label="Metric" onChange={(e) => dispatch({ type: 'SET_METRIC', metric: e.target.value })}>
          {metricList(kind, summary).map((m) => (
            <option key={m} value={m}>
              {metricLabel(m)}
            </option>
          ))}
        </select>
      </label>
      <span className="lab-field muted" id="lab-regime" title="no strategy carries a REGIME indicator yet (plan §11.2)">
        Regimes: not in this strategy
      </span>
      <span className="lab-field muted" id="lab-events" title="no event feed is connected">
        Event windows: feed unavailable
      </span>
      <span className="lab-field muted" id="lab-partition" title="partitions arrive in Phase 5">
        {kind === 'opt' ? 'Partition: none (grid job)' : 'Partition: none (no partition on this experiment)'}
      </span>
      <span
        className={'status-chip' + (live ? ' live' : status === 'failed' || status === 'lost' ? ' error' : '')}
        id="lab-status"
        title={
          live
            ? `${status}: the numbers are provisional until it finishes (the snapshot time is when the counts arrived, UTC; they refresh every 2 s)`
            : status
              ? `${kind === 'opt' ? 'job' : 'experiment'} status`
              : 'nothing open'
        }
      >
        {live
          ? summary
            ? statusLabel(summary.snapshots.latest, summary.receivedAt, summary.counts.completed, summary.counts.scheduled)
            : 'PROVISIONAL · loading the counts'
          : (status ?? (loading ? 'loading' : 'no source'))}
      </span>
      {refreshError && <span className="error">refresh failed: {refreshError}</span>}
      <LinkedChip id="lab-linked" />
    </div>
  );
}
