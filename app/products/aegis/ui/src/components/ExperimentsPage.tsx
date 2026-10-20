import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { applyCellToStrategy, surfaceLine } from '../experiments';
import { DASH, num, pct, timeLabel } from '../format';
import type { ExperimentReport, ExperimentSummary } from '../results';
import { unsavedEdits, useDispatch, useWorkspace } from '../state/workspace';
import { ExperimentPlanner } from './ExperimentPlanner';
import { ExperimentReportView } from './ExperimentReport';
import { formatSeconds } from './OptimizePopover';

/** Saved experiments (spec §8.2): the list, the planner, the running view, the report. */
export function ExperimentsPage() {
  const state = useWorkspace();
  const { document, strategy } = state;
  const dispatch = useDispatch();
  const [items, setItems] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusStudy, setFocusStudy] = useState<string | null>(null);
  const [selected, setSelected] = useState<ExperimentDocument | null>(null);
  const [report, setReport] = useState<ExperimentReport | null>(null);
  const [planning, setPlanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const edited = unsavedEdits(state);

  const refresh = useCallback(() => {
    api
      .experiments()
      .then(setItems)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);
  const load = useCallback(async (id: string) => {
    const doc = await api.experiment(id);
    setSelected(doc);
    setReport(doc.latest_report ? await api.experimentReport(id) : null);
  }, []);
  useEffect(refresh, [refresh]);
  const { focus } = state;
  useEffect(() => {
    if (!focus?.experimentId) return;
    setSelectedId(focus.experimentId); // a deep link from the Library (Mission 9)
    setFocusStudy(focus.studyId ?? null);
    dispatch({ type: 'CLEAR_FOCUS' });
  }, [focus, dispatch]);
  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setReport(null);
      return;
    }
    load(selectedId).catch((e: unknown) => setError(errorMessage(e)));
  }, [selectedId, load]);

  const live = (selected && (selected.status === 'running' || selected.status === 'queued')) || (items ?? []).some((i) => i.status === 'running');
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      refresh();
      if (selectedId) load(selectedId).catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [live, refresh, selectedId, load]);

  const act = async (work: () => Promise<unknown>, reloadSelected = true) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      refresh();
      if (reloadSelected && selectedId) await load(selectedId);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const use = (_cell: number, params: Record<string, number>) => {
    const base = strategy ?? selected?.spec;
    if (!base) return;
    dispatch({ type: 'SET_STRATEGY', strategy: applyCellToStrategy(base, params) });
    dispatch({ type: 'SET_PAGE', page: 'charts' });
  };
  const saveDocument = () =>
    act(async () => {
      if (document && strategy) dispatch({ type: 'SET_DOCUMENT', document: await api.updateStrategy(document.id, { spec: strategy }) });
    });

  const progress = selected?.progress as { cells_done: number; cells_planned: number; chunks_done: number; chunks_total: number } | undefined;
  const plan = selected?.plan as { bars?: number; workers?: number; mode?: string; planned_runs?: number } | undefined;
  const remaining = selected && progress && plan && selected.ms_per_cell_bar ? ((progress.cells_planned - progress.cells_done) * (plan.bars ?? 0) * selected.ms_per_cell_bar) / 1000 / ((plan.workers ?? 1) * 0.8) : null;

  return (
    <div className="experiments-page" id="experiments-page">
      <div className="panel-title">
        Experiments <span className="small muted">maps of a strategy's control surface · peaks are marked fragile unless a plateau supports them</span>
      </div>
      <div className="actions" style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn btn-green"
          id="experiment-new"
          disabled={busy || !document}
          title={document ? undefined : 'Load a strategy document first'}
          onClick={() => setPlanning(true)}
        >
          New experiment
        </button>
        {document && edited && planning && (
          <span className="notice warn" id="experiment-gate" style={{ margin: 0 }}>
            save or revert the document first: an experiment pins its saved spec{' '}
            <button type="button" className="btn" id="experiment-gate-save" disabled={busy || document.builtin} onClick={saveDocument}>
              Save
            </button>{' '}
            <button type="button" className="btn" id="experiment-gate-revert" onClick={() => dispatch({ type: 'SET_DOCUMENT', document })}>
              Revert
            </button>
          </span>
        )}
      </div>
      {planning && document && !edited && (
        <ExperimentPlanner
          document={document}
          onClose={() => setPlanning(false)}
          onCreated={(id) => {
            setPlanning(false);
            setSelectedId(id);
            refresh();
          }}
        />
      )}
      {error && (
        <div className="notice warn" id="experiments-error">
          {error}
        </div>
      )}
      {items === null ? (
        <div className="empty-state">Loading experiments…</div>
      ) : items.length === 0 ? (
        <div className="empty-state">No experiments yet.</div>
      ) : (
        <table className="exp-table small" id="experiments-list">
          <thead>
            <tr>
              <th>Name</th>
              <th>Strategy</th>
              <th>Surface</th>
              <th>Cells</th>
              <th>Status</th>
              <th>Objective</th>
              <th>Decision</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {items.filter((item) => typeof item.id === 'string' && item.progress).map((item) => (
              <tr key={item.id} id={`exp-${item.id}`} className={item.id === selectedId ? 'selected' : ''} onClick={() => setSelectedId(item.id)}>
                <td>
                  {item.name}
                  {item.parent && <div className="muted">refines {item.parent}</div>}
                </td>
                <td>{item.strategy_id}</td>
                <td>{surfaceLine({ parameters: item.paths.map((p) => ({ path: p, start: 0, stop: 0, step: 1 })) }, item.mode && item.valid_cells !== null && item.planned_runs !== null && item.sampled_fraction !== null ? { mode: item.mode, valid_cells: item.valid_cells, planned_runs: item.planned_runs, sampled_fraction: item.sampled_fraction } : null)}</td>
                <td>
                  {item.progress.cells_done.toLocaleString()} / {item.progress.cells_planned.toLocaleString()}
                </td>
                <td>
                  <span className={'badge' + (item.status === 'failed' ? ' error' : '')}>{item.status}</span>
                </td>
                <td>{item.objective}</td>
                <td>{item.decision ? item.decision.verdict : DASH}</td>
                <td>{timeLabel(item.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected && progress && (
        <div className="report-section" id="experiment-progress">
          <div className="panel-title">
            {selected.name} <span className={'badge' + (selected.status === 'failed' ? ' error' : '')}>{selected.status}</span>
          </div>
          <div className="small muted">
            {surfaceLine(selected.surface, plan && plan.mode ? (selected.plan as never) : null)} · {selected.data.symbol} {selected.data.timeframe} {selected.data.start} → {selected.data.end} · objective {selected.objective} · engine {selected.engine ?? DASH}
          </div>
          <div className="progress-bar" style={{ marginTop: 6 }}>
            <div style={{ width: `${progress.cells_planned ? Math.min(100, (100 * progress.cells_done) / progress.cells_planned) : 0}%` }} />
          </div>
          <div className="small" style={{ marginTop: 4 }}>
            {progress.cells_done.toLocaleString()} of {progress.cells_planned.toLocaleString()} cells · chunk {progress.chunks_done} of {progress.chunks_total} ·{' '}
            {selected.ms_per_cell_bar && plan?.bars ? `${num(selected.ms_per_cell_bar * plan.bars, 1)} ms per cell per worker` : 'cost not measured yet'}
            {remaining !== null && (selected.status === 'running' || selected.status === 'paused') ? ` · ≈ ${formatSeconds(remaining)} remaining` : ''}
            {selected.plan && (selected.plan as { mode?: string }).mode === 'sampled' ? ` · sampled ${pct((selected.plan as { sampled_fraction?: number }).sampled_fraction ?? 0)}` : ''}
          </div>
          {selected.error && <div className="notice warn">{selected.error}</div>}
          <div className="actions" style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button type="button" className="btn" id="experiment-pause" disabled={busy || selected.status !== 'running'} onClick={() => act(() => api.pauseExperiment(selected.id))}>
              Pause
            </button>
            <button
              type="button"
              className="btn"
              id="experiment-resume"
              disabled={busy || !(selected.status === 'paused' || selected.status === 'queued' || selected.status === 'failed')}
              title={selected.status === 'failed' ? 'Continue from the cells already on disk' : undefined}
              onClick={() => act(() => api.resumeExperiment(selected.id))}
            >
              Resume
            </button>
            <button type="button" className="btn" id="experiment-cancel" disabled={busy || !(selected.status === 'running' || selected.status === 'queued' || selected.status === 'paused')} onClick={() => act(() => api.cancelExperiment(selected.id))}>
              Cancel
            </button>
            <button
              type="button"
              className="btn"
              id="experiment-delete"
              disabled={busy || selected.status === 'running' || selected.status === 'queued' || selected.status === 'paused'}
              onClick={() =>
                act(async () => {
                  await api.deleteExperiment(selected.id);
                  setSelectedId(null);
                }, false)
              }
            >
              Delete
            </button>
          </div>
        </div>
      )}
      {selected && report && (
        <ExperimentReportView
          experiment={selected}
          report={report}
          focusStudyId={focusStudy}
          onUse={use}
          onChanged={() => {
            refresh();
            if (selectedId) load(selectedId).catch((e: unknown) => setError(errorMessage(e)));
          }}
          onRefined={(childId) => {
            refresh();
            setSelectedId(childId);
          }}
        />
      )}
      {selected && !report && selected.status !== 'running' && selected.status !== 'queued' && (
        <div className="empty-state">No report yet{selected.status === 'paused' || selected.status === 'failed' ? ': resume the experiment to finish it' : ''}.</div>
      )}
    </div>
  );
}
