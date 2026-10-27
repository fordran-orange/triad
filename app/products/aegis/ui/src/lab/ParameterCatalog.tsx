import { useEffect, useState } from 'react';
import { searchFamilies, type CatalogEntry, type Family } from './catalog';
import { useLab, useLabDispatch } from './labState';
import { LinkedChip } from './LinkedChip';

const ACTIVE_TITLE = 'no screening evidence yet: all parameters Active (Phase 4)';

function parse(text: string): number | null {
  if (text.trim() === '') return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** A parameter's [lo, hi] brush: written to the shared filter on every change; both empty removes it. A bound
 *  left empty is the parameter's own end, shown as the placeholder. */
function RangeInputs({ entry }: { entry: CatalogEntry }) {
  const range = useLab().filter.ranges[entry.path];
  const dispatch = useLabDispatch();
  const [lo, setLo] = useState(range ? String(range[0]) : '');
  const [hi, setHi] = useState(range ? String(range[1]) : '');
  useEffect(() => {
    if (range === undefined) {
      setLo(''); // cleared elsewhere (Clear, Escape, a new source)
      setHi('');
    }
  }, [range]);
  const write = (nextLo: string, nextHi: string) => {
    const a = parse(nextLo);
    const b = parse(nextHi);
    dispatch({ type: 'SET_RANGE', path: entry.path, range: a === null && b === null ? null : [a ?? entry.start, b ?? entry.stop] });
  };
  return (
    <span className="entry-range">
      <input
        type="number"
        className="range-lo"
        data-path={entry.path}
        aria-label={`${entry.path} from`}
        placeholder={String(entry.start)}
        min={entry.start}
        max={entry.stop}
        step={entry.step}
        value={lo}
        onChange={(e) => {
          setLo(e.target.value);
          write(e.target.value, hi);
        }}
      />
      <span className="muted">–</span>
      <input
        type="number"
        className="range-hi"
        data-path={entry.path}
        aria-label={`${entry.path} to`}
        placeholder={String(entry.stop)}
        min={entry.start}
        max={entry.stop}
        step={entry.step}
        value={hi}
        onChange={(e) => {
          setHi(e.target.value);
          write(lo, e.target.value);
        }}
      />
    </span>
  );
}

/** The parameter rail: families per side, collapsible and searchable. In `controls` mode each parameter carries
 *  the X / Y axis radios (X = the heatmap's columns, Y = its rows) and a range brush; in `status` mode (Variable
 *  Intelligence) it carries its variable status instead. */
export function ParameterCatalog({ list, mode, loading }: { list: Family[] | null; mode: 'controls' | 'status'; loading: boolean }) {
  const { axes } = useLab();
  const dispatch = useLabDispatch();
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const shown = list ? searchFamilies(list, search) : [];
  const paths = (list ?? []).flatMap((f) => f.entries.map((e) => e.path));
  // The other axis keeps its parameter; choosing the parameter it holds swaps the two.
  const other = (path: string, candidates: Array<string | undefined>) =>
    candidates.find((c): c is string => c !== undefined && c !== path && paths.includes(c)) ?? paths.find((p) => p !== path) ?? path;
  // axes = [rows (Y), columns (X)], the order the dock and the matrix route use.
  const setX = (path: string) => dispatch({ type: 'SET_AXES', axes: [other(path, [axes?.[0], axes?.[1]]), path] });
  const setY = (path: string) => dispatch({ type: 'SET_AXES', axes: [path, other(path, [axes?.[1], axes?.[0]])] });
  const toggle = (key: string) => setCollapsed((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]));
  const total = paths.length;

  return (
    <aside className="lab-catalog" id="lab-catalog" aria-label="Parameters">
      <div className="catalog-head">
        <span className="catalog-title">Parameters{list ? ` · ${total}` : ''}</span>
        {mode === 'controls' && <LinkedChip />}
      </div>
      <input
        type="search"
        id="lab-catalog-search"
        className="catalog-search"
        placeholder="Search parameters"
        aria-label="Search parameters"
        value={search}
        disabled={list === null}
        title={list === null ? 'open a source first' : undefined}
        onChange={(e) => setSearch(e.target.value)}
      />
      {list === null ? (
        <div className="lab-empty">{loading ? 'Loading parameters…' : 'No source open: choose one in the context bar.'}</div>
      ) : list.length === 0 ? (
        <div className="lab-empty">No parameters: this source varies none.</div>
      ) : shown.length === 0 ? (
        <div className="lab-empty">No parameter matches “{search.trim()}”.</div>
      ) : (
        shown.map((family) => {
          const open = !collapsed.includes(family.key);
          return (
            <section className="family" key={family.key} data-family={family.key}>
              <button type="button" className="family-toggle" aria-expanded={open} onClick={() => toggle(family.key)}>
                <span className="family-caret">{open ? '▾' : '▸'}</span> {family.label} <span className="muted">· {family.entries.length}</span>
              </button>
              {open && (
                <ul className="family-entries">
                  {family.entries.map((entry) => (
                    <li className="catalog-entry" key={entry.path}>
                      <div className="entry-head" title={entry.path}>
                        <span className="entry-field">{entry.field}</span>
                        <span className="muted">
                          {entry.start}–{entry.stop} / {entry.step} · {entry.count} values
                        </span>
                      </div>
                      {mode === 'controls' ? (
                        <div className="entry-controls">
                          <label title="X: the heatmap's columns">
                            <input type="radio" name="lab-axis-x" data-path={entry.path} checked={axes?.[1] === entry.path} onChange={() => setX(entry.path)} /> X
                          </label>
                          <label title="Y: the heatmap's rows">
                            <input type="radio" name="lab-axis-y" data-path={entry.path} checked={axes?.[0] === entry.path} onChange={() => setY(entry.path)} /> Y
                          </label>
                          <RangeInputs entry={entry} />
                        </div>
                      ) : (
                        <div className="entry-controls">
                          <span className="status-chip" title={ACTIVE_TITLE}>
                            Active (default)
                          </span>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })
      )}
    </aside>
  );
}
