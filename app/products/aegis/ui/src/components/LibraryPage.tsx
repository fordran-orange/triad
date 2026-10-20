import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { api, errorMessage, type StrategySummary } from '../api/client';
import { DASH, timeLabel } from '../format';
import { comparable, headlineText, kindLabel } from '../library';
import { LIBRARY_KINDS, type Cell, type JobStatus, type LibraryEntry, type LibraryFilters, type LibraryKind, type LibraryPage as Page, type WalkForwardStatus } from '../results';
import { applyConfigs, selectionFromData, TIMEFRAMES, unsavedEdits, useDispatch, useWorkspace, type Side } from '../state/workspace';
import { LibraryBacktestView } from './LibraryBacktestView';
import { entryKey, LibraryList } from './LibraryList';
import { describeParams, OptimizationJobView } from './OptimizationTab';
import { WalkForwardJobView } from './WalkForwardTab';

const LIMIT = 50;
const DEFAULT_FILTERS: LibraryFilters = { kinds: [], symbol: '', timeframe: '', strategy: '', starred: false, decision: '', q: '', sort: 'created', offset: 0, limit: LIMIT, deleted: false };
const POLL_MS = 2000; // while the index is still preparing headlines
const SEARCH_MS = 300;

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
  const current = selected ? (entries.find((e) => e.kind === selected.kind && e.id === selected.id) ?? null) : null;
  const ticked = Object.values(checked);
  const compare = comparable(ticked);

  const star = async (entry: LibraryEntry) => {
    try {
      await api.annotate(entry.kind, entry.id, { label: entry.label, notes: entry.notes, starred: !entry.starred });
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
          <span style={{ marginLeft: 'auto' }}>
            <button type="button" className="btn" id="library-compare" disabled={!compare.ok} title={compare.ok ? 'Compare the two ticked backtests' : compare.reason}>
              Compare
            </button>
          </span>
        </div>
        {error && <div className="error">{error}</div>}
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
        {!selected && <div className="empty-state">Select a saved result to open it read-only. Tick two backtests to compare them.</div>}
        {selected && !current && page && <PendingEntry kind={selected.kind} id={selected.id} />}
        {current && <EntryView key={entryKey(current)} entry={current} />}
      </div>
    </div>
  );
}

/** A deep-linked item that the current filters or page do not list: fetch nothing; say so. */
function PendingEntry({ kind, id }: { kind: LibraryKind; id: string }) {
  if (kind === 'backtest') {
    const entry: LibraryEntry = { kind, id, name: 'Backtest', label: '', notes: '', starred: false, symbols: [], timeframe: null, start: null, end: null, strategy_id: null, strategy_name: null, created_at: null, status: null, decision: null, headline: {}, links: {} };
    return <LibraryBacktestView entry={entry} />;
  }
  return <div className="empty-state">{kindLabel(kind)} {id} is not on this page of the list.</div>;
}

function EntryView({ entry }: { entry: LibraryEntry }) {
  if (entry.deleted_at) return <DeletedView entry={entry} />;
  switch (entry.kind) {
    case 'backtest':
      return <LibraryBacktestView entry={entry} />;
    case 'optimization':
      return <LibraryOptimizationView entry={entry} />;
    case 'walkforward':
      return <LibraryWalkForwardView entry={entry} />;
    default:
      return <LibraryDocumentView entry={entry} />;
  }
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
        <div className="small">{headlineText(entry)}</div>
      </div>
      <div className="library-actions">{children}</div>
    </div>
  );
}

function DeletedView({ entry }: { entry: LibraryEntry }) {
  return (
    <div className="library-doc">
      <ViewHead entry={entry} />
      <div className="notice warn">Deleted {timeLabel(entry.deleted_at)}. It stays in Recently deleted until it is restored or the trash is emptied.</div>
    </div>
  );
}

/** Confirm before a Load replaces unsaved strategy edits. */
function useLoad() {
  const state = useWorkspace();
  return (what: string) => !unsavedEdits(state) || window.confirm(`Load ${what} into the workspace? Unsaved strategy edits will be replaced.`);
}

function LibraryOptimizationView({ entry }: { entry: LibraryEntry }) {
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
      <div className="library-job-body opt-tab">
        <OptimizationJobView side={side} job={job} selected={pick?.params ?? null} onPick={(cell) => setPick((p) => (p && JSON.stringify(p.params) === JSON.stringify(cell.params) ? null : cell))} library />
      </div>
    </div>
  );
}

function LibraryWalkForwardView({ entry }: { entry: LibraryEntry }) {
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
      <div className="library-job-body">
        <WalkForwardJobView side={job.side} job={job} library />
      </div>
    </div>
  );
}

/** Experiments and studies keep their report views on the Experiments page (spec §5.4). */
function LibraryDocumentView({ entry }: { entry: LibraryEntry }) {
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
      {entry.notes && <div className="small library-notes-text">{entry.notes}</div>}
    </div>
  );
}
