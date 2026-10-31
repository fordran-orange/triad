import { useEffect, useState } from 'react';
import type { LabParameter } from '../results';
import { fixValueAction, parseNumber as parse, searchFamilies, type CatalogEntry, type Family } from './catalog';
import { familyTree } from './familiesModel';
import { filterLines } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { activeFilterCount, clearActions } from './labStore';
import { LinkedChip } from './LinkedChip';

const ACTIVE_TITLE = 'no screening evidence yet: all parameters Active (Phase 4)';

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

/** A parameter's fixed value (§5.2's "fix a value"): written to the shared filter on every change, blank removes it.
 *  A fixed value filters the trials and holds the exact slice of the heatmap too. Cleared elsewhere (the chip's
 *  Clear, Escape, a new source) like the ranges. */
function FixValueInput({ entry }: { entry: CatalogEntry }) {
  const fixed = useLab().filter.values[entry.path];
  const dispatch = useLabDispatch();
  const [text, setText] = useState(fixed === undefined ? '' : String(fixed));
  useEffect(() => {
    if (fixed === undefined) setText('');
  }, [fixed]);
  return (
    <label className="entry-fix" title="fix one value: only the trials with it, and the exact slice holds it">
      =
      <input
        type="number"
        className="fix-value"
        data-path={entry.path}
        aria-label={`${entry.path} fixed value`}
        min={entry.start}
        max={entry.stop}
        step={entry.step}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          dispatch(fixValueAction(entry.path, e.target.value));
        }}
      />
    </label>
  );
}

/** Screen E's family tree: the families by side (long first) and indicator id, each with its parameters, its values and how
 *  many of them have a tested trial, and under each parameter its brush and fixed value (the pinned filters and slices). */
function FamilyTree({ shown, parameters, collapsed, toggle }: { shown: Family[]; parameters: readonly LabParameter[] | null; collapsed: string[]; toggle: (key: string) => void }) {
  const entryOf = new Map(shown.flatMap((family) => family.entries.map((entry) => [entry.path, entry] as const)));
  return (
    <>
      {familyTree(shown, parameters).map((node) => {
        const open = !collapsed.includes(node.key);
        return (
          <section
            className="family"
            key={node.key}
            id={`lab-families-family-${node.side}-${node.id}`}
            data-family={node.key}
            data-side={node.side}
            data-parameters={node.parameters}
            data-values={node.values}
            data-tested={node.tested ?? ''}
          >
            <button type="button" className="family-toggle" aria-expanded={open} onClick={() => toggle(node.key)}>
              <span className="family-caret">{open ? '▾' : '▸'}</span> {node.label}
            </button>
            <div className="sub family-counts" title="the parameters of this indicator on this side, the values of their ranges, and the values that have a tested trial">
              {node.text}
            </div>
            {open && (
              <ul className="family-entries">
                {node.entries.map((e) => {
                  const entry = entryOf.get(e.path);
                  if (entry === undefined) return null;
                  return (
                    <li className="catalog-entry" key={e.path} data-path={e.path}>
                      <div className="entry-head" title={e.path}>
                        <span className="entry-field">{e.field}</span>
                        <span className="muted">
                          {entry.start}–{entry.stop} / {entry.step} · {e.count} values
                          {e.tested !== null ? ` · ${e.tested} of ${e.of} ${e.bucketed ? 'buckets' : 'values'} tested` : ''}
                        </span>
                      </div>
                      <div className="entry-controls">
                        <RangeInputs entry={entry} />
                        <FixValueInput entry={entry} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </>
  );
}

/** The filters and slices in force, each as a line, with the Clear that removes the brushes and fixed values. */
function PinnedFilters() {
  const { filter } = useLab();
  const dispatch = useLabDispatch();
  const lines = filterLines(filter);
  const active = activeFilterCount(filter);
  return (
    <div className="catalog-pinned" id="lab-families-pinned" data-filters={active}>
      <div className="catalog-subtitle">Pinned filters &amp; slices</div>
      {lines.length === 0 ? (
        <div className="sub">none: every trial is in view</div>
      ) : (
        <ul className="catalog-pinned-list">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="btn"
        id="lab-families-clear"
        disabled={active === 0}
        title={active === 0 ? 'nothing to clear' : 'clears the brushes, the fixed values and the side'}
        onClick={() => clearActions(filter).forEach(dispatch)}
      >
        Clear
      </button>
    </div>
  );
}

/** The parameter rail: families per side, collapsible and searchable. In `controls` mode each parameter carries
 *  the X / Y axis radios (X = the heatmap's columns, Y = its rows), a range brush and a fixed value; in `status` mode (Variable
 *  Intelligence) it carries its variable status instead; in `families` mode (Screen E) it is the family tree, grouped by side
 *  and indicator id, with the counts of each family, each parameter's brush and fixed value, and the filters in force. */
export function ParameterCatalog({
  list,
  mode,
  loading,
  parameters = null,
}: {
  list: Family[] | null;
  mode: 'controls' | 'status' | 'families';
  loading: boolean;
  /** The summary's parameters, for the tested counts of the `families` mode. */
  parameters?: readonly LabParameter[] | null;
}) {
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
  const families = mode === 'families';
  const matching = shown.reduce((sum, family) => sum + family.entries.length, 0);

  return (
    <aside className="lab-catalog" id={families ? 'lab-families-catalog' : 'lab-catalog'} aria-label="Parameters">
      <div className="catalog-head">
        <span className="catalog-title">Parameters{list ? ` · ${total}` : ''}</span>
        {mode !== 'status' && <LinkedChip />}
      </div>
      <input
        type="search"
        id={families ? 'lab-families-search' : 'lab-catalog-search'}
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
        <div className="lab-empty" id={families ? 'lab-families-no-match' : undefined}>
          No parameter matches “{search.trim()}”.
        </div>
      ) : families ? (
        <>
          {search.trim() !== '' && (
            <div className="sub" id="lab-families-matches" data-families={shown.length} data-parameters={matching}>
              {shown.length} of {list.length} {list.length === 1 ? 'family matches' : 'families match'} · {matching} {matching === 1 ? 'parameter' : 'parameters'} of {total}
            </div>
          )}
          <FamilyTree shown={shown} parameters={parameters} collapsed={collapsed} toggle={toggle} />
          <PinnedFilters />
        </>
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
                          <FixValueInput entry={entry} />
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
