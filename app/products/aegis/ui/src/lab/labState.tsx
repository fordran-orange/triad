// The Optimization Lab's store as React context: the pure reducer of labStore.ts behind a provider. Every Lab view
// reads this one store, so moving between sub-views never loses the filter, the selection or the pins. The app
// mounts the provider around its page switch, so leaving the Lab and coming back keeps them too.
import { createContext, useCallback, useContext, useMemo, useReducer, useRef, useState, type Dispatch, type MutableRefObject, type ReactNode } from 'react';
import { initialLabState, labReducer, type LabAction, type LabState } from './labStore';
import type { TrialRow } from './useLabSource';

/** What the Lab's data hook remembers between visits to the page, beside the store. */
export interface LabSession {
  /** A hand-over from the dock was adopted: the newest experiment is never auto-opened over it. */
  adopted: boolean;
  /** The first experiment list has been seen (and the newest finished experiment opened if nothing was open). */
  autoOpened: boolean;
  /** The dock's selected configuration, waiting for its job to load; consumed once. */
  handed: { source: string; params: Record<string, number> } | null;
}

export interface LabMemory {
  session: MutableRefObject<LabSession>;
  /** The rows the table handed over, for the selection card (ids carry their source, so no source's rows clash). */
  knownRows: Record<string, TrialRow>;
  rememberRow: (row: TrialRow) => void;
  /** The grid jobs opened in the Lab this session, newest first: the picker lists them. */
  optSources: string[];
  addOptSource: (id: string) => void;
}

const LabStateContext = createContext<LabState>(initialLabState);
const LabDispatchContext = createContext<Dispatch<LabAction>>(() => undefined);
const LabMemoryContext = createContext<LabMemory | null>(null);

export function LabProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(labReducer, initialLabState);
  const session = useRef<LabSession>({ adopted: false, autoOpened: false, handed: null });
  const [knownRows, setKnownRows] = useState<Record<string, TrialRow>>({});
  const [optSources, setOptSources] = useState<string[]>([]);
  const rememberRow = useCallback((row: TrialRow) => {
    setKnownRows((rows) => {
      // The newest pick goes last; the selection card reads it, older picks fall away.
      const kept = Object.entries(rows)
        .filter(([id]) => id !== row.id)
        .slice(-24);
      return { ...Object.fromEntries(kept), [row.id]: row };
    });
  }, []);
  const addOptSource = useCallback((id: string) => setOptSources((ids) => (ids.includes(id) ? ids : [id, ...ids])), []);
  const memory = useMemo<LabMemory>(() => ({ session, knownRows, rememberRow, optSources, addOptSource }), [knownRows, rememberRow, optSources, addOptSource]);
  return (
    <LabStateContext.Provider value={state}>
      <LabDispatchContext.Provider value={dispatch}>
        <LabMemoryContext.Provider value={memory}>{children}</LabMemoryContext.Provider>
      </LabDispatchContext.Provider>
    </LabStateContext.Provider>
  );
}

export const useLab = () => useContext(LabStateContext);
export const useLabDispatch = () => useContext(LabDispatchContext);
export function useLabMemory(): LabMemory {
  const memory = useContext(LabMemoryContext);
  if (memory === null) throw new Error('useLabMemory needs a LabProvider above it');
  return memory;
}
