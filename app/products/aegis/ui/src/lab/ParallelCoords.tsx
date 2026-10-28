// Trial Lab's parallel coordinates (spec §7.9, aggregated mode): the server's bundles of the filtered trials over
// the active parameters, one polyline per bundle through its bins' centres (opacity by count, colour by the bundle's
// median through the dock's `Heatmap.cells()` tones, so a losing median is red), the pinned trials as exact lines
// over them, and a brush per axis that writes the shared filter. Every decision is `parallelBundles.ts`'s; this
// asks for the view, draws it and turns a drag into the filter.
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { errorMessage } from '../api/client';
import { cells, profitKind } from '../components/Heatmap';
import type { LabEnvelope, LabParallel } from '../results';
import { AXIS_COLOUR, Brush1D, CHART_FONT, LABEL_COLOUR, linearScale, observeResize, setupCanvas, strokeLine } from './charts/canvas';
import { valueText, type Tone } from './labHeatmapModel';
import { objectiveText } from './LabKpiStrip';
import { panelLabel } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { filterHash, type PinSlot } from './labStore';
import { LabError } from './NotBuilt';
import { axisLabel, axisPositions, brushToFilter, exactLine, nearestAxis, opacityFor, PARALLEL_MAX_AXES, parallelBasis, parallelSummary, polyline } from './parallelBundles';
import type { LabQueryData, Stamped } from './useLabQuery';
import { sourceFamilies } from './useLabSource';

const PAD = 48; // the first and the last axis stand this far in from the canvas's edges
const TOP = 36; // room above the axes for the `.parallel-axis` names and each axis's top value
const BOTTOM = 20; // and below them for its bottom value
const HIT = 14; // a press this close to an axis brushes it
/** A bundle's stroke by the tone of its median: green only for a winning value, red for a losing one. */
const LINE: Record<Tone, string> = { hot: '#39d98a', gain: '#2f9e6a', mid: '#7690a3', cool: '#dd98a0', loss: '#ff5c67', empty: '#4f6b80' };
const PIN_COLOUR: Record<PinSlot, string> = { A: '#f5bd51', B: '#2da7ff', C: '#b784ff' };
const PIN_SLOTS: PinSlot[] = ['A', 'B', 'C'];
const BRUSH_FILL = 'rgba(45, 167, 255, 0.18)';
const BRUSH_EDGE = '#2da7ff';

export function ParallelCoords({ data }: { data: LabQueryData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { loaded, query, knownRows, tick } = data;
  // The active parameters in catalog order (Phase 2: every parameter is active), at most PARALLEL_MAX_AXES.
  const entries = useMemo(() => (loaded ? sourceFamilies(loaded).flatMap((f) => f.entries) : []), [loaded]);
  const shown = entries.slice(0, PARALLEL_MAX_AXES);
  const axes = shown.map((e) => e.path);
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const metric = lab.metric;
  const lowerIsBetter = metric === 'max_drawdown';
  // The view in hand answers this key; a refresh of the same key keeps it on screen while it updates, another
  // filter, metric or parameter set drops it.
  const viewKey = source === null || axes.length === 0 ? null : [source, axes.join(','), metric, filterHash(lab.filter)].join('|');

  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<{ key: string; envelope: Stamped<LabEnvelope<LabParallel>> } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [pending, setPending] = useState(false);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = viewKey === null ? null : `${viewKey}|${tick}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null) return;
    setPending(true);
    query<LabParallel>('parallel', { axes, metric })
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the view
        setPending(false);
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setPending(false);
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the source, the parameter set, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry]);
  const envelope = answer !== null && answer.key === viewKey ? answer.envelope : null;
  const error = failure !== null && failure.key === viewKey ? failure.message : null;

  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w, h) => setSize((s) => (s.w === w && s.h === h ? s : { w, h })));
  }, []);
  const xs = axisPositions(axes.length, size.w, PAD);
  const scales = shown.map((e) => linearScale([Math.min(e.start, e.stop), Math.max(e.start, e.stop)], [size.h - BOTTOM, TOP]));

  // The pinned trials of this source whose rows are known: drawn exactly, over the bundles.
  const pinned = PIN_SLOTS.flatMap((slot) => {
    const id = lab.pins[slot];
    const row = id !== undefined && source !== null && id.startsWith(`${source}#`) ? knownRows[id] : undefined;
    return row ? [{ slot, row }] : [];
  });
  const pinsActive = PIN_SLOTS.some((slot) => lab.pins[slot] !== undefined);

  // A drag along an axis: the live range while it goes on, the filter written on release.
  const [drag, setDrag] = useState<{ axis: number; range: [number, number] | null } | null>(null);
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
    brush.down(e.clientY - box.top);
    setDrag({ axis: i, range: null });
    const move = (ev: MouseEvent) => {
      brush.move(ev.clientY - box.top);
      setDrag({ axis: i, range: brush.range });
    };
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      endDrag.current = null;
    };
    const up = () => {
      stop();
      brush.up();
      setDrag(null);
    };
    endDrag.current = stop;
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  useEffect(() => {
    const el = canvas.current;
    if (el === null) return;
    const ctx = setupCanvas(el, size.w, size.h);
    if (size.w <= 0 || size.h <= TOP + BOTTOM) return;
    const room = axes.length > 1 ? xs[1] - xs[0] - 6 : size.w - 2 * PAD;
    ctx.font = CHART_FONT;
    ctx.textAlign = 'center';
    shown.forEach((entry, i) => {
      const x = Math.round(xs[i]) + 0.5;
      ctx.strokeStyle = AXIS_COLOUR;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, TOP);
      ctx.lineTo(x, size.h - BOTTOM);
      ctx.stroke();
      ctx.fillStyle = LABEL_COLOUR;
      ctx.textBaseline = 'bottom';
      ctx.fillText(valueText(Math.max(entry.start, entry.stop)), xs[i], TOP - 3, room);
      ctx.textBaseline = 'top';
      ctx.fillText(valueText(Math.min(entry.start, entry.stop)), xs[i], size.h - BOTTOM + 3, room);
    });
    if (envelope !== null && envelope.bundles.length > 0) {
      const most = Math.max(...envelope.bundles.map((b) => b.count));
      // The bundles' tones are the dock's: one row of medians through `cells()`, a null median never coloured.
      const tones = cells([0], envelope.bundles.map((_, k) => k), [envelope.bundles.map((b) => b.median)], lowerIsBetter, profitKind(metric))[0] ?? [];
      const centres = envelope.bins.map((b) => b.centres);
      ctx.lineWidth = 1.5;
      for (let k = envelope.bundles.length - 1; k >= 0; k--) {
        const bundle = envelope.bundles[k]; // the smallest first, so the largest lie on top
        ctx.globalAlpha = opacityFor(bundle.count, most);
        ctx.strokeStyle = LINE[tones[k]?.tone ?? 'empty'];
        strokeLine(ctx, polyline(bundle, scales, centres, xs));
      }
      ctx.globalAlpha = 1;
    }
    shown.forEach((entry, i) => {
      const range = drag !== null && drag.axis === i && drag.range !== null ? drag.range : (lab.filter.ranges[entry.path] ?? null);
      if (range === null) return;
      const top = scales[i](range[1]);
      const bottom = scales[i](range[0]);
      ctx.fillStyle = BRUSH_FILL;
      ctx.fillRect(xs[i] - 8, Math.min(top, bottom), 16, Math.max(Math.abs(bottom - top), 2));
      ctx.strokeStyle = BRUSH_EDGE;
      ctx.lineWidth = 1;
      ctx.strokeRect(xs[i] - 8, Math.min(top, bottom), 16, Math.max(Math.abs(bottom - top), 2));
    });
    ctx.lineWidth = 2.5;
    for (const { slot, row } of pinned) {
      const line = exactLine(row.params, axes, scales, xs);
      ctx.strokeStyle = PIN_COLOUR[slot];
      strokeLine(ctx, line);
      const last = [...line].reverse().find((p) => p !== null);
      if (last) {
        ctx.fillStyle = PIN_COLOUR[slot];
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(slot, last[0] + 6, last[1]);
      }
    }
  });

  const basis =
    envelope !== null
      ? `${parallelBasis(envelope.basis, pinsActive ? pinned.length : null)}${panelLabel(envelope)}`
      : loaded === null
        ? data.loading
          ? 'loading the source…'
          : 'no source open'
        : axes.length === 0
          ? 'no parameters to draw: this source varies none'
          : error !== null
            ? 'no bundles: the query failed'
            : 'loading the bundles…';
  const summary = envelope !== null ? parallelSummary(envelope, metric, lowerIsBetter, (v) => objectiveText(metric, v)) : basis;
  const labelWidth = axes.length > 1 ? Math.max(xs[1] - xs[0] - 6, 24) : Math.max(size.w - 2 * PAD, 24);

  return (
    <div className="lab-parallel-panel">
      <div className="parallel-toolbar">
        <span className="lab-basis" id="lab-parallel-basis">
          {basis}
        </span>
      </div>
      <div className="sub">
        Each line is a bundle of trials sharing a quantile bin on every axis; drag along an axis to brush it into the shared filter, click an axis to clear its brush, Esc clears every brush.
        {entries.length > PARALLEL_MAX_AXES ? ` The first ${PARALLEL_MAX_AXES} of ${entries.length} parameters, in catalog order.` : ''}
        {pending ? ' · updating…' : ''}
      </div>
      {error !== null && <LabError message={`Parallel coordinates unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {envelope?.empty ? <div className="lab-empty">{envelope.empty}</div> : null}
      <div className="lab-parallel" id="lab-parallel" ref={wrap}>
        <canvas id="lab-parallel-canvas" ref={canvas} role="img" aria-label={summary} onMouseDown={onMouseDown} />
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
