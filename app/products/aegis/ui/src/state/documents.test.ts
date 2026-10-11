import { describe, expect, it } from 'vitest';
import { documentToFetch } from './documents';

describe('document sync decision', () => {
  it('fetches the document named by the strategy id once, when it is not already loaded', () => {
    expect(documentToFetch('breakout', null, null)).toBe('breakout');
    expect(documentToFetch('breakout', 'breakout', null)).toBeNull();
    expect(documentToFetch('breakout', 'other', 'breakout')).toBeNull(); // already tried; a 404 must not loop
    expect(documentToFetch(null, null, null)).toBeNull();
  });
});
