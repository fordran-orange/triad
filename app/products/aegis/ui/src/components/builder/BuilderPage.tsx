import { ReactFlowProvider } from '@xyflow/react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { api, errorMessage } from '../../api/client';
import type { StrategySide } from '../../contracts';
import { sideFromGraph, type SideGraph } from '../../builder/graph';
import { History } from '../../builder/history';
import { saveDocument } from '../../state/documents';
import { useRunBacktest } from '../../state/run';
import { withDefaultRanges } from '../../builder/apply';
import { currentCanvas, SIDE_KEY, sideGraph, unsavedEdits, useDispatch, useWorkspace, type Side } from '../../state/workspace';
import { PhraseBar } from './PhraseBar';
import { Canvas } from './Canvas';
import { Palette } from './Palette';

export interface Snapshot {
  graph: SideGraph;
  spec: StrategySide;
}

/** The Strategy Lab's builder (Mission 13 spec §4.6): the text line, Long / Short tabs, the palette
 * and the canvas over the workspace strategy, and a status line that says "Ready" or names the
 * first problem. */
export function BuilderPage() {
  const state = useWorkspace();
  const { strategy, document, builderSide: side, running } = state;
  const dispatch = useDispatch();
  const run = useRunBacktest();
  const [flash, setFlash] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Mission 13 review I3: the worker refused Save because the document was saved elsewhere since
  // it was opened here; the message stays until the saved version is reloaded.
  const [conflict, setConflict] = useState<string | null>(null);
  const histories = useRef<Record<string, History<Snapshot>>>({});
  const readOnly = !!document?.builtin;

  useEffect(() => {
    if (!flash) return;
    const timer = window.setTimeout(() => setFlash(null), 4000);
    return () => window.clearTimeout(timer);
  }, [flash]);

  const historyOf = useCallback(
    (which: Side): History<Snapshot> | null => {
      if (!strategy) return null;
      const key = `${document?.id ?? 'workspace'}:${which}`;
      histories.current[key] ??= new History<Snapshot>({ graph: sideGraph(state, which), spec: strategy[SIDE_KEY[which]] });
      return histories.current[key];
    },
    [document?.id, state, strategy],
  );

  const push = useCallback(
    (which: Side, snapshot: Snapshot) => {
      historyOf(which)?.push(snapshot);
    },
    [historyOf],
  );

  const commit = useCallback(
    (graph: SideGraph, positionsOnly = false) => {
      if (!strategy || readOnly) return;
      setFlash(null); // a refusal is news only until the next edit
      const before = strategy[SIDE_KEY[side]];
      const read = positionsOnly ? null : sideFromGraph(graph, before);
      const spec = read?.side ? withDefaultRanges(read.side, before) : null;
      dispatch({ type: 'SET_SIDE_GRAPH', side, graph, spec });
      push(side, { graph, spec: spec ?? before });
    },
    [dispatch, push, readOnly, side, strategy],
  );

  const move = useCallback(
    (step: 'undo' | 'redo') => {
      const snapshot = historyOf(side)?.[step]();
      if (snapshot) dispatch({ type: 'SET_SIDE_GRAPH', side, graph: snapshot.graph, spec: snapshot.spec });
    },
    [dispatch, historyOf, side],
  );

  if (!strategy) return <div className="empty-state">Loading the strategy…</div>;

  const problems: Record<Side, string | null> = {
    long: sideFromGraph(sideGraph(state, 'long'), strategy.long_side).problem,
    short: sideFromGraph(sideGraph(state, 'short'), strategy.short_side).problem,
  };
  const ready = !problems.long && !problems.short;
  const edited = unsavedEdits(state);

  const onKeyDown = (event: KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName) || !(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === 'z' && !event.shiftKey) move('undo');
    else if (key === 'y' || (key === 'z' && event.shiftKey)) move('redo');
    else return;
    event.preventDefault();
  };

  const save = async () => {
    if (!document || readOnly) return;
    setSaving(true);
    setError(null);
    setConflict(null);
    const outcome = await saveDocument(document, { spec: strategy, canvas: currentCanvas(state) });
    if (outcome.kind === 'saved') dispatch({ type: 'SET_DOCUMENT', document: outcome.document });
    else if (outcome.kind === 'conflict') setConflict(outcome.message);
    else setError(outcome.message);
    setSaving(false);
  };

  /** The saved version replaces what is here; nothing unsaved goes silently, the operator is asked. */
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

  const status = flash ?? (problems[side] ? problems[side] : !ready ? `${side === 'long' ? 'Short' : 'Long'} side: ${problems[side === 'long' ? 'short' : 'long']}` : 'Ready');

  return (
    <div className="builder" id="builder" tabIndex={-1} onKeyDown={onKeyDown}>
      <div className="builder-phrase" id="builder-phrase">
        <PhraseBar push={push} readOnly={readOnly} />
      </div>
      <div className="builder-head">
        {(['long', 'short'] as Side[]).map((which) => (
          <button
            key={which}
            type="button"
            className={'builder-tab' + (which === side ? ' on' : '') + (problems[which] ? ' problem' : '')}
            id={`builder-tab-${which}`}
            aria-pressed={which === side}
            onClick={() => dispatch({ type: 'SET_BUILDER_SIDE', side: which })}
          >
            {which === 'long' ? 'Long' : 'Short'}
          </button>
        ))}
        <span className="builder-name muted">
          {document ? document.name : 'workspace strategy (not saved as a document)'}
          {readOnly && ' · read-only: duplicate it to edit'}
        </span>
        <span className="spacer" />
        <button
          type="button"
          className="btn"
          id="builder-run"
          disabled={!ready || running}
          title={ready ? 'Run the backtest on the chart page' : 'The canvas has a problem: see the status line'}
          onClick={() => {
            dispatch({ type: 'SET_PAGE', page: 'charts' });
            void run();
          }}
        >
          Run backtest
        </button>
        <button
          type="button"
          className="btn btn-green"
          id="builder-save"
          disabled={!ready || readOnly || !document || !edited || saving}
          title={readOnly ? 'The built-in strategy is read-only' : !document ? 'Open a saved strategy to save it' : undefined}
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
      <div className="builder-body">
        <Palette readOnly={readOnly} />
        <ReactFlowProvider>
          <Canvas key={`${document?.id ?? 'workspace'}:${side}`} graph={sideGraph(state, side)} readOnly={readOnly} onChange={commit} onRefused={setFlash} />
        </ReactFlowProvider>
      </div>
      <div className={'builder-status' + (status === 'Ready' ? ' ready' : ' problem')} id="builder-status" role="status">
        {status}
        {error && <span className="badge error">{error}</span>}
        {conflict && (
          <span className="badge error" id="builder-conflict">
            {conflict}{' '}
            <button type="button" className="btn" id="builder-reload" onClick={() => void reload()} title="Replace what is here with the saved strategy; you are asked first">
              Reload
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
