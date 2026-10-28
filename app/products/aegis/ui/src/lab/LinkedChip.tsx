import { useState } from 'react';
import { filterLines } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { activeFilterCount, canonicalFilter } from './labStore';

/** `Linked · k filters` on every panel that reads the shared filter; a click lists the filters with Clear. The
 *  chip carries the exact filter as `data-filter` (its canonical text). Only the context bar's chip carries an id
 *  (`#lab-linked`, its Clear `#lab-linked-clear`). */
export function LinkedChip({ id }: { id?: string }) {
  const { filter } = useLab();
  const dispatch = useLabDispatch();
  const [open, setOpen] = useState(false);
  const count = activeFilterCount(filter);
  const lines = filterLines(filter);
  const clear = () => {
    for (const path of Object.keys(filter.ranges)) dispatch({ type: 'SET_RANGE', path, range: null });
    for (const path of Object.keys(filter.values)) dispatch({ type: 'FIX_VALUE', path, value: null });
    dispatch({ type: 'SET_SCOPE', scope: 'combined' });
    setOpen(false);
  };
  return (
    <span className="linked-wrap">
      <button
        type="button"
        className={'linked-chip' + (count > 0 ? ' on' : '')}
        id={id}
        data-filter={canonicalFilter(filter)}
        aria-expanded={open}
        title="The filter every Lab panel shares; click to list it"
        onClick={() => setOpen((v) => !v)}
      >
        Linked · {count} filter{count === 1 ? '' : 's'}
      </button>
      {open && (
        <span className="linked-list" role="dialog" aria-label="Active filters">
          {lines.length === 0 ? <span className="muted">No filter is active: every trial is in view.</span> : lines.map((line) => <span key={line}>{line}</span>)}
          <span className="linked-actions">
            <button type="button" className="btn" id={id ? `${id}-clear` : undefined} disabled={count === 0} title={count === 0 ? 'nothing to clear' : undefined} onClick={clear}>
              Clear
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              Close
            </button>
          </span>
        </span>
      )}
    </span>
  );
}
