import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { rowFromTrial } from './candidateModel';
import { useLab, useLabDispatch } from './labState';
import type { LabQueryData } from './useLabQuery';

/** A trial whose row could not be fetched, and why. */
export interface PickFailure {
  id: string;
  message: string;
}

/** Selects a trial picked from a chart or a ranking by its id. The selection moves at once (the rail's candidate card
 *  needs only the id); the trial's row, which the rail's trial card reads, follows from the trial route when the table has
 *  not handed it over. A failed fetch leaves the id and the card as they are and is returned as `failure` for the panel to
 *  print with its cause: only the latest pick's failure counts, and a new pick or a new source clears it. */
export function usePickTrial(data: LabQueryData): { pick: (id: string) => void; failure: PickFailure | null } {
  const dispatch = useLabDispatch();
  const lab = useLab();
  const { loaded, knownRows, rememberRow } = data;
  const scope = lab.filter.scope;
  const source = loaded === null ? null : `${loaded.kind}:${loaded.id}`;
  const [failure, setFailure] = useState<PickFailure | null>(null);
  const latest = useRef<string | null>(null);
  useEffect(() => {
    latest.current = null;
    setFailure(null);
  }, [source]);
  const pick = useCallback(
    (id: string) => {
      latest.current = id;
      setFailure(null);
      dispatch({ type: 'SELECT_TRIALS', ids: [id] });
      if (loaded === null || knownRows[id] !== undefined) return;
      const from = id.slice(0, id.lastIndexOf('#'));
      api
        .labTrial(from, id)
        .then((trial) => rememberRow(rowFromTrial(trial, loaded.kind, loaded.kind === 'opt' ? loaded.job.side : scope)))
        .catch((e: unknown) => {
          if (latest.current === id) setFailure({ id, message: errorMessage(e) });
        });
    },
    [dispatch, loaded, knownRows, rememberRow, scope],
  );
  return { pick, failure };
}
