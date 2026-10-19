import { useEffect, useState } from 'react';
import { api, errorMessage, type StudyBody } from '../api/client';
import type { ExperimentDocument, StudyPlan } from '../contracts';
import { leverLabel } from '../experiments';
import { planLine } from '../studies';

const DEFAULT_SYMBOLS = ['QQQ', 'SPY', 'ITOT'];

interface Props {
  experiment: ExperimentDocument;
  onClose: () => void;
  onCreated: (studyId: string) => void;
}

/** The study planner (Mission 8 spec §8): symbols, range, window lengths and the live plan line.
 *  The definition is the experiment's; a lever means a new experiment (plan ruling P15). */
export function StudyPlanner({ experiment, onClose, onCreated }: Props) {
  const bars = Number((experiment.plan as { bars?: number }).bars ?? 0);
  const [available, setAvailable] = useState<string[] | null>(null);
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [inSample, setInSample] = useState(bars);
  const [outOfSample, setOutOfSample] = useState(Math.floor(bars / 4));
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .symbols()
      .then((response) => {
        const names = response.symbols.map((s) => s.symbol);
        setAvailable(names);
        setSymbols((current) => {
          const kept = current.filter((s) => names.includes(s));
          return kept.length ? kept : names.slice(0, 1);
        });
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  const body: StudyBody = {
    experiment_id: experiment.id,
    symbols,
    start: start || null,
    end: end || null,
    in_sample_bars: inSample || null,
    out_of_sample_bars: outOfSample || null,
  };
  const key = JSON.stringify(body);
  useEffect(() => {
    if (available === null) return;
    if (symbols.length === 0) {
      setPlan(null);
      setError('choose at least one symbol');
      return;
    }
    const timer = setTimeout(() => {
      api
        .studyPlan(JSON.parse(key) as StudyBody)
        .then((p) => {
          setPlan(p);
          setError(null);
        })
        .catch((e: unknown) => {
          setPlan(null);
          setError(errorMessage(e));
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [key, available, symbols.length]);

  const toggle = (symbol: string) => setSymbols((current) => (current.includes(symbol) ? current.filter((s) => s !== symbol) : [...current, symbol]));
  const startStudy = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated((await api.createStudy(body)).study_id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="report-card" id="study-planner">
      <div className="panel-title">
        Walk {experiment.name} forward{' '}
        <span className="small muted">
          inherits the pinned spec, surface, objective {experiment.objective}, tolerance {experiment.tolerance}, budget and seed
        </span>
      </div>
      <div className="study-form small">
        <div id="study-symbols" className="study-symbols">
          Symbols{' '}
          {(available ?? []).map((symbol) => (
            <label key={symbol} style={{ marginRight: 10 }}>
              <input type="checkbox" id={`study-symbol-check-${symbol}`} checked={symbols.includes(symbol)} onChange={() => toggle(symbol)} /> {symbol}
            </label>
          ))}
        </div>
        <label>
          From <input id="study-start-date" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          to <input id="study-end-date" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <span className="muted">(empty: each archive's whole span)</span>
        <label>
          In-sample bars <input id="study-in-sample" type="number" min={35} value={inSample} onChange={(e) => setInSample(Number(e.target.value))} style={{ width: 90 }} />
        </label>
        <label>
          Out-of-sample bars <input id="study-out-of-sample" type="number" min={20} value={outOfSample} onChange={(e) => setOutOfSample(Number(e.target.value))} style={{ width: 90 }} />
        </label>
      </div>
      <div id="study-plan" className="small" style={{ marginTop: 6 }}>
        {plan ? (
          <>
            <b>{planLine(plan)}</b>
            <div className="muted">
              {plan.symbols.map((s) => `${s.symbol}: ${s.windows} windows of ${plan.in_sample_bars.toLocaleString()} + ${plan.out_of_sample_bars.toLocaleString()} bars (${s.unused_tail_bars} unused tail bars)`).join(' · ')}
              {plan.skipped ? ` · ${plan.skipped} cells skipped per window (${Object.entries(plan.skip_reasons).map(([r, c]) => `${r}: ${c}`).join(', ')})` : ''}
            </div>
            {(plan.levers ?? []).length > 0 && (
              <div className="muted" id="study-levers">
                Each window's map is sampled under the experiment's budget. To map exhaustively, apply a lever in a new experiment:{' '}
                {(plan.levers ?? []).map((lever) => leverLabel(lever)).join(' · ')}
              </div>
            )}
          </>
        ) : (
          <span className="muted">{error ? '' : 'planning…'}</span>
        )}
      </div>
      {error && (
        <div className="notice warn" id="study-error">
          {error}
        </div>
      )}
      <div className="actions" style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button type="button" className="btn btn-green" id="study-start" disabled={busy || !plan} onClick={startStudy}>
          Start
        </button>
        <button type="button" className="btn" id="study-planner-close" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
