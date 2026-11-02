// The convergence chart's words (Global Constraint: every chart states its basis). The compact chart is the only one the operator
// sees (Trial Lab's rail), and it draws a thinned best-so-far: the basis line that says so must be there too.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { LabConvergence, LabEnvelope } from '../results';
import { labCounts } from './analyticsFixtures';
import { convergenceModel } from './convergenceModel';
import { ConvergenceReadout } from './ConvergenceChart';

const BASIS = "Tested (exact); neighbours read every completed block-0 trial of the snapshot, the filter selects each batch's top trials; best-so-far thinned evenly to 1000 of 41000 points";

function answer(): LabEnvelope<LabConvergence> {
  return {
    view: 'convergence',
    filter_hash: 'abcd1234',
    scope: labCounts(),
    snapshot: null,
    provisional: false,
    empty: null,
    metric: 'combined.net_pnl',
    orientation: 1,
    best: [[0, -50], [10, -20], [20, 30], [40, 90]],
    best_total: 41,
    robust: [],
    robust_reason: 'fewer than 2 complete batches of 5000 trials',
    batches: 0,
    partial: 41,
    r: 1,
    m: 1,
    basis: BASIS,
    constants: { CONVERGENCE_BATCH: 5000, CONVERGENCE_TOP: 0.01, CONVERGENCE_MAX_POINTS: 1000, MIN_BATCHES: 2, NEIGHBOUR_R: 1 },
  };
}

function tag(markup: string, id: string): { tag: string; text: string } | undefined {
  const found = new RegExp(`<div ([^>]*)id="${id}"([^>]*)>([^<]*)</div>`).exec(markup);
  return found === null ? undefined : { tag: `${found[1]}${found[2]}`, text: found[3].replaceAll('&#x27;', "'") }; // the markup escapes an apostrophe
}

describe('the convergence readout', () => {
  const model = convergenceModel(answer());

  it('states the worker\'s basis in the compact chart too, as a line of its own under the summary', () => {
    const compact = renderToStaticMarkup(createElement(ConvergenceReadout, { id: 'lab-convergence', model, compact: true }));
    expect(tag(compact, 'lab-convergence-basis')?.text).toBe(BASIS);
    expect(compact.indexOf('id="lab-convergence-summary"')).toBeGreaterThan(-1);
    expect(compact.indexOf('id="lab-convergence-basis"')).toBeGreaterThan(compact.indexOf('id="lab-convergence-summary"'));
    expect(tag(compact, 'lab-convergence-basis')?.tag).toContain('class="sub');
  });

  it('states it at full size as well, once', () => {
    const full = renderToStaticMarkup(createElement(ConvergenceReadout, { id: 'lab-convergence', model, compact: false }));
    expect(tag(full, 'lab-convergence-basis')?.text).toBe(BASIS);
    expect(full.match(/id="lab-convergence-basis"/g)).toHaveLength(1);
  });

  it('carries the thinning the basis names: the points drawn are fewer than the trials', () => {
    const compact = renderToStaticMarkup(createElement(ConvergenceReadout, { id: 'lab-convergence', model, compact: true }));
    expect(compact).toContain('thinned evenly to 1000 of 41000 points');
  });
});
