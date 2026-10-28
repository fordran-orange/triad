// The experiment heatmap of Trial Lab (spec §7.1 exact slice, §7.2 aggregated projection), drawn on canvas from
// the matrix `useLabQuery` fetches for the axes, mode, stat, metric, filter and slice in view. Every decision is
// `labHeatmapModel.ts`'s; this draws it, writes the mode and the stat to the store, and resolves a selected square:
// an exact tested square selects its trial, an untested one opens the panel's one line, an aggregate one opens its
// distribution (never a configuration). Two stacked canvases: the squares layer is painted once per answer, size or
// metric, over a few frames; the hover, the selection and the cursor live on an overlay that repaints alone.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { errorMessage } from '../api/client';
import { DASH } from '../format';
import type { LabEnvelope, LabMatrix, LabPage, LabSquareStats } from '../results';
import { CHART_FONT, drawAxes, fitText, hatchPattern, HitGrid, LABEL_COLOUR, linearScale, observeResize, ordinalScale, outlineRect, paintInFrames, setupCanvas } from './charts/canvas';
import { objectiveText } from './LabKpiStrip';
import {
  cursorDims,
  HEAT_MARGIN,
  heatBasis,
  heatLayout,
  heatModel,
  locateSquare,
  metricName,
  selectSquareAction,
  squareLabel,
  squareView,
  trialSquare,
  valueText,
  type HeatSquare,
  type Tone,
} from './labHeatmapModel';
import { answered } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { filterHash, type LabMode, type LabStat } from './labStore';
import { LabError } from './NotBuilt';
import type { LabQueryData, Stamped } from './useLabQuery';

/** The squares' fills and texts: the dock's `.cell` tones (styles.css), so a tone looks the same on both. */
const TONE_FILL: Record<Tone, string> = { hot: '#1b5c42', gain: '#143125', mid: '#16222e', cool: '#35232a', loss: '#4a1f27', empty: '#0f1a24' };
const TONE_TEXT: Record<Tone, string> = { hot: '#d9ffe9', gain: '#9fdcbd', mid: '#9fb3c2', cool: '#dd98a0', loss: '#ffb3bb', empty: '#4f6b80' };
const HATCH = '#1b2935';
const SELECTED = '#f5bd51'; // the dock's selected square
const CURSOR = '#2da7ff';
const HOVER = '#d8e5ef';
const FLAG = '#f5bd51'; // a confounded square's corner
const LOW_N_ALPHA = 0.45;
/** The rectangles one frame paints: a 200 × 200 grid of distinct squares paints over ~16 frames, never in one long
 *  task (touching squares that look alike paint as one run, so an all-untested grid is one rectangle per row). */
const FRAME_RECTS = 2500;
const STATS: LabStat[] = ['best', 'median', 'mean', 'worst'];
const SQUARE_PAGE = 50;

type HeatmapData = Pick<LabQueryData, 'loaded' | 'loading' | 'expMatrix' | 'retryMatrix' | 'query' | 'tick'>;
type At = { r: number; c: number };
/** An answered matrix and what it was asked for: the basis and the summary describe it until the next one lands. */
type Answer = { source: string; envelope: Stamped<LabEnvelope<LabMatrix>>; metric: string; mode: LabMode };

/** Paints the squares layer: the frame and the axis values first, then the squares a few rows per frame (hatched
 *  untested ones, toned tested ones, dim under low n; touching squares that look alike as one run), then the
 *  confounded corners and the values and n where a square has room. Returns the cancel. */
function paintHeat(canvas: HTMLCanvasElement, w: number, h: number, matrix: LabMatrix | null, squares: HeatSquare[][], metric: string): () => void {
  const ctx = setupCanvas(canvas, w, h);
  const idle = () => undefined;
  if (matrix === null) return idle;
  const rows = matrix.rows.length;
  const cols = matrix.cols.length;
  const L = heatLayout(w, h, rows, cols);
  if (L.cellW <= 0 || L.cellH <= 0) return idle;
  const gap = L.cellW >= 6 && L.cellH >= 6 ? 1 : 0;
  const sw = L.cellW - gap;
  const sh = L.cellH - gap;
  const right = L.x0 + cols * L.cellW;
  const bottom = L.y0 + rows * L.cellH;
  const hatch = hatchPattern(ctx, TONE_FILL.empty, HATCH);
  const frame = () => {
    drawAxes(ctx, linearScale([0, cols], [L.x0, right]), linearScale([0, rows], [L.y0, bottom]), { x: `${matrix.cols_path} →`, y: `${matrix.rows_path} ↓` }, CHART_FONT);
    // The axis values, thinned to the room they have.
    ctx.font = CHART_FONT;
    ctx.fillStyle = LABEL_COLOUR;
    const x = ordinalScale(matrix.cols, [L.x0, right]);
    const everyX = Math.max(1, Math.ceil(40 / L.cellW));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    matrix.cols.forEach((v, c) => c % everyX === 0 && ctx.fillText(valueText(v), x(v) + L.cellW / 2, bottom + 4, L.cellW * everyX - 2));
    const everyY = Math.max(1, Math.ceil(14 / L.cellH));
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    matrix.rows.forEach((v, r) => r % everyY === 0 && ctx.fillText(valueText(v), L.x0 - 6, L.y0 + r * L.cellH + L.cellH / 2, HEAT_MARGIN.left - 30));
  };
  const look = (s: HeatSquare) => (s.untested ? 'hatch' : s.lowN ? `${s.tone}|low` : s.tone);
  const paintRow = (row: HeatSquare[]) => {
    let start = 0;
    for (let c = 1; c <= row.length; c++) {
      if (c < row.length && gap === 0 && look(row[c]) === look(row[start])) continue;
      const s = row[start];
      ctx.globalAlpha = !s.untested && s.lowN ? LOW_N_ALPHA : 1;
      ctx.fillStyle = s.untested ? hatch : TONE_FILL[s.tone];
      ctx.fillRect(L.x0 + start * L.cellW, L.y0 + s.r * L.cellH, (c - start) * L.cellW - gap, sh);
      start = c;
    }
    ctx.globalAlpha = 1;
  };
  const marks = () => {
    ctx.fillStyle = FLAG;
    ctx.beginPath();
    let flagged = false;
    for (const row of squares)
      for (const s of row) {
        if (s.confounded.length === 0) continue;
        const k = Math.max(3, Math.min(8, sw / 3, sh / 3));
        const x = L.x0 + s.c * L.cellW;
        const y = L.y0 + s.r * L.cellH;
        ctx.moveTo(x, y);
        ctx.lineTo(x + k, y);
        ctx.lineTo(x, y + k);
        ctx.closePath();
        flagged = true;
      }
    if (flagged) ctx.fill();
    if (sw < 34 || sh < 14) return;
    ctx.font = CHART_FONT;
    for (const row of squares)
      for (const s of row) {
        if (s.untested) continue;
        const x = L.x0 + s.c * L.cellW;
        const y = L.y0 + s.r * L.cellH;
        ctx.globalAlpha = s.lowN ? LOW_N_ALPHA : 1;
        ctx.fillStyle = TONE_TEXT[s.tone];
        if (s.value !== null) {
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          fitText(ctx, squareLabel(metric, s.value), x + sw / 2, y + sh / 2 + (sh >= 32 ? 4 : 0), sw - 4);
        }
        if (sw >= 48 && sh >= 32) {
          ctx.textAlign = 'right';
          ctx.textBaseline = 'top';
          ctx.fillText(`n ${s.n}`, x + sw - 3, y + 2);
        }
      }
    ctx.globalAlpha = 1;
  };
  const per = Math.max(1, Math.floor(FRAME_RECTS / cols));
  const chunks: Array<() => void> = [frame];
  for (let r0 = 0; r0 < rows; r0 += per) {
    const band = squares.slice(r0, r0 + per);
    chunks.push(() => band.forEach(paintRow));
  }
  chunks.push(marks);
  return paintInFrames(chunks);
}

/** Paints the overlay: the hover, the selected square (amber) and the cursor (blue, inset when they coincide). A
 *  square too small to show an outline inside it gets one around it. */
function paintMarks(canvas: HTMLCanvasElement | null, w: number, h: number, rows: number, cols: number, marks: { hover: At | null; mark: At | null; cursor: At | null }): void {
  if (canvas === null) return;
  const ctx = setupCanvas(canvas, w, h);
  const L = heatLayout(w, h, rows, cols);
  if (L.cellW <= 0 || L.cellH <= 0) return;
  const gap = L.cellW >= 6 && L.cellH >= 6 ? 1 : 0;
  const sw = L.cellW - gap;
  const sh = L.cellH - gap;
  const grow = Math.max(0, (6 - Math.min(L.cellW, L.cellH)) / 2);
  const box = (at: At, colour: string, inset: number, width: number) =>
    outlineRect(ctx, L.x0 + at.c * L.cellW + inset - grow, L.y0 + at.r * L.cellH + inset - grow, sw - 2 * inset + 2 * grow, sh - 2 * inset + 2 * grow, colour, width);
  const { hover, mark, cursor } = marks;
  if (hover) box(hover, HOVER, 0, 1);
  if (mark) box(mark, SELECTED, 0, 2);
  if (cursor) box(cursor, CURSOR, mark && mark.r === cursor.r && mark.c === cursor.c && sw >= 10 ? 2 : 0, 2);
}

/** A square's hover title: its two values, its value or why it has none, its n and its flags. */
function squareTitle(matrix: LabMatrix, s: HeatSquare, metric: string): string {
  const where = `${matrix.rows_path} = ${valueText(matrix.rows[s.r])} / ${matrix.cols_path} = ${valueText(matrix.cols[s.c])}`;
  if (s.untested) return `${where} · untested`;
  const value = s.value === null ? `no ${metric} value` : objectiveText(metric, s.value);
  const flags = `${s.lowN ? ' · low n' : ''}${s.confounded.length ? ` · confounded by ${s.confounded.join(', ')}` : ''}`;
  return `${where} · ${value} · n ${s.n}${flags}${s.trialId ? ` · ${s.trialId}` : ''}`;
}

/** An aggregate square's distribution over all its n, drawn from the server's histogram (≤ 20 bars). */
function Histogram({ histogram, metric }: { histogram: LabSquareStats['histogram']; metric: string }) {
  const { edges, counts } = histogram;
  if (counts.length === 0 || edges.length < 2) return null;
  const W = 220;
  const H = 56;
  const most = Math.max(1, ...counts);
  const bar = W / counts.length;
  return (
    <>
      <svg className="square-hist" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`distribution of ${metric} in ${counts.length} bins`}>
        {counts.map((n, i) => {
          const height = (n / most) * (H - 2);
          return <rect key={i} x={i * bar + 0.5} y={H - height} width={Math.max(bar - 1, 1)} height={height} />;
        })}
      </svg>
      <div className="sub hist-range">
        <span>{objectiveText(metric, edges[0])}</span>
        <span>{objectiveText(metric, edges[edges.length - 1])}</span>
      </div>
    </>
  );
}

/** The trials an aggregate square holds, a page at a time (`square_trials`, its total the square's n). */
function SquareTrials({ data, matrix, values, metric, scope }: { data: HeatmapData; matrix: LabMatrix; values: [number, number]; metric: string; scope: string }) {
  const lab = useLab();
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<{ key: string; page: LabPage | null; error: string | null } | null>(null);
  const key = `${filterHash(lab.filter)}|${lab.metric}|${offset}|${data.tick}|${retry}`;
  useEffect(() => {
    let cancelled = false;
    data
      .query<LabPage>('square_trials', { rows: matrix.rows_path, cols: matrix.cols_path, row_value: values[0], col_value: values[1], offset, limit: SQUARE_PAGE })
      .then((envelope) => !cancelled && envelope !== null && setState({ key, page: envelope, error: null }))
      .catch((e: unknown) => !cancelled && setState({ key, page: null, error: errorMessage(e) }));
    return () => {
      cancelled = true;
    };
    // The key stands for the filter, the metric (a page carries only its column), the page, the refresh tick and
    // Retry; the square is the component's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (state === null || state.key !== key) return <div className="muted" id="lab-square-trials">loading the square’s trials…</div>;
  if (state.error !== null) return <LabError id="lab-square-trials" message={`Trials unavailable: ${state.error}`} onRetry={() => setRetry((n) => n + 1)} />;
  const page = state.page;
  if (page === null) return null;
  const column = `${scope}.${metric}`;
  return (
    <div id="lab-square-trials" className="square-trials">
      <table>
        <tbody>
          {page.rows.map((row) => (
            <tr key={row.trial_id} data-square-trial={row.trial_id}>
              <td>trial {row.trial_no}</td>
              <td>{objectiveText(metric, row.values[column] ?? null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="square-pager">
        <span className="sub">
          trials {page.rows.length === 0 ? 0 : offset + 1}–{offset + page.rows.length} of {page.total}
        </span>
        <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - SQUARE_PAGE))}>
          Previous
        </button>
        <button type="button" className="btn" disabled={offset + page.rows.length >= page.total} onClick={() => setOffset(offset + SQUARE_PAGE)}>
          Next
        </button>
      </div>
    </div>
  );
}

/** `#lab-square-panel`: an untested square's one line, or an aggregate square's distribution with its trials. */
function SquarePanel({ data, matrix, at, stats, metric, scope }: { data: HeatmapData; matrix: LabMatrix; at: At; stats: LabSquareStats | null; metric: string; scope: string }) {
  if (stats === null)
    return (
      <aside className="square-panel" id="lab-square-panel" aria-label="Selected square">
        <div className="lab-line">untested: no trial has these values</div>
      </aside>
    );
  const values: [number, number] = [matrix.rows[at.r], matrix.cols[at.c]];
  const fmt = (v: number | null) => objectiveText(metric, v);
  return (
    <aside className="square-panel" id="lab-square-panel" aria-label="Selected square">
      <div className="rail-title">
        {matrix.rows_path} = {valueText(values[0])} · {matrix.cols_path} = {valueText(values[1])}
      </div>
      <div className="lab-basis">Aggregated from tested (n = {stats.n})</div>
      <div className="lab-line">
        n = {stats.n}
        {stats.low_n ? ' · low n' : ''}
      </div>
      <div className="sub">
        IQR {fmt(stats.p25)}–{fmt(stats.p75)} · range {fmt(stats.min)}–{fmt(stats.max)}
      </div>
      <div className="square-actions">
        <button type="button" className="btn" id="lab-square-pin" disabled title="an aggregate is not a runnable strategy">
          Pin
        </button>
        <button type="button" className="btn" id="lab-square-send" disabled title="an aggregate is not a runnable strategy">
          Send to Validation
        </button>
      </div>
      <Histogram histogram={stats.histogram} metric={metric} />
      {stats.histogram.nulls > 0 && <div className="sub">{stats.histogram.nulls} without a {metric} value (undefined, not in the histogram)</div>}
      {stats.confounded.length > 0 && <div className="sub square-confounded">confounded by {stats.confounded.join(', ')}</div>}
      <SquareTrials key={`${matrix.rows_path}|${matrix.cols_path}|${values[0]}|${values[1]}`} data={data} matrix={matrix} values={values} metric={metric} scope={scope} />
    </aside>
  );
}

/** Trial Lab's heatmap for an experiment. */
export function LabHeatmap({ data }: { data: HeatmapData }) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { loaded, expMatrix, retryMatrix } = data;
  const envelope = expMatrix.envelope; // the answer for the view in hand; null while it is asked
  const metric = lab.metric;
  const source = loaded ? `${loaded.kind}:${loaded.id}` : null;
  const current = useMemo<Answer | null>(() => (envelope !== null && source !== null ? { source, envelope, metric, mode: lab.mode } : null), [envelope, source, metric, lab.mode]);
  // The basis and the summary describe the last answer this source gave until the next one lands: a pending query
  // shows as `data-loading` and `#lab-heatmap-loading`, never inside them.
  const [last, setLast] = useState<Answer | null>(null);
  useEffect(() => {
    if (current !== null) setLast(current);
  }, [current]);
  const shown = answered(current, last, source);
  const model = useMemo(() => (shown === null ? null : heatModel(shown.envelope, shown.metric, shown.mode, shown.metric === 'max_drawdown')), [shown]);
  const dims = cursorDims(envelope);

  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = wrap.current;
    if (el === null) return;
    return observeResize(el, (w, h) => setSize((s) => (s.w === w && s.h === h ? s : { w, h })));
  }, []);

  // The selection, in one loop for the mouse and the keys: both dispatch `selectSquareAction`; the square is then
  // found on this matrix by its axes and values and resolved here.
  const square = lab.selected !== null && 'square' in lab.selected ? lab.selected.square : null;
  const selectedTrial = lab.selected !== null && 'trials' in lab.selected && lab.selected.trials.length === 1 ? lab.selected.trials[0] : null;
  const at = envelope !== null && square !== null ? locateSquare(envelope, square) : null;
  const view = envelope !== null && at !== null ? squareView(envelope, lab.mode, at.r, at.c) : null;
  const mark = at ?? (envelope !== null && selectedTrial !== null ? trialSquare(envelope, selectedTrial) : null);
  const cursor = lab.cursor !== null && dims !== null ? { r: Math.min(lab.cursor.r, dims.rows.length - 1), c: Math.min(lab.cursor.c, dims.cols.length - 1) } : null;
  const trialToSelect = view?.kind === 'trial' ? view.trialId : null;
  useEffect(() => {
    // An exact tested square is its trial: the selection moves to it, and the table and the rail follow.
    if (trialToSelect !== null) dispatch({ type: 'SELECT_TRIALS', ids: [trialToSelect] });
  }, [trialToSelect, dispatch]);

  // The squares layer: painted only when a new answer or the size arrives (the metric is part of the answer).
  const painted = current !== null && shown === current && model !== null ? model.squares : null;
  useEffect(() => {
    const el = base.current;
    if (el === null) return;
    return paintHeat(el, size.w, size.h, current?.envelope ?? null, painted ?? [], current?.metric ?? metric);
    // `painted` is the model of `current`, which carries its metric.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, painted, size.w, size.h]);

  // The overlay: the hover (kept off React state, so crossing squares re-renders nothing), the selection, the cursor.
  const rows = envelope?.rows.length ?? 0;
  const cols = envelope?.cols.length ?? 0;
  const hover = useRef<At | null>(null);
  const marks = useRef<{ mark: At | null; cursor: At | null }>({ mark: null, cursor: null });
  useEffect(() => {
    marks.current = { mark, cursor };
    if (envelope === null) hover.current = null;
    paintMarks(overlay.current, size.w, size.h, rows, cols, { hover: hover.current, mark, cursor });
    // The marks' coordinates stand for them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mark?.r, mark?.c, cursor?.r, cursor?.c, size.w, size.h, rows, cols, envelope]);

  const layout = heatLayout(size.w, size.h, rows, cols);
  const grid = new HitGrid(rows, cols, layout.x0, layout.y0, layout.cellW, layout.cellH);
  const hit = (e: MouseEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return grid.at(e.clientX - box.left, e.clientY - box.top);
  };
  const onMove = (e: MouseEvent<HTMLCanvasElement>) => {
    const found = hit(e);
    const was = hover.current;
    if (was?.r === found?.r && was?.c === found?.c) return;
    hover.current = found;
    const s = found !== null && painted !== null ? (painted[found.r]?.[found.c] ?? null) : null;
    e.currentTarget.title = s !== null && envelope !== null ? squareTitle(envelope, s, metric) : '';
    paintMarks(overlay.current, size.w, size.h, rows, cols, { hover: found, ...marks.current });
  };
  const onLeave = (e: MouseEvent<HTMLCanvasElement>) => {
    hover.current = null;
    e.currentTarget.title = '';
    paintMarks(overlay.current, size.w, size.h, rows, cols, { hover: null, ...marks.current });
  };
  const onClick = (e: MouseEvent<HTMLCanvasElement>) => {
    const found = hit(e);
    if (found === null || dims === null) return;
    dispatch(selectSquareAction(dims, found.r, found.c));
    if (lab.cursor) dispatch({ type: 'MOVE_CURSOR', dr: found.r - lab.cursor.r, dc: found.c - lab.cursor.c, rows: dims.rows.length, cols: dims.cols.length }); // the cursor follows the click
  };

  const params = loaded?.kind === 'exp' ? loaded.document.surface.parameters.length : null;
  const oneAxis = params !== null && params < 2;
  const pending = expMatrix.error === null && !oneAxis && (loaded === null ? data.loading : envelope === null || expMatrix.loading);
  const basis = shown !== null ? heatBasis(shown.envelope) : '';
  const summary = model?.summary ?? '';
  const empty = current !== null ? (current.envelope.empty ?? model?.empty ?? null) : null;
  const stats = view?.kind === 'aggregate' ? view.stats : null;

  return (
    <div className="lab-heatmap" id="lab-heatmap" data-loading={pending ? 'true' : 'false'}>
      <div className="heat-toolbar">
        <span className="lab-basis" id="lab-heatmap-basis">
          {basis}
        </span>
        {pending && (
          <span className="sub lab-loading" id="lab-heatmap-loading">
            {loaded === null ? 'loading the source…' : 'loading the matrix…'}
          </span>
        )}
        <span className="lab-mode" role="group" aria-label="Heatmap mode">
          <button
            type="button"
            id="lab-mode-exact"
            className={'chip' + (lab.mode === 'exact' ? ' active' : '')}
            aria-pressed={lab.mode === 'exact'}
            title="Tested (exact): the slice through the other parameters' values; a square is one trial, or untested"
            onClick={() => dispatch({ type: 'SET_MODE', mode: 'exact' })}
          >
            Exact
          </button>
          <button
            type="button"
            id="lab-mode-aggregate"
            className={'chip' + (lab.mode === 'aggregate' ? ' active' : '')}
            aria-pressed={lab.mode === 'aggregate'}
            title="Aggregated from tested: every trial with the square's two values, the other parameters varying"
            onClick={() => dispatch({ type: 'SET_MODE', mode: 'aggregate' })}
          >
            Aggregate
          </button>
        </span>
        <label className="lab-field" title={lab.mode === 'aggregate' ? 'the statistic each aggregate square shows' : 'an exact square is one trial: the statistic applies to aggregate squares'}>
          Stat
          <select id="lab-stat" value={lab.stat} disabled={lab.mode !== 'aggregate'} onChange={(e) => dispatch({ type: 'SET_STAT', stat: e.target.value as LabStat })}>
            {STATS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="sub" id="lab-heatmap-axes">
        Y (rows): {envelope?.rows_path ?? lab.axes?.[0] ?? DASH} · X (columns): {envelope?.cols_path ?? lab.axes?.[1] ?? DASH} · {metricName(metric)}
      </div>
      {oneAxis && <div className="lab-empty">no matrix: the experiment varies fewer than two parameters</div>}
      {expMatrix.error !== null && <LabError message={`Matrix unavailable: ${expMatrix.error}`} onRetry={retryMatrix} />}
      {empty !== null && <div className="lab-empty heat-empty">{empty}</div>}
      <div className="heat-body">
        <div className="heat-canvas-wrap" ref={wrap}>
          <canvas id="lab-heatmap-canvas" ref={base} tabIndex={0} role="img" aria-label={summary} onMouseMove={onMove} onMouseLeave={onLeave} onClick={onClick} />
          <canvas className="heat-overlay" ref={overlay} aria-hidden="true" />
        </div>
        {envelope !== null && at !== null && view !== null && view.kind !== 'trial' && (
          <SquarePanel data={data} matrix={envelope} at={at} stats={stats} metric={metric} scope={lab.filter.scope} />
        )}
      </div>
      <div className="sub" id="lab-heatmap-summary" aria-live="polite">
        {summary}
      </div>
      <div className="sub">Arrow keys move the cursor across the squares, Enter selects one; Esc clears the brush.</div>
    </div>
  );
}
