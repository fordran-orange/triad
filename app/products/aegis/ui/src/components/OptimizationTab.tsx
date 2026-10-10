import { DASH } from '../format';
import { useWorkspace } from '../state/workspace';
import { Heatmap } from './Heatmap';

export function OptimizationTab() {
  const { optimization } = useWorkspace();
  const job = optimization.long ?? optimization.short ?? null;
  return (
    <div className="result-body">
      <Heatmap title="Optimization Heatmap" metric="Net P&L" fast={[]} slow={[]} matrix={null} />
      <div className="results-table">
        <div className="panel-title">
          Optimization Results <span className="small">{job ? job.status : 'not run'}</span>
        </div>
        {!job && <div className="empty-state">Optimizer not connected yet — no parameter sets have been evaluated.</div>}
        <table>
          <thead>
            <tr>
              <th>Parameter set</th>
              <th>Net P&L</th>
              <th>Max DD</th>
              <th>MAR</th>
              <th>Win rate</th>
              <th>Trades</th>
              <th>Side</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="muted">{DASH}</td>
              <td>{DASH}</td>
              <td>{DASH}</td>
              <td>{DASH}</td>
              <td>{DASH}</td>
              <td>{DASH}</td>
              <td>{DASH}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
