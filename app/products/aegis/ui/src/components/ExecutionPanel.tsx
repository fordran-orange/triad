import { useDispatch, useWorkspace, type ExecutionField } from '../state/workspace';

export function ExecutionPanel() {
  const { strategy, settings } = useWorkspace();
  const dispatch = useDispatch();
  const x = strategy?.execution;
  const setExecution = (field: ExecutionField, raw: string) => {
    const value = Number(raw);
    if (Number.isFinite(value) && value >= 0) dispatch({ type: 'SET_EXECUTION', field, value });
  };
  const setCapital = (raw: string) => {
    const value = Number(raw);
    if (Number.isFinite(value) && value > 0) dispatch({ type: 'SET_SETTINGS', settings: { initial_capital: value } });
  };
  const setAllocation = (raw: string) => {
    const value = Number(raw);
    if (Number.isFinite(value) && value > 0 && value <= 1) dispatch({ type: 'SET_SETTINGS', settings: { allocation_fraction: value } });
  };
  return (
    <div className="panel-section">
      <div className="section-label">Execution</div>
      <div className="row">
        <label>Signal</label>
        <select value={x?.signal_timing ?? 'bar_close'} disabled title="The engine signals on closed bars only">
          <option value="bar_close">Bar close</option>
        </select>
      </div>
      <div className="row">
        <label>Fill</label>
        <select value={x?.fill_timing ?? 'next_bar_open'} disabled title="The engine fills at the next bar open only">
          <option value="next_bar_open">Next bar open</option>
        </select>
      </div>
      <div className="row">
        <label htmlFor="commission">Commission / side</label>
        <input id="commission" type="number" step="0.01" min={0} value={x?.commission_per_side ?? ''} disabled={!x} onChange={(e) => setExecution('commission_per_side', e.target.value)} />
      </div>
      <div className="row">
        <label htmlFor="slippage">Slippage (bps)</label>
        <input id="slippage" type="number" step="0.1" min={0} value={x?.slippage_bps ?? ''} disabled={!x} onChange={(e) => setExecution('slippage_bps', e.target.value)} />
      </div>
      <div className="row">
        <label htmlFor="initial-capital">Initial capital</label>
        <input id="initial-capital" type="number" step="1000" min={1} value={settings.initial_capital} onChange={(e) => setCapital(e.target.value)} />
      </div>
      <div className="row">
        <label htmlFor="allocation">Allocation (0–1)</label>
        <input id="allocation" type="number" step="0.05" min={0.05} max={1} value={settings.allocation_fraction} onChange={(e) => setAllocation(e.target.value)} />
      </div>
    </div>
  );
}
