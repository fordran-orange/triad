import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import { shortHash } from '../format';
import { saveDocument } from '../state/documents';
import { currentCanvas, unsavedEdits, useDispatch, useWorkspace } from '../state/workspace';

/** The loaded strategy document: its name, whether the workspace has unsaved edits, Save, Revert. */
export function DocumentHeader() {
  const state = useWorkspace();
  const { document, strategy } = state;
  const dispatch = useDispatch();
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null); // Mission 13 review I3
  const [saving, setSaving] = useState(false);
  const edited = unsavedEdits(state);

  const save = async () => {
    if (!document || !strategy) return;
    setSaving(true);
    setError(null);
    setConflict(null);
    // Mission 13: blocks moved or loose blocks added in the builder are saved with the strategy.
    const canvas = state.canvasEdited ? { canvas: currentCanvas(state) } : {};
    const outcome = await saveDocument(document, { spec: strategy, ...canvas });
    if (outcome.kind === 'saved') dispatch({ type: 'SET_DOCUMENT', document: outcome.document });
    else if (outcome.kind === 'conflict') setConflict(outcome.message);
    else setError(outcome.message);
    setSaving(false);
  };

  /** The saved version replaces what is here; the operator is asked first, nothing goes silently. */
  const reload = async () => {
    if (!document) return;
    if (!window.confirm('Reload the saved strategy? The edits made here since you opened it will be lost.')) return;
    try {
      dispatch({ type: 'SET_DOCUMENT', document: await api.strategyDocument(document.id) });
      setConflict(null);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="panel-section document-header">
      <div className="section-label">
        Document
        {edited && (
          <span className="badge raw" id="unsaved-edits" title="The workspace strategy differs from the saved document">
            unsaved edits
          </span>
        )}
      </div>
      <div id="document-name">
        {document ? (
          <>
            {document.name} <span className="muted" title={document.strategy_hash}>{shortHash(document.strategy_hash)}</span>
            {document.builtin && <span className="badge">BUILT-IN</span>}
          </>
        ) : (
          <span className="muted">not saved as a document</span>
        )}
      </div>
      {document && (
        <div className="actions">
          <button
            type="button"
            className="btn btn-green"
            id="save-document"
            disabled={!edited || saving || document.builtin}
            title={document.builtin ? 'The built-in strategy is read-only; duplicate it in the Strategy Lab' : undefined}
            onClick={save}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="btn" id="revert-document" disabled={!edited || saving} onClick={() => dispatch({ type: 'SET_DOCUMENT', document })}>
            Revert
          </button>
        </div>
      )}
      {error && <div className="notice warn">{error}</div>}
      {conflict && (
        <div className="notice warn" id="document-conflict">
          {conflict}{' '}
          <button type="button" className="btn" id="document-reload" onClick={() => void reload()} title="Replace what is here with the saved strategy; you are asked first">
            Reload
          </button>
        </div>
      )}
    </div>
  );
}
