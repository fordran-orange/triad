import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage, type StrategySummary } from '../api/client';
import { DASH, shortHash, timeLabel } from '../format';
import { useDispatch, useWorkspace } from '../state/workspace';

const BUILTIN_ID = 'ema9-sma30-cross-v1';

type Editing = { id: string; mode: 'rename' | 'duplicate' | 'delete'; name: string } | null;

function usageLabel(u: StrategySummary['usage']): string {
  const part = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;
  return [part(u.runs, 'run'), part(u.optimizations, 'optimization'), part(u.walkforwards, 'walk-forward')].join(' · ');
}

/** Saved strategy documents (spec §8): list, New, Duplicate, Rename, Delete, Use in workspace. */
export function LabPage() {
  const { document } = useWorkspace();
  const dispatch = useDispatch();
  const [items, setItems] = useState<StrategySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api
      .strategies()
      .then(setItems)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);
  // Refetch after a save elsewhere (the right panel) as well as on mount.
  useEffect(refresh, [refresh, document?.updated_at, document?.id]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      setEditing(null);
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const use = (id: string) =>
    act(async () => {
      dispatch({ type: 'SET_DOCUMENT', document: await api.strategyDocument(id) });
      dispatch({ type: 'SET_PAGE', page: 'charts' });
    });
  const create = () =>
    act(async () => {
      const builtin = await api.strategyDocument(BUILTIN_ID);
      await api.createStrategy('Untitled strategy', builtin.spec);
    });
  const confirm = () => {
    if (!editing) return;
    const { id, mode, name } = editing;
    if (mode === 'rename')
      void act(async () => {
        dispatch({ type: 'DOCUMENT_RENAMED', document: await api.updateStrategy(id, { name }) });
      });
    else if (mode === 'duplicate') void act(() => api.duplicateStrategy(id, name));
    else
      void act(async () => {
        await api.deleteStrategy(id);
        // The workspace keeps its strategy, but it is no longer saved as a document.
        if (document?.id === id) dispatch({ type: 'ADOPT_DOCUMENT', document: null });
      });
  };

  return (
    <div className="lab-page" id="lab-page">
      <div className="panel-title">
        Strategy Lab <span className="small muted">saved strategy documents · the built-in reference is read-only</span>
      </div>
      <div className="actions">
        <button type="button" className="btn btn-green" id="lab-new" disabled={busy} onClick={create}>
          New strategy
        </button>
      </div>
      {error && (
        <div className="notice warn" id="lab-error" role="status">
          {error}
        </div>
      )}
      {items === null ? (
        <div className="empty-state">{error ? 'Strategy documents unavailable' : 'Loading strategy documents…'}</div>
      ) : (
        <table className="small lab-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Hash</th>
              <th>Updated</th>
              <th>Kinds</th>
              <th>Used by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const mine = editing?.id === item.id ? editing : null;
              return (
                <tr key={item.id} id={`doc-${item.id}`} className={document?.id === item.id ? 'selected' : ''}>
                  <td>
                    {mine && mine.mode !== 'delete' ? (
                      <input
                        id={mine.mode === 'rename' ? 'rename-input' : 'duplicate-input'}
                        value={mine.name}
                        aria-label={mine.mode === 'rename' ? 'New name' : 'Name of the copy'}
                        onChange={(e) => setEditing({ ...mine, name: e.target.value })}
                      />
                    ) : (
                      <>
                        {item.name} {item.builtin && <span className="badge">BUILT-IN</span>}
                        <div className="muted">{item.id}</div>
                      </>
                    )}
                  </td>
                  <td title={item.strategy_hash}>{shortHash(item.strategy_hash)}</td>
                  <td>{item.updated_at ? timeLabel(item.updated_at) : DASH}</td>
                  <td>{item.kinds.join(', ') || DASH}</td>
                  <td>{usageLabel(item.usage)}</td>
                  <td className="row-actions">
                    {mine ? (
                      <>
                        <button type="button" className="btn btn-green" id={`${mine.mode}-confirm`} disabled={busy || (mine.mode !== 'delete' && !mine.name.trim())} onClick={confirm}>
                          {mine.mode === 'delete' ? 'Delete for good' : mine.mode === 'rename' ? 'Save name' : 'Create copy'}
                        </button>
                        <button type="button" className="btn" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button type="button" className="btn" id={`use-${item.id}`} disabled={busy} onClick={() => use(item.id)}>
                          Use in workspace
                        </button>
                        <button type="button" className="btn" id={`duplicate-${item.id}`} disabled={busy} onClick={() => setEditing({ id: item.id, mode: 'duplicate', name: `${item.name} copy` })}>
                          Duplicate
                        </button>
                        <button
                          type="button"
                          className="btn"
                          id={`rename-${item.id}`}
                          disabled={busy || item.builtin}
                          title={item.builtin ? 'The built-in strategy is read-only' : undefined}
                          onClick={() => setEditing({ id: item.id, mode: 'rename', name: item.name })}
                        >
                          Rename
                        </button>
                        <button
                          type="button"
                          className="btn"
                          id={`delete-${item.id}`}
                          disabled={busy || item.builtin}
                          title={item.builtin ? 'The built-in strategy is read-only' : 'Refused while a run, optimization or walk-forward uses it'}
                          onClick={() => setEditing({ id: item.id, mode: 'delete', name: item.name })}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
