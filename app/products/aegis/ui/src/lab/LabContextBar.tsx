import { DASH } from '../format';
import { METRICS, METRIC_LABELS, OBJECTIVES, OBJECTIVE_LABELS } from '../results';
import { useLab, useLabDispatch } from './labState';
import { parseSource, sourceText, type LabScope } from './labStore';
import { LinkedChip } from './LinkedChip';
import { isLive, statusOf, type LabData } from './useLabSource';

const SCOPES: Array<{ key: 'long' | 'short' | 'both'; scope: LabScope; label: string }> = [
  { key: 'long', scope: 'long', label: 'Long' },
  { key: 'short', scope: 'short', label: 'Short' },
  { key: 'both', scope: 'combined', label: 'Both' },
];

/** The Lab's context toolbar: what is open (source, strategy, parent, data), the direction and metric the panels
 *  read, the states the strategy and the data do not carry yet, the run status and the linked filter. */
export function LabContextBar({ data }: { data: LabData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { experiments, listError, loaded, loading, refreshError, optSources } = data;
  const value = lab.source ? sourceText(lab.source) : '';
  const kind = loaded?.kind ?? lab.source?.kind ?? 'exp';
  const listed = value === '' || optSources.some((id) => `opt:${id}` === value) || (experiments ?? []).some((e) => `exp:${e.id}` === value);

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
  const status = loaded ? statusOf(loaded) : null;
  const live = status !== null && isLive(status);
  const metrics: Array<{ value: string; label: string }> =
    kind === 'opt' ? METRICS.map((m) => ({ value: m, label: METRIC_LABELS[m] })) : OBJECTIVES.map((m) => ({ value: m, label: OBJECTIVE_LABELS[m] }));

  return (
    <div className="lab-context" id="lab-context">
      <label className="lab-field">
        Source
        <select id="lab-source" value={value} aria-label="Source" onChange={(e) => open(e.target.value)}>
          <option value="" disabled>
            {experiments === null ? 'Loading experiments…' : 'Choose an experiment'}
          </option>
          {!listed && <option value={value}>{value}</option>}
          {optSources.map((id) => (
            <option key={id} value={`opt:${id}`}>
              Grid job {id.slice(0, 8)} (from the dock)
            </option>
          ))}
          {(experiments ?? []).map((e) => (
            <option key={e.id} value={`exp:${e.id}`}>
              {e.name} · {e.status}
            </option>
          ))}
        </select>
      </label>
      {lab.sourceError && (
        <span className="error" id="lab-source-error" role="alert">
          Could not open {lab.sourceError}
        </span>
      )}
      {listError && <span className="error">Experiments unavailable: {listError}</span>}
      <span className="lab-field" id="lab-strategy" title={job ? 'the strategy the job was planned from' : 'the strategy document the experiment pinned'}>
        Strategy <b>{strategy ?? (loading ? 'loading…' : DASH)}</b>
      </span>
      {doc?.parent && (
        <button type="button" className="chip" id="lab-parent" title="Open the experiment this one refines" onClick={() => open(`exp:${doc.parent}`)}>
          refines {doc.parent}
        </button>
      )}
      <span className="lab-field" id="lab-dataset">
        Data <b>{dataset ?? (loading ? 'loading…' : DASH)}</b>
      </span>
      <span className="lab-scope" role="group" aria-label="Direction">
        {SCOPES.map((s) => (
          <button
            type="button"
            key={s.key}
            id={`lab-scope-${s.key}`}
            className={'chip' + (lab.filter.scope === s.scope ? ' active' : '')}
            aria-pressed={lab.filter.scope === s.scope}
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
          {metrics.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
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
        title={live ? `${status}: the numbers are provisional until it finishes` : status ? `${kind === 'opt' ? 'job' : 'experiment'} status` : 'nothing open'}
      >
        {live ? 'PROVISIONAL · updates every 2 s' : (status ?? (loading ? 'loading' : 'no source'))}
      </span>
      {refreshError && <span className="error">refresh failed: {refreshError}</span>}
      <LinkedChip id="lab-linked" />
    </div>
  );
}
