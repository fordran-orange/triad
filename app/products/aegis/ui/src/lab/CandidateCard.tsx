// The candidate card in the rail's `#lab-selected` (spec §7.6): a tested trial's four robustness categories side by side,
// never summed, with no score and no overall label. Each is tested (resolved, with its classification) or unknown
// (unresolved, with the server's reason verbatim) and prints the inputs that decided it; the blocks' `selection-period
// consistency` sits beside C as an informational finding that never changes it. It replaces the Phase 1 line "temporal
// consistency: Phase 3". The decisions are `candidateModel.ts`'s; this asks for the `robustness` view with the trial and
// renders the model.
import { useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import type { LabEnvelope, LabRobustness } from '../results';
import { candidateCardModel, type CategoryView } from './candidateModel';
import { answered, isCandidateCard } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { LabError } from './NotBuilt';
import type { LabQueryData, Stamped } from './useLabQuery';

type Answer = { key: string; source: string; envelope: Stamped<LabEnvelope<LabRobustness>> };

function Category({ category }: { category: CategoryView }) {
  return (
    <section className="candidate-cat" id={`lab-candidate-${category.name}`} data-state={category.state} aria-label={`${category.name}: ${category.title}`}>
      <header className="candidate-head">
        <b>{category.name}</b> <span className="candidate-title">{category.title}</span>
        <span className="candidate-state" data-state={category.state}>
          {category.stateText}
        </span>
      </header>
      <div className="candidate-verdict" data-state={category.state}>
        {category.verdict}
      </div>
      <dl className="candidate-inputs">
        {category.inputs.map((input) => (
          <div key={input.label}>
            <dt>{input.label}</dt>
            <dd>{input.text}</dd>
          </div>
        ))}
      </dl>
      {category.notes.map((note) => (
        <div className="sub candidate-note" key={note}>
          {note}
        </div>
      ))}
      {category.findings.map((finding) => (
        <div className="candidate-finding" id={`lab-candidate-${category.name}-finding`} key={finding.name} title="informational: it never changes this category">
          <div className="sub">
            {finding.name} · informational, never changes {category.name}
          </div>
          <div className="candidate-verdict">{finding.verdict}</div>
          <dl className="candidate-inputs">
            {finding.lines.map((line) => (
              <div key={line.label}>
                <dt>{line.label}</dt>
                <dd>{line.text}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </section>
  );
}

/** The four categories of one trial of the open source. */
export function CandidateCard({ data, trialId }: { data: LabQueryData; trialId: string }) {
  const lab = useLab();
  const { query, tick } = data;
  // The card does not depend on the filter, but an answer that lands after the filter moved is discarded by `query`, and
  // the key moving is what asks again. B reads the finished importance: the count of importance tasks seen finished is part of
  // the mark, so the card asks again when one finishes (in the Importance tab, or in the background after it was left), and
  // so does every refresh while the source runs.
  const viewKey = [trialId, lab.metric, filterHash(lab.filter)].join('|');
  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = `${viewKey}|${tick}|${retry}|${data.importanceDone}`;
    if (asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    query<LabRobustness>('robustness', { trial: trialId })
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the card
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source: trialId, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the trial, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry, data.importanceDone]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, trialId);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const card = shown !== null && isCandidateCard(shown.envelope) ? shown.envelope.card : null;
  const model = useMemo(() => (card === null ? null : candidateCardModel(card)), [card]);
  const pending = error === null && current === null;

  return (
    <div className="candidate-card" id="lab-candidate" data-loading={pending ? 'true' : 'false'}>
      <div className="rail-title">Robustness · four categories</div>
      {error !== null && <LabError message={`Robustness unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {model === null ? (
        error === null && (
          <div className="muted" id="lab-candidate-loading">
            loading the four categories…
          </div>
        )
      ) : (
        <>
          <div className="sub" id="lab-candidate-summary">
            {model.summary} · never summed, no score
          </div>
          <div className="sub" id="lab-candidate-header">
            {model.trialLabel} · value <b className={model.valueLoses ? 'red' : undefined}>{model.value}</b> · τ {model.tau} · tolerance {model.tolerance}
            {model.toleranceLabel !== null ? ` (${model.toleranceLabel})` : ''}
          </div>
          <div className="candidate-grid">
            {model.categories.map((category) => (
              <Category key={category.name} category={category} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
