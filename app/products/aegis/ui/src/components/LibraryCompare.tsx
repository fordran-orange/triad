import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import { curvePaths, diffText, METRIC_NAMES, type CurveUnit } from '../compare';
import { DASH, money, num, pct, shortHash, timeLabel } from '../format';
import { markText, objectiveValue } from '../library';
import type { CompareIdentity, CompareResult, CompareSideTrades } from '../results';

type Scope = 'combined' | 'long' | 'short';
const SCOPES: Scope[] = ['combined', 'long', 'short'];
// Red is reserved for losing money (operator, 2026-10-19): a negative P&L or return in A or B.
const LOSS_METRICS = new Set(['net_pnl', 'net_return', 'cagr', 'expectancy']);
const COLOR = { a: '#2da7ff', b: '#f5a524' }; // the two runs; neither is red nor green
const WIDTH = 1000;
const HEIGHT = 220;
const DD_HEIGHT = 70;

const loss = (metric: string, v: number | null) => LOSS_METRICS.has(metric) && v !== null && v < 0;
const hours = (h: number | null) => (h === null ? DASH : h < 48 ? `${num(h, 1)} h` : `${num(h / 24, 1)} d`);

function Identity({ which, id, assumed }: { which: 'A' | 'B'; id: CompareIdentity; assumed: boolean }) {
  return (
    <div className="compare-identity">
      <div>
        <b style={{ color: which === 'A' ? COLOR.a : COLOR.b }}>{which}</b> <b>{id.label || id.strategy_name || id.run_id.slice(0, 8)}</b>
      </div>
      <div className="small muted">
        {id.symbol ?? DASH} · {id.timeframe ?? DASH} · {id.start ?? DASH} → {id.end ?? DASH}
      </div>
      <div className="small muted">
        strategy {id.strategy_name ?? DASH} ({shortHash(id.strategy_hash)}) · result {shortHash(id.result_hash)} · data {shortHash(id.data_hash)}
      </div>
      <div className="small muted">
        capital {money(id.initial_capital)}
        {assumed ? ' (assumed: saved before settings were recorded)' : ''} · saved {timeLabel(id.created_at)}
      </div>
    </div>
  );
}

function TradesRow({ label, t }: { label: string; t: CompareSideTrades }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{num(t.count, 0)}</td>
      <td className={t.avg_net !== null && t.avg_net < 0 ? 'red' : ''}>{money(t.avg_net)}</td>
      <td>{pct(t.win_rate)}</td>
      <td>{hours(t.avg_hold_hours)}</td>
      <td>{hours(t.max_hold_hours)}</td>
    </tr>
  );
}

/** Two saved backtests side by side (spec §7): identity and notes, strategy differences, metrics
 *  with direction marks, both equity curves on one calendar axis, and trade summaries. */
export function LibraryCompare({ a, b, onClose }: { a: string; b: string; onClose: () => void }) {
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>('combined');
  const [unit, setUnit] = useState<Exclude<CurveUnit, 'dd'>>('pct');

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError(null);
    api
      .libraryCompare(a, b)
      .then((r) => !cancelled && setResult(r))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [a, b]);

  const head = (
    <div className="library-view-head">
      <div className="panel-title">Compare two backtests</div>
      <button type="button" className="btn" id="compare-close" onClick={onClose}>
        Close
      </button>
    </div>
  );
  if (error)
    return (
      <div id="library-compare-view">
        {head}
        <div className="error">{error}</div>
      </div>
    );
  if (!result)
    return (
      <div id="library-compare-view">
        {head}
        <div className="empty-state">Comparing…</div>
      </div>
    );

  const curves = curvePaths(result.equity, WIDTH, HEIGHT, unit);
  const dd = curvePaths(result.equity, WIDTH, DD_HEIGHT, 'dd');
  const fmt = (v: number) => (unit === 'pct' ? pct(v) : money(v));
  const zeroY = curves.range && unit === 'pct' && curves.range.max > curves.range.min ? HEIGHT - ((0 - curves.range.min) / (curves.range.max - curves.range.min)) * HEIGHT : null;

  return (
    <div id="library-compare-view" className="library-compare">
      {head}
      <div className="compare-identities">
        <Identity which="A" id={result.identity.a} assumed={result.capital_assumed.a} />
        <Identity which="B" id={result.identity.b} assumed={result.capital_assumed.b} />
      </div>
      <div className="legend" id="compare-notes">
        {result.notes.map((n) => (
          <span key={n} className="badge">
            {n}
          </span>
        ))}
        {result.notes.length === 0 && <span className="muted small">different data and strategies</span>}
      </div>

      <div className="report-section" id="compare-differences">
        <div className="panel-title">Strategy differences</div>
        {result.differences.length === 0 ? (
          <div className="small muted">Same strategy and settings.</div>
        ) : (
          <table className="compare-table">
            <thead>
              <tr>
                <th>Path</th>
                <th>A</th>
                <th>B</th>
              </tr>
            </thead>
            <tbody>
              {result.differences.map((d) => (
                <tr key={d.path}>
                  <td>{d.path}</td>
                  <td>{JSON.stringify(d.a)}</td>
                  <td>{JSON.stringify(d.b)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="report-section">
        <div className="panel-title">
          Metrics
          <span className="legend" id="compare-scope">
            {SCOPES.map((s) => (
              <button key={s} type="button" className={'chip' + (scope === s ? ' active' : '')} aria-pressed={scope === s} onClick={() => setScope(s)}>
                {s}
              </button>
            ))}
          </span>
        </div>
        <table className="compare-table" id={`compare-metrics-${scope}`}>
          <thead>
            <tr>
              <th>Metric</th>
              <th>A</th>
              <th>B</th>
              <th>B − A</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {result.metrics[scope].map((r) => (
              <tr key={r.metric}>
                <td>{METRIC_NAMES[r.metric] ?? r.metric}</td>
                <td className={loss(r.metric, r.a) ? 'red' : ''}>{objectiveValue(r.metric, r.a)}</td>
                <td className={loss(r.metric, r.b) ? 'red' : ''}>{objectiveValue(r.metric, r.b)}</td>
                <td>{diffText(r)}</td>
                <td className="muted">{markText(r.mark)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="report-section">
        <div className="panel-title">
          Combined equity and drawdown
          <span className="legend" id="compare-unit">
            <button type="button" className={'chip' + (unit === 'pct' ? ' active' : '')} aria-pressed={unit === 'pct'} onClick={() => setUnit('pct')}>
              % return
            </button>
            <button type="button" className={'chip' + (unit === 'usd' ? ' active' : '')} aria-pressed={unit === 'usd'} onClick={() => setUnit('usd')}>
              $ equity
            </button>
          </span>
        </div>
        {curves.domain && curves.range ? (
          <div id="compare-chart">
            <div className="legend small">
              <span style={{ color: COLOR.a }}>━ A</span>
              <span style={{ color: COLOR.b }}>━ B</span>
              <span className="muted">
                {fmt(curves.range.min)} … {fmt(curves.range.max)}
              </span>
            </div>
            <svg className="compare-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label="Both runs' combined equity on one calendar axis">
              {zeroY !== null && <line x1={0} x2={WIDTH} y1={zeroY} y2={zeroY} stroke="#2a3d50" strokeDasharray="4 4" />}
              <path d={curves.a} fill="none" stroke={COLOR.a} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
              <path d={curves.b} fill="none" stroke={COLOR.b} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            </svg>
            <div className="small muted">Drawdown {dd.range ? `(deepest ${pct(-dd.range.min)})` : ''}</div>
            <svg className="compare-svg dd" viewBox={`0 0 ${WIDTH} ${DD_HEIGHT}`} preserveAspectRatio="none" role="img" aria-label="Both runs' drawdown">
              <path d={dd.a} fill="none" stroke={COLOR.a} strokeWidth={1} vectorEffect="non-scaling-stroke" />
              <path d={dd.b} fill="none" stroke={COLOR.b} strokeWidth={1} vectorEffect="non-scaling-stroke" />
            </svg>
            <div className="legend small muted compare-axis">
              <span>{new Date(curves.domain.start).toISOString().slice(0, 10)}</span>
              <span>{new Date(curves.domain.end).toISOString().slice(0, 10)}</span>
            </div>
          </div>
        ) : (
          <div className="empty-state">Neither run has an equity path.</div>
        )}
      </div>

      <div className="report-section" id="compare-trades">
        <div className="panel-title">Trades</div>
        <table className="compare-table">
          <thead>
            <tr>
              <th />
              <th>Count</th>
              <th>Avg net P&amp;L</th>
              <th>Win rate</th>
              <th>Avg hold</th>
              <th>Longest hold</th>
            </tr>
          </thead>
          <tbody>
            <TradesRow label="A · long" t={result.trades.a.long} />
            <TradesRow label="B · long" t={result.trades.b.long} />
            <TradesRow label="A · short" t={result.trades.a.short} />
            <TradesRow label="B · short" t={result.trades.b.short} />
          </tbody>
        </table>
      </div>
    </div>
  );
}
