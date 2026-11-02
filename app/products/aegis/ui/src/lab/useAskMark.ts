// The one hook behind "ask on mount and on a new key, at most every 30 s while the source runs, and once when the run ends"
// (decision 10; the decisions are `refreshRule.ts`'s). It returns a counter that a panel puts in its ask: the ask effect is
// keyed on the panel's own view key and this mark, so a new key and its bump arrive in one render and make one ask. The mark
// bumps for a new key and when `live` turns false, both during render (derived state, so a panel never asks on the key
// before the bump and again on the bump), and by its timer while `live`. There is one timer per hook: each ask re-arms it,
// and a new key, the end of the run and the unmount clear it.
import { useEffect, useRef, useState } from 'react';
import { advanceAskMark, refreshDelay, startAskMark } from './refreshRule';

export function useAskMark(key: string | null, live: boolean): number {
  const [held, setHeld] = useState(() => startAskMark(key, live));
  const mark = advanceAskMark(held, key, live);
  if (mark !== held) setHeld(mark);

  // The time of the last ask: the mark moving is an ask, and the timer counts its interval from it.
  const askedAt = useRef<number | null>(null);
  useEffect(() => {
    askedAt.current = Date.now();
  }, [mark.count]);

  useEffect(() => {
    const delay = refreshDelay(live && key !== null, askedAt.current, Date.now());
    if (delay === null) return;
    const timer = setTimeout(() => setHeld((was) => ({ ...was, count: was.count + 1 })), delay);
    return () => clearTimeout(timer);
  }, [key, live, mark.count]);

  return mark.count;
}
