// Screen E's page as the Lab's store drives it (first render, static markup): what Maximize keeps, what Clear is enabled by, and
// the square that is picked. The effects (the asks) do not run in a static render; the store's own rules are in labStore.test.ts.
import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Parameter, Surface } from '../contracts';
import { FamiliesPage } from './FamiliesPage';
import { LabStateContext } from './labState';
import { initialLabState, type LabFilter, type LabState, type TrellisPick } from './labStore';
import type { LabQueryData } from './useLabQuery';

const surface: Surface = {
  parameters: [['long_side.indicators.ema.length', 5, 20, 1], ['long_side.stop_loss_pct', 1, 5, 0.5]].map(
    ([path, start, stop, step]): Parameter => ({ path: path as string, start: start as number, stop: stop as number, step: step as number }),
  ),
};
const document = { id: 'e1', name: 'E', status: 'done', objective: 'net_pnl', surface, spec: { id: 's', name: 'S', description: '', long_side: { direction: 'long', indicators: [{ id: 'ema', kind: 'ema', length: 9 }] }, short_side: null } };
const data = {
  loaded: { kind: 'exp', id: 'e1', document, report: null, strategyName: 'S' },
  loading: false,
  query: () => Promise.resolve(null),
  tick: 0,
  summary: null,
  summaryError: null,
  knownRows: {},
  importanceDone: 0,
  noteTask: () => undefined,
  watchTask: () => undefined,
} as unknown as LabQueryData;
const props = { data, sort: { column: null, descending: true }, onSort: () => undefined, onSelect: () => undefined, memory: { current: { key: '', top: 0 } } };

function page(state: Partial<LabState>): string {
  const inside: ReactElement = createElement(FamiliesPage, props);
  return renderToStaticMarkup(createElement(LabStateContext.Provider, { value: { ...initialLabState, ...state } }, inside));
}

/** The opening tag of the element with `id`, and one attribute of it (undefined when the id or the attribute is absent; a bare
 *  attribute such as `hidden` or `disabled` is rendered as the empty string). */
function attribute(markup: string, id: string, name: string): string | undefined {
  const found = new RegExp(`<[a-z]+ [^>]*id="${id}"[^>]*>`).exec(markup)?.[0];
  return found === undefined ? undefined : new RegExp(` ${name}="([^"]*)"`).exec(found)?.[1];
}

const filter = (over: Partial<LabFilter>): LabFilter => ({ ...initialLabState.filter, ...over });

describe('Maximize', () => {
  it('keeps the parameter tree mounted and hides it, so its search and collapsed families survive a Restore', () => {
    const maximized = page({ maximized: true });
    expect(attribute(maximized, 'lab-families', 'data-maximized')).toBe('true');
    expect(attribute(maximized, 'lab-families-catalog', 'id')).toBe('lab-families-catalog'); // hidden, not gone
    expect(attribute(maximized, 'lab-families-catalog', 'hidden')).toBe('');
    expect(attribute(maximized, 'lab-families-search', 'id')).toBe('lab-families-search');
    const restored = page({ maximized: false });
    expect(attribute(restored, 'lab-families', 'data-maximized')).toBe('false');
    expect(attribute(restored, 'lab-families-catalog', 'id')).toBe('lab-families-catalog');
    expect(attribute(restored, 'lab-families-catalog', 'hidden')).toBeUndefined();
  });
});

describe('Clear in the pinned filters', () => {
  const disabled = (state: Partial<LabState>) => attribute(page(state), 'lab-families-clear', 'disabled') !== undefined;

  it('is enabled by a brush, a fixed value or a side: what it clears', () => {
    expect(disabled({})).toBe(true);
    expect(disabled({ filter: filter({ ranges: { 'long_side.stop_loss_pct': [2, 3] } }) })).toBe(false);
    expect(disabled({ filter: filter({ values: { 'long_side.stop_loss_pct': 2 } }) })).toBe(false);
    expect(disabled({ filter: filter({ scope: 'long' }) })).toBe(false);
  });

  it('is enabled by a picked square, which it also drops, and its tooltip says so', () => {
    const pick: TrellisPick = { pair: 0, axes: ['long_side.indicators.ema.length', 'long_side.stop_loss_pct'], rows: [15, 15], cols: [2, 2.5], n: 120, snapshot: null };
    vi.spyOn(console, 'error').mockImplementation(() => undefined); // the table under the drill-down: a layout effect in a static render
    expect(disabled({ familiesPick: pick })).toBe(false);
    const title = (state: Partial<LabState>) => attribute(page(state), 'lab-families-clear', 'title');
    expect(title({ familiesPick: pick })).toBe('clears the brushes, the fixed values, the side and the picked square');
    expect(title({ filter: filter({ ranges: { 'long_side.stop_loss_pct': [2, 3] } }) })).toBe('clears the brushes, the fixed values, the side and the picked square');
    expect(title({})).toBe('nothing to clear');
    vi.restoreAllMocks();
  });

  it('is not enabled by a pass or status chip, which it leaves alone', () => {
    expect(disabled({ filter: filter({ status: ['ok'] }) })).toBe(true);
    expect(disabled({ filter: filter({ pass: ['IS'] }) })).toBe(true);
    expect(disabled({ filter: filter({ pass: ['IS'], status: ['ok'], ranges: { 'long_side.stop_loss_pct': [2, 3] } }) })).toBe(false);
    // The Linked chip still counts the chips: it says how many filters are in force, not what Clear takes away.
    expect(page({ filter: filter({ status: ['ok'] }) })).toContain('Linked · 1 filter');
  });
});

describe('the picked square', () => {
  afterEach(() => vi.restoreAllMocks());
  const pick: TrellisPick = { pair: 0, axes: ['long_side.indicators.ema.length', 'long_side.stop_loss_pct'], rows: [15, 15], cols: [2, 2.5], n: 120, snapshot: null };

  it('is read from the Lab\'s store, so the drill-down still shows it when the page is opened again', () => {
    const empty = page({});
    expect(empty).toContain('pick a trellis square to see the trials in it');
    // The trial table under the drill-down lays out in a layout effect, which a static render warns it cannot run: not what is tested.
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const picked = page({ familiesPick: pick });
    expect(picked).not.toContain('pick a trellis square to see the trials in it');
    expect(attribute(picked, 'lab-families-drill', 'data-n')).toBe('120');
    expect(picked).toContain('L ema.length = 15');
    expect(attribute(picked, 'lab-families-drill-n', 'data-n')).toBe('120');
  });
});
