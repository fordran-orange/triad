// The Optimization Lab's store as React context: the pure reducer of labStore.ts behind a provider. Every Lab view
// reads this one store, so moving between sub-views never loses the filter, the selection or the pins.
import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react';
import { initialLabState, labReducer, type LabAction, type LabState } from './labStore';

const LabStateContext = createContext<LabState>(initialLabState);
const LabDispatchContext = createContext<Dispatch<LabAction>>(() => undefined);

export function LabProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(labReducer, initialLabState);
  return (
    <LabStateContext.Provider value={state}>
      <LabDispatchContext.Provider value={dispatch}>{children}</LabDispatchContext.Provider>
    </LabStateContext.Provider>
  );
}

export const useLab = () => useContext(LabStateContext);
export const useLabDispatch = () => useContext(LabDispatchContext);
