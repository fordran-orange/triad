import { useEffect, useRef } from 'react';
import { api, ApiError } from '../api/client';
import { useDispatch, useWorkspace } from './workspace';

/** The last id that came back 404, and the document that was loaded when it did. */
export interface Missing {
  strategy: string;
  document: string | null;
}

/** The document to fetch so the workspace knows where its strategy came from: the strategy's id,
 *  unless that document is already loaded, or that id just 404ed under the same loaded document
 *  (so a missing document never loops, while any change of document allows a fresh look). */
export function documentToFetch(strategyId: string | null, documentId: string | null, missing: Missing | null): string | null {
  if (!strategyId || strategyId === documentId) return null;
  if (missing && missing.strategy === strategyId && missing.document === documentId) return null;
  return strategyId;
}

/** Keep `document` in step with the workspace strategy's id (a run reloaded from the drawer, an
 *  apply, a strategy chosen in the lab): adopt the saved document by that id, or none. */
export function useDocumentSync(): void {
  const { strategy, document } = useWorkspace();
  const dispatch = useDispatch();
  const missing = useRef<Missing | null>(null);
  const wanted = documentToFetch(strategy?.id ?? null, document?.id ?? null, missing.current);
  useEffect(() => {
    if (!wanted) return;
    let cancelled = false;
    api
      .strategyDocument(wanted)
      .then((found) => {
        if (cancelled) return;
        missing.current = null;
        dispatch({ type: 'ADOPT_DOCUMENT', document: found });
      })
      .catch((e: unknown) => {
        if (cancelled || !(e instanceof ApiError) || e.status !== 404) return;
        missing.current = { strategy: wanted, document: null }; // the state the adopt below produces
        dispatch({ type: 'ADOPT_DOCUMENT', document: null });
      });
    return () => {
      cancelled = true;
    };
  }, [wanted, dispatch]);
}
