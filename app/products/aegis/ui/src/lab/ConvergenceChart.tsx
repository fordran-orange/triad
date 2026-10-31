// The convergence chart (spec §7.10, decision 10): best-so-far as a step line and the robust-region median per batch with its
// quartile band, from the worker's `convergence` view. Compact in Trial Lab's rail (the Run Monitor, Phase 5, adopts the same
// component at full size). Every decision is `convergenceModel.ts`'s; this asks for the view, draws it and says what it is.
//
// When it asks (decision 10): on mount, on a new source, metric or filter, and at most every 30 s while the source runs. A
// new chunk is a server cache miss that costs up to 1.8 s at 1M trials, so it is never tied to the Lab's 2 s refresh tick.
// When the source stops running it asks once more, so a settled answer replaces the provisional one. A stale answer is dropped
// (a newer ask owns the chart), and the timer stops on unmount and on a new source.
import { useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import type { LabConvergence, LabEnvelope } from '../results';
import { AXIS_COLOUR, CHART_FONT, LABEL_COLOUR, linearScale, niceTicks, observeResize, setupCanvas, strokeLine } from './charts/canvas';
import { convergenceModel, refreshDelay, type ConvergenceModel } from './convergenceModel';
import { answered, snapshotLabel } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { objectiveText } from './metricRules';
import { LabError } from './NotBuilt';
import type { LabQueryData, Stamped } from './useLabQuery';
import { isLive, statusOf } from './useLabSource';

const BEST = '#2da7ff';
const LOSS = '#ff5c67'; // a P&L-signed value below zero is never the blue of a best
const ROBUST = '#b784ff';
const BAND = 'rgba(183, 132, 255, 0.22)';
const RULE = '#7690a3';
const HEIGHT = { compact: 84, full: 240 };
const PAD = { compact: { l: 4, r: 4, t: 4, b: 16 }, full: { l: 64, r: 10, t: 8, b: 22 } };

type Answer = { key: string; source: string; envelope: Stamped<LabEnvelope<LabConvergence>> };

/** Paints the chart: the baseline, the break-even rule when the data reaches it, the robust band and median (a run at a time,
 *  a lone batch as a bar and a dot), then the best step line over them, red where it loses. Nothing is drawn past the last kept
 *  trial or the last complete batch. */
function paint(canvas: HTMLCanvasElement, width: number, compact: boolean, model: ConvergenceModel | null): void {
  const height = compact ? HEIGHT.compact : HEIGHT.full;
  const ctx = setupCanvas(canvas, width, height);
  if (model === null || model.xDomain === null || model.yDomain === null || width <= 0) return;
  const pad = compact ? PAD.compact : PAD.full;
  const x = linearScale(model.xDomain, [pad.l, width - pad.r]);
  const y = linearScale(model.yDomain, [height - pad.b, pad.t]);
  ctx.font = CHART_FONT;
  ctx.fillStyle = LABEL_COLOUR;
  ctx.strokeStyle = AXIS_COLOUR;
  ctx.lineWidth = 1;
  const base = Math.round(height - pad.b) + 0.5;
  ctx.beginPath();
  ctx.moveTo(pad.l, base);
  ctx.lineTo(width - pad.r, base);
  ctx.stroke();
  // The trial numbers at the two ends (compact), or ticks along both axes (full).
  ctx.textBaseline = 'top';
  if (compact) {
    ctx.textAlign = 'left';
    ctx.fillText(`trial ${model.xDomain[0].toLocaleString('en-US')}`, pad.l, base + 3);
    ctx.textAlign = 'right';
    ctx.fillText(model.xDomain[1].toLocaleString('en-US'), width - pad.r, base + 3);
  } else {
    ctx.textAlign = 'center';
    for (const tick of niceTicks(model.xDomain, 6)) ctx.fillText(tick.toLocaleString('en-US'), x(tick), base + 4);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const tick of niceTicks(model.yDomain, 5)) ctx.fillText(objectiveText(model.metric, tick), pad.l - 6, y(tick));
  }
  if (model.breakEven !== null) {
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = RULE;
    ctx.beginPath();
    ctx.moveTo(pad.l, Math.round(y(model.breakEven)) + 0.5);
    ctx.lineTo(width - pad.r, Math.round(y(model.breakEven)) + 0.5);
    ctx.stroke();
    ctx.restore();
  }
  for (const run of model.runs) {
    if (run.length > 1) {
      ctx.fillStyle = BAND;
      ctx.beginPath();
      run.forEach((p, i) => (i === 0 ? ctx.moveTo(x(p.x), y(p.p75)) : ctx.lineTo(x(p.x), y(p.p75))));
      [...run].reverse().forEach((p) => ctx.lineTo(x(p.x), y(p.p25)));
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = ROBUST;
      ctx.lineWidth = 1.5;
      strokeLine(ctx, run.map((p) => [x(p.x), y(p.median)] as const));
    } else {
      const p = run[0];
      ctx.strokeStyle = ROBUST;
      ctx.lineWidth = 1.5;
      strokeLine(ctx, [[x(p.x), y(p.p25)], [x(p.x), y(p.p75)]]);
      ctx.fillStyle = ROBUST;
      ctx.beginPath();
      ctx.arc(x(p.x), y(p.median), 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.lineWidth = 1.75;
  if (model.pieces.length === 0 && model.best.length === 1) {
    ctx.fillStyle = BEST;
    ctx.beginPath();
    ctx.arc(x(model.best[0].x), y(model.best[0].y), 2.5, 0, Math.PI * 2);
    ctx.fill();
  }
  for (const piece of model.pieces) {
    ctx.strokeStyle = piece.loses ? LOSS : BEST;
    strokeLine(ctx, [[x(piece.x0), y(piece.y0)], [x(piece.x1), y(piece.y1)]]);
  }
}

export function ConvergenceChart({ data, compact = false, id = 'lab-convergence' }: { data: LabQueryData; compact?: boolean; id?: string }) {
  const lab = useLab();
  const { loaded, query } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const live = loaded !== null && isLive(statusOf(loaded));
  // The view honours the filter (decision 7), so a new filter is a new ask; the Lab's 2 s refresh tick is not part of it.
  const viewKey = source === null ? null : [source, lab.metric, filterHash(lab.filter)].join('|');

  const [retry, setRetry] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  const askedAt = useRef<number | null>(null);
  useEffect(() => {
    // `live` is in the mark: when the run ends, one more ask settles the answer.
    const mark = viewKey === null ? null : `${viewKey}|${live}|${retry}|${refresh}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (viewKey === null || source === null) return;
    askedAt.current = Date.now();
    query<LabConvergence>('convergence', {})
      .then((envelope) => {
        if (mine !== seq.current) return; // a newer ask owns the chart
        if (envelope === null) return; // the filter or the source moved on: its own ask follows
        setAnswer({ key: viewKey, source, envelope });
        setFailure(null);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setFailure({ key: viewKey, message: errorMessage(e) });
      });
    // The key stands for the source, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, live, retry, refresh]);

  // While the source runs, ask again once the interval since the last ask has passed. Each ask re-arms the timer; a new source,
  // the end of the run and the unmount clear it.
  useEffect(() => {
    const delay = refreshDelay(live && viewKey !== null, askedAt.current, Date.now());
    if (delay === null) return;
    const timer = setTimeout(() => setRefresh((n) => n + 1), delay);
    return () => clearTimeout(timer);
  }, [live, viewKey, retry, refresh]);

  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const model = useMemo(() => (shown === null ? null : convergenceModel(shown.envelope)), [shown]);
  const pending = loaded === null ? data.loading : viewKey !== null && error === null && current === null;

  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w) => setWidth((prev) => (prev === w ? prev : w)));
  }, []);
  useEffect(() => {
    if (canvas.current !== null) paint(canvas.current, width, compact, model);
  }, [model, width, compact]);

  const drawn = model !== null && model.best.length > 0;
  // Under two batches the robust series is empty: the compact chart still draws `best` and says why in a line; the full chart
  // reads the envelope's own `empty`.
  const note = model === null ? '' : model.robustNote !== '' ? model.robustNote : (model.robustReason ?? '');
  // The full chart prints the envelope's `empty` below, which is that same reason: once is enough.
  const showNote = note !== '' && (compact || model?.emptyReason === null);
  return (
    <div className={'lab-convergence' + (compact ? ' compact' : '')} id={id} data-loading={pending ? 'true' : 'false'} data-provisional={model?.provisional ? 'true' : 'false'}>
      <div className="convergence-toolbar">
        {model !== null && model.provisional && shown !== null && (
          <span className="status-chip live" id={`${id}-provisional`}>
            {snapshotLabel(shown.envelope.snapshot, shown.envelope.receivedAt)}
          </span>
        )}
        {model !== null && <span className="sub">{model.better}</span>}
        {pending && (
          <span className="sub lab-loading" id={`${id}-loading`}>
            {loaded === null ? 'loading the source…' : 'loading the convergence…'}
          </span>
        )}
      </div>
      {error !== null && <LabError id={`${id}-error`} message={`Convergence unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {model !== null && !drawn && (
        <div className="lab-empty convergence-empty" id={`${id}-empty`}>
          {model.emptyReason ?? 'no trial has a defined value yet'}
        </div>
      )}
      <div className="convergence-plot" ref={wrap} hidden={!drawn}>
        <canvas id={`${id}-canvas`} ref={canvas} role="img" aria-label={model?.summary ?? 'convergence'} />
      </div>
      {drawn && model !== null && (
        <>
          <div className="sub convergence-summary" id={`${id}-summary`} aria-live="polite">
            {model.summary}
          </div>
          <div className="sub convergence-legend" id={`${id}-legend`}>
            <span className="convergence-key best" /> best so far (step, red where it loses) · <span className="convergence-key robust" /> robust median, quartile band
          </div>
          {showNote && (
            <div className="sub" id={`${id}-robust`} data-robust={model.runs.length > 0 ? 'drawn' : 'empty'}>
              {note}
            </div>
          )}
          {!compact && model.emptyReason !== null && (
            <div className="lab-empty convergence-empty" id={`${id}-empty`}>
              {model.emptyReason}
            </div>
          )}
          {!compact && (
            <div className="sub" id={`${id}-basis`} title="the worker's basis line">
              {model.basis}
            </div>
          )}
        </>
      )}
    </div>
  );
}
