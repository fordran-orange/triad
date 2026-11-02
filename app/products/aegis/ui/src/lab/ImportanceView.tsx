// Trial Lab's Importance tab (spec §7.3, §7.4a): the ranked list of the parameters with the three uncertainties side by
// side in each row (the bootstrap whisker, the block range and the detection floor tick), the labels and statuses the
// worker recommends, the availability of the rule and its veto, and the caveat that conditions every share. The worker
// computes it as a background task in three stages; this asks for the view, polls while the task runs (useTaskView),
// and draws what the response says. Every decision is `importanceModel.ts`'s. Condition 6 of §7.4a (the operator's
// confirmation) is Phase 4, so nothing here applies or proposes anything.
import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import type { LabImportance } from '../results';
import { AXIS_COLOUR, drawWhisker, linearScale, setupCanvas } from './charts/canvas';
import { axisMax, availabilityText, caveatOf, constantsLine, importanceRows, partialLabel, sampleLine, stateNotice, type ImportanceRow, type RowMarks } from './importanceModel';
import { metricName } from './metricRules';
import { displayShare, panelLabel } from './labQuery';
import { axisLabel } from './parallelBundles';
import { AssumptionsLine } from './AssumptionsLine';
import { LabError } from './NotBuilt';
import { TaskBar } from './TaskBar';
import type { LabQueryData } from './useLabQuery';
import { useTaskView } from './useTaskView';

const MARKS_W = 190;
const MARKS_H = 28;
const PAD = 4;
const WHISKER = '#2da7ff';
const BLOCK = '#b784ff';
const FLOOR = '#f5bd51';
const NULL_TICK = '#7690a3';

/** Paints one row's three marks on a shared 0..`max` axis: the 90 % whisker with the share on it, the block range as a
 *  bar under it, and the detection floor as a tall tick with the null's 95th percentile as a short one. Clamped at 0 (the
 *  stored value is not). */
function paintMarks(canvas: HTMLCanvasElement, marks: RowMarks, max: number): void {
  const ctx = setupCanvas(canvas, MARKS_W, MARKS_H);
  const x = linearScale([0, max], [PAD, MARKS_W - PAD]);
  const at = (v: number) => x(Math.min(Math.max(displayShare(v), 0), max));
  ctx.strokeStyle = AXIS_COLOUR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(Math.round(x(0)) + 0.5, 2);
  ctx.lineTo(Math.round(x(0)) + 0.5, MARKS_H - 2);
  ctx.stroke();
  if (marks.tick !== null) {
    ctx.strokeStyle = NULL_TICK;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(at(marks.tick), 9);
    ctx.lineTo(at(marks.tick), MARKS_H - 9);
    ctx.stroke();
  }
  if (marks.floor !== null) {
    ctx.strokeStyle = FLOOR;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(at(marks.floor), 3);
    ctx.lineTo(at(marks.floor), MARKS_H - 3);
    ctx.stroke();
  }
  if (marks.block !== null) {
    const a = at(marks.block[0]);
    const b = at(marks.block[1]);
    ctx.fillStyle = BLOCK;
    ctx.fillRect(Math.min(a, b), MARKS_H - 10, Math.max(Math.abs(b - a), 2), 5);
  }
  if (marks.lo !== null && marks.hi !== null) drawWhisker(ctx, x, 9, Math.min(Math.max(displayShare(marks.lo), 0), max), Math.min(Math.max(displayShare(marks.hi), 0), max), WHISKER, 4);
  if (marks.share !== null) {
    ctx.fillStyle = '#f4f8fb';
    ctx.beginPath();
    ctx.arc(at(marks.share), 9, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

function Marks({ row, max }: { row: ImportanceRow; max: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const marks = row.marks;
  // Every number of the marks, not the row's text: the text rounds to 0.1 %, and two answers can differ below that.
  const marksKey = marks === null ? '' : JSON.stringify(marks);
  useEffect(() => {
    if (canvas.current !== null && marks !== null) paintMarks(canvas.current, marks, max);
    // The key stands for the marks' numbers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marksKey, max]);
  if (marks === null) return <span className="importance-marks importance-unmeasured" aria-hidden="true" />;
  return <canvas className="importance-marks" ref={canvas} role="img" aria-label={`${axisLabel(row.path)}: ${row.text}`} title={row.text} />;
}

function Row({ row, max }: { row: ImportanceRow; max: number }) {
  return (
    <li
      className={'importance-row' + (row.resolved ? '' : ' unresolved')}
      id={`lab-importance-row-${row.index}`}
      data-path={row.path}
      data-param={row.paramIndex}
      data-label={row.label}
      data-resolved={row.resolved ? 'true' : 'false'}
      data-status-kind={row.statusKind}
    >
      <span className="importance-rank">{row.rank ?? '—'}</span>
      <span className="importance-name" title={row.path}>
        {axisLabel(row.path)}
      </span>
      <Marks row={row} max={max} />
      <span className="importance-numbers">{row.resolved ? row.text : `${row.label}: not ranked`}</span>
      <span className="importance-status" data-kind={row.statusKind}>
        {row.status}
      </span>
      {row.reason !== '' && <span className="importance-reason sub">{row.reason}</span>}
      {row.flags.length > 0 && <span className="importance-flags sub">{row.flags.join(' · ')}</span>}
      {row.failing !== null && <span className="importance-failing sub">{row.failing}</span>}
    </li>
  );
}

/** The Importance tab. `children` is the existing report's main effects, kept below the new estimators (the plan keeps the
 *  report and labels the new ones as additional). */
export function ImportanceView({ data, children }: { data: LabQueryData; children?: ReactNode }) {
  const task = useTaskView<LabImportance>(data, 'importance');
  const { shown, error, pending, current } = task;
  const view = shown?.envelope ?? null;
  const result = view?.importance ?? null;
  const rows = useMemo(() => (result === null ? [] : importanceRows(result)), [result]);
  const max = axisMax(rows);
  const notice = view === null ? null : stateNotice(view);
  const partial = result === null ? null : partialLabel(result);
  const sample = result === null ? '' : sampleLine(result);

  return (
    <div className="lab-importance" id="lab-importance" data-loading={pending ? 'true' : 'false'}>
      <div className="importance-toolbar">
        <span className="lab-basis" id="lab-importance-basis">
          {view !== null ? `${view.scope.basis}${panelLabel(view)}` : ''}
        </span>
        {partial !== null && (
          <span className="status-chip live" id="lab-importance-partial">
            {partial}
          </span>
        )}
        {view !== null && view.snapshot_label !== null && (
          <span className="sub" id="lab-importance-snapshot" title="the newest finished result is of an earlier snapshot of this experiment">
            {view.snapshot_label}
          </span>
        )}
        {pending && (
          <span className="sub lab-loading" id="lab-importance-loading">
            {data.loaded === null ? 'loading the source…' : 'loading the importance…'}
          </span>
        )}
      </div>
      <AssumptionsLine panel="importance" uniform />
      <TaskBar id="lab-importance-task" task={current?.envelope.task ?? null} cancelling={task.cancelling} rerunning={task.rerunning} error={task.stopError} onCancel={() => void task.cancel()} onRerun={task.runAgain} />
      {error !== null && <LabError message={`Importance unavailable: ${error}${task.pollStopped !== null ? ` · ${task.pollStopped}` : ''}`} onRetry={task.retry} />}
      {notice !== null && (
        <div className="lab-empty" id="lab-importance-notice" data-kind={notice.kind}>
          {notice.text}
        </div>
      )}
      {view !== null && view.empty !== null && result === null && <div className="lab-empty">{view.empty}</div>}
      {result !== null && (
        <>
          <div className="sub" id="lab-importance-result">
            Importance of {metricName(result.metric)} · {result.scope} scope · seed {result.seed} · {result.elapsed_s} s
            {sample !== '' ? ` · ${sample}` : ''}
          </div>
          <div className="importance-availability" id="lab-importance-availability" data-available={result.availability.available ? 'true' : 'false'}>
            {availabilityText(result)}
          </div>
          {result.availability.hint !== null && (
            <div className="sub" id="lab-importance-hint">
              hint: {result.availability.hint}
            </div>
          )}
          {result.veto !== null && (
            <div className="lab-warn" id="lab-importance-veto" role="alert">
              {result.veto}
            </div>
          )}
          {result.warnings.length > 0 && (
            <ul className="lab-warnings" id="lab-importance-warnings">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          {result.note !== null && (
            <div className="sub" id="lab-importance-missing">
              {result.note}
            </div>
          )}
          <div className="importance-legend" id="lab-importance-legend">
            <span>
              <i className="mark whisker" /> {result.uncertainty.design}
            </span>
            <span>
              <i className="mark block" /> {result.uncertainty.period}
            </span>
            <span>
              <i className="mark floor" /> {result.uncertainty.detection}
            </span>
            <span>
              <i className="mark tick" /> the null&apos;s 95th percentile of this share
            </span>
          </div>
          <div className="sub" id="lab-importance-axis">
            Marks are shares of the variance of {metricName(result.metric)}, from 0 % at the left to {Math.round(max * 1000) / 10} % at the right; a share below 0 is shown as 0.
          </div>
          <ol className="importance-list" id="lab-importance-list">
            {rows.map((row) => (
              <Row key={row.path} row={row} max={max} />
            ))}
          </ol>
          <div className="sub" id="lab-importance-constants">
            {constantsLine(result.constants)}
          </div>
        </>
      )}
      <div className="importance-caveat" id="lab-importance-caveat">
        {caveatOf(result)}
      </div>
      {children}
    </div>
  );
}
