// Trial Lab's Robustness (A–D) tab (spec §7.6): the filter's two rankings side by side. `peak` ranks by the metric
// alone; `robust` ranks lexicographically over the resolved categories (A, or B where A is unresolved and labelled so,
// then C, then D; unresolved sorts last and never counts), the metric breaking a tie. When they disagree the panel says
// so and names the stable candidate, or prints the worker's reason for there being none. Each row shows its value (real
// units) beside its classification or its reason, because §7.6's order can rank a low-value stable cell above a
// high-value unresolved one. A click selects the trial, whose four categories the rail's candidate card then shows. Every
// decision is `robustnessModel.ts`'s.
import { useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import type { LabEnvelope, LabRobustness } from '../results';
import { isCandidateCard, answered, panelLabel } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { LabError } from './NotBuilt';
import { axesLine, classTone, rankingRows, robustSummary, toleranceLine, type RankedRow } from './robustnessModel';
import type { LabQueryData, Stamped } from './useLabQuery';
import { metricName } from './labHeatmapModel';
import { usePickTrial } from './usePickTrial';

type Answer = { key: string; source: string; metric: string; envelope: Stamped<LabEnvelope<LabRobustness>> };

function List({ id, title, hint, rows, selected, onPick }: { id: string; title: string; hint: string; rows: RankedRow[]; selected: string | null; onPick: (trialId: string) => void }) {
  return (
    <section className="robust-list" id={id} aria-label={title}>
      <div className="rail-title">{title}</div>
      <div className="sub">{hint}</div>
      {rows.length === 0 ? (
        <div className="lab-empty">no candidates</div>
      ) : (
        <ol className="robust-rows">
          {rows.map((row) => (
            <li key={row.trialId}>
              <button
                type="button"
                className={'robust-row' + (selected === row.trialId ? ' selected' : '') + (row.stable ? ' stable' : '')}
                data-trial={row.trialId}
                data-state={row.state}
                data-tone={classTone(row.state, row.state === 'resolved' ? row.classification : null)}
                data-ranked-by={row.rankedBy ?? ''}
                onClick={() => onPick(row.trialId)}
                title={`${row.trialLabel} · ${row.valueText} · ${row.classification}`}
              >
                <span className="robust-place">{row.place}</span>
                <span className="robust-trial">{row.trialLabel}</span>
                <span className={'robust-value' + (row.loses ? ' red' : '')}>{row.valueText}</span>
                <span className="robust-class">
                  {row.state === 'resolved' ? row.classification : <span className="robust-reason">{row.classification}</span>}
                  {row.rankedBy !== null && <> <span className="robust-by">by {row.rankedBy}</span></>}
                  {row.stable && <> <span className="robust-stable">stable</span></>}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function RobustnessView({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const pick = usePickTrial(data);
  const { loaded, query, tick } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const metric = lab.metric;
  const viewKey = source === null ? null : ['robustness', source, metric, filterHash(lab.filter)].join('|');

  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${tick}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null || source === null) return;
    setAsking(true);
    query<LabRobustness>('robustness', {})
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the view
        setAsking(false);
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source, metric, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setAsking(false);
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the source, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const envelope = shown?.envelope ?? null;
  // Without a `trial` the view answers the rankings; a card here would be another panel's answer.
  const rankings = envelope !== null && !isCandidateCard(envelope) ? envelope.rankings : null;
  const askedMetric = shown?.metric ?? metric;

  const rows = useMemo(
    () => ({
      peak: rankings === null ? [] : rankingRows(rankings, 'peak', askedMetric),
      robust: rankings === null ? [] : rankingRows(rankings, 'robust', askedMetric),
    }),
    [rankings, askedMetric],
  );
  const summary = rankings === null ? null : robustSummary(rankings, askedMetric);
  const selected = lab.selected !== null && 'trials' in lab.selected && lab.selected.trials.length === 1 ? lab.selected.trials[0] : null;
  const pending = loaded === null ? data.loading : viewKey !== null && error === null && (current === null || asking);

  return (
    <div className="lab-robustness" id="lab-robustness" data-loading={pending ? 'true' : 'false'}>
      <div className="robustness-toolbar">
        <span className="lab-basis" id="lab-robustness-basis">
          {envelope !== null ? `${envelope.scope.basis}${panelLabel(envelope)}` : ''}
        </span>
        {pending && (
          <span className="sub lab-loading" id="lab-robustness-loading">
            {loaded === null ? 'loading the source…' : 'loading the rankings…'}
          </span>
        )}
      </div>
      {error !== null && <LabError message={`Robustness unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {envelope !== null && envelope.empty !== null && <div className="lab-empty">{envelope.empty}</div>}
      {rankings !== null && envelope !== null && summary !== null && (
        <>
          <div className="robustness-summary">
            {summary.agreement !== '' && (
              <div id="lab-robustness-agreement" data-disagree={summary.disagree ? 'true' : 'false'} className={summary.disagree ? 'lab-warn' : ''}>
                {summary.agreement}
              </div>
            )}
            <div id="lab-robustness-stable" data-trial={summary.stableId ?? ''}>
              {summary.stable}
            </div>
            <div className="sub" id="lab-robustness-tolerance">
              {toleranceLine(envelope.tolerance, envelope.tolerance_label)} · {metricName(askedMetric)}
            </div>
            <div className="sub" id="lab-robustness-axes">
              {axesLine(envelope.axes)}
            </div>
          </div>
          <div className="robustness-lists">
            <List
              id="lab-robustness-peak"
              title={`Peak · ${metricName(askedMetric)} alone`}
              hint="ranked by the metric, whatever its surroundings"
              rows={rows.peak}
              selected={selected}
              onPick={pick}
            />
            <List
              id="lab-robustness-robust"
              title="Robust · A, else B, then C, then D"
              hint="stable cells first; an unresolved category sorts last and never counts; the metric breaks a tie"
              rows={rows.robust}
              selected={selected}
              onPick={pick}
            />
          </div>
        </>
      )}
    </div>
  );
}
