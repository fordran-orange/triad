import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { api, errorMessage, type StrategySummary } from '../api/client';
import { DASH, timeLabel } from '../format';
import { comparable, headlineText, kindLabel, losing, openedEntry } from '../library';
import { LIBRARY_KINDS, type Cell, type JobStatus, type LibraryEntry, type LibraryFilters, type LibraryKind, type LibraryPage as Page, type WalkForwardStatus } from '../results';
import { applyConfigs, selectionFromData, TIMEFRAMES, unsavedEdits, useDispatch, useWorkspace, type Side } from '../state/workspace';
import { LibraryBacktestView } from './LibraryBacktestView';
import { LibraryCompare } from './LibraryCompare';
import { entryKey, LibraryList } from './LibraryList';
import { describeParams, OptimizationJobView } from './OptimizationTab';
import { WalkForwardJobView } from './WalkForwardTab';

const LIMIT = 50;
const DEFAULT_FILTERS: LibraryFilters = { kinds: [], symbol: '', timeframe: '', strategy: '', starred: false, decision: '', q: '', sort: 'created', offset: 0, limit: LIMIT, deleted: false };
const POLL_MS = 2000; // while the index is still preparing headlines
const SEARCH_MS = 300;
const LABEL_MAX = 80; // spec §6.1
const NOTES_MAX = 2000;

/** Every saved result in one place (Mission 9 spec §8): the filter bar and list, and the selected
 *  item's read-only view. Nothing here changes the workspace except a Load the operator presses. */
export function LibraryPage() {
  const { focus, symbols } = useWorkspace();
  const dispatch = useDispatch();
  const [filters, setFilters] = useState<LibraryFilters>(DEFAULT_FILTERS);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selected, setSelected] = useState<{ kind: LibraryKind; id: string } | null>(null);
  const [checked, setChecked] = useState<Record<string, LibraryEntry>>({});
  const [tick, setTick] = useState(0);
  const [comparing, setComparing] = useState<[string, string] | null>(null);
  const [notice, setNotice] = useState<ReactNode>(null);
  const [fetched, setFetched] = useState<LibraryEntry | null>(null);
  const [missing, setMissing] = useState(false);

  const set = (patch: Partial<LibraryFilters>) => setFilters((f) => ({ ...f, offset: 0, ...patch }));
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // A deep link from the Runs drawer opens its run here once.
  useEffect(() => {
    if (!focus?.libraryKind || !focus.libraryId) return;
    setSelected({ kind: focus.libraryKind, id: focus.libraryId });
    dispatch({ type: 'CLEAR_FOCUS' });
  }, [focus, dispatch]);

  useEffect(() => {
    api
      .strategies()
      .then(setStrategies)
      .catch(() => setStrategies([]));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setFilters((f) => (f.q === search ? f : { ...f, q: search, offset: 0 })), SEARCH_MS);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    api
      .library(filters)
      .then((p) => {
        if (cancelled) return;
        setPage(p);
        setError(null);
      })
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [filters, tick]);

  // Headlines are computed incrementally on first use; keep asking until none is left preparing.
  useEffect(() => {
    if (!page || page.preparing === 0) return;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [page, refresh]);

  const entries = page?.entries ?? [];
  const listed = selected !== null && entries.some((e) => e.kind === selected.kind && e.id === selected.id);
  const current = openedEntry(entries, selected, fetched);

  // An opened item the list page does not show keeps its full view: fetch it by id, again
  // after every change (milestone QA D2).
  useEffect(() => {
    setMissing(false);
    if (!selected || !page || listed) return;
    let cancelled = false;
    api
      .libraryEntry(selected.kind, selected.id)
      .then((e) => !cancelled && setFetched(e))
      .catch(() => {
        if (cancelled) return;
        setFetched(null);
        setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, page, listed]);
  const ticked = Object.values(checked);
  const compare = comparable(ticked);

  const uncheck = (keys: string[]) =>
    setChecked((c) => {
      const next = { ...c };
      for (const k of keys) delete next[k];
      return next;
    });
  const named = (e: LibraryEntry) => `${kindLabel(e.kind).toLowerCase()} "${e.label || e.name}"`;

  const remove = async (entry: LibraryEntry) => {
    if (!window.confirm(`Move ${named(entry)} to Recently deleted? It can be restored until the trash is emptied.`)) return;
    try {
      await api.libraryDelete(entry.kind, entry.id);
      uncheck([entryKey(entry)]);
      setSelected(null);
      setNotice(`Moved ${named(entry)} to Recently deleted.`);
      refresh();
    } catch (e) {
      setNotice(<span className="error">{errorMessage(e)}</span>);
    }
  };

  // Studies go before experiments, so an experiment ticked with its studies is not refused for them.
  const ORDER: Record<LibraryKind, number> = { study: 0, backtest: 1, optimization: 1, walkforward: 1, experiment: 2 };
  const removeSelected = async () => {
    const items = [...ticked].sort((x, y) => ORDER[x.kind] - ORDER[y.kind]);
    if (items.length === 0 || !window.confirm(`Move ${items.length} ticked result${items.length === 1 ? '' : 's'} to Recently deleted?`)) return;
    const moved: string[] = [];
    const refusals: string[] = [];
    for (const e of items) {
      try {
        await api.libraryDelete(e.kind, e.id);
        moved.push(entryKey(e));
      } catch (err) {
        refusals.push(`${named(e)}: ${errorMessage(err)}`);
      }
    }
    uncheck(moved);
    if (selected && moved.includes(entryKey(selected))) setSelected(null);
    setNotice(
      <>
        Moved {moved.length} to Recently deleted.
        {refusals.length > 0 && (
          <ul id="library-refusals">
            {refusals.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </>,
    );
    refresh();
  };

  const restore = async (entry: LibraryEntry) => {
    try {
      await api.libraryRestore(entry.kind, entry.id);
      uncheck([entryKey(entry)]);
      setSelected(null);
      setNotice(`Restored ${named(entry)}.`);
      refresh();
    } catch (e) {
      setNotice(<span className="error">{errorMessage(e)}</span>);
    }
  };

  // The one destructive act: always an explicit click, with a confirmation naming the count.
  const emptyTrash = async () => {
    const items = ticked.length ? ticked.map((e) => ({ kind: e.kind, id: e.id })) : null;
    let count = items?.length ?? 0;
    try {
      if (!items) count = (await api.library({ ...DEFAULT_FILTERS, deleted: true, limit: 1 })).total;
      if (count === 0) return;
      const what = items ? `the ${count} ticked deleted result${count === 1 ? '' : 's'}` : count === 1 ? 'the 1 deleted result' : `all ${count} deleted results`;
      if (!window.confirm(`Permanently erase ${what}? This cannot be undone.`)) return;
      const { erased } = await api.libraryEmpty(items);
      setChecked({});
      setSelected(null);
      setNotice(`Erased ${erased} for good.`);
      refresh();
    } catch (e) {
      setNotice(<span className="error">{errorMessage(e)}</span>);
    }
  };

  const tickForCompare = (entry: LibraryEntry) => setChecked((c) => ({ ...c, [entryKey(entry)]: entry }));

  const star = async (entry: LibraryEntry) => {
    try {
      await api.annotate(entry.kind, entry.id, { starred: !entry.starred }); // only the star: a label saved a moment ago stays
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="library-page" id="library-page">
      <div className="library-side">
        <div className="library-filters">
          <div className="legend">
            {LIBRARY_KINDS.map((kind) => {
              const on = filters.kinds.includes(kind);
              return (
                <button
                  key={kind}
                  type="button"
                  id={`library-kind-${kind}`}
                  className={'chip' + (on ? ' active' : '')}
                  aria-pressed={on}
                  onClick={() => setFilters((f) => ({ ...f, offset: 0, kinds: f.kinds.includes(kind) ? f.kinds.filter((k) => k !== kind) : [...f.kinds, kind] }))}
                >
                  {kindLabel(kind)} {page ? page.counts_by_kind[kind] ?? 0 : ''}
                </button>
              );
            })}
          </div>
          <div className="library-filter-row">
            <input id="library-search" type="search" placeholder="Search name, label, notes, strategy" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search the library" />
          </div>
          <div className="library-filter-row">
            <select id="library-symbol" aria-label="Symbol" value={filters.symbol} onChange={(e) => set({ symbol: e.target.value })}>
              <option value="">Any symbol</option>
              {(symbols ?? []).map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol}
                </option>
              ))}
            </select>
            <select id="library-timeframe" aria-label="Timeframe" value={filters.timeframe} onChange={(e) => set({ timeframe: e.target.value })}>
              <option value="">Any timeframe</option>
              {TIMEFRAMES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select id="library-strategy" aria-label="Strategy" value={filters.strategy} onChange={(e) => set({ strategy: e.target.value })}>
              <option value="">Any strategy</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="library-filter-row">
            <select id="library-decision" aria-label="Decision" value={filters.decision} onChange={(e) => set({ decision: e.target.value })}>
              <option value="">Any decision</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
              <option value="deferred">Deferred</option>
            </select>
            <select id="library-sort" aria-label="Sort" value={filters.sort} onChange={(e) => set({ sort: e.target.value as LibraryFilters['sort'] })}>
              <option value="created">Newest first</option>
              <option value="net_pnl">Net P&amp;L</option>
              <option value="mar">MAR</option>
            </select>
            <label className="muted small">
              <input id="library-starred" type="checkbox" checked={filters.starred} onChange={(e) => set({ starred: e.target.checked })} /> Starred
            </label>
            <label className="muted small">
              <input
                id="library-deleted"
                type="checkbox"
                checked={filters.deleted}
                onChange={(e) => {
                  setChecked({});
                  setSelected(null);
                  setComparing(null);
                  setNotice(null);
                  set({ deleted: e.target.checked });
                }}
              />{' '}
              Recently deleted
            </label>
          </div>
        </div>
        <div className="library-summary small muted">
          {page ? `${page.total.toLocaleString()} ${filters.deleted ? 'deleted' : 'saved'} result${page.total === 1 ? '' : 's'}` : 'Loading…'}
          {page && page.preparing > 0 && (
            <span id="library-preparing" className="badge" title="Headline numbers are being computed once for older results">
              preparing {page.preparing}
            </span>
          )}
          <span className="library-toolbar">
            {filters.deleted ? (
              <button type="button" className="btn" id="library-empty" disabled={!page || page.total === 0} onClick={emptyTrash} title={ticked.length ? 'Erase the ticked deleted results for good' : 'Erase every deleted result for good'}>
                {ticked.length ? `Empty ${ticked.length} ticked` : 'Empty'}
              </button>
            ) : (
              <>
                <button type="button" className="btn" id="library-delete-selected" disabled={ticked.length === 0} onClick={removeSelected} title="Move the ticked results to Recently deleted">
                  Delete selected
                </button>
                <button
                  type="button"
                  className="btn"
                  id="library-compare"
                  disabled={!compare.ok}
                  title={compare.ok ? 'Compare the two ticked backtests' : compare.reason}
                  onClick={() => compare.ok && setComparing([ticked[0].id, ticked[1].id])}
                >
                  Compare
                </button>
              </>
            )}
          </span>
        </div>
        {error && <div className="error">{error}</div>}
        {notice && (
          <div className="notice library-notice" id="library-notice" role="status">
            {notice}
            <button type="button" className="btn btn-ghost" aria-label="Dismiss" onClick={() => setNotice(null)}>
              ✕
            </button>
          </div>
        )}
        {page && entries.length === 0 && <div className="empty-state">{filters.deleted ? 'Nothing was deleted recently.' : 'No saved results match these filters.'}</div>}
        <LibraryList
          entries={entries}
          selected={selected ? entryKey(selected) : null}
          checked={checked}
          onSelect={(e) => setSelected({ kind: e.kind, id: e.id })}
          onCheck={(e, on) =>
            setChecked((c) => {
              const next = { ...c };
              if (on) next[entryKey(e)] = e;
              else delete next[entryKey(e)];
              return next;
            })
          }
          onStar={star}
        />
        {page && page.total > LIMIT && (
          <div className="library-pager small muted">
            <button type="button" className="btn" disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - LIMIT) }))}>
              ‹ Newer
            </button>
            <span>
              {filters.offset + 1}–{Math.min(filters.offset + LIMIT, page.total)} of {page.total}
            </span>
            <button type="button" className="btn" disabled={filters.offset + LIMIT >= page.total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + LIMIT }))}>
              Older ›
            </button>
          </div>
        )}
      </div>
      <div className="library-view" id="library-view">
        {comparing ? (
          <LibraryCompare a={comparing[0]} b={comparing[1]} onClose={() => setComparing(null)} />
        ) : (
          <>
            {!selected && <div className="empty-state">Select a saved result to open it read-only. Tick two backtests to compare them.</div>}
            {selected && !current && (missing ? <div className="empty-state">{kindLabel(selected.kind)} {selected.id} is no longer saved.</div> : <div className="empty-state">Opening…</div>)}
            {current && <EntryView key={entryKey(current)} entry={current} onChanged={refresh} onRemove={remove} onRestore={restore} onCompareWith={tickForCompare} />}
          </>
        )}
      </div>
    </div>
  );
}

interface EntryActions {
  onChanged: () => void;
  onRemove: (entry: LibraryEntry) => void;
  onRestore: (entry: LibraryEntry) => void;
  onCompareWith: (entry: LibraryEntry) => void;
}

function EntryView({ entry, onChanged, onRemove, onRestore, onCompareWith }: { entry: LibraryEntry } & EntryActions) {
  if (entry.deleted_at) return <DeletedView entry={entry} onRestore={onRestore} />;
  const keep = <Housekeeping entry={entry} onChanged={onChanged} onRemove={onRemove} />;
  switch (entry.kind) {
    case 'backtest':
      return (
        <LibraryBacktestView
          entry={entry}
          housekeeping={keep}
          actions={
            <button type="button" className="btn" id="library-compare-with" onClick={() => onCompareWith(entry)} title="Tick this backtest; tick a second one, then Compare">
              Compare with…
            </button>
          }
        />
      );
    case 'optimization':
      return <LibraryOptimizationView entry={entry} housekeeping={keep} />;
    case 'walkforward':
      return <LibraryWalkForwardView entry={entry} housekeeping={keep} />;
    default:
      return <LibraryDocumentView entry={entry} housekeeping={keep} />;
  }
}

/** Label, notes and Delete for the open item (spec §6). The star lives on the row. */
function Housekeeping({ entry, onChanged, onRemove }: { entry: LibraryEntry; onChanged: () => void; onRemove: (entry: LibraryEntry) => void }) {
  const [label, setLabel] = useState(entry.label);
  const [notes, setNotes] = useState(entry.notes);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setLabel(entry.label);
    setNotes(entry.notes);
  }, [entry.label, entry.notes]);
  const dirty = label !== entry.label || notes !== entry.notes;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.annotate(entry.kind, entry.id, { label: label.trim(), notes });
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="library-housekeeping">
      <input id="library-label" aria-label="Label" maxLength={LABEL_MAX} placeholder="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
      <textarea id="library-notes" aria-label="Notes" maxLength={NOTES_MAX} rows={2} placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div className="library-actions">
        <button type="button" className="btn" id="library-save-annotation" disabled={!dirty || busy} onClick={save}>
          Save label and notes
        </button>
        <button type="button" className="btn" id="library-delete" disabled={busy} onClick={() => onRemove(entry)} title="Move it to Recently deleted">
          Delete
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function ViewHead({ entry, children }: { entry: LibraryEntry; children?: ReactNode }) {
  return (
    <div className="library-view-head">
      <div>
        <div className="panel-title">
          <span>
            {entry.starred ? '★ ' : ''}
            {entry.label || entry.name}
          </span>
        </div>
        <div className="small muted">
          {kindLabel(entry.kind)} · {entry.symbols.join(', ') || DASH} · {entry.timeframe ?? DASH} · {entry.start ?? DASH} → {entry.end ?? DASH} · strategy {entry.strategy_name ?? DASH} · saved {timeLabel(entry.created_at)}
        </div>
        <div className={'small' + (losing(entry) ? ' red' : '')}>{headlineText(entry)}</div>
      </div>
      <div className="library-actions">{children}</div>
    </div>
  );
}

function DeletedView({ entry, onRestore }: { entry: LibraryEntry; onRestore: (entry: LibraryEntry) => void }) {
  return (
    <div className="library-doc">
      <ViewHead entry={entry}>
        <button type="button" className="btn btn-primary" id="library-restore" onClick={() => onRestore(entry)}>
          Restore
        </button>
      </ViewHead>
      <div className="notice warn">Deleted {timeLabel(entry.deleted_at)}. It stays in Recently deleted until it is restored or the trash is emptied.</div>
    </div>
  );
}

/** Confirm before a Load replaces unsaved strategy edits. */
function useLoad() {
  const state = useWorkspace();
  return (what: string) => !unsavedEdits(state) || window.confirm(`Load ${what} into the workspace? Unsaved strategy edits will be replaced.`);
}

function LibraryOptimizationView({ entry, housekeeping }: { entry: LibraryEntry; housekeeping: ReactNode }) {
  const { selection } = useWorkspace();
  const dispatch = useDispatch();
  const confirmLoad = useLoad();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<Cell | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .job(entry.id)
      .then((j) => !cancelled && setJob(j))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [entry.id]);
  if (error) return <div className="error">{error}</div>;
  if (!job) return <div className="empty-state">Loading the optimization…</div>;
  const side: Side = job.side;
  const load = () => {
    if (!pick || !confirmLoad('this cell')) return;
    const configs = { long: side === 'long' ? pick.params : null, short: side === 'short' ? pick.params : null };
    dispatch({ type: 'SET_STRATEGY', strategy: applyConfigs(job.strategy, configs, { enablePicked: true }) });
    dispatch({ type: 'SET_SELECTION', selection: selectionFromData(job.data, selection) });
    dispatch({ type: 'SET_LINK_SIDES', linked: false });
    dispatch({ type: 'SET_PAGE', page: 'charts' });
  };
  return (
    <div className="library-job">
      <ViewHead entry={entry}>
        <span className="muted small">{pick ? `Picked ${describeParams(pick.params, job.strategy[side === 'long' ? 'long_side' : 'short_side'])}` : 'Pick a cell in the matrix or the table'}</span>
        <button type="button" className="btn btn-primary" id="library-load" disabled={!pick} onClick={load} title="Write the picked cell into this optimization's strategy and load it with its data">
          Load the picked cell into the workspace
        </button>
      </ViewHead>
      {housekeeping}
      <div className="library-job-body opt-tab">
        <OptimizationJobView side={side} job={job} selected={pick?.params ?? null} onPick={(cell) => setPick((p) => (p && JSON.stringify(p.params) === JSON.stringify(cell.params) ? null : cell))} library />
      </div>
    </div>
  );
}

function LibraryWalkForwardView({ entry, housekeeping }: { entry: LibraryEntry; housekeeping: ReactNode }) {
  const [job, setJob] = useState<WalkForwardStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .walkforwardJob(entry.id)
      .then((j) => !cancelled && setJob(j))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [entry.id]);
  if (error) return <div className="error">{error}</div>;
  if (!job) return <div className="empty-state">Loading the walk-forward…</div>;
  return (
    <div className="library-job">
      <ViewHead entry={entry} />
      {housekeeping}
      <div className="library-job-body">
        <WalkForwardJobView side={job.side} job={job} library />
      </div>
    </div>
  );
}

/** Experiments and studies keep their report views on the Experiments page (spec §5.4). */
function LibraryDocumentView({ entry, housekeeping }: { entry: LibraryEntry; housekeeping: ReactNode }) {
  const dispatch = useDispatch();
  const experimentId = entry.kind === 'experiment' ? entry.id : typeof entry.links.experiment_id === 'string' ? entry.links.experiment_id : null;
  const open = () => {
    if (!experimentId) return;
    dispatch({ type: 'SET_PAGE', page: 'experiments', focus: entry.kind === 'study' ? { experimentId, studyId: entry.id } : { experimentId } });
  };
  return (
    <div className="library-doc">
      <ViewHead entry={entry}>
        <button type="button" className="btn btn-primary" id="library-open" disabled={!experimentId} onClick={open} title="Open its report on the Experiments page">
          Open on the Experiments page
        </button>
      </ViewHead>
      {housekeeping}
    </div>
  );
}
