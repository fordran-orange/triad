import { useWorkspace } from '../state/workspace';

export function ExecutionPanel() {
  const { strategy } = useWorkspace();
  const x = strategy?.execution;
  return (
    <div className="panel-section">
      <div className="section-label">Execution</div>
      <div className="row">
        <label>Signal</label>
        <select value={x?.signal_timing ?? 'bar_close'} disabled>
          <option value="bar_close">Bar close</option>
        </select>
      </div>
      <div className="row">
        <label>Fill</label>
        <select value={x?.fill_timing ?? 'next_bar_open'} disabled>
          <option value="next_bar_open">Next bar open</option>
        </select>
      </div>
      <div className="row">
        <label>Commission / side</label>
        <input type="number" step="0.01" min={0} value={x?.commission_per_side ?? ''} disabled title="Editing connects in the backtest phase" />
      </div>
      <div className="row">
        <label>Slippage (bps)</label>
        <input type="number" step="0.1" min={0} value={x?.slippage_bps ?? ''} disabled title="Editing connects in the backtest phase" />
      </div>
    </div>
  );
}
