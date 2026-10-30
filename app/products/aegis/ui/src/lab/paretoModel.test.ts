import { describe, expect, it } from 'vitest';
import { pareto } from './analyticsFixtures';
import { objectiveText } from './metricRules';
import {
  axisTitle,
  densityRects,
  directionText,
  objectiveOptions,
  paretoBasis,
  paretoCounts,
  paretoScales,
  paretoSummary,
  plotBox,
  plotPoints,
  pointTitle,
  pointTone,
  usableObjectives,
  withObjective,
} from './paretoModel';

const AVAILABLE = ['net_pnl', 'mar', 'max_drawdown', 'trade_count'];

describe('the objective pickers', () => {
  it('usableObjectives keeps the chosen metrics the source offers, in order, and pads to two', () => {
    expect(usableObjectives(['net_pnl', 'max_drawdown'], AVAILABLE)).toEqual(['net_pnl', 'max_drawdown']);
    // A grid job offers four metrics: a CAGR choice carried over from an experiment is dropped, then padded.
    expect(usableObjectives(['net_pnl', 'cagr'], AVAILABLE)).toEqual(['net_pnl', 'max_drawdown']);
    expect(usableObjectives(['cagr', 'mar'], AVAILABLE)).toEqual(['mar', 'net_pnl']);
    expect(usableObjectives([], AVAILABLE)).toEqual(['net_pnl', 'max_drawdown']);
  });

  it('usableObjectives never holds a metric twice or more than three, and tolerates a source with one metric', () => {
    expect(usableObjectives(['net_pnl', 'net_pnl', 'mar'], AVAILABLE)).toEqual(['net_pnl', 'mar']);
    expect(usableObjectives(['net_pnl', 'mar', 'max_drawdown', 'trade_count'], AVAILABLE)).toEqual(['net_pnl', 'mar', 'max_drawdown']);
    expect(usableObjectives([], ['net_pnl'])).toEqual(['net_pnl']);
    expect(usableObjectives(['net_pnl'], [])).toEqual([]);
  });

  it('objectiveOptions offers every available metric except those the other pickers hold', () => {
    expect(objectiveOptions(['net_pnl', 'max_drawdown'], 0, AVAILABLE)).toEqual(['net_pnl', 'mar', 'trade_count']);
    expect(objectiveOptions(['net_pnl', 'max_drawdown'], 1, AVAILABLE)).toEqual(['mar', 'max_drawdown', 'trade_count']);
    expect(objectiveOptions(['net_pnl', 'max_drawdown'], 2, AVAILABLE)).toEqual(['mar', 'trade_count']);
    expect(objectiveOptions(['net_pnl', 'max_drawdown', 'mar'], 2, AVAILABLE)).toEqual(['mar', 'trade_count']);
  });

  it('withObjective sets a slot, swaps with the picker that held the metric, and drops the third on null', () => {
    expect(withObjective(['net_pnl', 'max_drawdown'], 0, 'mar')).toEqual(['mar', 'max_drawdown']);
    expect(withObjective(['net_pnl', 'max_drawdown'], 0, 'max_drawdown')).toEqual(['max_drawdown', 'net_pnl']);
    expect(withObjective(['net_pnl', 'max_drawdown'], 2, 'mar')).toEqual(['net_pnl', 'max_drawdown', 'mar']);
    expect(withObjective(['net_pnl', 'max_drawdown', 'mar'], 2, null)).toEqual(['net_pnl', 'max_drawdown']);
    // The two required pickers cannot be emptied, and a third cannot copy a metric another picker holds.
    expect(withObjective(['net_pnl', 'max_drawdown'], 1, null)).toEqual(['net_pnl', 'max_drawdown']);
    expect(withObjective(['net_pnl', 'max_drawdown'], 2, 'net_pnl')).toEqual(['net_pnl', 'max_drawdown']);
    expect(withObjective(['net_pnl', 'max_drawdown'], 2, null)).toEqual(['net_pnl', 'max_drawdown']);
  });
});

describe('reading direction and losses', () => {
  it('names the direction from the payload orientation, which is for reading only', () => {
    expect(directionText(1)).toBe('higher is better');
    expect(directionText(-1)).toBe('lower is better');
    expect(axisTitle('max_drawdown', -1)).toContain('lower is better');
    expect(axisTitle('net_pnl', 1)).toContain('higher is better');
    expect(axisTitle('net_pnl', 1)).toContain('Net P&L');
  });

  it('a front point is a loss when any money-signed objective is below break-even, never otherwise', () => {
    expect(pointTone(['net_pnl', 'max_drawdown'], [-100, 0.05])).toBe('loss');
    expect(pointTone(['net_pnl', 'max_drawdown'], [500, 0.12])).toBe('front');
    expect(pointTone(['net_pnl', 'max_drawdown'], [0, 0.12])).toBe('front');
    expect(pointTone(['max_drawdown', 'mar'], [0.3, -0.2])).toBe('loss');
    expect(pointTone(['max_drawdown', 'trade_count'], [0.3, 12])).toBe('front');
  });
});

describe('the plot frame', () => {
  it('plotBox leaves room for the titles and ticks, and is null when nothing would be left', () => {
    expect(plotBox(400, 300)).toEqual({ x0: 78, x1: 382, y0: 12, y1: 256 });
    expect(plotBox(100, 300)).toBeNull();
    expect(plotBox(400, 60)).toBeNull();
  });

  it('paretoScales maps the density range onto the box with the y axis up, and is null without a range', () => {
    const scales = paretoScales(pareto(), 400, 300);
    expect(scales).not.toBeNull();
    expect(scales?.x(-200)).toBe(78);
    expect(scales?.x(1000)).toBe(382);
    expect(scales?.y(0)).toBe(256); // the low value at the bottom
    expect(scales?.y(0.4)).toBe(12);
    const base = pareto();
    expect(paretoScales({ ...base, density: { ...base.density, x: null, y: null } }, 400, 300)).toBeNull();
    expect(paretoScales(base, 100, 300)).toBeNull();
  });
});

describe('plotPoints', () => {
  const view = pareto();
  const scales = paretoScales(view, 400, 300)!;

  it('places each drawn point at its real values; the drawn count is not the front size', () => {
    const points = plotPoints(view, scales);
    expect(points).toHaveLength(3);
    expect(view.front_size).toBe(5);
    expect(points[1].x).toBe(scales.x(500));
    expect(points[1].y).toBe(scales.y(0.12));
    expect(points.map((p) => p.id)).toEqual(['exp:e1#1', 'exp:e1#2', 'exp:e1#3']);
  });

  it('colours a losing point red whatever its rank, and the rest as the front', () => {
    expect(plotPoints(view, scales).map((p) => p.tone)).toEqual(['loss', 'front', 'front']);
  });

  it('two objectives draw one radius; with a third, the dot grows with how good the third is', () => {
    const two = plotPoints(view, scales);
    expect(new Set(two.map((p) => p.r)).size).toBe(1);
    const three = pareto({
      objectives: ['net_pnl', 'mar', 'max_drawdown'],
      orientation: [1, 1, -1],
      points: [
        { trial_id: 'exp:e1#1', values: [100, 1, 0.3] },
        { trial_id: 'exp:e1#2', values: [200, 2, 0.1] },
        { trial_id: 'exp:e1#3', values: [300, 3, 0.2] },
      ],
    });
    const r = plotPoints(three, scales).map((p) => p.r);
    // Drawdown is lower-is-better: the 0.1 point is the best third objective, so the biggest dot.
    expect(r[1]).toBeGreaterThan(r[2]);
    expect(r[2]).toBeGreaterThan(r[0]);
    // The same values with a higher-is-better third objective grow the other way.
    const flipped = plotPoints({ ...three, objectives: ['net_pnl', 'mar', 'trade_count'], orientation: [1, 1, 1] }, scales).map((p) => p.r);
    expect(flipped[0]).toBeGreaterThan(flipped[2]);
    expect(flipped[2]).toBeGreaterThan(flipped[1]);
  });

  it('a third objective that is one value everywhere gives every dot one middling radius', () => {
    const flat = pareto({
      objectives: ['net_pnl', 'mar', 'trade_count'],
      orientation: [1, 1, 1],
      points: [
        { trial_id: 'exp:e1#1', values: [100, 1, 40] },
        { trial_id: 'exp:e1#2', values: [200, 2, 40] },
      ],
    });
    const r = plotPoints(flat, scales).map((p) => p.r);
    expect(r[0]).toBe(r[1]);
    expect(Number.isFinite(r[0])).toBe(true);
  });
});

describe('densityRects (the dominated cloud as a bitmap: only bins that hold trials)', () => {
  const view = pareto();
  const scales = paretoScales(view, 400, 300)!;

  it('draws one rectangle per bin holding a trial, none for an empty bin, and every trial exactly once', () => {
    const rects = densityRects(view, scales);
    const filled = view.density.counts.flat().filter((n) => n > 0).length;
    expect(rects).toHaveLength(filled);
    expect(rects.reduce((sum, r) => sum + r.count, 0)).toBe(view.dominated);
  });

  it('places a bin by its edges with counts[y][x] ascending on both axes', () => {
    // counts[0][1] = 6: x bin 1 spans 100..400 (300-wide bins from -200), y bin 0 spans 0..0.1.
    const rect = densityRects(view, scales).find((r) => r.count === 6)!;
    expect(rect.x).toBe(scales.x(100));
    expect(rect.w).toBeCloseTo(scales.x(400) - scales.x(100), 9);
    expect(rect.y).toBeCloseTo(scales.y(0.1), 9);
    expect(rect.h).toBeCloseTo(scales.y(0) - scales.y(0.1), 9);
    expect(rect.w).toBeGreaterThan(0);
    expect(rect.h).toBeGreaterThan(0);
  });

  it('a bin is a loss only when all of it is below break-even on a money-signed axis', () => {
    const shifted = pareto({ density: { ...view.density, x: [-400, 800] } }); // bins: -400..-100, -100..200, 200..500, 500..800
    const s = paretoScales(shifted, 400, 300)!;
    const tones = densityRects(shifted, s).map((r) => [r.bx, r.tone] as const);
    expect(tones.filter(([bx]) => bx === 0).every(([, tone]) => tone === 'loss')).toBe(true);
    expect(tones.filter(([bx]) => bx === 1).every(([, tone]) => tone === 'cloud')).toBe(true); // straddles zero
    expect(tones.filter(([bx]) => bx >= 2).every(([, tone]) => tone === 'cloud')).toBe(true);
    // Drawdown (y) carries no sign: no bin is a loss for being high.
    const swapped = pareto({ objectives: ['max_drawdown', 'trade_count'], orientation: [-1, 1], density: { ...view.density, axes: ['max_drawdown', 'trade_count'], x: [0, 0.4], y: [0, 100] } });
    expect(densityRects(swapped, paretoScales(swapped, 400, 300)!).every((r) => r.tone === 'cloud')).toBe(true);
  });

  it('the fuller the bin the stronger it is drawn, inside (0, 1]', () => {
    const rects = densityRects(view, scales);
    const byCount = [...rects].sort((a, b) => a.count - b.count);
    for (let i = 1; i < byCount.length; i++) expect(byCount[i].alpha).toBeGreaterThanOrEqual(byCount[i - 1].alpha);
    for (const r of rects) {
      expect(r.alpha).toBeGreaterThan(0);
      expect(r.alpha).toBeLessThanOrEqual(1);
    }
    expect(byCount[0].alpha).toBeLessThan(byCount[byCount.length - 1].alpha);
  });

  it('draws nothing for a view with no trial defined on every objective', () => {
    const none = pareto({ density: { ...view.density, x: null, y: null, counts: [[0]] }, front: [], points: [], front_size: 0, dominated: 0 });
    expect(paretoScales(none, 400, 300)).toBeNull();
    expect(densityRects(none, null)).toEqual([]);
    expect(plotPoints(none, null)).toEqual([]);
  });
});

describe('the counts and the basis the panel prints', () => {
  it('prints the true front size, with the drawn count apart and the sampled label', () => {
    const view = pareto();
    expect(paretoCounts(view)).toEqual({ frontSize: 5, dominated: 40, excluded: 2, drawn: 3, sampled: true, sampledLabel: 'Sampled subset (3 of 5)' });
    const whole = pareto({ sampled: false, basis: 'Tested (exact)', front_size: 3 });
    expect(paretoCounts(whole)).toMatchObject({ frontSize: 3, drawn: 3, sampled: false, sampledLabel: 'all 3 front points drawn' });
  });

  it('prints the front basis and the cloud basis as the server sends them, and the provisional line while running', () => {
    const view = pareto();
    const basis = paretoBasis(view, { provisional: false, snapshot: null, receivedAt: '2026-10-30T10:00:00Z' });
    expect(basis).toContain('Sampled subset (3 of 5)');
    expect(basis).toContain('Aggregated from tested (n = 40)');
    expect(basis).not.toContain('PROVISIONAL');
    const running = paretoBasis(view, { provisional: true, snapshot: { generation: 2, chunk_watermark: 9 }, receivedAt: '2026-10-30T10:00:05Z' });
    expect(running).toContain('PROVISIONAL · snapshot 10:00:05 · gen 2');
  });

  it('the summary names the objectives with their direction and every count', () => {
    const text = paretoSummary(pareto());
    expect(text).toContain('Net P&L (higher is better)');
    expect(text).toContain('Max drawdown (lower is better)');
    expect(text).toContain('5 on the front');
    expect(text).toContain('40 dominated');
    expect(text).toContain('2 excluded');
    expect(text).toContain('3 drawn');
  });

  it('a point titles itself with the trial number and every objective in real units', () => {
    const view = pareto();
    const title = pointTitle(view, 1);
    expect(title).toContain('trial 2');
    expect(title).toContain(objectiveText('net_pnl', 500));
    expect(title).toContain(objectiveText('max_drawdown', 0.12)); // the real drawdown, not its negation
    expect(pointTitle(view, 9)).toBe('');
  });
});
