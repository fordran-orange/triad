import { useDispatch, useWorkspace } from '../state/workspace';

const ITEMS: Array<{ label: string; page?: 'charts' | 'lab'; id?: string; disabled?: boolean }> = [
  { label: 'Dashboard', disabled: true },
  { label: 'Charts', page: 'charts', id: 'nav-charts' },
  { label: 'Strategy Lab', page: 'lab', id: 'nav-lab' },
  { label: 'Indicators', disabled: true },
  { label: 'Data', disabled: true },
  { label: 'Experiments', disabled: true },
  { label: 'Paper Trade', disabled: true },
  { label: 'Settings', disabled: true },
];

export function SideNav() {
  const { status, page } = useWorkspace();
  const dispatch = useDispatch();
  return (
    <aside className="sidebar">
      {ITEMS.map((item) =>
        item.page ? (
          <button
            type="button"
            key={item.label}
            id={item.id}
            className={'nav' + (page === item.page ? ' active' : '')}
            aria-current={page === item.page ? 'page' : undefined}
            onClick={() => dispatch({ type: 'SET_PAGE', page: item.page! })}
          >
            <span className="dot" />
            {item.label}
          </button>
        ) : (
          <div key={item.label} className={'nav' + (item.disabled ? ' disabled' : '')} title={item.disabled ? 'Not yet built' : undefined} aria-disabled={item.disabled}>
            <span className="dot" />
            {item.label}
          </div>
        ),
      )}
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
