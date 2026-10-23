import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage, type StrategySummary } from '../../api/client';
import { DASH, shortHash, timeLabel } from '../../format';
import { unsavedEdits, useDispatch, useWorkspace } from '../../state/workspace';

const BUILTIN_ID = 'ema9-sma30-cross-v1';

type Editing = { id: string; mode: 'rename' | 'duplicate' | 'delete'; name: string } | null;

function usageLabel(u: StrategySummary['usage']): string {
  const part = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;
  return [part(u.runs, 'run'), part(u.optimizations, 'optimization'), part(u.walkforwards, 'walk-forward')].join(' · ');
}

/** Saved strategy documents (Mission 5 spec §8) beside the builder (Mission 13): a row opens its
 * strategy in the builder; New, Duplicate, Rename, Delete and Use in workspace as before. */
export function StrategyList({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const state = useWorkspace();
  const { document } = state;
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
  const open = (id: string) => {
    if (id === document?.id) return;
    if (unsavedEdits(state) && !window.confirm('Open another strategy? Unsaved edits will be replaced.')) return;
    void act(async () => dispatch({ type: 'SET_DOCUMENT', document: await api.strategyDocument(id) }));
  };
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
    <aside className={'strategy-list' + (collapsed ? ' collapsed' : '')} id="strategy-list">
      <div className="panel-title">
        {!collapsed && <span>Strategies</span>}
        <button type="button" className="btn small" id="strategy-list-toggle" onClick={onToggle} title={collapsed ? 'Show the saved strategies' : 'Hide the saved strategies'}>
          {collapsed ? '‹' : '›'}
        </button>
      </div>
      {!collapsed && (
        <>
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
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const mine = editing?.id === item.id ? editing : null;
              return (
                <tr key={item.id} id={`doc-${item.id}`} className={document?.id === item.id ? 'selected' : ''} onClick={() => !mine && open(item.id)} title="Open in the builder">
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
                        <div className="muted">
                          {item.id} · <span title={item.strategy_hash}>{shortHash(item.strategy_hash)}</span> · {item.updated_at ? timeLabel(item.updated_at) : DASH}
                        </div>
                        <div className="muted">
                          {item.kinds.join(', ') || DASH} · {usageLabel(item.usage)}
                        </div>
                      </>
                    )}
                  <div className="row-actions" onClick={(e) => e.stopPropagation()}>
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
                  </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
        </>
      )}
    </aside>
  );
}
