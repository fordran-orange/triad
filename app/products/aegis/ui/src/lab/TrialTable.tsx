import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type MutableRefObject, type ReactElement } from 'react';
import { errorMessage } from '../api/client';
import { DASH } from '../format';
import type { LabEnvelope, LabPage, LabRow } from '../results';
import { lossTone, objectiveText } from './LabKpiStrip';
import { defaultSort, emptyTableText, expRowFromLab, optPath, optRowFromLab, pageKey, panelLabel, SHARPE, SHARPE_TITLE, tableValueColumns, undefinedLast } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { sourceText, type PinSlot } from './labStore';
import { LinkedChip } from './LinkedChip';
import { LabError } from './NotBuilt';
import { pageFor, ROW_HEIGHT, windowRows } from './trialWindow';
import type { LabQueryData, Stamped } from './useLabQuery';
import { jobPaths, optMetric, type TrialRow } from './useLabSource';

/** The table's order: a column and a direction, or `column: null` for the metric in view, best first. */
export interface TrialSort {
  column: string | null;
  descending: boolean;
}

/** Where the table was scrolled, kept by the page so a trip through another view comes back to the same rows. */
export type ScrollMemory = MutableRefObject<{ key: string; top: number }>;

interface Column {
  /** As the worker names it: `trial_no`, a parameter path, `<scope>.<metric>`, or `valid` (not sortable). */
  key: string;
  label: string;
  title: string;
  kind: 'id' | 'param' | 'metric' | 'valid';
}

/** Rows fetched beyond the rendered window, so a scroll of a few rows needs no new request (the page stays ≤ 500). */
const FETCH_OVERSCAN = 100;
const PINS: PinSlot[] = ['A', 'B', 'C'];

const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const shortPath = (path: string) => path.replace('_side.indicators.', '.').replace('_side.', '.');
const paramText = (value: number | null) => (value === null ? DASH : Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6))));
/** `exp:<id>#94` → `trial 94`; `opt:<id>#3` → `#3`. */
export const trialShort = (id: string) => (id.startsWith('exp:') ? `trial ${id.slice(id.lastIndexOf('#') + 1)}` : id.slice(id.lastIndexOf('#')));

/** Best first: lower is better only for max drawdown. */
const bestDescending = (metric: string) => metric !== 'max_drawdown';
const metricOf = (column: string) => column.slice(column.indexOf('.') + 1);

/** The page the table holds: what it answers (the key and the refresh tick), its window of rows and the answer. */
type Page = { key: string; tick: number; offset: number; rows: LabRow[]; total: number; envelope: Stamped<LabEnvelope<LabPage>> };

/** The trials table: windowed rows (22 px, overscan 10), sortable, one click or arrow key selects a trial. The rows
 *  come a page at a time from the worker's `page` view of the linked filter, for an experiment and a grid job alike;
 *  every row is a tested trial. */
export function TrialTable({
  data,
  sort,
  onSort,
  onSelect,
  memory,
}: {
  data: LabQueryData;
  sort: TrialSort;
  onSort: (sort: TrialSort) => void;
  onSelect: (row: TrialRow) => void;
  memory: ScrollMemory;
}) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { tick, summary } = data;
  const loaded = data.loaded;
  const scroller = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLTableSectionElement>(null);
  const [view, setView] = useState({ top: 0, height: 0 });
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const seq = useRef(0);
  const pending = useRef<{ key: string; tick: number; retry: number; offset: number; limit: number } | null>(null);
  const focusNext = useRef<number | null>(null);

  const source = loaded ? sourceText(loaded) : '';
  const job = loaded?.kind === 'opt' ? loaded.job : null;
  const scope = job ? job.side : lab.filter.scope;
  const metric = job ? optMetric(job, lab.metric) : lab.metric;
  const objective = job ? job.objective : loaded?.kind === 'exp' ? loaded.document.objective : 'net_pnl';
  // The summary names the layout; while it loads, the experiment document's own `cells_layout` does.
  const layout = (summary?.layout ?? (loaded?.kind === 'exp' ? loaded.document.cells_layout : null)) === 2 ? 2 : 1;
  const fallback = defaultSort(scope, metric, objective); // never the trade Sharpe (§7.12)
  const sortColumn = sort.column ?? fallback.column;
  const descending = sort.column === null ? fallback.descending : sort.descending;
  const queryKey = pageKey(source, sortColumn, descending, lab.filter);

  const paths = loaded === null ? [] : loaded.kind === 'opt' ? jobPaths(loaded.job).map((path) => optPath(path, loaded.job.side)) : loaded.document.surface.parameters.map((p) => p.path);
  const metricColumn = `${scope}.${metric}`;
  const values = tableValueColumns(scope, objective, layout);
  const shownValues = values.includes(metricColumn) ? values : [metricColumn, ...values];
  const side = scope === 'combined' ? 'combined sides' : `${scope} side`;
  const columns: Column[] = [
    { key: 'trial_no', label: 'trial', title: 'the trial number in the source; every row is a tested trial', kind: 'id' },
    ...paths.map((path): Column => ({ key: path, label: shortPath(path), title: path, kind: 'param' })),
    ...shownValues.map(
      (column): Column => ({ key: column, label: column, title: metricOf(column) === SHARPE ? SHARPE_TITLE : `${metricOf(column)} for the ${side}`, kind: 'metric' }),
    ),
    ...(job ? [] : [{ key: 'valid', label: 'valid', title: 'whether the trial is a valid parameter combination', kind: 'valid' } as Column]),
  ];

  const progress = loaded?.kind === 'exp' ? (loaded.document.progress as { cells_done?: unknown }) : null;
  const estimate = Math.max(1, job ? (job.cells_done ?? job.progress.done) : (numberOrNull(progress?.cells_done) ?? 1)); // probes once; the response gives the total
  const current = page !== null && page.key === queryKey ? page : null;
  const total = page ? page.total : estimate;
  const rendered = windowRows({ total, scrollTop: view.top, viewportHeight: view.height });
  const rowAt = (i: number): LabRow | null => (current && i >= current.offset && i < current.offset + current.rows.length ? current.rows[i - current.offset] : null);
  /** The row as the selection card reads it: the page row itself, its own trial id, params and values (a grid
   *  job's status lists its best cells re-ordered, so `job.cells[trial_no]` would be another cell). */
  const trialRow = (row: LabRow): TrialRow => (job ? optRowFromLab(row, job.side) : expRowFromLab(row));
  const select = (row: LabRow) => onSelect(trialRow(row));

  const measure = () => {
    const el = scroller.current;
    if (!el) return;
    const top = el.scrollTop;
    setView({ top, height: Math.max(0, el.clientHeight - (head.current?.offsetHeight ?? 0)) });
    memory.current = { key: queryKey, top };
  };
  // Back from another view: the same rows in the same place; a new order or a new filter starts at the top.
  // (Idempotent for the same key, so React's development double-run of effects does not undo the restore.)
  const lastKey = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (lastKey.current === null) {
      if (memory.current.key === queryKey) el.scrollTop = memory.current.top;
    } else if (lastKey.current !== queryKey) el.scrollTop = 0;
    lastKey.current = queryKey;
    measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  // The rows: the page view of the linked filter around the window, when the cached page does not hold it.
  useEffect(() => {
    if (loaded === null) return;
    const fresh = page !== null && page.key === queryKey && page.tick === tick;
    const end = Math.min(rendered.end, page?.total ?? rendered.end);
    if (fresh && rendered.start >= page.offset && end <= page.offset + page.rows.length) return;
    const p = pending.current;
    if (p && p.key === queryKey && p.tick === tick && p.retry === retry && rendered.start >= p.offset && rendered.end <= p.offset + p.limit) return;
    // A refresh asks over at least the trials the source now reports done (at least one): a table that counted
    // none while the first chunk ran asks again on every tick instead of keeping its empty window.
    const request = pageFor(windowRows({ total: Math.max(total, estimate), scrollTop: view.top, viewportHeight: view.height, overscan: FETCH_OVERSCAN }));
    if (request.limit === 0) return;
    const asked = { key: queryKey, tick, retry, ...request };
    pending.current = asked;
    const mine = ++seq.current;
    data
      .query<LabPage>('page', { sort: sortColumn, descending, offset: request.offset, limit: request.limit })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer request owns the table, or the filter moved on
        // The worker lists undefined values last whichever the direction; the page is held to that.
        setPage({ key: asked.key, tick: asked.tick, offset: request.offset, rows: undefinedLast(envelope.rows, sortColumn, descending), total: envelope.total, envelope });
        setError(null);
      })
      .catch((e: unknown) => mine === seq.current && setError(errorMessage(e)))
      .finally(() => {
        if (pending.current === asked) pending.current = null;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, queryKey, tick, retry, rendered.start, rendered.end, total, page]);

  // Arrow keys move the focus with the selection; the focus lands once the row is drawn.
  useEffect(() => {
    if (focusNext.current === null) return;
    const el = scroller.current?.querySelector<HTMLElement>(`tr[data-index="${focusNext.current}"]`);
    if (el) {
      el.focus({ preventScroll: true });
      focusNext.current = null;
    }
  });
  const ensureVisible = (i: number) => {
    const el = scroller.current;
    if (!el) return;
    const viewport = el.clientHeight - (head.current?.offsetHeight ?? 0);
    const top = i * ROW_HEIGHT;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + ROW_HEIGHT > el.scrollTop + viewport) el.scrollTop = top + ROW_HEIGHT - viewport;
  };
  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, i: number) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      e.stopPropagation(); // the rows own the arrows; the heatmap cursor does not move
      const next = i + (e.key === 'ArrowDown' ? 1 : -1);
      if (next < 0 || next >= total) return;
      const row = rowAt(next);
      if (row) select(row);
      focusNext.current = next;
      ensureVisible(next);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      const row = rowAt(i);
      if (row) select(row);
    }
  };

  const clickHeader = (column: Column) => {
    if (column.kind === 'valid') return; // the worker does not sort by it
    if (column.key === sortColumn) onSort({ column: column.key, descending: !descending });
    else onSort({ column: column.key, descending: column.kind === 'metric' ? bestDescending(metricOf(column.key)) : false });
  };

  const selectedIds = lab.selected && 'trials' in lab.selected ? lab.selected.trials : [];
  const single = selectedIds.length === 1 ? selectedIds[0] : null;
  const square = lab.selected !== null && 'square' in lab.selected;
  const scopeCounts = current?.envelope.scope ?? null;

  const body: ReactElement[] = [];
  for (let i = rendered.start; i < rendered.end; i++) {
    const row = rowAt(i);
    if (row === null) {
      body.push(
        <tr key={`loading-${i}`} className="trial-loading" data-index={i} tabIndex={-1}>
          <td colSpan={columns.length} className="muted">
            loading…
          </td>
        </tr>,
      );
      continue;
    }
    const isSelected = selectedIds.includes(row.trial_id);
    body.push(
      <tr
        key={row.trial_id}
        data-trial={row.trial_id}
        data-index={i}
        tabIndex={0}
        className={(isSelected ? 'selected' : '') + (row.valid === false ? ' muted' : '')}
        aria-selected={isSelected}
        onClick={() => select(row)}
        onKeyDown={(e) => onRowKey(e, i)}
      >
        {columns.map((column) => {
          if (column.kind === 'id')
            return (
              <td key={column.key}>
                {row.trial_no}
                <span className="badge trial-tested" title="a tested trial: its values are the engine's own, nothing estimated">
                  Tested
                </span>
              </td>
            );
          if (column.kind === 'param') return <td key={column.key}>{paramText(numberOrNull(row.params[column.key]))}</td>;
          if (column.kind === 'valid') return <td key={column.key}>{row.valid === null ? DASH : row.valid ? 'yes' : 'no'}</td>;
          const name = metricOf(column.key);
          const value = numberOrNull(row.values[column.key]);
          const tone = lossTone(name, value);
          return (
            <td key={column.key} className={tone === 'loss' ? 'red' : tone === 'gain' ? 'green' : undefined} title={value === null ? `${name}: undefined for this trial (never ranked as zero)` : undefined}>
              {objectiveText(name, value)}
            </td>
          );
        })}
      </tr>,
    );
  }

  const emptyText =
    scopeCounts !== null && scopeCounts.completed > 0
      ? emptyTableText(scopeCounts.completed, lab.filter)
      : `No trials yet${loaded?.kind === 'exp' && loaded.document.status === 'running' ? ': the first chunk is still running' : ''}.`;

  return (
    <div className="lab-trials">
      <div className="trial-toolbar">
        {scopeCounts === null ? (
          <span className="muted">loading trials…</span>
        ) : (
          <span className="muted trial-count" data-filtered={scopeCounts.filtered} data-completed={scopeCounts.completed} title="the trials the linked filter keeps, of the completed trials">
            {scopeCounts.filtered.toLocaleString('en-US')} of {scopeCounts.completed.toLocaleString('en-US')} trials
          </span>
        )}
        <span className="lab-basis" title="every row is a tested trial; nothing here is estimated">
          · Tested (exact)
          {panelLabel(current?.envelope ?? null)}
        </span>
        <LinkedChip />
        <span className="trial-pins">
          {PINS.map((slot) => {
            const held = lab.pins[slot];
            const unpin = held !== undefined && (single === null || single === held);
            const disabled = !unpin && single === null;
            const title = unpin
              ? `unpin ${held}`
              : disabled
                ? square
                  ? 'a square is not a trial: select one trial to pin it'
                  : `select one trial to pin it (or press ${PINS.indexOf(slot) + 1})`
                : held
                  ? `replace ${held} with ${single}`
                  : `pin ${single} as ${slot}`;
            return (
              <button
                type="button"
                key={slot}
                id={`lab-pin-${slot}`}
                className={'chip' + (held ? ' active' : '')}
                data-pinned={held ?? ''}
                disabled={disabled}
                title={title}
                onClick={() => (unpin ? dispatch({ type: 'UNPIN', slot }) : single !== null && dispatch({ type: 'PIN', slot, trialId: single }))}
              >
                {held ? `${slot} · ${trialShort(held)}` : `Pin ${slot}`}
              </button>
            );
          })}
          <button type="button" className="chip" id="lab-compare-pinned" disabled title="Candidate Compare arrives in Phase 5 (plan §11)">
            Compare pinned
          </button>
        </span>
      </div>
      <div className="trial-table" id="trial-table" ref={scroller} onScroll={measure}>
        <table>
          <thead ref={head}>
            <tr>
              {columns.map((column) =>
                column.kind === 'valid' ? (
                  <th key={column.key} title={column.title} aria-sort="none">
                    {column.label}
                  </th>
                ) : (
                  <th
                    key={column.key}
                    data-sort={column.key}
                    title={column.title}
                    aria-sort={column.key === sortColumn ? (descending ? 'descending' : 'ascending') : 'none'}
                    onClick={() => clickHeader(column)}
                  >
                    <button type="button" className="sort-button">
                      {column.label}
                      {column.key === sortColumn ? (descending ? ' ↓' : ' ↑') : ''}
                    </button>
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            <tr className="trial-pad-top" aria-hidden="true" style={{ height: rendered.padTop }}>
              <td colSpan={columns.length} />
            </tr>
            {current !== null && current.total === 0 ? (
              <tr className="trial-empty">
                <td colSpan={columns.length} className="muted">
                  {emptyText}
                </td>
              </tr>
            ) : (
              body
            )}
            <tr className="trial-pad-bottom" aria-hidden="true" style={{ height: rendered.padBottom }}>
              <td colSpan={columns.length} />
            </tr>
          </tbody>
        </table>
        {error && <LabError message={`Trials unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      </div>
    </div>
  );
}
