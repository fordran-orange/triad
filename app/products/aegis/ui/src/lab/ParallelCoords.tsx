// Trial Lab's parallel coordinates (spec §7.9): the server's bundles of the filtered trials over the active
// parameters, one polyline per bundle through its bins' centres (opacity by count, colour by the bundle's median
// through the dock's `Heatmap.cells()` tones, so a losing median is red), or, in the exact mode `#lab-parallel-mode`
// asks for, a stratified sample of actual trials, one polyline each through its own values (coloured by its metric the
// same way); the pinned trials as exact lines over either, and a brush per axis that writes the shared filter. The bundles are
// asked again on the Lab's 2 s tick while the source runs, as they always were; the sample (up to 5,000 lines) is asked on the 30 s
// rule instead (`useAskMark`). Every decision is `parallelBundles.ts`'s; this asks for the view, draws it and turns a drag into the filter. Two stacked
// canvases: the axes and the lines are painted once per answer or size, as hairlines over a few frames; the brushes and
// the pinned lines live on an overlay that a drag repaints alone, with no React state per mouse move.
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { errorMessage } from '../api/client';
import { cells, profitKind } from '../components/Heatmap';
import type { LabEnvelope, LabParallel } from '../results';
import { AssumptionsLine } from './AssumptionsLine';
import type { CatalogEntry } from './catalog';
import { AXIS_COLOUR, Brush1D, CHART_FONT, hairline, LABEL_COLOUR, linearScale, observeResize, paintInFrames, setupCanvas, strokeLine, type Scale } from './charts/canvas';
import { valueText, type Tone } from './labHeatmapModel';
import { lowerIsBetter, objectiveText } from './metricRules';
import { answered } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { filterHash, type PinSlot } from './labStore';
import { LabError } from './NotBuilt';
import {
  axisLabel,
  axisPositions,
  brushToFilter,
  exactLine,
  isSampleView,
  nearestAxis,
  opacityFor,
  PARALLEL_MAX_AXES,
  parallelCaption,
  parallelRequest,
  parallelSummary,
  polyline,
  sampleLine,
  sampleOrder,
  type ParallelMode,
} from './parallelBundles';
import { useAskMark } from './useAskMark';
import type { LabQueryData, Stamped } from './useLabQuery';
import { sourceFamilies, sourceLive, type TrialRow } from './useLabSource';

const PAD = 48; // the first and the last axis stand this far in from the canvas's edges
const TOP = 36; // room above the axes for the `.parallel-axis` names and each axis's top value
const BOTTOM = 20; // and below them for its bottom value
const HIT = 14; // a press this close to an axis brushes it
/** The bundles one frame strokes: 2,000 hairline bundles paint over 8 frames, never in one long task. */
const FRAME_BUNDLES = 250;
/** The sampled lines one frame strokes: 5,000 hairlines paint over 10 frames. */
const FRAME_LINES = 500;
/** A sampled line is one trial, so it is faint: the density of the lines is what reads. */
const SAMPLE_ALPHA = 0.3;
/** A bundle's stroke by the tone of its median: green only for a winning value, red for a losing one. */
const LINE: Record<Tone, string> = { hot: '#39d98a', gain: '#2f9e6a', mid: '#7690a3', cool: '#dd98a0', loss: '#ff5c67', empty: '#4f6b80' };
const PIN_COLOUR: Record<PinSlot, string> = { A: '#f5bd51', B: '#2da7ff', C: '#b784ff' };
const PIN_SLOTS: PinSlot[] = ['A', 'B', 'C'];
const BRUSH_FILL = 'rgba(45, 167, 255, 0.18)';
const BRUSH_EDGE = '#2da7ff';

/** An answered view and what it was asked for: the basis and the summary describe it until the next one lands. */
type Answer = { key: string; source: string; metric: string; mode: ParallelMode; envelope: Stamped<LabEnvelope<LabParallel>> };
type Live = { axis: number; range: [number, number] | null };
type Pinned = { slot: PinSlot; row: TrialRow };

/** Where each axis stands and its scale over the parameter's catalog range (so a brush keeps its meaning while the
 *  quantile bins move with the filter). */
function geometry(active: CatalogEntry[], w: number, h: number): { xs: number[]; scales: Scale[] } {
  return {
    xs: axisPositions(active.length, w, PAD),
    scales: active.map((e) => linearScale([Math.min(e.start, e.stop), Math.max(e.start, e.stop)], [h - BOTTOM, TOP])),
  };
}

/** Paints the base layer: the axes with their end values at once, then the bundles as hairlines, the smallest first
 *  so the largest lie on top, or the sampled lines, the worst first so the best lie on top, a frame's worth at a time.
 *  Returns the cancel. */
function paintBundles(canvas: HTMLCanvasElement, w: number, h: number, active: CatalogEntry[], view: LabParallel | null, metric: string): () => void {
  const ctx = setupCanvas(canvas, w, h);
  if (w <= 0 || h <= TOP + BOTTOM) return () => undefined;
  const { xs, scales } = geometry(active, w, h);
  const room = active.length > 1 ? xs[1] - xs[0] - 6 : w - 2 * PAD;
  const chunks: Array<() => void> = [
    () => {
      ctx.font = CHART_FONT;
      ctx.textAlign = 'center';
      active.forEach((entry, i) => {
        const x = Math.round(xs[i]) + 0.5;
        ctx.strokeStyle = AXIS_COLOUR;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, TOP);
        ctx.lineTo(x, h - BOTTOM);
        ctx.stroke();
        ctx.fillStyle = LABEL_COLOUR;
        ctx.textBaseline = 'bottom';
        ctx.fillText(valueText(Math.max(entry.start, entry.stop)), xs[i], TOP - 3, room);
        ctx.textBaseline = 'top';
        ctx.fillText(valueText(Math.min(entry.start, entry.stop)), xs[i], h - BOTTOM + 3, room);
      });
    },
  ];
  if (view !== null && isSampleView(view)) {
    const lines = view.lines ?? [];
    const lower = lowerIsBetter(metric);
    const order = sampleOrder(lines, lower);
    // The lines' tones are the dock's too: one row of metrics through `cells()`, a losing value red whatever its rank.
    const tones = cells([0], lines.map((_, k) => k), [lines.map((l) => l.metric)], lower, profitKind(metric))[0] ?? [];
    const width = hairline();
    for (let start = 0; start < order.length; start += FRAME_LINES) {
      const band = order.slice(start, start + FRAME_LINES);
      chunks.push(() => {
        ctx.lineWidth = width;
        ctx.globalAlpha = SAMPLE_ALPHA;
        for (const k of band) {
          ctx.strokeStyle = LINE[tones[k]?.tone ?? 'empty'];
          strokeLine(ctx, sampleLine(lines[k].values, scales, xs));
        }
        ctx.globalAlpha = 1;
      });
    }
  } else if (view !== null && view.bundles.length > 0) {
    const { bundles } = view;
    const most = Math.max(...bundles.map((b) => b.count));
    // The bundles' tones are the dock's: one row of medians through `cells()`, a null median never coloured.
    const tones = cells([0], bundles.map((_, k) => k), [bundles.map((b) => b.median)], metric === 'max_drawdown', profitKind(metric))[0] ?? [];
    const centres = view.bins.map((b) => b.centres);
    const width = hairline();
    for (let end = bundles.length; end > 0; end -= FRAME_BUNDLES) {
      const start = Math.max(0, end - FRAME_BUNDLES);
      chunks.push(() => {
        ctx.lineWidth = width;
        for (let k = end - 1; k >= start; k--) {
          ctx.globalAlpha = opacityFor(bundles[k].count, most);
          ctx.strokeStyle = LINE[tones[k]?.tone ?? 'empty'];
          strokeLine(ctx, polyline(bundles[k], scales, centres, xs));
        }
        ctx.globalAlpha = 1;
      });
    }
  }
  return paintInFrames(chunks);
}

/** Paints the overlay: each axis's committed range (the live one on the axis being dragged) and the pinned trials'
 *  exact lines with their slot letters. A handful of shapes, so a drag repaints it on every move. */
function paintOverlay(canvas: HTMLCanvasElement | null, w: number, h: number, active: CatalogEntry[], ranges: Record<string, [number, number]>, pinned: Pinned[], live: Live | null): void {
  if (canvas === null) return;
  const ctx = setupCanvas(canvas, w, h);
  if (w <= 0 || h <= TOP + BOTTOM) return;
  const { xs, scales } = geometry(active, w, h);
  active.forEach((entry, i) => {
    const range = live !== null && live.axis === i && live.range !== null ? live.range : (ranges[entry.path] ?? null);
    if (range === null) return;
    const top = Math.min(scales[i](range[1]), scales[i](range[0]));
    const height = Math.max(Math.abs(scales[i](range[0]) - scales[i](range[1])), 2);
    ctx.fillStyle = BRUSH_FILL;
    ctx.fillRect(xs[i] - 8, top, 16, height);
    ctx.strokeStyle = BRUSH_EDGE;
    ctx.lineWidth = 1;
    ctx.strokeRect(xs[i] - 8, top, 16, height);
  });
  ctx.lineWidth = 2.5;
  ctx.font = CHART_FONT;
  for (const { slot, row } of pinned) {
    const line = exactLine(row.params, active.map((e) => e.path), scales, xs);
    ctx.strokeStyle = PIN_COLOUR[slot];
    strokeLine(ctx, line);
    const end = [...line].reverse().find((p) => p !== null);
    if (end) {
      ctx.fillStyle = PIN_COLOUR[slot];
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(slot, end[0] + 6, end[1]);
    }
  }
}

export function ParallelCoords({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { loaded, query, knownRows, tick } = data;
  // The active parameters in catalog order (Phase 2: every parameter is active), at most PARALLEL_MAX_AXES.
  const entries = useMemo(() => (loaded ? sourceFamilies(loaded).flatMap((f) => f.entries) : []), [loaded]);
  const active = entries.slice(0, PARALLEL_MAX_AXES);
  const axes = active.map((e) => e.path);
  const axesKey = active.map((e) => `${e.path}:${e.start}:${e.stop}`).join(',');
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const metric = lab.metric;
  // Aggregated bundles (the default) or the exact mode's sample: this panel's own choice, asked of the worker as `parallel_mode`.
  const [mode, setMode] = useState<ParallelMode>('bundles');
  // The view in hand answers this key; a refresh of the same key keeps it drawn while it updates, another filter,
  // metric, mode or parameter set waits for its own answer.
  const viewKey = source === null || axes.length === 0 ? null : [source, axes.join(','), metric, mode, filterHash(lab.filter)].join('|');
  // The sample is up to 5,000 lines a time: in that mode the panel asks on the 30 s rule, not on every tick. The bundles keep the tick.
  const askMark = useAskMark(viewKey, mode === 'sample' && sourceLive(loaded));
  const cadence = mode === 'sample' ? askMark : tick;

  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${cadence}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null || source === null) return;
    setAsking(true);
    query<LabParallel>('parallel', parallelRequest(mode, axes, metric))
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the view
        setAsking(false);
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source, metric, mode, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setAsking(false);
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the source, the parameter set, the metric, the mode and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, cadence, retry]);
  // Drawn: the answer for the view in hand. The basis and the sentence about what a line is describe that answer alone and are
  // blank while a new view loads, as the canvas is (after the mode is toggled they would describe the previous mode); the summary
  // keeps the last answer this source gave until the next lands (a pending query shows as `data-loading` and `#lab-parallel-loading`).
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;

  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w, h) => setSize((s) => (s.w === w && s.h === h ? s : { w, h })));
  }, []);
  const { xs, scales } = geometry(active, size.w, size.h);

  // The pinned trials of this source whose rows are known: drawn exactly, over the bundles.
  const pinned: Pinned[] = PIN_SLOTS.flatMap((slot) => {
    const id = lab.pins[slot];
    const row = id !== undefined && source !== null && id.startsWith(`${source}#`) ? knownRows[id] : undefined;
    return row ? [{ slot, row }] : [];
  });
  const pinsActive = PIN_SLOTS.some((slot) => lab.pins[slot] !== undefined);
  const pinsKey = pinned.map((p) => `${p.slot}:${p.row.id}`).join(',');
  const rangesKey = JSON.stringify(lab.filter.ranges);

  // The base layer: painted only when a new answer, the size or the parameter set arrives.
  useEffect(() => {
    const el = base.current;
    if (el === null) return;
    return paintBundles(el, size.w, size.h, active, current?.envelope ?? null, current?.metric ?? metric);
    // The answer, the size and the axes key stand for what the layer shows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, size.w, size.h, axesKey]);

  // The overlay: the committed ranges and the pinned lines, and the live brush while a drag goes on.
  const live = useRef<Live | null>(null);
  useEffect(() => {
    paintOverlay(overlay.current, size.w, size.h, active, lab.filter.ranges, pinned, live.current);
    // The keys stand for the ranges, the pins and the axes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.w, size.h, axesKey, rangesKey, pinsKey]);

  // A drag along an axis paints its live range on the overlay from the gesture itself and writes the filter once,
  // on release.
  const endDrag = useRef<(() => void) | null>(null);
  useEffect(() => () => endDrag.current?.(), []);
  const onMouseDown = (e: ReactMouseEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    const i = nearestAxis(xs, e.clientX - box.left, HIT);
    if (i < 0) return;
    e.preventDefault();
    const path = axes[i];
    const brush = new Brush1D(scales[i], (range) => dispatch(brushToFilter(path, range)));
    const { w, h } = size;
    const ranges = lab.filter.ranges;
    const paint = () => paintOverlay(overlay.current, w, h, active, ranges, pinned, live.current);
    brush.down(e.clientY - box.top);
    live.current = { axis: i, range: null };
    const move = (ev: MouseEvent) => {
      brush.move(ev.clientY - box.top);
      live.current = { axis: i, range: brush.range };
      paint();
    };
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      endDrag.current = null;
      live.current = null;
    };
    const up = () => {
      stop();
      brush.up();
      paint();
    };
    endDrag.current = stop;
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  const pending = loaded === null ? data.loading : viewKey !== null && error === null && (current === null || asking);
  const caption = parallelCaption(current === null ? null : current.envelope, pinsActive ? pinned.length : null);
  const basis = caption.basis;
  const summary = shown !== null ? parallelSummary(shown.envelope, shown.metric, shown.metric === 'max_drawdown', (v) => objectiveText(shown.metric, v)) : '';
  const labelWidth = axes.length > 1 ? Math.max(xs[1] - xs[0] - 6, 24) : Math.max(size.w - 2 * PAD, 24);

  return (
    <div className="lab-parallel-panel" data-loading={pending ? 'true' : 'false'}>
      <div className="parallel-toolbar">
        <span className="lab-basis" id="lab-parallel-basis">
          {basis}
        </span>
        <span className="parallel-mode" id="lab-parallel-mode" role="group" aria-label="Data mode" data-mode={mode}>
          <button
            type="button"
            id="lab-parallel-mode-bundles"
            className={'chip' + (mode === 'bundles' ? ' active' : '')}
            aria-pressed={mode === 'bundles'}
            title="Aggregated: bundles of trials that share a quantile bin on every axis (the default)"
            onClick={() => setMode('bundles')}
          >
            Aggregated
          </button>
          <button
            type="button"
            id="lab-parallel-mode-sample"
            className={'chip' + (mode === 'sample' ? ' active' : '')}
            aria-pressed={mode === 'sample'}
            title="Exact: a stratified sample of actual trials, one line each, bounded and seeded by the worker"
            onClick={() => setMode('sample')}
          >
            Exact (sampled)
          </button>
        </span>
        {pending && (
          <span className="sub lab-loading" id="lab-parallel-loading">
            {loaded === null ? 'loading the source…' : mode === 'sample' ? 'loading the sample…' : 'loading the bundles…'}
          </span>
        )}
      </div>
      <AssumptionsLine panel="parallel" />
      <div className="sub" id="lab-parallel-note">
        {caption.lead}
        drag along an axis to brush it into the shared filter, click an axis to clear its brush, Esc clears every brush.
        {entries.length > PARALLEL_MAX_AXES ? ` The first ${PARALLEL_MAX_AXES} of ${entries.length} parameters, in catalog order.` : ''}
      </div>
      {loaded !== null && axes.length === 0 && <div className="lab-empty">no parameters to draw: this source varies none</div>}
      {error !== null && <LabError message={`Parallel coordinates unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {current?.envelope.empty ? <div className="lab-empty">{current.envelope.empty}</div> : null}
      <div className="lab-parallel" id="lab-parallel" ref={wrap} data-loading={pending ? 'true' : 'false'}>
        <canvas id="lab-parallel-canvas" ref={base} role="img" aria-label={summary} onMouseDown={onMouseDown} />
        <canvas className="parallel-overlay" ref={overlay} aria-hidden="true" />
        {size.w > 0 &&
          axes.map((path, i) => (
            <span key={path} className="parallel-axis" data-path={path} data-x={xs[i]} title={path} style={{ left: `${xs[i]}px`, maxWidth: `${labelWidth}px` }}>
              {axisLabel(path)}
            </span>
          ))}
      </div>
      <div className="sub" id="lab-parallel-summary" aria-live="polite">
        {summary}
      </div>
    </div>
  );
}
