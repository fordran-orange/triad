import { useWorkspace } from '../state/workspace';

const ITEMS: Array<{ label: string; active?: boolean; disabled?: boolean }> = [
  { label: 'Dashboard', disabled: true },
  { label: 'Charts', active: true },
  { label: 'Strategy Lab', disabled: true },
  { label: 'Indicators', disabled: true },
  { label: 'Data', disabled: true },
  { label: 'Experiments', disabled: true },
  { label: 'Paper Trade', disabled: true },
  { label: 'Settings', disabled: true },
];

export function SideNav() {
  const { status } = useWorkspace();
  return (
    <aside className="sidebar">
      {ITEMS.map((item) => (
        <div
          key={item.label}
          className={'nav' + (item.active ? ' active' : '') + (item.disabled ? ' disabled' : '')}
          title={item.disabled ? 'Not yet built' : undefined}
          aria-disabled={item.disabled}
        >
          <span className="dot" />
          {item.label}
        </div>
      ))}
      <div className="sidebar-bottom">
        <div className="green">● PRODUCT BUILD MODE</div>
        <div style={{ marginTop: 5 }} id="governance-line" title="From GET /aegis/api/status">
          {status ? (
            <>
              {status.mode.replace('_', '-')}
              <br />
              Exchange {status.exchange}
            </>
          ) : (
            <>status not loaded</>
          )}
        </div>
      </div>
    </aside>
  );
}
