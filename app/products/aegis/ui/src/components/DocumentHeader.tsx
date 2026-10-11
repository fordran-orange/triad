import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import { shortHash } from '../format';
import { unsavedEdits, useDispatch, useWorkspace } from '../state/workspace';

/** The loaded strategy document: its name, whether the workspace has unsaved edits, Save, Revert. */
export function DocumentHeader() {
  const state = useWorkspace();
  const { document, strategy } = state;
  const dispatch = useDispatch();
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const edited = unsavedEdits(state);

  const save = async () => {
    if (!document || !strategy) return;
    setSaving(true);
    setError(null);
    try {
      dispatch({ type: 'SET_DOCUMENT', document: await api.updateStrategy(document.id, { spec: strategy }) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
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
    </div>
  );
}
