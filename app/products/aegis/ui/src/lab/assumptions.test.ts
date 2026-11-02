// Spec §7.11: every analytic panel states its assumptions. One shared line, four clauses in a fixed order (the uniform-design
// clause only where the panel's numbers rest on the uniform rows), on every panel the Lab draws. Static markup of each panel
// with no source open or one open and no answer yet: the line is part of the panel's frame, not of an answer.
import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { Parameter, Surface } from '../contracts';
import { ASSUMPTION_CLAUSES, AssumptionsLine, assumptionsText } from './AssumptionsLine';
import { ConvergenceChart } from './ConvergenceChart';
import { FamiliesPage } from './FamiliesPage';
import { ImportanceView } from './ImportanceView';
import { InteractionMatrix } from './InteractionMatrix';
import { LabHeatmap } from './LabHeatmap';
import { ParetoView } from './ParetoView';
import { RobustnessView } from './RobustnessView';
import type { LabQueryData } from './useLabQuery';

const GRID = 'Discrete grids: every parameter has a step';
const UNIFORM = 'Uniform-design rows';
const IN_SAMPLE = 'Metrics are in-sample on the selection partition';
const RAW = 'Raw archives, not research-eligible';

/** Every `lab-assumptions-<panel>` paragraph in the markup, with its panel, its data-panel and its text. */
function lines(markup: string): Array<{ panel: string; dataPanel: string | undefined; className: string | undefined; text: string }> {
  return [...markup.matchAll(/<p ([^>]*id="lab-assumptions-([a-z]+)"[^>]*)>([^<]*)<\/p>/g)].map((m) => ({
    panel: m[2],
    dataPanel: /data-panel="([^"]*)"/.exec(m[1])?.[1],
    className: /class="([^"]*)"/.exec(m[1])?.[1],
    text: m[3],
  }));
}

describe('the assumptions line', () => {
  it('states four clauses in a fixed order, the uniform-design one only when asked', () => {
    expect(ASSUMPTION_CLAUSES).toEqual({ grid: GRID, uniform: UNIFORM, inSample: IN_SAMPLE, raw: RAW });
    expect(assumptionsText(false)).toBe([GRID, IN_SAMPLE, RAW].join(' · '));
    expect(assumptionsText(true)).toBe([GRID, UNIFORM, IN_SAMPLE, RAW].join(' · '));
  });

  it('is a paragraph with its panel in the id and in data-panel', () => {
    const [found] = lines(renderToStaticMarkup(createElement(AssumptionsLine, { panel: 'heatmap' })));
    expect(found).toEqual({ panel: 'heatmap', dataPanel: 'heatmap', className: 'lab-assumptions', text: assumptionsText(false) });
    expect(lines(renderToStaticMarkup(createElement(AssumptionsLine, { panel: 'importance', uniform: true })))[0].text).toBe(assumptionsText(true));
  });
});

// --- the panels ------------------------------------------------------------------------------------------------------------

const surface: Surface = {
  parameters: [['long_side.indicators.ema.length', 5, 20, 1], ['long_side.stop_loss_pct', 1, 5, 0.5]].map(
    ([path, start, stop, step]): Parameter => ({ path: path as string, start: start as number, stop: stop as number, step: step as number }),
  ),
};
const document = { id: 'e1', name: 'E', status: 'done', objective: 'net_pnl', surface, spec: { id: 's', name: 'S', description: '', long_side: { direction: 'long', indicators: [{ id: 'ema', kind: 'ema', length: 9 }] }, short_side: null } };
/** The fields of the Lab's data that a first render reads; nothing is asked in a static render (effects do not run). */
const data = (loaded: unknown) =>
  ({
    loaded,
    loading: false,
    query: () => Promise.resolve(null),
    tick: 0,
    summary: null,
    summaryError: null,
    knownRows: {},
    importanceDone: 0,
    noteTask: () => undefined,
    watchTask: () => undefined,
    expMatrix: { key: null, envelope: null, loading: false, error: null },
    retryMatrix: () => undefined,
  }) as unknown as LabQueryData;
const open = data({ kind: 'exp', id: 'e1', document, report: null, strategyName: 'S' });
const closed = data(null);
const pageProps = { sort: { column: null, descending: true }, onSort: () => undefined, onSelect: () => undefined, memory: { current: { key: '', top: 0 } } };
const render = (element: ReactElement) => renderToStaticMarkup(element);

/** The panels whose numbers rest on the uniform-design rows (importance, the interactions, and the trellis they rank). */
const UNIFORM_PANELS = ['trellis', 'importance', 'interactions'];

describe('every analytic panel states its assumptions', () => {
  const found = new Map<string, string>();
  const add = (markup: string) => lines(markup).forEach((l) => found.set(l.panel, l.text));

  it('Screen E: the trellis, the neighbourhood map, the drill-down, the parallel coordinates and the importance', () => {
    const page = render(createElement(FamiliesPage, { data: open, ...pageProps }));
    for (const panel of ['trellis', 'neighbourhood', 'drill', 'parallel', 'importance']) expect(lines(page).filter((l) => l.panel === panel), panel).toHaveLength(1);
    add(page);
  });

  it('Trial Lab\'s tabs: the heatmap, the interactions, the Pareto front, the robustness rankings and the parallel coordinates', () => {
    add(render(createElement(LabHeatmap, { data: closed })));
    add(render(createElement(InteractionMatrix, { data: closed })));
    add(render(createElement(ParetoView, { data: closed })));
    add(render(createElement(RobustnessView, { data: closed })));
    add(render(createElement(ImportanceView, { data: closed })));
    for (const panel of ['heatmap', 'interactions', 'pareto', 'robustness', 'importance']) expect(found.has(panel), panel).toBe(true);
  });

  it('the convergence chart, compact in the rail and at full size', () => {
    for (const compact of [true, false]) {
      const chart = lines(render(createElement(ConvergenceChart, { data: closed, compact })));
      expect(chart.map((l) => l.panel)).toEqual(['convergence']);
      found.set('convergence', chart[0].text);
    }
  });

  it('every one is the same line: the uniform-design clause appears exactly on the importance, interactions and trellis panels', () => {
    expect([...found.keys()].sort()).toEqual(['convergence', 'drill', 'heatmap', 'importance', 'interactions', 'neighbourhood', 'parallel', 'pareto', 'robustness', 'trellis']);
    for (const [panel, text] of found) {
      expect(text, panel).toBe(assumptionsText(UNIFORM_PANELS.includes(panel)));
      expect(text.includes(UNIFORM), panel).toBe(UNIFORM_PANELS.includes(panel));
    }
  });
});
