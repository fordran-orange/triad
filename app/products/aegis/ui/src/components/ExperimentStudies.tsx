import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { DASH, timeLabel } from '../format';
import type { StudySummary } from '../results';
import { StudyPlanner } from './StudyPlanner';
import { StudyView } from './StudyView';

/** "Walk forward" on an experiment's report (Mission 8 spec §8): the planner, the experiment's
 *  studies with their decisions, and the selected study. */
export function ExperimentStudies({ experiment }: { experiment: ExperimentDocument }) {
  const [items, setItems] = useState<StudySummary[] | null>(null);
  const [planning, setPlanning] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api
      .studies(experiment.id)
      .then(setItems)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [experiment.id]);
  useEffect(refresh, [refresh]);
  const finished = experiment.status === 'done' && experiment.latest_report !== null;

  return (
    <div className="report-section" id="walk-forward">
      <div className="panel-title">
        Walk forward <span className="small muted">does the plateau choice hold out of sample? each symbol walks itself</span>
      </div>
      <div className="actions" style={{ display: 'flex', gap: 6, margin: '6px 0' }}>
        <button
          type="button"
          className="btn btn-green"
          id="experiment-walk-forward"
          disabled={!finished}
          title={finished ? undefined : 'A study needs a finished experiment with a report'}
          onClick={() => setPlanning(true)}
        >
          Walk forward
        </button>
      </div>
      {planning && (
        <StudyPlanner
          experiment={experiment}
          onClose={() => setPlanning(false)}
          onCreated={(id) => {
            setPlanning(false);
            setSelectedId(id);
            refresh();
          }}
        />
      )}
      {error && <div className="notice warn">{error}</div>}
      {items && items.length > 0 ? (
        <table className="exp-table small" id="studies-of-experiment">
          <thead>
            <tr>
              <th>Study</th>
              <th>Symbols</th>
              <th>Windows</th>
              <th>Status</th>
              <th>Decision</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} id={`study-row-${item.id}`} className={item.id === selectedId ? 'selected' : ''} onClick={() => setSelectedId(item.id)} style={{ cursor: 'pointer' }}>
                <td>{item.name}</td>
                <td>{item.symbols.join(', ')}</td>
                <td>
                  {item.progress?.windows_done ?? 0} / {item.progress?.windows_total ?? DASH}
                </td>
                <td>
                  <span className={'badge' + (item.status === 'failed' ? ' error' : '')}>{item.status}</span>
                </td>
                <td>{item.decision ? `${item.decision.verdict}${item.decision.notes ? ` — ${item.decision.notes}` : ''}` : DASH}</td>
                <td>{timeLabel(item.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="muted small">{items === null ? 'Loading studies…' : 'No studies of this experiment yet.'}</div>
      )}
      {selectedId && (
        <StudyView
          key={selectedId}
          studyId={selectedId}
          onChanged={refresh}
          onDeleted={() => {
            setSelectedId(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}
