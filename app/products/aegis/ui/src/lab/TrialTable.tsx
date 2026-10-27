import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MutableRefObject, type ReactElement } from 'react';
import { api, errorMessage } from '../api/client';
import { DASH } from '../format';
import type { CellsPage } from '../results';
import { lossTone, objectiveText } from './LabKpiStrip';
import { useLab, useLabDispatch } from './labState';
import type { PinSlot } from './labStore';
import { LinkedChip } from './LinkedChip';
import { pageFor, ROW_HEIGHT, windowRows } from './trialWindow';
import { jobPaths, type LoadedSource, type OptJob, type TrialRow } from './useLabSource';

/** The table's order: a column and a direction, or `column: null` for the metric in view, best first. */
export interface TrialSort {
  column: string | null;
  descending: boolean;
}

/** Where the table was scrolled, kept by the page so a trip through another view comes back to the same rows. */
export type ScrollMemory = MutableRefObject<{ key: string; top: number }>;

interface Column {
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
/** `exp:<id>#94` → `cell 94`; `opt:<id>#3` → `#3`. */
export const trialShort = (id: string) => (id.startsWith('exp:') ? `cell ${id.slice(id.lastIndexOf('#') + 1)}` : id.slice(id.lastIndexOf('#')));

function expRow(experimentId: string, paths: string[], raw: CellsPage['rows'][number]): TrialRow {
  const params: Record<string, number | null> = {};
  for (const path of paths) params[path] = numberOrNull(raw[path]);
  const values: Record<string, number | null> = {};
  for (const [column, value] of Object.entries(raw)) if (/^(combined|long|short)\./.test(column)) values[column] = numberOrNull(value);
  return { id: `exp:${experimentId}#${raw.cell}`, label: `cell ${raw.cell}`, params, values, valid: raw.valid };
}

function optRows(job: OptJob): TrialRow[] {
  return job.cells.map((cell, i) => ({
    id: `opt:${job.job_id}#${i}`,
    label: `#${i}`,
    params: { ...cell.params },
    values: Object.fromEntries(Object.entries(cell.metrics).map(([k, v]) => [k, numberOrNull(v)])),
    valid: null,
  }));
}

/** Best first: lower is better only for max drawdown. */
const bestDescending = (metric: string) => metric !== 'max_drawdown';

/** The trials table: windowed rows (22 px, overscan 10), sortable, one click or arrow key selects a trial; the
 *  experiment's rows come a page at a time from the worker, a job's rows are the cells its status sent. */
export function TrialTable({
  loaded,
  tick,
  sort,
  onSort,
  onSelect,
  memory,
}: {
  loaded: LoadedSource;
  tick: number;
  sort: TrialSort;
  onSort: (sort: TrialSort) => void;
  onSelect: (row: TrialRow) => void;
  memory: ScrollMemory;
}) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const scroller = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLTableSectionElement>(null);
  const [view, setView] = useState({ top: 0, height: 0 });
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<{ key: string; tick: number; offset: number; rows: TrialRow[]; total: number } | null>(null);
  const seq = useRef(0);
  const pending = useRef<{ key: string; tick: number; offset: number; limit: number } | null>(null);
  const focusNext = useRef<number | null>(null);

  const scope = loaded.kind === 'opt' ? loaded.job.side : lab.filter.scope;
  const metric = lab.metric;
  const metricColumn = loaded.kind === 'exp' ? `${scope}.${metric}` : metric;
  const sortColumn = sort.column ?? metricColumn;
  const descending = sort.column === null ? bestDescending(metric) : sort.descending;
  const queryKey = `${loaded.kind}:${loaded.id}|${sortColumn}|${descending}`;

  const paths = loaded.kind === 'exp' ? loaded.document.surface.parameters.map((p) => p.path) : jobPaths(loaded.job);
  const columns: Column[] = [
    loaded.kind === 'exp' ? { key: 'cell', label: 'cell', title: 'the cell number in the experiment', kind: 'id' } : { key: 'index', label: '#', title: 'the cell’s place in the list the job sent', kind: 'id' },
    ...paths.map((path): Column => ({ key: path, label: shortPath(path), title: path, kind: 'param' })),
    { key: metricColumn, label: loaded.kind === 'exp' ? metricColumn : `${scope}.${metric}`, title: `${metric} for the ${scope === 'combined' ? 'combined sides' : `${scope} side`}`, kind: 'metric' },
    ...(loaded.kind === 'exp' ? [{ key: 'valid', label: 'valid', title: 'whether the cell is a valid parameter combination', kind: 'valid' } as Column] : []),
  ];

  // A job's rows live in its status: sorted here, no paging.
  const optSorted = useMemo(() => {
    if (loaded.kind !== 'opt') return null;
    const rows = optRows(loaded.job);
    const value = (row: TrialRow, index: number): number | null => (sortColumn === 'index' ? index : sortColumn in row.params ? row.params[sortColumn] : (row.values[sortColumn] ?? null));
    const indexed = rows.map((row, index) => ({ row, index, v: value(row, index) }));
    indexed.sort((a, b) => {
      if (a.v === null && b.v === null) return a.index - b.index;
      if (a.v === null) return 1; // nulls last whichever way
      if (b.v === null) return -1;
      const order = a.v < b.v ? -1 : a.v > b.v ? 1 : a.index - b.index;
      return descending ? -order : order;
    });
    return indexed.map((x) => x.row);
  }, [loaded, sortColumn, descending]);

  const progress = loaded.kind === 'exp' ? (loaded.document.progress as { cells_done?: unknown }) : null;
  const estimate = Math.max(1, numberOrNull(progress?.cells_done) ?? 1); // probes once; the response gives the total
  const total = optSorted ? optSorted.length : page ? page.total : estimate;
  const rendered = windowRows({ total, scrollTop: view.top, viewportHeight: view.height });
  const rowAt = (i: number): TrialRow | null => {
    if (optSorted) return optSorted[i] ?? null;
    if (page && page.key === queryKey && i >= page.offset && i < page.offset + page.rows.length) return page.rows[i - page.offset];
    return null;
  };

  const measure = () => {
    const el = scroller.current;
    if (!el) return;
    const top = el.scrollTop;
    setView({ top, height: Math.max(0, el.clientHeight - (head.current?.offsetHeight ?? 0)) });
    memory.current = { key: queryKey, top };
  };
  // Back from another view: the same rows in the same place; a new order starts at the top. (Idempotent for the
  // same key, so React's development double-run of effects does not undo the restore.)
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

  // The experiment's rows: fetch the page around the window when the cached page does not hold it.
  const experimentId = loaded.kind === 'exp' ? loaded.id : null;
  useEffect(() => {
    if (experimentId === null) return;
    const fresh = page !== null && page.key === queryKey && page.tick === tick;
    const end = Math.min(rendered.end, page?.total ?? rendered.end);
    if (fresh && rendered.start >= page.offset && end <= page.offset + page.rows.length) return;
    const p = pending.current;
    if (p && p.key === queryKey && p.tick === tick && rendered.start >= p.offset && rendered.end <= p.offset + p.limit) return;
    const request = pageFor(windowRows({ total, scrollTop: view.top, viewportHeight: view.height, overscan: FETCH_OVERSCAN }));
    if (request.limit === 0) return;
    const asked = { key: queryKey, tick, ...request };
    pending.current = asked;
    const mine = ++seq.current;
    api
      .experimentCells(experimentId, { offset: request.offset, limit: request.limit, sort: sortColumn, descending })
      .then((result) => {
        if (mine !== seq.current) return; // a newer request owns the table
        setPage({ key: asked.key, tick: asked.tick, offset: request.offset, rows: result.rows.map((raw) => expRow(experimentId, paths, raw)), total: result.total });
        setError(null);
      })
      .catch((e: unknown) => mine === seq.current && setError(errorMessage(e)))
      .finally(() => {
        if (pending.current === asked) pending.current = null;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [experimentId, queryKey, tick, rendered.start, rendered.end, total, page]);

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
      if (row) onSelect(row);
      focusNext.current = next;
      ensureVisible(next);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      const row = rowAt(i);
      if (row) onSelect(row);
    }
  };

  const clickHeader = (column: Column) => {
    if (column.key === sortColumn) onSort({ column: column.key, descending: !descending });
    else onSort({ column: column.key, descending: column.kind === 'metric' ? bestDescending(metric) : false });
  };

  const selectedIds = lab.selected && 'trials' in lab.selected ? lab.selected.trials : [];
  const single = selectedIds.length === 1 ? selectedIds[0] : null;
  const square = lab.selected !== null && 'square' in lab.selected;
  const filtersOff = Object.keys(lab.filter.ranges).length + Object.keys(lab.filter.values).length;
  const known = optSorted !== null || (page !== null && page.key === queryKey);
  const shown = loaded.kind === 'opt' ? (loaded.job.cells_shown ?? loaded.job.cells.length) : 0;
  const done = loaded.kind === 'opt' ? (loaded.job.cells_done ?? loaded.job.progress.done) : 0;

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
    const isSelected = selectedIds.includes(row.id);
    body.push(
      <tr
        key={row.id}
        data-trial={row.id}
        data-index={i}
        tabIndex={0}
        className={(isSelected ? 'selected' : '') + (row.valid === false ? ' muted' : '')}
        aria-selected={isSelected}
        onClick={() => onSelect(row)}
        onKeyDown={(e) => onRowKey(e, i)}
      >
        {columns.map((column) => {
          if (column.kind === 'id') return <td key={column.key}>{loaded.kind === 'exp' ? row.label.replace('cell ', '') : row.label.replace('#', '')}</td>;
          if (column.kind === 'param') return <td key={column.key}>{paramText(row.params[column.key] ?? null)}</td>;
          if (column.kind === 'valid') return <td key={column.key}>{row.valid === null ? DASH : row.valid ? 'yes' : 'no'}</td>;
          const value = row.values[column.key] ?? null;
          const tone = lossTone(metric, value);
          return (
            <td key={column.key} className={tone === 'loss' ? 'red' : tone === 'gain' ? 'green' : undefined} title={value === null ? 'no value: the cell was skipped or has no trades' : undefined}>
              {objectiveText(metric, value)}
            </td>
          );
        })}
      </tr>,
    );
  }

  return (
    <div className="lab-trials">
      <div className="trial-toolbar">
        <span className="lab-basis" title="every row is a tested trial; nothing here is estimated">
          Tested (exact)
        </span>
        <span className="muted">
          {loaded.kind === 'opt'
            ? shown < done
              ? `the best ${shown.toLocaleString('en-US')} of ${done.toLocaleString('en-US')} cells the job sent`
              : `${optSorted?.length.toLocaleString('en-US')} cells`
            : known
              ? `${total.toLocaleString('en-US')} trials`
              : 'loading trials…'}
        </span>
        <LinkedChip />
        {filtersOff > 0 && (
          <span className="muted" title="the experiment endpoints take no filter; the Phase 2 query layer applies it on the worker">
            ranges are recorded; the table lists every trial until Phase 2
          </span>
        )}
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
              {columns.map((column) => (
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
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="trial-pad-top" aria-hidden="true" style={{ height: rendered.padTop }}>
              <td colSpan={columns.length} />
            </tr>
            {known && total === 0 ? (
              <tr className="trial-empty">
                <td colSpan={columns.length} className="muted">
                  No trials yet{loaded.kind === 'exp' && loaded.document.status === 'running' ? ': the first chunk is still running' : ''}.
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
        {error && <div className="error trial-error">Trials unavailable: {error}</div>}
      </div>
    </div>
  );
}
