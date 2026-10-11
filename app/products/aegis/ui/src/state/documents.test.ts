import { describe, expect, it } from 'vitest';
import { documentToFetch } from './documents';

describe('document sync decision', () => {
  it('fetches the document named by the strategy id when it is not the loaded one', () => {
    expect(documentToFetch('breakout', null, null)).toBe('breakout');
    expect(documentToFetch('breakout', 'breakout', null)).toBeNull();
    expect(documentToFetch(null, null, null)).toBeNull();
  });

  it('does not refetch an id that just 404ed, but does once the loaded document changed', () => {
    const missing = { strategy: 'breakout', document: null };
    expect(documentToFetch('breakout', null, missing)).toBeNull(); // a 404 must not loop
    expect(documentToFetch('breakout', 'other', missing)).toBe('breakout');
  });

  it('rebinds after a run reload even when that id was fetched before (review finding #1)', () => {
    // run R1 (donchian-rsi) adopted, then "Use in workspace" on my-other, then R1 reloaded:
    expect(documentToFetch('donchian-rsi', 'my-other', null)).toBe('donchian-rsi');
  });
});
