import { useEffect, useMemo, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { cellsView, type CellRow } from '../experiments';
import { DASH, num, shortHash } from '../format';
import { OBJECTIVE_LABELS, OBJECTIVES, type ExperimentReport, type Objective } from '../results';

const PAGE = 50;
const MAX_TICKED = 8;
const COLORS = ['#2da7ff', '#39d98a', '#f5a524', '#c084fc', '#ff8fab', '#5eead4', '#fde047', '#fb923c'];

interface Props {
  experiment: ExperimentDocument;
  report: ExperimentReport | null;
  onUse: (cell: number, params: Record<string, number>) => void;
}

/** The cells, sortable and paged from the worker, filterable by plateau, with equity overlays
 *  for ticked cells and Materialize / Use per row. */
export function CellsTable({ experiment, report, onUse }: Props) {
  const paths = experiment.surface.parameters.map((p) => p.path);
  const objective = experiment.objective as Objective;
  const [sort, setSort] = useState<string>(`combined.${objective}`);
  const [descending, setDescending] = useState(true);
  const [plateau, setPlateau] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CellRow[]>([]);
  const [total, setTotal] = useState(0);
  const [ticked, setTicked] = useState<number[]>([]);
  const [curves, setCurves] = useState<Record<string, number[]>>({});
  const [materialized, setMaterialized] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  const plateauOf = useMemo(() => {
    const map = new Map<number, number>();
    for (const p of report?.plateaus ?? []) for (const cell of p.cells) map.set(cell, p.id);
    return map;
  }, [report]);
  const named = useMemo(() => new Set(report?.cells_named ?? []), [report]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const query = plateau === null ? { offset, limit: PAGE, sort, descending } : { offset: 0, limit: 5000, sort, descending };
    api
      .experimentCells(experiment.id, query)
      .then((page) => {
        if (cancelled) return;
        const withPlateau = page.rows.map((r) => ({ ...r, plateau: plateauOf.get(r.cell) ?? null })) as CellRow[];
        if (plateau === null) {
          setRows(withPlateau);
          setTotal(page.total);
        } else {
          const filtered = cellsView(withPlateau, { sort, descending, plateau });
          setTotal(filtered.length);
          setRows(filtered.slice(offset, offset + PAGE));
        }
      })
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [experiment.id, experiment.progress, offset, sort, descending, plateau, plateauOf]);

  useEffect(() => {
    if (ticked.length === 0) {
      setCurves({});
      return;
    }
    let cancelled = false;
    api
      .experimentCurves(experiment.id, ticked)
      .then((found) => !cancelled && setCurves(found))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [experiment.id, ticked]);

  const toggle = (cell: number) => setTicked((t) => (t.includes(cell) ? t.filter((c) => c !== cell) : t.length >= MAX_TICKED ? t : [...t, cell]));
  const materialize = async (cell: number) => {
    setError(null);
    try {
      const run = await api.materializeCell(experiment.id, cell);
      setMaterialized((m) => ({ ...m, [cell]: run.result_hash }));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const header = (column: string, label: string) => (
    <th
      key={column}
      onClick={() => {
        if (sort === column) setDescending((d) => !d);
        else {
          setSort(column);
          setDescending(true);
        }
        setOffset(0);
      }}
      title="Sort"
      style={{ cursor: 'pointer' }}
    >
      {label}
      {sort === column ? (descending ? ' ▼' : ' ▲') : ''}
    </th>
  );
  const shownMetrics: Objective[] = [objective, ...(['net_pnl', 'max_drawdown', 'trade_count', 'exposure'] as Objective[]).filter((m) => m !== objective)];
  const allCurves = Object.entries(curves);
  const values = allCurves.flatMap(([, c]) => c);
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 1;
  const spanY = hi - lo || 1;

  return (
    <div className="report-section" id="cells-table">
      <h4>
        Cells <span className="muted small">{total.toLocaleString()} shown of {Number((experiment.progress as { cells_done?: number }).cells_done ?? 0).toLocaleString()} run</span>
      </h4>
      <div className="row" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label>
          Plateau{' '}
          <select
            id="cells-plateau"
            value={plateau === null ? '' : String(plateau)}
            onChange={(e) => {
              setPlateau(e.target.value === '' ? null : Number(e.target.value));
              setOffset(0);
            }}
          >
            <option value="">all cells</option>
            {(report?.plateaus ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                plateau {p.id} ({p.size})
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
          ‹ prev
        </button>
        <span className="muted small">
          {total === 0 ? DASH : `${offset + 1}–${Math.min(offset + PAGE, total)}`}
        </span>
        <button type="button" className="btn" disabled={offset + PAGE >= total} onClick={() => setOffset((o) => o + PAGE)}>
          next ›
        </button>
        <span className="muted small">tick up to {MAX_TICKED} cells to overlay their equity</span>
      </div>
      {allCurves.length > 0 && (
        <svg viewBox="0 0 1000 160" preserveAspectRatio="none" style={{ width: '100%', height: 150 }} aria-label="equity overlays" id="cells-overlay">
          {allCurves.map(([cell, curve], i) => (
            <path
              key={cell}
              d={curve.map((v, k) => `${k === 0 ? 'M' : 'L'}${((k / (curve.length - 1)) * 1000).toFixed(1)} ${(160 - ((v - lo) / spanY) * 160).toFixed(1)}`).join(' ')}
              fill="none"
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      )}
      {allCurves.length > 0 && (
        <div className="legend small">
          {allCurves.map(([cell], i) => (
            <b key={cell} style={{ color: COLORS[i % COLORS.length] }}>
              cell {cell}
            </b>
          ))}
          <span className="muted">
            min {num(lo, 0)} · max {num(hi, 0)}
          </span>
        </div>
      )}
      {error && <div className="notice warn">{error}</div>}
      <div style={{ overflow: 'auto' }}>
        <table className="cells-table">
          <thead>
            <tr>
              <th />
              {header('cell', 'cell')}
              {paths.map((p) => header(p, p.split('.').slice(2).join('.')))}
              {shownMetrics.map((m) => header(`combined.${m}`, OBJECTIVE_LABELS[m]))}
              <th>long</th>
              <th>short</th>
              <th>plateau</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const params = Object.fromEntries(paths.map((p) => [p, Number(r[p])]));
              return (
                <tr key={r.cell} id={`cell-${r.cell}`} className={named.has(r.cell) ? 'named' : ''}>
                  <td>
                    <input type="checkbox" aria-label={`overlay cell ${r.cell}`} checked={ticked.includes(r.cell)} onChange={() => toggle(r.cell)} />
                  </td>
                  <td>{r.cell}</td>
                  {paths.map((p) => (
                    <td key={p}>{num(r[p] as number, 4)}</td>
                  ))}
                  {shownMetrics.map((m) => (
                    <td key={m}>{r.valid ? num(r[`combined.${m}`] as number | null, m === 'trade_count' ? 0 : 3) : <span className="muted">{String(r.skip_reason ?? 'skipped')}</span>}</td>
                  ))}
                  <td>{num(r['long.net_pnl'] as number | null, 0)}</td>
                  <td>{num(r['short.net_pnl'] as number | null, 0)}</td>
                  <td>{r.plateau ?? DASH}</td>
                  <td style={{ textAlign: 'left', whiteSpace: 'nowrap' }}>
                    <button type="button" className="btn small" id={`materialize-${r.cell}`} onClick={() => materialize(r.cell)} title="Rerun this cell as a full backtest and keep it under runs">
                      Materialize
                    </button>{' '}
                    <button type="button" className="btn small" id={`use-cell-${r.cell}`} onClick={() => onUse(r.cell, params)} title="Load these parameters into the workspace as unsaved edits">
                      Use
                    </button>
                    {materialized[r.cell] && <span className="muted small" title={materialized[r.cell]}> hash {shortHash(materialized[r.cell])}</span>}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8 + paths.length + shownMetrics.length} className="muted">
                  {DASH}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="muted small">Sorted by {sort}; {OBJECTIVES.length} metrics per scope are stored for every cell.</div>
    </div>
  );
}
