// Screen E's trellis (spec §5.5): the top pairs of parameters by the interactions' priority, each an aggregated matrix of at
// most TRELLIS_MAX_SIDE × TRELLIS_MAX_SIDE squares with its n. The pairs are the importance task's `interactions` view (a task
// view, asked through `useTaskView` exactly as the Interaction matrix tab asks it: it polls while the task runs and no longer,
// offers Cancel and Run again, and leaving this page creates no work), in the order the worker sent them; a pair it could not
// resolve is not drawn, and until a stage is delivered no pair is: nothing is guessed. Each pair's matrix is the worker's `matrix`
// view in aggregate mode (the median, or the mean where an axis is over the side limit and its squares are merged). A square
// under the floor (in trials, or in trials with a value) is hatched and carries no tone; an untested square is hatched and holds
// no value. A click picks a square, whose defining filter is the drill-down's (§7.8): its n is the `page` total of that filter.
// The floor, the side and the number of pairs are the worker's (`constants` of its answers); every decision is
// `familiesModel.ts`'s. A pair asks on mount and on a new key, at most every 30 s while the source runs and once more when it
// ends (`useAskMark`), never on the Lab's 2 s tick.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import type { LabEnvelope, LabInteractions, LabMatrix } from '../results';
import { AssumptionsLine } from './AssumptionsLine';
import {
  arrowTarget,
  cellTitle,
  countLabel,
  isPicked,
  pickOf,
  refreshedPick,
  rovingCell,
  trellisLegend,
  trellisModel,
  trellisPairs,
  trellisStat,
  type TrellisModel,
  type TrellisPairSpec,
  type TrellisPick,
} from './familiesModel';
import { stateNotice } from './importanceModel';
import { askFailure, panelLabel } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { metricName } from './metricRules';
import { LabError } from './NotBuilt';
import { axisLabel } from './parallelBundles';
import { TaskBar } from './TaskBar';
import { useAskMark } from './useAskMark';
import type { LabQueryData, Stamped } from './useLabQuery';
import { sourceFamilies, sourceLive } from './useLabSource';
import { useTaskView } from './useTaskView';

/** An answered matrix with the hash of the Lab's filter it was asked under (a pick takes it with its n). */
type Answer = { key: string; envelope: Stamped<LabEnvelope<LabMatrix>>; filterKey: string };

/** The squares of one pair as the DOM the walk reads: one button per square, carrying its exact trial count (`data-n`), the trials
 *  among them with a value (`data-defined`), its state (`untested`, `thin`, `undefined`, `ok`) and the two value ranges it stands
 *  for. A square with no trial is hatched and cannot be picked; a thin one is hatched without a tone and can. The grid is one
 *  tab stop (a roving tabindex: the picked square, else the first tested one, else wherever focus last was inside it); the arrow
 *  keys move between its squares, and Enter or Space picks the focused one. */
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
  const [focused, setFocused] = useState<{ r: number; c: number } | null>(null);
  const stop = focused !== null && model.cells[focused.r]?.[focused.c] !== undefined ? focused : rovingCell(model, pick);
  const move = (event: KeyboardEvent<HTMLButtonElement>, r: number, c: number) => {
    const to = arrowTarget(model.rows.length, model.cols.length, { r, c }, event.key);
    if (to === null) return;
    event.preventDefault();
    event.currentTarget.parentElement?.querySelector<HTMLElement>(`[data-r="${to.r}"][data-c="${to.c}"]`)?.focus();
  };
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
            data-defined={cell.defined}
            data-state={cell.state}
            data-r={cell.r}
            data-c={cell.c}
            data-rows={`${cell.rows.lo},${cell.rows.hi}`}
            data-cols={`${cell.cols.lo},${cell.cols.hi}`}
            aria-pressed={picked}
            aria-disabled={cell.n === 0}
            tabIndex={stop !== null && stop.r === cell.r && stop.c === cell.c ? 0 : -1}
            title={cellTitle(model, cell, metric)}
            onClick={() => cell.n > 0 && onPick(pickOf(index, model, cell))}
            onFocus={() => setFocused((was) => (was?.r === cell.r && was?.c === cell.c ? was : { r: cell.r, c: cell.c }))}
            onKeyDown={(event) => move(event, cell.r, cell.c)}
          >
            {cell.n > 0 ? countLabel(cell.n) : ''}
          </button>
        );
      })}
    </div>
  );
}

/** One pair: its matrix asked of the worker (a stale answer dropped, a failure with its own Retry unless the worker refused the
 *  request), drawn as a grid of squares. */
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
  const { loaded, query } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const [rows, cols] = spec.axes;
  const viewKey = source === null ? null : [source, rows, cols, stat, lab.metric, filterHash(lab.filter)].join('|');
  // The pair asks on mount and on a new key, at most every 30 s while the source runs, and once when it ends.
  const askMark = useAskMark(viewKey, sourceLive(loaded));
  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string; refused: boolean } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${askMark}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null) return;
    const under = filterHash(lab.filter);
    query<LabMatrix>('matrix', { rows, cols, mode: 'aggregate', stat })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer ask owns the pair, or the filter moved on
        setAnswer({ key: viewKey, envelope, filterKey: under });
        setFailure(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailure({ key: viewKey, ...askFailure(e) }));
    // The key stands for the source, the pair, the statistic, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, askMark, retry]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const error = failure !== null && failure.key === viewKey ? failure : null;
  const model: TrellisModel | null = useMemo(
    () => (current === null ? null : trellisModel(current.envelope, stat, lab.metric, current.envelope.constants, current.envelope.snapshot, current.filterKey)),
    [current, stat, lab.metric],
  );

  // A running source moves the picked square's n, and a brush moves the filter it was read under: the pick takes the new n with its
  // snapshot and filter, so the drill-down compares against it.
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
      {error !== null && <LabError message={`${spec.label}: matrix unavailable: ${error.message}`} onRetry={error.refused ? undefined : () => setRetry((n) => n + 1)} />}
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

/** The trellis: the top pairs, each its own matrix. `pick` is the picked square (the Lab's store keeps it, so the drill-down and
 *  the neighbourhood map read it) and `onPick` replaces it. */
export function Trellis({ data, pick, onPick }: { data: LabQueryData; pick: TrellisPick | null; onPick: (pick: TrellisPick) => void }) {
  const lab = useLab();
  const task = useTaskView<LabInteractions>(data, 'interactions');
  const { shown, error, pending, current } = task;
  const view = shown?.envelope ?? null;
  // The floor, the side and the number of pairs are the worker's: nothing is drawn before an answer carries them.
  const constants = view?.constants ?? null;
  const pairs = trellisPairs(view, constants?.TRELLIS_PAIRS ?? 0);
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
        {trellisLegend(lab.metric, constants)}
      </div>
      <AssumptionsLine panel="trellis" uniform />
      <div className="trellis-pairs" id="lab-families-pairs">
        {constants !== null &&
          pairs.pairs.map((spec, index) => (
            <Pair key={spec.axes.join('|')} data={data} spec={spec} index={index} stat={trellisStat(lengthOf(spec.axes[0]), lengthOf(spec.axes[1]), constants.TRELLIS_MAX_SIDE)} pick={pick} onPick={onPick} />
          ))}
      </div>
    </div>
  );
}
