import { useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { paramsText, recommendationText } from '../experiments';
import { DASH, num, pct, timeLabel } from '../format';
import { OBJECTIVE_LABELS, OBJECTIVES, PERCENT_OBJECTIVES, type ExperimentReport, type Objective } from '../results';
import { CellsTable } from './CellsTable';
import { Heatmap } from './Heatmap';
import { MainEffects } from './MainEffects';

interface Props {
  experiment: ExperimentDocument;
  report: ExperimentReport;
  onUse: (cell: number, params: Record<string, number>) => void;
  onChanged: () => void;
  onRefined: (childId: string) => void;
}

/** The report (spec §8.2): recommendation first, then the maps, the cells, the decision. */
export function ExperimentReportView({ experiment, report, onUse, onChanged, onRefined }: Props) {
  const [objective, setObjective] = useState<Objective>(report.objective);
  const [tolerance, setTolerance] = useState(report.tolerance);
  const [verdict, setVerdict] = useState<'accepted' | 'rejected' | 'deferred'>(experiment.decision?.verdict ? (experiment.decision.verdict as 'accepted') : 'accepted');
  const [notes, setNotes] = useState(String(experiment.decision?.notes ?? ''));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rec = report.recommendation;

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div id="experiment-report" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className={'report-card' + (rec ? '' : ' none')} id="recommendation">
        <div className="panel-title">
          Recommendation{' '}
          <span className="small muted">
            report {report.report_id} · {report.objective} · tolerance {num(report.tolerance, 2)} (τ {num(report.tau, 4)}) · {report.mode}
            {report.mode === 'sampled' ? ` ${pct(report.sampled_fraction)}` : ''} · {report.valid_cells.toLocaleString()} valid cells
            {report.null_objective_cells ? ` · ${report.null_objective_cells} with no ${report.objective}` : ''}
          </span>
        </div>
        <div id="recommendation-text" style={{ marginTop: 6 }}>
          {recommendationText(report)}
        </div>
        {rec && (
          <>
            <div className="small" style={{ marginTop: 6 }}>
              Centre metrics:{' '}
              {OBJECTIVES.map((m) => (
                <span key={m} style={{ marginRight: 10 }}>
                  {OBJECTIVE_LABELS[m]} <b>{PERCENT_OBJECTIVES.has(m) ? pct(rec.centre.metrics[m]) : num(rec.centre.metrics[m], m === 'trade_count' ? 0 : 2)}</b>
                </span>
              ))}
            </div>
            {rec.fragile_peaks.length > 0 && (
              <div className="small" style={{ marginTop: 4 }}>
                Fragile peaks (not recommended):{' '}
                {rec.fragile_peaks.map((p) => (
                  <span key={p.cell} className="badge raw" style={{ marginRight: 6 }} title={paramsText(p.params)}>
                    cell {p.cell} · {num(p.objective, 3)}
                  </span>
                ))}
              </div>
            )}
            {report.uncertainty && (
              <div className="small muted" style={{ marginTop: 6 }} id="uncertainty">
                Spread (iqr) {num(report.uncertainty.iqr, 4)} over {report.uncertainty.cells} cells; sampled fraction {pct(report.uncertainty.sampled_fraction)}. {report.uncertainty.statement}
              </div>
            )}
            <div className="actions" style={{ marginTop: 8, display: 'flex', gap: 6 }}>
              <button type="button" className="btn btn-green" id={`use-cell-${rec.centre.cell}`} onClick={() => onUse(rec.centre.cell, rec.centre.params)}>
                Use the centre in the workspace
              </button>
              <button type="button" className="btn" id="experiment-refine" disabled={busy} onClick={() => act(async () => onRefined((await api.refineExperiment(experiment.id)).id))} title="A new experiment around this plateau, one step wider each way">
                Refine around this plateau
              </button>
            </div>
          </>
        )}
        <div className="small muted" style={{ marginTop: 6 }}>Neighbours: {report.neighbour_rule}.</div>
      </div>

      <div className="report-section">
        <h4>Plateaus</h4>
        {report.plateaus.length === 0 ? (
          <div className="muted small">No plateau counted at this tolerance.</div>
        ) : (
          <table className="small" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>#</th>
                <th>cells</th>
                <th>median</th>
                <th>iqr</th>
                <th>cliff</th>
                <th>centre</th>
              </tr>
            </thead>
            <tbody>
              {report.plateaus.map((p) => (
                <tr key={p.id} id={`plateau-${p.id}`}>
                  <td>{p.id}</td>
                  <td>{p.size}</td>
                  <td>{num(p.median, 4)}</td>
                  <td>{num(p.iqr, 4)}</td>
                  <td>{p.cliff === null ? DASH : num(p.cliff, 4)}</td>
                  <td>{paramsText(p.centre.params)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h4 style={{ marginTop: 8 }}>Peaks</h4>
        {report.peaks.length === 0 ? (
          <div className="muted small">None.</div>
        ) : (
          <div className="small">
            {report.peaks.slice(0, 40).map((p) => (
              <span key={p.cell} className={'badge' + (p.fragile ? ' raw' : '')} style={{ marginRight: 6, marginBottom: 4, display: 'inline-block' }} title={paramsText(p.params)}>
                cell {p.cell} · {num(p.objective, 3)} · {p.fragile ? 'fragile' : `plateau ${p.plateau}`}
              </span>
            ))}
            {report.peaks.length > 40 && <span className="muted">… {report.peaks.length - 40} more</span>}
          </div>
        )}
      </div>

      <div className="report-section">
        <h4>Main effects</h4>
        <MainEffects effects={report.main_effects} objective={report.objective} />
      </div>

      <div className="report-section">
        <h4>Interactions</h4>
        {report.interactions === null ? (
          <div className="muted small">Not applicable: one parameter.</div>
        ) : report.interactions.length === 0 ? (
          <div className="muted small">None.</div>
        ) : (
          <div className="effects">
            {report.interactions.map((pair) => (
              <Heatmap
                key={pair.paths.join('|')}
                title={`${pair.paths[0]} × ${pair.paths[1]} · strength ${num(pair.strength, 4)}`}
                metric={report.objective}
                fast={pair.values_a}
                slow={pair.values_b}
                matrix={pair.matrix}
                rowLabel={pair.paths[0]}
                colLabel={pair.paths[1]}
                format={(v) => num(v, 2)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="report-section">
        <h4>Sensitivity</h4>
        <table className="small">
          <tbody>
            {Object.entries(report.sensitivity.shares).map(([path, share]) => (
              <tr key={path}>
                <td>{path}</td>
                <td>{pct(share)}</td>
              </tr>
            ))}
            <tr>
              <td className="muted">remainder (interactions and noise)</td>
              <td>{report.sensitivity.remainder === null ? DASH : pct(report.sensitivity.remainder)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="report-section" id="clusters">
        <h4>Outcome clusters</h4>
        {'refused' in report.clusters ? (
          <div className="muted small">Not reported: {report.clusters.refused}.</div>
        ) : (
          <div className="small">
            {report.clusters.k} groups, silhouette {num(report.clusters.silhouette, 2)}:
            <ul>
              {report.clusters.groups.map((g, i) => (
                <li key={i}>
                  group {i + 1}: {g.size} cells · exemplar cell {g.exemplar} · medians {Object.entries(g.medians).map(([k, v]) => `${k} ${num(v, 3)}`).join(', ')} · ranges{' '}
                  {Object.entries(g.parameter_ranges).map(([k, [lo, hi]]) => `${k} ${num(lo, 4)}–${num(hi, 4)}`).join(', ')}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <CellsTable experiment={experiment} report={report} onUse={onUse} />

      <div className="report-section">
        <h4>Recompute the report</h4>
        <div className="row" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <label htmlFor="report-objective">Objective</label>
          <select id="report-objective" value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
            {OBJECTIVES.map((m) => (
              <option key={m} value={m}>
                {OBJECTIVE_LABELS[m]}
              </option>
            ))}
          </select>
          <label htmlFor="report-tolerance">Tolerance</label>
          <input id="report-tolerance" type="number" min={0.01} max={1} step={0.01} value={tolerance} onChange={(e) => setTolerance(Number(e.target.value))} />
          <button type="button" className="btn" id="report-recompute" disabled={busy} onClick={() => act(async () => (await api.recomputeReport(experiment.id, { objective, tolerance })) && onChanged())}>
            Recompute
          </button>
          <span className="muted small">
            {(experiment.reports ?? []).length} report{(experiment.reports ?? []).length === 1 ? '' : 's'} kept
          </span>
        </div>
      </div>

      <div className="report-section" id="decision">
        <h4>Decision</h4>
        {experiment.decision ? (
          <div className="small" style={{ marginBottom: 6 }}>
            <b>{String(experiment.decision.verdict)}</b> on {timeLabel(String(experiment.decision.decided_at))}
            {experiment.decision.notes ? ` — ${String(experiment.decision.notes)}` : ''}
          </div>
        ) : (
          <div className="muted small" style={{ marginBottom: 6 }}>No decision recorded.</div>
        )}
        <div className="row" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select id="decision-verdict" value={verdict} onChange={(e) => setVerdict(e.target.value as 'accepted')}>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="deferred">deferred</option>
          </select>
          <input id="decision-notes" value={notes} placeholder="notes" onChange={(e) => setNotes(e.target.value)} style={{ flex: 1 }} />
          <button type="button" className="btn btn-green" id="decision-save" disabled={busy} onClick={() => act(async () => (await api.decideExperiment(experiment.id, { verdict, notes })) && onChanged())}>
            Save decision
          </button>
        </div>
      </div>
      {error && (
        <div className="notice warn" id="report-error">
          {error}
        </div>
      )}
    </div>
  );
}
