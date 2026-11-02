// The hook behind every panel that asks again while its source runs, driven by react-dom/client and `act` with fake timers.
// The test environment is node (no jsdom, and none is added): a component that renders nothing needs no DOM, only a
// container react-dom accepts, so a small stand-in for one is all that stands in for the page.
import { createElement, useEffect } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CONVERGENCE_REFRESH_MS } from './refreshRule';
import { useAskMark } from './useAskMark';

const globals = globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean };

/** The least a container must be for react-dom to mount into it: an element node with no document behind it. */
function container(): Element {
  return { nodeType: 1, tagName: 'DIV', namespaceURI: null, ownerDocument: null, textContent: '', addEventListener: () => undefined, removeEventListener: () => undefined } as unknown as Element;
}

/** A panel that asks as `useAskMark` says: its ask is the effect keyed on the key and the mark, as every consumer's is. */
function Probe({ askKey, live, asks }: { askKey: string | null; live: boolean; asks: string[] }) {
  const mark = useAskMark(askKey, live);
  useEffect(() => {
    if (askKey !== null) asks.push(`${askKey}#${mark}`);
  }, [askKey, mark, asks]);
  return null;
}

describe('useAskMark', () => {
  let root: Root;
  let asks: string[];
  const show = (askKey: string | null, live: boolean) => act(() => root.render(createElement(Probe, { askKey, live, asks })));

  beforeEach(() => {
    globals.IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal('window', { HTMLIFrameElement: class {} }); // react-dom reads `window.event` and `window.HTMLIFrameElement` on a commit; nothing else of a page
    vi.useFakeTimers();
    asks = [];
    root = createRoot(container());
  });
  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
    vi.unstubAllGlobals();
    globals.IS_REACT_ACT_ENVIRONMENT = false;
  });

  it('asks once on mount, once for a new key, and not again for a rerender with the same key', () => {
    show('a', false);
    expect(asks).toEqual(['a#0']);
    show('a', false);
    expect(asks).toEqual(['a#0']);
    show('b', false);
    expect(asks).toEqual(['a#0', 'b#1']); // the key and the mark arrive together: one ask, never two
  });

  it('asks nothing for a key it does not have', () => {
    show(null, true);
    expect(asks).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('while the source runs asks again at 30 s and not at 29 s', () => {
    show('a', true);
    expect(asks).toEqual(['a#0']);
    act(() => vi.advanceTimersByTime(CONVERGENCE_REFRESH_MS - 1_000));
    expect(asks).toEqual(['a#0']);
    act(() => vi.advanceTimersByTime(1_000));
    expect(asks).toEqual(['a#0', 'a#1']);
    act(() => vi.advanceTimersByTime(CONVERGENCE_REFRESH_MS));
    expect(asks).toEqual(['a#0', 'a#1', 'a#2']); // and again 30 s after that
  });

  it('has one timer, re-armed by each ask: a new key starts the 30 s again', () => {
    show('a', true);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(20_000));
    show('b', true);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(29_000));
    expect(asks).toEqual(['a#0', 'b#1']);
    act(() => vi.advanceTimersByTime(1_000));
    expect(asks).toEqual(['a#0', 'b#1', 'b#2']);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('asks once more when the run ends, then no more: its timer is cleared', () => {
    show('a', true);
    act(() => vi.advanceTimersByTime(10_000));
    show('a', false);
    expect(asks).toEqual(['a#0', 'a#1']); // the settled ask
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(10 * CONVERGENCE_REFRESH_MS));
    expect(asks).toEqual(['a#0', 'a#1']);
  });

  it('clears its timer on unmount', () => {
    show('a', true);
    expect(vi.getTimerCount()).toBe(1);
    act(() => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(2 * CONVERGENCE_REFRESH_MS));
    expect(asks).toEqual(['a#0']);
    root = createRoot(container()); // the cleanup of the test unmounts this one
  });
});
