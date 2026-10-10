import { useCallback } from 'react';
import { api, errorMessage } from '../api/client';
import type { StrategySpec } from '../contracts';
import { useDispatch, useWorkspace } from './workspace';

/** Posts {strategy, data, settings} and lands the envelope in the workspace; `override` runs a spec just applied. */
export function useRunBacktest() {
  const { strategy, selection, settings } = useWorkspace();
  const dispatch = useDispatch();
  return useCallback(
    async (override?: StrategySpec) => {
      const spec = override ?? strategy;
      if (!spec) return;
      dispatch({ type: 'RUN_STARTED' });
      try {
        dispatch({ type: 'RUN_COMPLETED', run: await api.backtest({ strategy: spec, data: selection, settings }) });
      } catch (error) {
        dispatch({ type: 'RUN_FAILED', error: errorMessage(error) });
      }
    },
    [strategy, selection, settings, dispatch],
  );
}
