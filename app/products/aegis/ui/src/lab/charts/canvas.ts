// The Lab's hand-written Canvas 2D primitives (spec §12, the charting decision): linear and ordinal scales, plot
// axes, a hover hit grid, a 1-D axis brush, device-pixel scaling and resize, and the few drawing helpers the
// heatmap and the parallel coordinates share. Nothing React and nothing fetched: the scales, the hit grid and the
// brush are pure and run under vitest in node; the drawing helpers take the context they draw on.

/** A continuous map from data values to pixels, with its inverse. */
export interface Scale {
  (v: number): number;
  invert(px: number): number;
  domain: [number, number];
  range: [number, number];
}

/** `domain` onto `range`, linearly. A degenerate domain (lo === hi) maps every value to the range midpoint and a
 *  degenerate range inverts to the domain midpoint: neither ever gives NaN. */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;
  const reach = r1 - r0;
  const scale = ((v: number) => (span === 0 ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * reach)) as Scale;
  scale.invert = (px: number) => {
    if (span === 0) return d0;
    if (reach === 0) return (d0 + d1) / 2;
    return d0 + ((px - r0) / reach) * span;
  };
  scale.domain = [d0, d1];
  scale.range = [r0, r1];
  return scale;
}

export interface OrdinalScale {
  /** The start pixel of the value's band; NaN for a value the scale does not hold. */
  (v: number): number;
  /** The width of one band (negative when the range runs backwards). */
  band: number;
  /** The index of the band under `px`: a band holds its start and not its end; -1 outside every band. */
  index(px: number): number;
}

/** One equal band per value across `range`, in the order given. */
export function ordinalScale(values: number[], range: [number, number]): OrdinalScale {
  const [r0, r1] = range;
  const n = values.length;
  const band = n > 0 ? (r1 - r0) / n : 0;
  const at = new Map<number, number>();
  values.forEach((v, i) => {
    if (!at.has(v)) at.set(v, i);
  });
  const scale = ((v: number) => {
    const i = at.get(v);
    return i === undefined ? Number.NaN : r0 + i * band;
  }) as OrdinalScale;
  scale.band = band;
  scale.index = (px: number) => {
    if (band === 0) return -1;
    const i = Math.floor((px - r0) / band);
    return i >= 0 && i < n ? i : -1;
  };
  return scale;
}

/** The device-pixel ratio, 1 outside a browser. */
function pixelRatio(): number {
  return typeof window !== 'undefined' && window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
}

/** Sizes `canvas` to width × height CSS pixels at the device-pixel ratio and returns its context, scaled so that
 *  drawing is in CSS pixels, and cleared. */
export function setupCanvas(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D {
  const ratio = pixelRatio();
  const w = Math.max(0, Math.floor(width));
  const h = Math.max(0, Math.floor(height));
  const pw = Math.round(w * ratio);
  const ph = Math.round(h * ratio);
  if (canvas.width !== pw) canvas.width = pw;
  if (canvas.height !== ph) canvas.height = ph;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext('2d');
  if (ctx === null) throw new Error('this browser gives the canvas no 2D context');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return ctx;
}

/** The Lab's chart text: the app's face at 11 px, the smallest size the Lab shows (walk item 106). */
export const CHART_FONT = '11px Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
/** The axis lines (--line, lifted a step so they read on the panel) and the axis text (--muted). */
export const AXIS_COLOUR = '#2c3d4b';
export const LABEL_COLOUR = '#7690a3';
/** How far below the x axis its title sits, and how far left of the y axis the y title's centre sits: a caller
 *  leaves at least this room (and the tick labels' own) around the plot. */
export const X_TITLE_GAP = 20;
export const Y_TITLE_GAP = 60;

/** The plot's frame: the y axis along the left of x's range, the x axis along the bottom of y's range, and the two
 *  titles (x centred below, y turned along the left). The tick labels are the caller's: an ordinal axis names its
 *  values, a linear one its ends. */
export function drawAxes(ctx: CanvasRenderingContext2D, x: Scale, y: Scale, labels: { x: string; y: string }, font: string): void {
  const left = Math.min(...x.range);
  const right = Math.max(...x.range);
  const top = Math.min(...y.range);
  const bottom = Math.max(...y.range);
  ctx.save();
  ctx.strokeStyle = AXIS_COLOUR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(Math.round(left) - 0.5, top);
  ctx.lineTo(Math.round(left) - 0.5, Math.round(bottom) + 0.5);
  ctx.lineTo(right, Math.round(bottom) + 0.5);
  ctx.stroke();
  ctx.font = font;
  ctx.fillStyle = LABEL_COLOUR;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  if (labels.x) ctx.fillText(labels.x, (left + right) / 2, bottom + X_TITLE_GAP, Math.max(right - left, 40));
  if (labels.y) {
    ctx.translate(left - Y_TITLE_GAP, (top + bottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = 'middle';
    ctx.fillText(labels.y, 0, 0, Math.max(bottom - top, 40));
  }
  ctx.restore();
}

/** Hit testing over a grid of equal squares: `rows` × `cols` squares of cellW × cellH from (x0, y0). */
export class HitGrid {
  constructor(
    readonly rows: number,
    readonly cols: number,
    readonly x0: number,
    readonly y0: number,
    readonly cellW: number,
    readonly cellH: number,
  ) {}

  /** The square under (px, py), or null outside the grid. A square holds its top and left edges. */
  at(px: number, py: number): { r: number; c: number } | null {
    if (!(this.cellW > 0 && this.cellH > 0)) return null;
    const c = Math.floor((px - this.x0) / this.cellW);
    const r = Math.floor((py - this.y0) / this.cellH);
    return r >= 0 && r < this.rows && c >= 0 && c < this.cols ? { r, c } : null;
  }
}

/** A drag shorter than this, in pixels, is a click. */
export const BRUSH_MIN_PX = 3;

/** One gesture of a 1-D brush along an axis: press, drag, release. While the drag goes on `range` is the live
 *  [lo, hi] in the axis's values (ordered whichever way the drag went, stopped at the axis ends); the release hands
 *  `onChange` that range, or null for a click without a drag (which clears the axis's brush). The filter is written
 *  once per gesture, on release. */
export class Brush1D {
  private start: number | null = null;
  private live: [number, number] | null = null;

  constructor(
    private readonly axis: Scale,
    private readonly onChange: (range: [number, number] | null) => void,
  ) {}

  get range(): [number, number] | null {
    return this.live;
  }

  private clamp(px: number): number {
    const lo = Math.min(...this.axis.range);
    const hi = Math.max(...this.axis.range);
    return Math.min(Math.max(px, lo), hi);
  }

  down(px: number): void {
    this.start = this.clamp(px);
    this.live = null;
  }

  move(px: number): void {
    if (this.start === null) return;
    const at = this.clamp(px);
    if (Math.abs(at - this.start) < BRUSH_MIN_PX) {
      this.live = null;
      return;
    }
    const a = this.axis.invert(this.start);
    const b = this.axis.invert(at);
    this.live = [Math.min(a, b), Math.max(a, b)];
  }

  up(): void {
    if (this.start === null) return;
    this.start = null;
    this.onChange(this.live);
  }
}

/** Calls `cb` with the element's content size (whole CSS pixels) now and whenever it changes; returns the
 *  disconnect. Without a ResizeObserver it listens to the window instead. */
export function observeResize(el: HTMLElement, cb: (w: number, h: number) => void): () => void {
  if (typeof ResizeObserver === 'undefined') {
    const on = () => cb(Math.floor(el.clientWidth), Math.floor(el.clientHeight));
    on();
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }
  const observer = new ResizeObserver((entries) => {
    const box = entries[entries.length - 1]?.contentRect;
    if (box) cb(Math.floor(box.width), Math.floor(box.height));
  });
  observer.observe(el);
  return () => observer.disconnect();
}

// --- drawing helpers -------------------------------------------------------------------------------------------

/** A rectangle filled with `fill` and striped with `stripe` (the hatch of an untested square: never filled with a
 *  value). */
export function hatchRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, fill: string, stripe: string): void {
  if (w <= 0 || h <= 0) return;
  ctx.save();
  ctx.fillStyle = fill;
  ctx.fillRect(x, y, w, h);
  if (w >= 3 && h >= 3) {
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.strokeStyle = stripe;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let d = -h; d < w; d += 6) {
      ctx.moveTo(x + d, y + h);
      ctx.lineTo(x + d + h, y);
    }
    ctx.stroke();
  }
  ctx.restore();
}

/** An outline just inside a rectangle (the cursor, the selected square). */
export function outlineRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, colour: string, width = 2): void {
  if (w <= 0 || h <= 0) return;
  ctx.save();
  ctx.strokeStyle = colour;
  ctx.lineWidth = width;
  const inset = Math.min(width / 2, w / 2, h / 2);
  ctx.strokeRect(x + inset, y + inset, Math.max(w - 2 * inset, 0), Math.max(h - 2 * inset, 0));
  ctx.restore();
}

/** Strokes a line through `points`; a null point breaks it (a value the line does not have). */
export function strokeLine(ctx: CanvasRenderingContext2D, points: ReadonlyArray<readonly [number, number] | null>): void {
  ctx.beginPath();
  let open = false;
  for (const point of points) {
    if (point === null || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) {
      open = false;
      continue;
    }
    if (open) ctx.lineTo(point[0], point[1]);
    else ctx.moveTo(point[0], point[1]);
    open = true;
  }
  ctx.stroke();
}

/** Draws `text` centred in a box when it fits there; returns whether it was drawn. */
export function fitText(ctx: CanvasRenderingContext2D, text: string, cx: number, cy: number, maxWidth: number): boolean {
  if (maxWidth <= 0 || ctx.measureText(text).width > maxWidth) return false;
  ctx.fillText(text, cx, cy);
  return true;
}
