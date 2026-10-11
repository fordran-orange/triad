import { useEffect, useRef } from 'react';
import { api, ApiError } from '../api/client';
import { useDispatch, useWorkspace } from './workspace';

/** The document to fetch so the workspace knows where its strategy came from: the strategy's id,
 *  unless that document is already loaded or was already tried (a 404 must not loop). */
export function documentToFetch(strategyId: string | null, documentId: string | null, lastTried: string | null): string | null {
  if (!strategyId || strategyId === documentId || strategyId === lastTried) return null;
  return strategyId;
}

/** Keep `document` in step with the workspace strategy's id (a run reloaded from the drawer, an
 *  apply, a strategy chosen in the lab): adopt the saved document by that id, or none. */
export function useDocumentSync(): void {
  const { strategy, document } = useWorkspace();
  const dispatch = useDispatch();
  const lastTried = useRef<string | null>(null);
  const wanted = documentToFetch(strategy?.id ?? null, document?.id ?? null, lastTried.current);
  useEffect(() => {
    if (!wanted) return;
    lastTried.current = wanted;
    let cancelled = false;
    api
      .strategyDocument(wanted)
      .then((found) => !cancelled && dispatch({ type: 'ADOPT_DOCUMENT', document: found }))
      .catch((e: unknown) => {
        if (!cancelled && e instanceof ApiError && e.status === 404) dispatch({ type: 'ADOPT_DOCUMENT', document: null });
      });
    return () => {
      cancelled = true;
    };
  }, [wanted, dispatch]);
}
