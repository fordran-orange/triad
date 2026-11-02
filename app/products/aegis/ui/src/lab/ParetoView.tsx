// Trial Lab's Pareto tab (spec §7.7): the rank-1 front of two or three chosen metrics over the filtered trials. The
// dominated trials are a density bitmap (a bin that holds none is left unpainted), the front is the exact points the
// worker sends (all of them up to its cap, else a labelled sample that keeps each objective's best), and a click selects
// a point's trial. Points are at their REAL values: the orientation only says which way is better. The front's size,
// the dominated and excluded counts and the sampled label are the response's, and `#lab-pareto-front-size` is the true
// front size, not the number of dots. Every decision is `paretoModel.ts`'s; this asks for the view, draws it and turns a
// click into the selection. Two stacked canvases: the frame, bitmap and points are painted once per answer or size; the
// hover and the selection live on an overlay that repaints alone.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { errorMessage } from '../api/client';
import type { LabEnvelope, LabPareto } from '../results';
import { AXIS_COLOUR, CHART_FONT, drawAxes, LABEL_COLOUR, niceTicks, observeResize, ScatterHit, setupCanvas } from './charts/canvas';
import { trialLabel } from './candidateModel';
import { squareLabel } from './labHeatmapModel';
import { breakEven, metricName } from './metricRules';
import { answered, metricList } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { filterHash } from './labStore';
import { AssumptionsLine } from './AssumptionsLine';
import { LabError } from './NotBuilt';
import {
  axisTitle,
  densityRects,
  objectiveOptions,
  paretoBasis,
  paretoCounts,
  paretoScales,
  paretoSummary,
  plotPoints,
  pointTitle,
  usableObjectives,
  withObjective,
  type DensityRect,
  type ParetoScales,
  type PlotPoint,
} from './paretoModel';
import type { LabQueryData, Stamped } from './useLabQuery';
import { usePickTrial } from './usePickTrial';

const CLOUD = [118, 144, 163]; // the dominated cloud: the Lab's muted blue-grey
const LOSS = [255, 92, 103]; // --red
const FRONT = '#2da7ff';
const LOSS_POINT = '#ff5c67';
const OUTLINE = '#071018';
const SELECTED = '#f5bd51';
const HOVER = '#d8e5ef';
const ZERO = '#4f6b80';
/** A press this close to a point selects it. */
const HIT = 9;

type Answer = { key: string; source: string; envelope: Stamped<LabEnvelope<LabPareto>> };

/** Paints the frame: the tick lines and labels, the break-even rules, the axes, the density bitmap and the front points. */
function paintBase(canvas: HTMLCanvasElement, w: number, h: number, view: LabPareto | null, scales: ParetoScales | null, rects: DensityRect[], points: PlotPoint[]): void {
  const ctx = setupCanvas(canvas, w, h);
  if (view === null || scales === null) return;
  const { box } = scales;
  const [mx, my] = view.objectives;
  ctx.font = CHART_FONT;
  ctx.fillStyle = LABEL_COLOUR;
  ctx.strokeStyle = AXIS_COLOUR;
  ctx.lineWidth = 1;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (const v of niceTicks(scales.x.domain, 6)) {
    const x = Math.round(scales.x(v)) + 0.5;
    ctx.globalAlpha = 0.35;
    ctx.beginPath();
    ctx.moveTo(x, box.y0);
    ctx.lineTo(x, box.y1);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillText(squareLabel(mx, v), x, box.y1 + 4, 70);
  }
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const v of niceTicks(scales.y.domain, 5)) {
    const y = Math.round(scales.y(v)) + 0.5;
    ctx.globalAlpha = 0.35;
    ctx.beginPath();
    ctx.moveTo(box.x0, y);
    ctx.lineTo(box.x1, y);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillText(squareLabel(my, v), box.x0 - 6, y, box.x0 - 10);
  }
  drawAxes(ctx, scales.x, scales.y, { x: axisTitle(mx, view.orientation[0] ?? 1), y: axisTitle(my, view.orientation[1] ?? 1) }, CHART_FONT);
  // Where a money-signed objective stops losing money, when it is inside the frame: bins and points left of it are red.
  ctx.strokeStyle = ZERO;
  ctx.setLineDash([4, 3]);
  const evenX = breakEven(mx);
  const evenY = breakEven(my);
  const [x0, x1] = scales.x.domain;
  const [y0, y1] = scales.y.domain;
  if (evenX !== null && evenX > x0 && evenX < x1) {
    ctx.beginPath();
    ctx.moveTo(Math.round(scales.x(evenX)) + 0.5, box.y0);
    ctx.lineTo(Math.round(scales.x(evenX)) + 0.5, box.y1);
    ctx.stroke();
  }
  if (evenY !== null && evenY > y0 && evenY < y1) {
    ctx.beginPath();
    ctx.moveTo(box.x0, Math.round(scales.y(evenY)) + 0.5);
    ctx.lineTo(box.x1, Math.round(scales.y(evenY)) + 0.5);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  for (const r of rects) {
    const [cr, cg, cb] = r.tone === 'loss' ? LOSS : CLOUD;
    ctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${r.alpha * (r.tone === 'loss' ? 0.75 : 1)})`;
    ctx.fillRect(r.x, r.y, Math.max(r.w, 1), Math.max(r.h, 1));
  }
  ctx.lineWidth = 1;
  ctx.strokeStyle = OUTLINE;
  for (const p of points) {
    ctx.fillStyle = p.tone === 'loss' ? LOSS_POINT : FRONT;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

/** Paints the overlay: the selected trial's ring (amber) and the hovered point's (light). */
function paintMarks(canvas: HTMLCanvasElement | null, w: number, h: number, points: PlotPoint[], hover: number | null, selected: number | null): void {
  if (canvas === null) return;
  const ctx = setupCanvas(canvas, w, h);
  const ring = (i: number | null, colour: string, width: number) => {
    const p = i === null ? undefined : points[i];
    if (p === undefined) return;
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r + 3, 0, Math.PI * 2);
    ctx.stroke();
  };
  ring(selected, SELECTED, 2);
  ring(hover, HOVER, 1.5);
}

export function ParetoView({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { pick, failure: pickFailure } = usePickTrial(data);
  const { loaded, query, tick } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const available = useMemo(() => metricList(loaded?.kind ?? 'exp', data.summary), [loaded?.kind, data.summary]);
  const objectives = useMemo(() => usableObjectives(lab.objectives, available), [lab.objectives, available]);
  const objectivesKey = objectives.join(',');
  // The view in hand answers this key; a refresh of the same key keeps it drawn while it updates, another filter or
  // objective set waits for its own answer.
  const viewKey = source === null || objectives.length < 2 ? null : ['pareto', source, objectivesKey, filterHash(lab.filter)].join('|');

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
    query<LabPareto>('pareto', { objectives })
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the view
        setAsking(false);
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setAsking(false);
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the source, the objectives and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const view = current?.envelope ?? null;
  const described = shown?.envelope ?? null;

  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w, h) => setSize((s) => (s.w === w && s.h === h ? s : { w, h })));
  }, []);

  const scales = useMemo(() => (view === null ? null : paretoScales(view, size.w, size.h)), [view, size.w, size.h]);
  const points = useMemo(() => (view === null ? [] : plotPoints(view, scales)), [view, scales]);
  const rects = useMemo(() => (view === null ? [] : densityRects(view, scales)), [view, scales]);
  const hit = useMemo(
    () =>
      new ScatterHit(
        points.map((p) => p.x),
        points.map((p) => p.y),
        HIT,
      ),
    [points],
  );
  const selectedId = lab.selected !== null && 'trials' in lab.selected && lab.selected.trials.length === 1 ? lab.selected.trials[0] : null;
  const selected = selectedId === null ? null : points.findIndex((p) => p.id === selectedId);
  const selectedIndex = selected !== null && selected >= 0 ? selected : null;

  useEffect(() => {
    const el = base.current;
    if (el === null) return;
    paintBase(el, size.w, size.h, view, scales, rects, points);
    // The memoised scales, rectangles and points are the answer's and the size's.
  }, [view, scales, rects, points, size.w, size.h]);

  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    paintMarks(overlay.current, size.w, size.h, points, hover, selectedIndex);
  }, [points, hover, selectedIndex, size.w, size.h]);
  useEffect(() => setHover(null), [points]);

  const locate = (e: MouseEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return hit.at(e.clientX - box.left, e.clientY - box.top);
  };
  const readoutIndex = hover ?? selectedIndex;
  const readout = view !== null && readoutIndex !== null ? pointTitle(view, readoutIndex) : '';

  const counts = described !== null ? paretoCounts(described) : null;
  const pending = loaded === null ? data.loading : viewKey !== null && error === null && (current === null || asking);
  const picker = (slot: 0 | 1 | 2, id: string, label: string) => (
    <label className="lab-field">
      {label}
      <select
        id={id}
        value={objectives[slot] ?? ''}
        onChange={(e) => dispatch({ type: 'SET_OBJECTIVES', objectives: withObjective(objectives, slot, e.target.value === '' ? null : e.target.value) })}
      >
        {slot === 2 && <option value="">none</option>}
        {objectiveOptions(objectives, slot, available).map((metric) => (
          <option key={metric} value={metric}>
            {metricName(metric)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="lab-pareto" id="lab-pareto" data-loading={pending ? 'true' : 'false'}>
      <div className="pareto-toolbar">
        {picker(0, 'lab-pareto-x', 'X')}
        {picker(1, 'lab-pareto-y', 'Y')}
        {picker(2, 'lab-pareto-z', 'Size (3rd)')}
        <span className="lab-basis" id="lab-pareto-basis">
          {described !== null && shown !== null ? paretoBasis(described, shown.envelope) : ''}
        </span>
        {pending && (
          <span className="sub lab-loading" id="lab-pareto-loading">
            {loaded === null ? 'loading the source…' : 'loading the front…'}
          </span>
        )}
      </div>
      <AssumptionsLine panel="pareto" />
      {counts !== null && (
        <div className="pareto-counts" id="lab-pareto-counts">
          <span>
            Front size{' '}
            <b id="lab-pareto-front-size" data-value={counts.frontSize}>
              {counts.frontSize}
            </b>
          </span>
          <span>
            dominated{' '}
            <b id="lab-pareto-dominated" data-value={counts.dominated}>
              {counts.dominated}
            </b>
          </span>
          <span title="a trial with an objective that is undefined is compared with nothing">
            excluded{' '}
            <b id="lab-pareto-excluded" data-value={counts.excluded}>
              {counts.excluded}
            </b>
          </span>
          <span>
            drawn{' '}
            <b id="lab-pareto-drawn" data-value={counts.drawn}>
              {counts.drawn}
            </b>
          </span>
          <span id="lab-pareto-sampled" data-sampled={counts.sampled ? 'true' : 'false'}>
            {counts.sampledLabel}
          </span>
        </div>
      )}
      {error !== null && <LabError message={`Pareto front unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {pickFailure !== null && <LabError id="lab-pareto-pick-error" message={`${trialLabel(pickFailure.id)}: its row is unavailable (${pickFailure.message}); the selection and its four categories stand`} onRetry={() => pick(pickFailure.id)} />}
      {view !== null && view.empty !== null && <div className="lab-empty">{view.empty}</div>}
      <div className="lab-pareto-plot" ref={wrap}>
        <canvas id="lab-pareto-canvas" ref={base} role="img" aria-label={view === null ? '' : paretoSummary(view)} />
        <canvas
          className="pareto-overlay"
          ref={overlay}
          aria-hidden="true"
          title={readout}
          onMouseMove={(e) => {
            const found = locate(e);
            setHover((was) => (was === found ? was : found));
          }}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const found = locate(e);
            if (found !== null && points[found] !== undefined) pick(points[found].id);
          }}
        />
      </div>
      <div className="sub" id="lab-pareto-readout" aria-live="polite">
        {readout}
      </div>
      <div className="sub" id="lab-pareto-legend">
        Points are the front at their real values, not joined: blue = on the front, red = a money-signed objective is below break-even there; shading = the dominated trials, aggregated, an empty bin left unpainted
        {objectives.length > 2 ? '; a bigger dot = a better third objective' : ''}. Click a point to select its trial.
      </div>
      <div className="sub" id="lab-pareto-summary">
        {view === null ? '' : paretoSummary(view)}
      </div>
    </div>
  );
}
