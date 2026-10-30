import { useEffect, useState, type ReactNode } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { recommendationText } from '../experiments';
import { DASH, money, num, pct, shortHash } from '../format';
import type { LabTrial } from '../results';
import { CandidateCard } from './CandidateCard';
import { metricsLine, squareAt } from './LabCenter';
import { valueText } from './labHeatmapModel';
import { lowN, SHARPE, SHARPE_LABEL } from './labQuery';
import { useLab } from './labState';
import { sourceText, type PinSlot } from './labStore';
import { lossTone } from './metricRules';
import { LabError } from './NotBuilt';
import type { LabQueryData } from './useLabQuery';
import { currentMatrix, type LoadedSource, type TrialRow } from './useLabSource';

const PINS: PinSlot[] = ['A', 'B', 'C'];
/** The card's metrics: the four Phase 1 ones, exposure, and the trade Sharpe last — never without net P&L, max
 *  drawdown, trade count and exposure beside it (§7.12). */
const CARD_METRICS = ['net_pnl', 'mar', 'max_drawdown', 'trade_count', 'exposure', 'sharpe_trade'] as const;
type CardMetric = (typeof CARD_METRICS)[number];
const CARD_LABELS: Record<CardMetric, string> = { net_pnl: 'Net P&L', mar: 'MAR', max_drawdown: 'Max DD', trade_count: 'Trades', exposure: 'Exposure', sharpe_trade: SHARPE_LABEL };
const cardValue = (metric: CardMetric, value: number | null) =>
  metric === 'net_pnl' ? money(value) : metric === 'max_drawdown' || metric === 'exposure' ? pct(value) : num(value, metric === 'trade_count' ? 0 : 2);

interface Provenance {
  source: string;
  id: string;
  strategy_hash: string | null;
  data: { symbol: string | null; timeframe: string | null; start: string | null; end: string | null; sha256?: string | null };
  engine: string | null;
  strategy_id?: string;
  report?: number | null;
}

/** What the provenance block shows and Copy JSON copies: the identity of the open source, nothing derived. */
function provenance(loaded: LoadedSource): Provenance {
  if (loaded.kind === 'exp') {
    const d = loaded.document;
    return {
      source: sourceText(loaded),
      id: d.id,
      strategy_id: d.strategy_id,
      strategy_hash: d.strategy_hash,
      data: { symbol: d.data.symbol, timeframe: d.data.timeframe, start: d.data.start, end: d.data.end },
      engine: d.engine ?? null,
      report: loaded.report?.report_id ?? null,
    };
  }
  const j = loaded.job;
  return {
    source: sourceText(loaded),
    id: j.job_id,
    strategy_hash: j.strategy_hash ?? null,
    data: { symbol: j.data.symbol ?? null, timeframe: j.data.timeframe ?? null, start: j.data.start ?? null, end: j.data.end ?? null, sha256: j.data.sha256 ?? null },
    engine: j.engine ?? null,
  };
}

/** The bars the source's trials ran on (an experiment's plan, a job's frame), for the trade frequency. */
function barsOf(loaded: LoadedSource | null): number | null {
  if (loaded === null) return null;
  const bars = loaded.kind === 'exp' ? loaded.document.plan.bars : loaded.job.bars;
  return typeof bars === 'number' && bars > 0 ? bars : null;
}

function TrialCard({ row, scope, bars, data }: { row: TrialRow; scope: string; bars: number | null; data: LabQueryData }) {
  // Every metric of the trial from the trial route (a table page carries only the columns it shows), for an
  // experiment's trial and a grid job's alike.
  const exp = row.id.startsWith('exp:');
  const [detail, setDetail] = useState<{ id: string; trial: LabTrial } | null>(null);
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const src = row.id.slice(0, row.id.lastIndexOf('#'));
    api
      .labTrial(src, row.id)
      .then((trial) => {
        if (cancelled) return;
        setDetail({ id: row.id, trial });
        setFailed(null);
      })
      .catch((e: unknown) => !cancelled && setFailed({ id: row.id, message: errorMessage(e) }));
    return () => {
      cancelled = true;
    };
  }, [row.id, retry]);
  const metrics = detail !== null && detail.id === row.id ? (detail.trial.metrics[scope as 'combined' | 'long' | 'short'] ?? null) : null;
  const valueOf = (m: CardMetric): number | null => {
    const v: unknown = metrics !== null ? metrics[m] : row.values[exp ? `${scope}.${m}` : m];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };
  const trades = valueOf('trade_count');
  const low = trades === null || lowN(trades);
  const perBars = trades !== null && bars !== null ? num((trades / bars) * 1000, 1) : DASH;
  return (
    <>
      <div className="rail-id mono">{row.id}</div>
      <dl className="rail-params">
        {Object.entries(row.params).map(([path, value]) => (
          <div key={path}>
            <dt title={path}>{path}</dt>
            <dd>{value === null ? DASH : value}</dd>
          </div>
        ))}
      </dl>
      <div className="rail-metrics">
        {CARD_METRICS.map((m) => {
          const value = valueOf(m);
          const tone = lossTone(m, value);
          if (m === SHARPE)
            return (
              <span key={m} className="rail-sharpe" title={value === null ? 'undefined: fewer than 2 trades, zero variance, or not computed for this source' : `${scope} ${SHARPE_LABEL}`}>
                {CARD_LABELS[m]} <b>{cardValue(m, value)}</b>
                {low && (
                  <span className="low-n" title={trades === null ? 'the trade count is not known' : `${trades} trades: fewer than the minimum for a trade Sharpe`}>
                    low n
                  </span>
                )}{' '}
                · {perBars} trades / 1,000 bars
              </span>
            );
          return (
            <span key={m} title={value === null ? 'no value for this trial' : `${scope} ${m}`}>
              {CARD_LABELS[m]} <b className={tone === 'loss' ? 'red' : tone === 'gain' ? 'green' : undefined}>{cardValue(m, value)}</b>
            </span>
          );
        })}
      </div>
      <div className="sub">annualized Sharpe: not computed</div>
      <div className="sub">metrics for {scope === 'combined' ? 'both sides together' : `the ${scope} side`}</div>
      {failed !== null && failed.id === row.id && <LabError message={`Trial detail unavailable: ${failed.message}`} onRetry={() => setRetry((n) => n + 1)} />}
      <CandidateCard data={data} trialId={row.id} />
    </>
  );
}

/** The right rail: deterministic findings, the (not yet built) AI block kept visibly apart, the selection, the
 *  pins, risk, the gate, provenance with Copy JSON, and the follow-up sweep. */
export function IntelligenceRail({ data, onRefined }: { data: LabQueryData; onRefined: (child: ExperimentDocument) => void }) {
  const lab = useLab();
  const { loaded, loading, knownRows } = data;
  const [busy, setBusy] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);
  const [copied, setCopied] = useState<'idle' | 'copied' | 'manual'>('idle');
  const key = lab.source ? sourceText(lab.source) : null;
  useEffect(() => {
    setCopied('idle');
    setRefineError(null);
  }, [key]);

  const report = loaded?.kind === 'exp' ? loaded.report : null;
  const scope = loaded?.kind === 'opt' ? loaded.job.side : lab.filter.scope;
  const prov = loaded ? provenance(loaded) : null;
  const json = prov ? JSON.stringify(prov, null, 2) : '';

  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(json);
      setCopied('copied');
    } catch {
      setCopied('manual'); // no clipboard here (an insecure origin, a denied permission): select the text instead
    }
  };

  const refineBlocked =
    loaded === null
      ? loading
        ? 'loading the source'
        : 'open an experiment first'
      : loaded.kind === 'opt'
        ? 'a grid job has no experiment to refine'
        : report === null
          ? 'no report yet: nothing to refine'
          : report.recommendation === null
            ? 'the latest report has no recommendation to refine around'
            : null;
  const refine = async () => {
    if (loaded?.kind !== 'exp') return;
    setBusy(true);
    setRefineError(null);
    try {
      onRefined(await api.refineExperiment(loaded.id));
    } catch (e) {
      setRefineError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const selected = lab.selected;
  let selection: ReactNode;
  if (selected === null) selection = <div className="muted">No trial selected: click a row in the trials table, or use the arrow keys there.</div>;
  else if ('trials' in selected) {
    const row = selected.trials.length === 1 ? knownRows[selected.trials[0]] : undefined;
    selection =
      selected.trials.length !== 1 ? (
        <div>{selected.trials.length.toLocaleString('en-US')} trials selected</div>
      ) : row ? (
        <TrialCard row={row} scope={scope} bars={barsOf(loaded)} data={data} />
      ) : (
        // A trial picked from a chart or a ranking, whose row the table has not handed over: its id and its four categories.
        <>
          <div className="rail-id mono">{selected.trials[0]}</div>
          <CandidateCard data={data} trialId={selected.trials[0]} />
        </>
      );
  } else if (loaded?.kind === 'exp') {
    // An experiment's square: its two values; the heatmap's square panel shows what it holds.
    const { axes, values } = selected.square;
    selection = (
      <>
        <div>
          Square: {axes[0]} = {valueText(values[0])} · {axes[1]} = {valueText(values[1])}
        </div>
        <div className="sub">a square is not a trial, so it cannot be pinned: the heatmap&apos;s square panel shows what it holds</div>
      </>
    );
  } else {
    const m = currentMatrix(data).matrix;
    const metric = data.optMetric;
    const { x, y } = selected.square;
    if (m === null || metric === null || m.rows[y] === undefined || m.cols[x] === undefined) selection = <div className="muted">A square of a matrix no longer in view.</div>;
    else {
      const at = squareAt(m, metric, y, x);
      selection = (
        <>
          <div>
            Square: {m.rows_path} = {m.rows[y]} · {m.cols_path} = {m.cols[x]}
          </div>
          <div className="sub">
            Aggregated from tested (n = {at.count}) · a square is not a trial, so it cannot be pinned
          </div>
          {at.best ? (
            <>
              <div className="rail-params mono">
                {Object.entries(at.best.params)
                  .map(([p, v]) => `${p} ${v}`)
                  .join(' · ')}
              </div>
              <div className="rail-metrics">best of the rest: {metricsLine(at.best.metrics)}</div>
            </>
          ) : (
            <div className="muted">no tested cell has a value here</div>
          )}
        </>
      );
    }
  }

  return (
    <aside className="lab-rail" id="lab-rail" aria-label="Intelligence">
      <section className="rail-block" id="lab-findings">
        <div className="rail-title">Findings{report ? ` · report ${report.report_id}, deterministic` : ''}</div>
        {loaded === null ? (
          <div className="muted">{loading ? 'Loading…' : 'No source open.'}</div>
        ) : loaded.kind === 'opt' ? (
          <div className="muted">no report: a grid job is not an experiment, so it has no findings report</div>
        ) : report === null ? (
          <div className="muted">no report yet</div>
        ) : (
          <>
            <p>{report.statement}</p>
            <p>{recommendationText(report)}</p>
          </>
        )}
      </section>
      <section className="rail-block rail-ai" id="lab-ai">
        AI explanations: Phase 8 · AI explains, it never decides
      </section>
      <section className="rail-block" id="lab-selected">
        <div className="rail-title">Selected</div>
        {selection}
      </section>
      <section className="rail-block" id="lab-pins">
        <div className="rail-title">Pinned</div>
        {PINS.map((slot) => (
          <div key={slot} className="rail-pin" data-slot={slot}>
            {slot}: <span className="mono">{lab.pins[slot] ?? 'none'}</span>
          </div>
        ))}
      </section>
      <section className="rail-block" id="lab-risk">
        <div className="rail-title">Risk warnings</div>
        <div className="muted">none computed in Phase 1</div>
      </section>
      <section className="rail-block" id="lab-gate" title="the Strategy Gate is not being built now (Q1): nothing here passes or fails a strategy">
        Strategy Gate: not built
      </section>
      <section className="rail-block" id="lab-provenance">
        <div className="rail-title">Provenance</div>
        {prov === null ? (
          <div className="muted">{loading ? 'Loading…' : 'No source open.'}</div>
        ) : (
          <>
            <dl className="rail-params">
              <div>
                <dt>id</dt>
                <dd className="mono">{prov.id}</dd>
              </div>
              <div>
                <dt>strategy_hash</dt>
                <dd className="mono" title={prov.strategy_hash ?? 'not recorded on this source'}>
                  {prov.strategy_hash === null ? DASH : shortHash(prov.strategy_hash)}
                </dd>
              </div>
              <div>
                <dt>data</dt>
                <dd>{[prov.data.symbol, prov.data.timeframe, prov.data.start, '→', prov.data.end].map((v) => v ?? DASH).join(' ')}</dd>
              </div>
              <div>
                <dt>engine</dt>
                <dd title={prov.engine === null ? 'not recorded on this source' : undefined}>{prov.engine ?? DASH}</dd>
              </div>
            </dl>
            <button type="button" className="btn" id="lab-copy-json" onClick={() => void copy()}>
              {copied === 'copied' ? 'Copied' : 'Copy JSON'}
            </button>
            {copied === 'manual' && (
              <>
                <div className="sub">The clipboard is not available here: select the text and copy it.</div>
                <textarea className="lab-copy-fallback" readOnly value={json} aria-label="Provenance JSON" ref={(el) => el?.select()} />
              </>
            )}
          </>
        )}
      </section>
      <div className="rail-action">
        {report?.recommendation && <div className="sub">Next sweep: around plateau {report.recommendation.plateau} (centre cell {report.recommendation.centre.cell}), one step wider each way.</div>}
        <button type="button" className="btn btn-green" id="lab-refine" disabled={busy || refineBlocked !== null} title={refineBlocked ?? 'a new experiment around the recommended plateau (POST /experiments/{id}/refine)'} onClick={() => void refine()}>
          {busy ? 'Queueing…' : 'Queue focused follow-up sweep'}
        </button>
        {refineError && <div className="error">Refine failed: {refineError}</div>}
      </div>
    </aside>
  );
}
