// When a Lab panel that asks the worker for something expensive asks again (decision 10), nothing React and nothing asked.
// A new chunk is a server cache miss that costs up to 1.8 s at 1M trials, so these panels are not tied to the Lab's 2 s
// refresh tick: they ask on mount and on a new key (the source, the pair, the metric, the filter), at most every 30 s while
// the source runs, and once more when the run ends so a settled answer replaces the provisional one. The convergence chart,
// the trellis pairs, the neighbourhood map, the drill-down's total and the sampled parallel coordinates all follow this rule
// through `useAskMark`; the decisions it makes live here so they run under vitest in node.

/** The panels ask again at most this often while their source runs. */
export const CONVERGENCE_REFRESH_MS = 30_000;

/** The wait before the next ask: never while the source is not running (it was asked when it settled), at once when it was
 *  never asked, else what is left of the interval since `lastAskedAt`. A clock that went back never waits longer than the
 *  interval. Milliseconds. */
export function refreshDelay(live: boolean, lastAskedAt: number | null, now: number): number | null {
  if (!live) return null;
  if (lastAskedAt === null) return 0;
  return Math.min(CONVERGENCE_REFRESH_MS, Math.max(0, CONVERGENCE_REFRESH_MS - (now - lastAskedAt)));
}

/** What a panel asked on last: the key it asked for, whether its source was running, and the ask count. A panel asks once for
 *  each count it has not asked on. */
export interface AskMark {
  key: string | null;
  live: boolean;
  count: number;
}

/** The mark a panel mounts with: count 0, which its first ask is made on. */
export function startAskMark(key: string | null, live: boolean): AskMark {
  return { key, live, count: 0 };
}

/** The mark after a render with `key` and `live`: one more ask for a new key, and one more when the run ends (live turning
 *  false), whichever of them moved, never two for one render. A source starting to run is noted and asks nothing: its timer
 *  does. The same object when nothing moved, so the caller writes nothing. */
export function advanceAskMark(mark: AskMark, key: string | null, live: boolean): AskMark {
  if (mark.key !== key || (mark.live && !live)) return { key, live, count: mark.count + 1 };
  return mark.live === live ? mark : { ...mark, live };
}
