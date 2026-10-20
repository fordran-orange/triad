import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage, type StudyStatus } from '../api/client';
import { num, timeLabel } from '../format';
import type { StudyProgress, StudyReport } from '../results';
import { formatSeconds } from './OptimizePopover';
import { StudyReportView } from './StudyReport';

interface Props {
  studyId: string;
  onChanged: () => void;
  onDeleted: () => void;
}

type Verdict = 'accepted' | 'rejected' | 'deferred';

/** One study (spec §8): progress with Pause, Resume, Cancel and Delete, then the report and the
 *  decision form. Polls every 2 s while it runs. */
export function StudyView({ studyId, onChanged, onDeleted }: Props) {
  const [study, setStudy] = useState<StudyStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState<Verdict>('accepted');
  const [notes, setNotes] = useState('');

  const load = useCallback(async () => {
    const loaded = await api.study(studyId);
    setStudy(loaded);
    return loaded;
  }, [studyId]);
  useEffect(() => {
    load()
      .then((loaded) => {
        const decision = loaded.decision as { verdict?: Verdict; notes?: string } | null | undefined;
        if (decision?.verdict) setVerdict(decision.verdict);
        setNotes(String(decision?.notes ?? ''));
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [load]);
  const live = study !== null && (study.status === 'running' || study.status === 'queued');
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      load()
        .then(onChanged)
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [live, load, onChanged]);

  const act = async (work: () => Promise<unknown>, reload = true) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      if (reload) await load();
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!study) return <div className="empty-state">{error ?? 'Loading the study…'}</div>;
  const progress = study.progress as unknown as StudyProgress;
  const decision = study.decision as { verdict?: string; notes?: string; decided_at?: string } | null | undefined;
  const report = study.report as unknown as StudyReport | null | undefined;
  const plan = study.plan as { symbols?: Array<{ cells_per_window: number }> };
  const cellsPerWindow = plan.symbols?.[0]?.cells_per_window ?? 0;
  const unfinished = study.status === 'running' || study.status === 'queued' || study.status === 'paused';
  return (
    <div className="report-section" id={`study-${study.id}`} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="panel-title">
        {study.name}{' '}
        <span className={'badge' + (study.status === 'failed' ? ' error' : '')} id="study-status">
          {study.status}
        </span>
      </div>
      <div className="small muted">
        {study.symbols.join(', ')} · {study.timeframe} {study.start} → {study.end} · in-sample {study.in_sample_bars.toLocaleString()} / out-of-sample {study.out_of_sample_bars.toLocaleString()} bars ·
        objective {study.objective}
      </div>
      <div id="study-progress">
        <div className="progress-bar">
          <div style={{ width: `${progress.windows_total ? Math.min(100, (100 * progress.windows_done) / progress.windows_total) : 0}%` }} />
        </div>
        <div className="small" style={{ marginTop: 4 }}>
          {progress.windows_done} of {progress.windows_total} windows
          {progress.symbol !== null && progress.symbol !== undefined && unfinished ? ` · next: ${progress.symbol} window ${progress.window}` : ''} · {progress.cells_done.toLocaleString()} in-sample cells
          ({cellsPerWindow.toLocaleString()} per window) ·{' '}
          {study.ms_per_cell_bar ? `${num(study.ms_per_cell_bar * study.in_sample_bars, 1)} ms per cell per worker (measured)` : 'cost not measured yet'}
          {study.estimated_seconds !== undefined && unfinished ? ` · ≈ ${formatSeconds(study.estimated_seconds)} remaining` : ''}
        </div>
      </div>
      {study.error && <div className="notice warn">{study.error}</div>}
      <div className="actions" style={{ display: 'flex', gap: 6 }}>
        <button type="button" className="btn" id="study-pause" disabled={busy || study.status !== 'running'} onClick={() => act(() => api.pauseStudy(study.id))}>
          Pause
        </button>
        <button
          type="button"
          className="btn"
          id="study-resume"
          disabled={busy || !(study.status === 'paused' || study.status === 'queued' || study.status === 'failed')}
          onClick={() => act(() => api.resumeStudy(study.id))}
        >
          Resume
        </button>
        <button type="button" className="btn" id="study-cancel" disabled={busy || !unfinished} onClick={() => act(() => api.cancelStudy(study.id))}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          id="study-delete"
          title="Move it to Recently deleted in the Library"
          disabled={busy || unfinished}
          onClick={() =>
            act(async () => {
              await api.deleteStudy(study.id);
              onDeleted();
            }, false)
          }
        >
          Delete
        </button>
      </div>
      {report ? <StudyReportView study={study} report={report} /> : !live && <div className="empty-state">No report yet{study.status === 'paused' ? ': resume the study to finish it' : ''}.</div>}
      <div className="report-section" id="study-decision">
        <div className="panel-title">Decision</div>
        {decision?.verdict ? (
          <div className="small" style={{ marginBottom: 6 }} id="study-decision-current">
            <b>{decision.verdict}</b> on {timeLabel(decision.decided_at ?? null)}
            {decision.notes ? ` — ${decision.notes}` : ''}
          </div>
        ) : (
          <div className="muted small" style={{ marginBottom: 6 }}>
            No decision recorded.
          </div>
        )}
        <div style={{ display: 'flex', gap: 6 }}>
          <select id="study-decision-verdict" value={verdict} disabled={live} onChange={(e) => setVerdict(e.target.value as Verdict)}>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="deferred">deferred</option>
          </select>
          <input id="study-decision-notes" value={notes} placeholder="notes" disabled={live} onChange={(e) => setNotes(e.target.value)} style={{ flex: 1 }} />
          <button
            type="button"
            className="btn btn-green"
            id="study-decision-save"
            disabled={busy || live}
            title={live ? 'Decide when the study has finished, been cancelled or been paused' : undefined}
            onClick={() => act(() => api.decideStudy(study.id, { verdict, notes }))}
          >
            Save decision
          </button>
        </div>
      </div>
      {error && (
        <div className="notice warn" id="study-view-error">
          {error}
        </div>
      )}
    </div>
  );
}
