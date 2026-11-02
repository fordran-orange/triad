import { describe, expect, it } from 'vitest';
import * as convergence from './convergenceModel';
import { advanceAskMark, CONVERGENCE_REFRESH_MS, refreshDelay, startAskMark } from './refreshRule';

describe('how often a panel is asked while its source runs', () => {
  it('is never while the source is not running; at once when it was never asked; otherwise at most every 30 s', () => {
    expect(CONVERGENCE_REFRESH_MS).toBe(30_000);
    expect(refreshDelay(false, null, 1_000)).toBeNull();
    expect(refreshDelay(false, 500, 1_000)).toBeNull();
    expect(refreshDelay(true, null, 1_000)).toBe(0);
    expect(refreshDelay(true, 1_000, 1_000)).toBe(30_000);
    expect(refreshDelay(true, 1_000, 11_000)).toBe(20_000);
    expect(refreshDelay(true, 1_000, 31_000)).toBe(0);
    expect(refreshDelay(true, 40_000, 1_000)).toBe(30_000); // a clock that went back never waits longer than the interval
  });

  it('is one rule: the convergence model re-exports it, so its imports keep working', () => {
    expect(convergence.refreshDelay).toBe(refreshDelay);
    expect(convergence.CONVERGENCE_REFRESH_MS).toBe(CONVERGENCE_REFRESH_MS);
  });
});

describe('the ask mark', () => {
  it('starts at 0 on the key and liveness it mounted with', () => {
    expect(startAskMark('a', true)).toEqual({ key: 'a', live: true, count: 0 });
    expect(startAskMark(null, false)).toEqual({ key: null, live: false, count: 0 });
  });

  it('bumps for a new key, once, and is the same object for the same key', () => {
    const mounted = startAskMark('a', true);
    expect(advanceAskMark(mounted, 'a', true)).toBe(mounted); // nothing moved: nothing is asked
    const next = advanceAskMark(mounted, 'b', true);
    expect(next).toEqual({ key: 'b', live: true, count: 1 });
    expect(advanceAskMark(next, 'b', true)).toBe(next);
    expect(advanceAskMark(startAskMark(null, true), 'a', true).count).toBe(1); // a key arriving after none is a new key
    expect(advanceAskMark(advanceAskMark(next, null, true), 'b', true).count).toBe(3); // and so is the same key coming back
  });

  it('bumps once when the run ends, so a settled answer replaces the provisional one; not when it starts', () => {
    const running = startAskMark('a', true);
    const ended = advanceAskMark(running, 'a', false);
    expect(ended).toEqual({ key: 'a', live: false, count: 1 });
    expect(advanceAskMark(ended, 'a', false)).toBe(ended); // a finished source is asked no more
    const started = advanceAskMark(ended, 'a', true);
    expect(started).toEqual({ key: 'a', live: true, count: 1 }); // liveness is noted, nothing is asked for it
  });

  it('bumps once when a new key arrives as the run ends', () => {
    expect(advanceAskMark(startAskMark('a', true), 'b', false)).toEqual({ key: 'b', live: false, count: 1 });
  });
});
