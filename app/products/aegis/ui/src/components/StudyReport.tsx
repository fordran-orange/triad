import { useState } from 'react';
import { api, errorMessage, type StudyCellsPage, type StudyStatus } from '../api/client';
import { paramsText } from '../experiments';
import { DASH, money, num, pct, shortHash, timeLabel } from '../format';
import { STUDY_RULES, type StudyReport, type StudyRule } from '../results';
import { equityPaths, flatShading, ruleRows, windowMarks } from '../studies';

const WIDTH = 640;
const HEIGHT = 180;
const COLOURS: Record<StudyRule, string> = { plateau: 'var(--green)', peak: 'var(--amber)', frozen: 'var(--blue)' };

/** The study's report (spec §7): the summary with its caveats, then per symbol the three rules,
 *  the chart, stability and the window table whose rows open the window's in-sample cells. */
export function StudyReportView({ study, report }: { study: StudyStatus; report: StudyReport }) {
  return (
    <div id="study-report" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="report-card" id="study-summary">
        <div className="panel-title">
          {report.summary} <span className="badge raw">{report.label}</span>
        </div>
        <div className="small muted" style={{ marginTop: 4 }}>
          {report.data_label} · objective {report.objective} · {report.caveats.join('; ')}
        </div>
        {report.frozen_absent && (
          <div className="small" id="study-frozen-absent" style={{ marginTop: 4 }}>
            Frozen centre: absent — {report.frozen_absent}.
          </div>
        )}
        <div className="small" style={{ marginTop: 4 }}>
          <a id="study-markdown" href={api.studyMarkdownUrl(study.id)} target="_blank" rel="noreferrer">
            Markdown
          </a>
        </div>
      </div>
      {Object.keys(report.symbols).map((symbol) => (
        <SymbolSection key={symbol} study={study} report={report} symbol={symbol} />
      ))}
    </div>
  );
}

function SymbolSection({ study, report, symbol }: { study: StudyStatus; report: StudyReport; symbol: string }) {
  const entry = report.symbols[symbol];
  const rows = ruleRows(report, symbol);
  const { paths, domain } = equityPaths(entry.curves, WIDTH, HEIGHT);
  const bands = flatShading(entry.window_rows, domain, WIDTH);
  const marks = windowMarks(entry.window_rows, domain, WIDTH);
  const [open, setOpen] = useState<number | null>(null);
  const stability = entry.stability;
  return (
    <div className="report-section" id={`study-symbol-${symbol}`}>
      <div className="panel-title">
        {symbol} <span className="small muted">{entry.flat_line} (plateau rule)</span>
      </div>
      <div className="small" style={{ margin: '4px 0 6px' }}>
        {entry.comparison}
      </div>
      <table className="exp-table small" id={`study-rules-${symbol}`}>
        <thead>
          <tr>
            <th>Rule</th>
            <th>Net P&amp;L</th>
            <th>Return</th>
            <th>CAGR</th>
            <th>Max drawdown</th>
            <th>MAR</th>
            <th>Trades</th>
            <th>Exposure</th>
            <th>Hash</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) =>
            row.absent ? (
              <tr key={row.rule}>
                <td>{row.label}</td>
                <td colSpan={8} className="muted">
                  absent — {row.absent}
                </td>
              </tr>
            ) : (
              <tr key={row.rule}>
                <td>
                  <span className="swatch" style={{ background: COLOURS[row.rule] }} /> {row.label}
                </td>
                <td>{row.cells.net_pnl}</td>
                <td>{row.cells.net_return}</td>
                <td>{row.cells.cagr}</td>
                <td>{row.cells.max_drawdown}</td>
                <td>{row.cells.mar}</td>
                <td>{row.cells.trades}</td>
                <td>{row.cells.exposure}</td>
                <td title={row.hash}>{shortHash(row.hash)}</td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      <svg className="study-chart" id={`study-chart-${symbol}`} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label={`${symbol} stitched out-of-sample equity by rule`}>
        {bands.map((band) => (
          <rect key={`flat-${band.index}`} className="study-flat" x={band.x0} y={0} width={Math.max(band.x1 - band.x0, 1)} height={HEIGHT}>
            <title>window {band.index}: plateau rule flat</title>
          </rect>
        ))}
        {marks.map((mark) => (
          <line key={`mark-${mark.index}`} className="study-mark" x1={mark.x} x2={mark.x} y1={0} y2={HEIGHT} />
        ))}
        {STUDY_RULES.map((rule) =>
          paths[rule] ? <path key={rule} d={paths[rule]} fill="none" stroke={COLOURS[rule]} strokeWidth={1.5} vectorEffect="non-scaling-stroke" /> : null,
        )}
      </svg>
      <div className="small muted" id={`study-stability-${symbol}`}>
        Plateau found in {pct(stability.plateau_share, 0)} of windows · centre inside the previous plateau in {pct(stability.centre_kept_share, 0)} · median move{' '}
        {num(stability.median_move, 2)}
        {Object.entries(stability.centre_path).map(([path, values]) => (
          <div key={path}>
            {path}: {values.map((v) => (v === null ? DASH : String(v))).join(' → ')}
          </div>
        ))}
      </div>
      <table className="exp-table small" id={`study-windows-${symbol}`}>
        <thead>
          <tr>
            <th>#</th>
            <th>Out of sample</th>
            <th>In-sample choice</th>
            <th>Plateau rule</th>
            <th>Peak rule</th>
            <th>Frozen</th>
            <th>Centre kept</th>
            <th>Moved</th>
          </tr>
        </thead>
        <tbody>
          {entry.window_rows.map((row) => (
            <WindowRow key={row.index} study={study} symbol={symbol} row={row} open={open === row.index} onToggle={() => setOpen(open === row.index ? null : row.index)} objective={report.objective} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WindowRow({
  study,
  symbol,
  row,
  open,
  onToggle,
  objective,
}: {
  study: StudyStatus;
  symbol: string;
  row: StudyReport['symbols'][string]['window_rows'][number];
  open: boolean;
  onToggle: () => void;
  objective: string;
}) {
  const [cells, setCells] = useState<StudyCellsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = () => {
    onToggle();
    if (!cells && !open) {
      api
        .studyWindowCells(study.id, symbol, row.index, { limit: 5000 })
        .then(setCells)
        .catch((e: unknown) => setError(errorMessage(e)));
    }
  };
  const nets = row.net_pnl ?? {};
  const paths = study.surface.parameters.map((p) => p.path);
  const key = `combined.${objective}`;
  const ranked = cells ? [...cells.rows].filter((r) => r.valid).sort((a, b) => Number(b[key] ?? -Infinity) - Number(a[key] ?? -Infinity)).slice(0, 20) : [];
  return (
    <>
      <tr id={`study-window-${symbol}-${row.index}`} className={(row.flat ? 'flat ' : '') + (open ? 'selected' : '')} onClick={toggle} style={{ cursor: 'pointer' }}>
        <td>{row.index}</td>
        <td>
          {timeLabel(row.oos_start)} → {timeLabel(row.oos_end)}
        </td>
        <td>{row.choice ?? DASH}</td>
        <td>{row.flat ? `flat · ${money(nets.plateau ?? null)}` : money(nets.plateau ?? null)}</td>
        <td>{money(nets.peak ?? null)}</td>
        <td>{'frozen' in nets ? money(nets.frozen ?? null) : DASH}</td>
        <td>{row.centre_inside === null || row.centre_inside === undefined ? DASH : row.centre_inside ? 'yes' : 'no'}</td>
        <td>{num(row.moved ?? null, 2)}</td>
      </tr>
      {open && (
        <tr id={`study-cells-${symbol}-${row.index}`}>
          <td colSpan={8}>
            {error && <div className="notice warn">{error}</div>}
            {!cells && !error && <span className="muted">loading the window's in-sample cells…</span>}
            {cells && (
              <div className="small">
                {cells.total} in-sample cells; the best 20 by {objective}
                {row.best ? ` (best single cell ${row.best.cell}: ${paramsText(row.best.params)})` : ''}:
                <table className="exp-table small">
                  <thead>
                    <tr>
                      <th>cell</th>
                      {paths.map((p) => (
                        <th key={p}>{p.split('.').slice(-2).join('.')}</th>
                      ))}
                      <th>{objective}</th>
                      <th>net P&amp;L</th>
                      <th>trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((r) => (
                      <tr key={String(r.cell)}>
                        <td>{String(r.cell)}</td>
                        {paths.map((p) => (
                          <td key={p}>{String(r[p])}</td>
                        ))}
                        <td>{num(r[key] as number | null, 3)}</td>
                        <td>{money(r['combined.net_pnl'] as number | null)}</td>
                        <td>{String(r['combined.trade_count'] ?? DASH)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

