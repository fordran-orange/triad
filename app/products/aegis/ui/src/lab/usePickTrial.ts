import { useCallback } from 'react';
import { api } from '../api/client';
import { rowFromTrial } from './candidateModel';
import { useLab, useLabDispatch } from './labState';
import type { LabQueryData } from './useLabQuery';

/** Selects a trial picked from a chart or a ranking by its id. The selection moves at once (the rail's candidate card
 *  needs only the id); the trial's row, which the rail's trial card reads, follows from the trial route when the table has
 *  not handed it over. A failed fetch leaves the id and the card, never a message of its own. */
export function usePickTrial(data: LabQueryData): (id: string) => void {
  const dispatch = useLabDispatch();
  const lab = useLab();
  const { loaded, knownRows, rememberRow } = data;
  const scope = lab.filter.scope;
  return useCallback(
    (id: string) => {
      dispatch({ type: 'SELECT_TRIALS', ids: [id] });
      if (loaded === null || knownRows[id] !== undefined) return;
      const source = id.slice(0, id.lastIndexOf('#'));
      api
        .labTrial(source, id)
        .then((trial) => rememberRow(rowFromTrial(trial, loaded.kind, loaded.kind === 'opt' ? loaded.job.side : scope)))
        .catch(() => undefined);
    },
    [dispatch, loaded, knownRows, rememberRow, scope],
  );
}
