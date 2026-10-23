import { ReactFlowProvider } from '@xyflow/react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { api, errorMessage } from '../../api/client';
import type { StrategySide } from '../../contracts';
import { sideFromGraph, type SideGraph } from '../../builder/graph';
import { History } from '../../builder/history';
import { useRunBacktest } from '../../state/run';
import { currentCanvas, defaultRanges, SIDE_KEY, sideGraph, unsavedEdits, useDispatch, useWorkspace, type Side } from '../../state/workspace';
import { Canvas } from './Canvas';
import { Palette } from './Palette';

export interface Snapshot {
  graph: SideGraph;
  spec: StrategySide;
}

/** A side read back from the canvas, with the default (disabled) ranges of each indicator it adds,
 * as an indicator added by hand gets them (spec §9.3). */
export function withDefaultRanges(next: StrategySide, before: StrategySide): StrategySide {
  const had = new Set((before.indicators ?? []).map((i) => i.id));
  const ranges = [...(next.optimization ?? [])];
  for (const spec of next.indicators ?? []) {
    if (had.has(spec.id)) continue;
    for (const range of defaultRanges(spec)) if (!ranges.some((r) => r.path === range.path)) ranges.push(range);
  }
  return { ...next, optimization: ranges };
}

/** The Strategy Lab's builder (Mission 13 spec §4.6): the text line, Long / Short tabs, the palette
 * and the canvas over the workspace strategy, and a status line that says "Ready" or names the
 * first problem. `phrase` is the text line (Task 8). */
export function BuilderPage({ phrase }: { phrase?: (push: (side: Side, snapshot: Snapshot) => void) => ReactNode }) {
  const state = useWorkspace();
  const { strategy, document, builderSide: side, running } = state;
  const dispatch = useDispatch();
  const run = useRunBacktest();
  const [flash, setFlash] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    try {
      dispatch({ type: 'SET_DOCUMENT', document: await api.updateStrategy(document.id, { spec: strategy, canvas: currentCanvas(state) }) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const status = flash ?? (problems[side] ? problems[side] : !ready ? `${side === 'long' ? 'Short' : 'Long'} side: ${problems[side === 'long' ? 'short' : 'long']}` : 'Ready');

  return (
    <div className="builder" id="builder" tabIndex={-1} onKeyDown={onKeyDown}>
      <div className="builder-phrase" id="builder-phrase">
        {phrase?.(push)}
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
      </div>
    </div>
  );
}
