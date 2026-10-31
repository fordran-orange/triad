// Screen E's robust neighbourhood map (spec §5.5): the aggregate median matrix of one pair of parameters, with the n of each
// square. A ring marks a square whose IQR is above the 75th percentile of the IQRs, so the stable surface reads at a glance;
// a square no trial tested is hatched and holds no value (nothing is interpolated or filled from its neighbours); a square
// under 8 trials (the server's `low n`) is dim and carries no ring. The selected candidate's square is outlined when its row is
// known, and its category A (local) and B (sampled region) states are printed from the same card payload the rail's candidate
// card reads (`useCandidateCard`): they are never recomputed here. Every decision is `familiesModel.ts`'s.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { errorMessage } from '../api/client';
import type { LabEnvelope, LabMatrix } from '../results';
import { useCandidateCard } from './CandidateCard';
import { CHART_FONT, drawAxes, fitText, HitGrid, hatchPattern, LABEL_COLOUR, linearScale, observeResize, ordinalScale, outlineRect, setupCanvas } from './charts/canvas';
import { candidateSquare, candidateStates, neighbourhoodModel, neighbourhoodTitle, type NeighbourhoodModel } from './familiesModel';
import { HATCH, LOW_N_ALPHA, TONE_FILL, TONE_TEXT } from './LabHeatmap';
import { heatLayout, HEAT_MARGIN, squareLabel, valueText } from './labHeatmapModel';
import { answered, panelLabel } from './labQuery';
import { useLab } from './labState';
import { filterHash } from './labStore';
import { metricName } from './metricRules';
import { LabError } from './NotBuilt';
import { axisLabel } from './parallelBundles';
import type { LabQueryData, Stamped } from './useLabQuery';

const HEIGHT = 300;
const RING = '#b784ff';
const CANDIDATE = '#f5bd51';
const HOVER = '#d8e5ef';
type At = { r: number; c: number };
type Answer = { key: string; source: string; envelope: Stamped<LabEnvelope<LabMatrix>>; metric: string };

/** Paints the map: the frame and the axis values, every square (hatched untested, toned tested, dim under low n), the IQR
 *  rings, the candidate's outline and the hover. One canvas redrawn whole on a hover: a lattice has at most a few hundred squares. */
function paint(canvas: HTMLCanvasElement, width: number, model: NeighbourhoodModel | null, metric: string, candidate: At | null, hover: At | null): void {
  const ctx = setupCanvas(canvas, width, HEIGHT);
  if (model === null) return;
  const rows = model.rows.length;
  const cols = model.cols.length;
  const L = heatLayout(width, HEIGHT, rows, cols);
  if (L.cellW <= 0 || L.cellH <= 0) return;
  const gap = L.cellW >= 6 && L.cellH >= 6 ? 1 : 0;
  const sw = L.cellW - gap;
  const sh = L.cellH - gap;
  const right = L.x0 + cols * L.cellW;
  const bottom = L.y0 + rows * L.cellH;
  const hatch = hatchPattern(ctx, TONE_FILL.empty, HATCH);
  drawAxes(ctx, linearScale([0, cols], [L.x0, right]), linearScale([0, rows], [L.y0, bottom]), { x: `${axisLabel(model.colsPath)} →`, y: `${axisLabel(model.rowsPath)} ↓` }, CHART_FONT);
  ctx.font = CHART_FONT;
  ctx.fillStyle = LABEL_COLOUR;
  const x = ordinalScale(model.cols, [L.x0, right]);
  const everyX = Math.max(1, Math.ceil(40 / L.cellW));
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  model.cols.forEach((v, c) => c % everyX === 0 && ctx.fillText(valueText(v), x(v) + L.cellW / 2, bottom + 4, L.cellW * everyX - 2));
  const everyY = Math.max(1, Math.ceil(14 / L.cellH));
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  model.rows.forEach((v, r) => r % everyY === 0 && ctx.fillText(valueText(v), L.x0 - 6, L.y0 + r * L.cellH + L.cellH / 2, HEAT_MARGIN.left - 30));
  for (const row of model.squares)
    for (const s of row) {
      const sx = L.x0 + s.c * L.cellW;
      const sy = L.y0 + s.r * L.cellH;
      ctx.globalAlpha = !s.untested && s.lowN ? LOW_N_ALPHA : 1;
      ctx.fillStyle = s.untested ? hatch : TONE_FILL[s.tone];
      ctx.fillRect(sx, sy, sw, sh);
      ctx.globalAlpha = 1;
      if (!s.untested && s.value !== null && sw >= 34 && sh >= 14) {
        ctx.font = CHART_FONT;
        ctx.globalAlpha = s.lowN ? LOW_N_ALPHA : 1;
        ctx.fillStyle = TONE_TEXT[s.tone];
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        fitText(ctx, squareLabel(metric, s.value), sx + sw / 2, sy + sh / 2, sw - 4);
        ctx.globalAlpha = 1;
      }
      if (s.ring) {
        ctx.strokeStyle = RING;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.ellipse(sx + sw / 2, sy + sh / 2, Math.max(sw / 2 - 3, 1), Math.max(sh / 2 - 3, 1), 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  if (candidate !== null) outlineRect(ctx, L.x0 + candidate.c * L.cellW, L.y0 + candidate.r * L.cellH, sw, sh, CANDIDATE, 2);
  if (hover !== null) outlineRect(ctx, L.x0 + hover.c * L.cellW, L.y0 + hover.r * L.cellH, sw, sh, HOVER, 1);
}

export function NeighbourhoodMap({ data, axes }: { data: LabQueryData; axes: [string, string] | null }) {
  const lab = useLab();
  const { loaded, query, tick, knownRows } = data;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const [rows, cols] = axes ?? [null, null];
  const metric = lab.metric;
  const viewKey = source === null || rows === null || cols === null || rows === cols ? null : [source, rows, cols, metric, filterHash(lab.filter)].join('|');

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
    if (viewKey === null || source === null || rows === null || cols === null) return;
    query<LabMatrix>('matrix', { rows, cols, mode: 'aggregate', stat: 'median' })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer ask owns the map, or the filter moved on
        setAnswer({ key: viewKey, source, envelope, metric });
        setFailure(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailure({ key: viewKey, message: errorMessage(e) }));
    // The key stands for the source, the pair, the metric and the filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, tick, retry]);
  const current = answer !== null && answer.key === viewKey ? answer : null;
  const shown = answered(current, answer, source);
  const error = failure !== null && failure.key === viewKey ? failure.message : null;
  const model = useMemo(() => (shown === null ? null : neighbourhoodModel(shown.envelope, shown.metric)), [shown]);

  // The selected candidate: one trial of this source. Its card is the rail's own payload.
  const selected = lab.selected !== null && 'trials' in lab.selected && lab.selected.trials.length === 1 ? lab.selected.trials[0] : null;
  const trialId = selected !== null && source !== null && selected.startsWith(`${source}#`) ? selected : null;
  const card = useCandidateCard(data, trialId);
  const states = useMemo(() => (card.card === null ? null : candidateStates(card.card)), [card.card]);
  const row = trialId === null ? undefined : knownRows[trialId];
  const mark = shown !== null && row !== undefined ? candidateSquare(shown.envelope, row.params) : null;

  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<At | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w) => setWidth((prev) => (prev === w ? prev : w)));
  }, []);
  useEffect(() => {
    if (canvas.current !== null) paint(canvas.current, width, model, shown?.metric ?? metric, mark, hover);
    // The model, the width, the candidate's square and the hover stand for what is drawn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, width, mark?.r, mark?.c, hover?.r, hover?.c]);

  const layout = model === null ? null : heatLayout(width, HEIGHT, model.rows.length, model.cols.length);
  const grid = layout === null || model === null ? null : new HitGrid(model.rows.length, model.cols.length, layout.x0, layout.y0, layout.cellW, layout.cellH);
  const hit = (e: MouseEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return grid === null ? null : grid.at(e.clientX - box.left, e.clientY - box.top);
  };
  const hovered = hover !== null && model !== null ? (model.squares[hover.r]?.[hover.c] ?? null) : null;
  const readout = hovered !== null && model !== null ? neighbourhoodTitle(model, hovered, shown?.metric ?? metric) : '';
  const pending = loaded === null ? data.loading : viewKey !== null && error === null && current === null;

  return (
    <div className="lab-neighbourhood" id="lab-families-neighbourhood" data-loading={pending ? 'true' : 'false'} data-rings={model?.rings ?? ''}>
      <div className="neighbourhood-toolbar">
        <span className="lab-basis" id="lab-families-neighbourhood-basis">
          {shown !== null ? `${shown.envelope.basis} · ${shown.envelope.legend}${panelLabel(shown.envelope)}` : ''}
        </span>
        {pending && (
          <span className="sub lab-loading" id="lab-families-neighbourhood-loading">
            {loaded === null ? 'loading the source…' : 'loading the map…'}
          </span>
        )}
      </div>
      <div className="sub" id="lab-families-neighbourhood-axes">
        {rows === null || cols === null
          ? 'no pair: pick a trellis square, or open a source that varies two parameters'
          : `median ${metricName(metric)} · rows ${axisLabel(rows)} ↓ · columns ${axisLabel(cols)} →`}
      </div>
      {error !== null && <LabError message={`Neighbourhood map unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      {shown !== null && shown.envelope.empty !== null && <div className="lab-empty">{shown.envelope.empty}</div>}
      <div className="lab-neighbourhood-wrap" ref={wrap} hidden={model === null}>
        <canvas
          id="lab-families-neighbourhood-canvas"
          ref={canvas}
          role="img"
          aria-label={model?.summary ?? 'robust neighbourhood map'}
          title={readout}
          onMouseMove={(e) => {
            const found = hit(e);
            setHover((was) => (was?.r === found?.r && was?.c === found?.c ? was : found));
          }}
          onMouseLeave={() => setHover(null)}
        />
      </div>
      <div className="sub" id="lab-families-neighbourhood-readout" aria-live="polite">
        {readout}
      </div>
      {model !== null && (
        <div className="sub" id="lab-families-neighbourhood-legend">
          Shade = the median of the square&apos;s trials (a loss is red) · hatched = untested, never filled · dim = low n · violet ring = IQR above the 75th percentile of the IQRs · amber outline = the selected candidate · {model.summary}
        </div>
      )}
      <div className="neighbourhood-candidate" id="lab-families-candidate" data-trial={trialId ?? ''}>
        {trialId === null ? (
          <div className="sub" id="lab-families-candidate-none">
            no candidate selected: click a trial in the drill-down to see its A and B states
          </div>
        ) : (
          <>
            <div className="sub">
              {trialId}
              {row !== undefined && shown !== null && mark === null ? ' · its square is not on this pair' : ''}
            </div>
            {card.error !== null && <LabError id="lab-families-candidate-error" message={`Robustness unavailable: ${card.error}`} onRetry={card.retry} />}
            {states === null && card.error === null && (
              <div className="muted" id="lab-families-candidate-loading">
                loading the candidate&apos;s categories…
              </div>
            )}
            {states?.map((state) => (
              <div className="neighbourhood-state" key={state.name} id={`lab-families-candidate-${state.name}`} data-state={state.state}>
                {state.text}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
