// Screen E's trellis (spec §5.5): the top pairs of parameters by the interactions' priority, each an aggregated matrix of at
// most 16 × 16 squares with its n. The pairs are the importance task's `interactions` view (a task view, asked through
// `useTaskView` exactly as the Interaction matrix tab asks it: it polls while the task runs and no longer, offers Cancel and Run
// again, and leaving this page creates no work), in the order the worker sent them; a pair it could not resolve is not drawn, and
// until a stage is delivered no pair is: nothing is guessed. Each pair's matrix is the worker's `matrix` view in aggregate mode
// (the median, or the mean where an axis is over 16 values and its squares are merged). A square under 30 trials is hatched and
// carries no tone; an untested square is hatched and holds no value. A click picks a square, whose defining filter is the
// drill-down's (§7.8): its n is the `page` total of that filter. Every decision is `familiesModel.ts`'s.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { errorMessage } from '../api/client';
import type { LabEnvelope, LabInteractions, LabMatrix } from '../results';
import { stateNotice } from './importanceModel';
import {
  cellTitle,
  countLabel,
  isPicked,
  pickOf,
  refreshedPick,
  TRELLIS_MAX_SIDE,
  TRELLIS_MIN_N,
  trellisModel,
  trellisPairs,
  trellisStat,
  type TrellisModel,
  type TrellisPairSpec,
  type TrellisPick,
} from './familiesModel';
import { panelLabel } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { metricName } from './metricRules';
import { LabError } from './NotBuilt';
import { axisLabel } from './parallelBundles';
import { TaskBar } from './TaskBar';
import type { LabQueryData, Stamped } from './useLabQuery';
import { useTaskView } from './useTaskView';
import { sourceFamilies } from './useLabSource';

type Answer = { key: string; envelope: Stamped<LabEnvelope<LabMatrix>> };

/** The squares of one pair as the DOM the walk reads: one button per square, carrying its exact trial count (`data-n`), its state
 *  (`untested`, `thin`, `undefined`, `ok`) and the two value ranges it stands for. A square with no trial is hatched and cannot
 *  be picked; a thin one is hatched without a tone and can. */
export function TrellisGrid({
  model,
  index,
  label,
  pick,
  metric,
  onPick,
}: {
  model: TrellisModel;
  index: number;
  label: string;
  pick: TrellisPick | null;
  metric: string;
  onPick: (pick: TrellisPick) => void;
}) {
  return (
    <div className="trellis-grid" role="group" aria-label={`${label}: ${model.summary}`}>
      {model.cells.flat().map((cell) => {
        const picked = isPicked(pick, model, cell);
        const className = ['cell', 'trellis-cell', cell.tone === 'mid' ? '' : cell.tone, cell.state === 'untested' ? 'hatched' : '', picked ? 'selected' : ''].filter(Boolean).join(' ');
        return (
          <button
            type="button"
            key={`${cell.r}-${cell.c}`}
            id={`lab-families-cell-${index}-${cell.r}-${cell.c}`}
            className={className}
            data-n={cell.n}
            data-state={cell.state}
            data-r={cell.r}
            data-c={cell.c}
            data-rows={`${cell.rows.lo},${cell.rows.hi}`}
            data-cols={`${cell.cols.lo},${cell.cols.hi}`}
            aria-pressed={picked}
            aria-disabled={cell.n === 0}
            title={cellTitle(model, cell, metric)}
            onClick={() => cell.n > 0 && onPick(pickOf(index, model, cell))}
          >
            {cell.n > 0 ? countLabel(cell.n) : ''}
          </button>
        );
      })}
    </div>
  );
}

/** One pair: its matrix asked of the worker (a stale answer dropped, a failure with its own Retry), drawn as a grid of squares. */
function Pair({
  data,
  spec,
  index,
  stat,
  pick,
  onPick,
}: {
  data: LabQueryData;
  spec: TrellisPairSpec;
  index: number;
  stat: 'median' | 'mean';
  pick: TrellisPick | null;
  onPick: (pick: TrellisPick) => void;
}) {
  const lab = useLab();
  const { loaded, query, tick } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const [rows, cols] = spec.axes;
  const viewKey = source === null ? null : [source, rows, cols, stat, lab.metric, filterHash(lab.filter)].join('|');
  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${tick}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null) return;
    query<LabMatrix>('matrix', { rows, cols, mode: 'aggregate', stat })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer ask owns the pair, or the filter moved on
        setAnswer({ key: viewKey, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailure({ key: viewKey, message: errorMessage(e) }));
    // The key stands for the source, the pair, the statistic, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const model: TrellisModel | null = useMemo(() => (current === null ? null : trellisModel(current.envelope, stat, lab.metric)), [current, stat, lab.metric]);

  // A running source moves the picked square's n: the pick takes the new one, so the drill-down compares against it.
  useEffect(() => {
    if (model === null || pick === null) return;
    const next = refreshedPick(pick, model);
    if (next !== pick) onPick(next);
  }, [model, pick, onPick]);

  const label = (path: string, values: { lo: number; hi: number }[]) => (values.length === 0 ? axisLabel(path) : `${axisLabel(path)} ${values[0].lo}–${values[values.length - 1].hi}`);
  return (
    <section
      className="trellis-pair"
      id={`lab-families-pair-${index}`}
      data-pair={index}
      data-rows={rows}
      data-cols={cols}
      data-stat={stat}
      data-merged={model?.merged ? 'true' : 'false'}
      data-total={model?.total ?? ''}
      data-loading={current === null && error === null ? 'true' : 'false'}
      style={{ '--trellis-cols': model?.cols.length ?? 1 } as CSSProperties}
    >
      <header className="trellis-head">
        <b title={`${rows} × ${cols}`}>{spec.label}</b>
        <span className="sub" title="Δ is what one parameter adds beyond the other: the larger of the pair's two increments, the importance task's priority for the pair">
          {spec.priority}
          {model !== null ? ` · ${model.stat} of ${metricName(lab.metric)}` : ''}
        </span>
      </header>
      {error !== null && <LabError message={`${spec.label}: matrix unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {model === null && error === null && <div className="lab-empty trellis-loading">loading the matrix…</div>}
      {model !== null && current !== null && (
        <>
          <div className="sub trellis-axes">
            rows {label(rows, model.rows)} ↓ · columns {label(cols, model.cols)} →
          </div>
          <TrellisGrid model={model} index={index} label={spec.label} pick={pick} metric={lab.metric} onPick={onPick} />
          <div className="sub trellis-basis" id={`lab-families-pair-${index}-basis`}>
            {current.envelope.basis}
            {panelLabel(current.envelope)} · {model.summary}
          </div>
          {model.valueNote !== null && <div className="sub trellis-note">{model.valueNote}</div>}
        </>
      )}
    </section>
  );
}

/** The trellis: the top pairs, each its own matrix. `pick` is the picked square (lifted to the page, so the drill-down and the
 *  neighbourhood map read it) and `onPick` replaces it. */
export function Trellis({ data, pick, onPick }: { data: LabQueryData; pick: TrellisPick | null; onPick: (pick: TrellisPick) => void }) {
  const lab = useLab();
  const task = useTaskView<LabInteractions>(data, 'interactions');
  const { shown, error, pending, current } = task;
  const view = shown?.envelope ?? null;
  const pairs = trellisPairs(view);
  // How many values each axis has, to know which pairs will merge: the catalog's own counts.
  const counts = useMemo(() => new Map((data.loaded ? sourceFamilies(data.loaded) : []).flatMap((f) => f.entries.map((e) => [e.path, e.count] as const))), [data.loaded]);
  const lengthOf = (path: string) => counts.get(path) ?? counts.get(path.replace(/^(long|short)_side\./, '')) ?? null;
  const notice = view === null || view.computed !== null ? null : stateNotice({ importance: null, task: view.task, reason: view.reason });
  const partial = view !== null && view.computed !== null && view.computed.partial ? `PARTIAL · stage ${view.computed.stage} of ${view.computed.stages}` : null;

  return (
    <div className="lab-trellis" id="lab-families-trellis" data-loading={pending ? 'true' : 'false'} data-pairs={pairs.pairs.length}>
      <div className="trellis-toolbar">
        <span className="lab-basis" id="lab-families-trellis-basis">
          {view !== null ? `${view.scope.basis}${panelLabel(view)}` : ''}
        </span>
        {partial !== null && (
          <span className="status-chip live" id="lab-families-trellis-partial">
            {partial}
          </span>
        )}
        {view !== null && view.snapshot_label !== null && (
          <span className="sub" id="lab-families-trellis-snapshot">
            {view.snapshot_label}
          </span>
        )}
        {pending && (
          <span className="sub lab-loading" id="lab-families-trellis-loading">
            {data.loaded === null ? 'loading the source…' : 'loading the pairs…'}
          </span>
        )}
      </div>
      <TaskBar id="lab-families-task" task={current?.envelope.task ?? null} cancelling={task.cancelling} rerunning={task.rerunning} error={task.stopError} onCancel={() => void task.cancel()} onRerun={task.runAgain} />
      {error !== null && <LabError message={`Pairs unavailable: ${error}${task.pollStopped !== null ? ` · ${task.pollStopped}` : ''}`} onRetry={task.retry} />}
      {notice !== null && (
        <div className="lab-empty" id="lab-families-trellis-notice" data-kind={notice.kind}>
          {notice.text}
        </div>
      )}
      {pairs.line !== '' && (
        <div className="sub" id="lab-families-pairs-line">
          {pairs.line}
        </div>
      )}
      <div className="sub" id="lab-families-legend">
        Each square is the {metricName(lab.metric)} of the trials with its two values (the median; the mean where an axis has more than {TRELLIS_MAX_SIDE} values and its squares are merged), a loss is red · hatched and without a colour = under{' '}
        {TRELLIS_MIN_N} trials, left out (n is shown) · hatched and empty = untested · the number on a square is its n · click a square for its trials.
      </div>
      <div className="trellis-pairs" id="lab-families-pairs">
        {pairs.pairs.map((spec, index) => (
          <Pair key={spec.axes.join('|')} data={data} spec={spec} index={index} stat={trellisStat(lengthOf(spec.axes[0]), lengthOf(spec.axes[1]))} pick={pick} onPick={onPick} />
        ))}
      </div>
    </div>
  );
}
