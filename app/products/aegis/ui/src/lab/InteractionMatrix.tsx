// Trial Lab's Interaction matrix tab (spec §7.4): the d × d matrix of the joint shares J of every pair of parameters
// from the importance task's fine grid, with Δ (what one parameter adds beyond the other) on hover. A pair whose value
// grid is too thinly covered is unresolved: its square is hatched, never shaded, and it is listed below in the order the
// worker sent. `I`, the interaction term, has no interval (display only: no rule reads it). Every decision is
// `interactionModel.ts`'s; the matrix is one canvas redrawn whole on a hover (a few hundred squares). The task is the
// importance task's, so the line, Cancel and Run again are the Importance tab's.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import type { LabInteractions } from '../results';
import { CHART_FONT, fitText, HitGrid, hatchPattern, LABEL_COLOUR, observeResize, outlineRect, setupCanvas } from './charts/canvas';
import { hoverText, interactionModel, jBasisLine, matrixLayout, matrixSummary, squareLook, truncatedNotice, unresolvedText, type InteractionModel } from './interactionModel';
import { displayShare, panelLabel } from './labQuery';
import { axisLabel } from './parallelBundles';
import { LabError } from './NotBuilt';
import { TaskBar } from './TaskBar';
import type { LabQueryData } from './useLabQuery';
import { useTaskView } from './useTaskView';
import { stateNotice } from './importanceModel';

const SHADE = [45, 167, 255]; // J's blue: a variance share carries no profit sign, so none of it is red or green
const HATCH_FILL = '#0f1a24';
const HATCH_STRIPE = '#2c3d4b';
const FLAG = '#f5bd51';
const HOVER = '#d8e5ef';
type At = { r: number; c: number };

/** Paints the whole matrix: the names, then every square (shaded by J, hatched when unresolved, blank where no pair was
 *  sent), the unbalanced corners, the detected-Δ dots, and the hover. */
function paint(canvas: HTMLCanvasElement, width: number, height: number, model: InteractionModel, hover: At | null): void {
  const ctx = setupCanvas(canvas, width, height);
  const L = matrixLayout(width, model.size);
  if (L.cell <= 0) return;
  const { cell } = L;
  const hatch = hatchPattern(ctx, HATCH_FILL, HATCH_STRIPE);
  ctx.font = CHART_FONT;
  ctx.fillStyle = LABEL_COLOUR;
  for (let i = 0; i < model.size; i++) {
    const name = axisLabel(model.labels[i]);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, L.x0 - 6, L.y0 + i * cell + cell / 2, L.x0 - 12);
    ctx.save();
    ctx.translate(L.x0 + i * cell + cell / 2, L.y0 - 6);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, 0, 0, L.y0 - 12);
    ctx.restore();
  }
  const gap = cell >= 6 ? 1 : 0;
  for (let r = 0; r < model.size; r++)
    for (let c = 0; c < model.size; c++) {
      const x = L.x0 + c * cell;
      const y = L.y0 + r * cell;
      const at = model.cells[r][c];
      const look = squareLook(at, model.maxJ);
      if (at === null || look.kind === 'outline') {
        // The diagonal, a pair the worker did not send, or a resolved pair with no J: an outline, never a value and never the
        // hatch of low coverage.
        ctx.strokeStyle = HATCH_STRIPE;
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, cell - gap - 1, cell - gap - 1);
        continue;
      }
      ctx.fillStyle = look.kind === 'hatch' ? hatch : `rgba(${SHADE[0]}, ${SHADE[1]}, ${SHADE[2]}, ${0.12 + 0.78 * look.t})`;
      ctx.fillRect(x, y, cell - gap, cell - gap);
      if (at.pair.unbalanced) {
        const k = Math.max(3, Math.min(8, cell / 3));
        ctx.fillStyle = FLAG;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + k, y);
        ctx.lineTo(x, y + k);
        ctx.closePath();
        ctx.fill();
      }
      if (!at.pair.unresolved && at.pair[at.own].detected) {
        ctx.fillStyle = '#f4f8fb';
        ctx.beginPath();
        ctx.arc(x + cell - gap - 4, y + cell - gap - 4, 2, 0, Math.PI * 2);
        ctx.fill();
      }
      if (look.kind === 'shade' && cell >= 30) {
        ctx.font = CHART_FONT;
        ctx.fillStyle = look.t > 0.55 ? '#071018' : '#d8e5ef';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        fitText(ctx, `${Math.round(displayShare(at.pair.J.value ?? 0) * 100)}%`, x + (cell - gap) / 2, y + (cell - gap) / 2, cell - 4);
      }
    }
  if (hover !== null) outlineRect(ctx, L.x0 + hover.c * cell, L.y0 + hover.r * cell, cell - gap, cell - gap, HOVER, 2);
}

export function InteractionMatrix({ data }: { data: LabQueryData }) {
  const task = useTaskView<LabInteractions>(data, 'interactions');
  const { shown, error, pending, current } = task;
  const view = shown?.envelope ?? null;
  const model = useMemo(() => (view === null ? null : interactionModel(view)), [view]);
  const notice = view === null || model !== null ? null : stateNotice({ importance: null, task: view.task, reason: view.reason });
  const truncated = view === null ? null : truncatedNotice(view);
  const summary = view === null ? '' : matrixSummary(view);

  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<At | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w) => setWidth((prev) => (prev === w ? prev : w)));
  }, []);
  const size = model?.size ?? 0;
  const layout = matrixLayout(width, size);
  useEffect(() => {
    const el = canvas.current;
    if (el === null || model === null) return;
    paint(el, width, layout.height, model, hover);
    // The model, the width and the hover stand for what is drawn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, width, hover]);

  const grid = new HitGrid(size, size, layout.x0, layout.y0, layout.cell, layout.cell);
  const locate = (e: MouseEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return grid.at(e.clientX - box.left, e.clientY - box.top);
  };
  const cellAt = hover !== null && model !== null ? model.cells[hover.r]?.[hover.c] ?? null : null;
  const readout = cellAt !== null && view !== null && view.constants !== null ? hoverText(cellAt, view.constants) : '';

  return (
    <div className="lab-interactions" id="lab-interactions" data-loading={pending ? 'true' : 'false'}>
      <div className="interactions-toolbar">
        <span className="lab-basis" id="lab-interactions-basis">
          {view !== null ? `${view.scope.basis}${panelLabel(view)}` : ''}
        </span>
        {view !== null && view.computed !== null && view.computed.partial && (
          <span className="status-chip live" id="lab-interactions-partial">
            PARTIAL · stage {view.computed.stage} of {view.computed.stages}
          </span>
        )}
        {view !== null && view.snapshot_label !== null && (
          <span className="sub" id="lab-interactions-snapshot">
            {view.snapshot_label}
          </span>
        )}
        {pending && (
          <span className="sub lab-loading" id="lab-interactions-loading">
            {data.loaded === null ? 'loading the source…' : 'loading the interactions…'}
          </span>
        )}
      </div>
      <TaskBar id="lab-interactions-task" task={current?.envelope.task ?? null} cancelling={task.cancelling} rerunning={task.rerunning} error={task.stopError} onCancel={() => void task.cancel()} onRerun={task.runAgain} />
      {error !== null && <LabError message={`Interactions unavailable: ${error}${task.pollStopped !== null ? ` · ${task.pollStopped}` : ''}`} onRetry={task.retry} />}
      {notice !== null && (
        <div className="lab-empty" id="lab-interactions-notice" data-kind={notice.kind}>
          {notice.text}
        </div>
      )}
      {truncated !== null && (
        <div className="notice" id="lab-interactions-truncated">
          {truncated}
        </div>
      )}
      {view !== null && jBasisLine(view) !== '' && (
        <div className="sub" id="lab-interactions-metric">
          {jBasisLine(view)}
        </div>
      )}
      {model !== null && view !== null && view.constants !== null && (
        <div className="sub" id="lab-interactions-legend">
          Shade = J, the pair&apos;s joint share of the variance · hatched = unresolved (under {view.constants.PAIR_MIN_COVERAGE} of the pair&apos;s value grid holds ≥ {view.constants.PAIR_MIN_N} rows) ·
          amber corner = unbalanced · dot = Δ of the row beyond the column exceeds its detection floor · hover for Δ and I; I has no interval and no rule reads it.
        </div>
      )}
      <div className="lab-interactions-wrap" ref={wrap}>
        {model !== null && (
          <canvas
            id="lab-interactions-canvas"
            ref={canvas}
            role="img"
            aria-label={summary}
            title={readout}
            onMouseMove={(e) => {
              const found = locate(e);
              setHover((was) => (was?.r === found?.r && was?.c === found?.c ? was : found));
            }}
            onMouseLeave={() => setHover(null)}
          />
        )}
      </div>
      <div className="sub" id="lab-interactions-readout" aria-live="polite">
        {readout}
      </div>
      <div className="sub" id="lab-interactions-summary">
        {summary}
      </div>
      {model !== null && view !== null && view.constants !== null && (
        <div id="lab-interactions-unresolved-block">
          <div className="rail-title">Unresolved pairs · {model.unresolved.length}</div>
          {model.unresolved.length === 0 ? (
            <div className="sub">every pair is resolved</div>
          ) : (
            <ul className="lab-interactions-list" id="lab-interactions-unresolved">
              {model.unresolved.map((pair) => (
                <li key={pair.pair.join('|')}>{unresolvedText(pair, view.constants!)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
