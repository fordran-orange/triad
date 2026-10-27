import { useState } from 'react';
import { useLab, useLabDispatch } from './labState';
import { activeFilterCount, type LabFilter } from './labStore';

/** One line per active constraint of the linked filter. */
function filterLines(filter: LabFilter): string[] {
  const lines: string[] = [];
  for (const [path, [lo, hi]] of Object.entries(filter.ranges)) lines.push(`${path} ∈ [${lo}, ${hi}]`);
  for (const [path, value] of Object.entries(filter.values)) lines.push(`${path} = ${value}`);
  if (filter.scope !== 'combined') lines.push(`direction: ${filter.scope} only`);
  for (const pass of filter.pass) lines.push(`pass: ${pass}`);
  for (const status of filter.status) lines.push(`status: ${status}`);
  return lines;
}

/** `Linked · k filters` on every panel that reads the shared filter; a click lists the filters with Clear.
 *  Only the context bar's chip carries an id (`#lab-linked`, its Clear `#lab-linked-clear`). */
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
