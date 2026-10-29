import { useEffect, useMemo, useState } from 'react';
import { api, errorMessage, type ExperimentBody } from '../api/client';
import { INDICATOR_KINDS, type Plan, type StrategyDocument } from '../contracts';
import { evaluationsLine, leverLabel, priceLabel, surfaceLine } from '../experiments';
import { num } from '../format';
import { effectiveParams } from '../rules';
import { OBJECTIVE_LABELS, OBJECTIVES, type ExperimentLever, type Objective } from '../results';
import { TIMEFRAMES, useWorkspace, type Selection, type Timeframe } from '../state/workspace';
import { formatSeconds } from './OptimizePopover';

interface Param {
  path: string;
  start: number;
  stop: number;
  step: number;
}

/** The screening blocks the checkbox asks for (Lab Phase 3, §7.3a: SCREEN_BLOCKS). */
const SCREEN_BLOCKS = 4;

interface Props {
  document: StrategyDocument;
  onCreated: (experimentId: string) => void;
  onClose: () => void;
}

/** Every parameter path the document offers, both sides, lengths and kind parameters. */
export function availablePaths(document: StrategyDocument): Array<{ path: string; current: number; whole: boolean }> {
  const out: Array<{ path: string; current: number; whole: boolean }> = [];
  for (const side of ['long_side', 'short_side'] as const) {
    const spec = document.spec[side];
    if (!spec.enabled) continue;
    for (const indicator of spec.indicators ?? []) {
      out.push({ path: `${side}.indicators.${indicator.id}.length`, current: indicator.length, whole: true });
      const info = INDICATOR_KINDS[indicator.kind.toUpperCase()];
      const params = effectiveParams(indicator);
      for (const name of Object.keys(info?.params ?? {})) {
        out.push({ path: `${side}.indicators.${indicator.id}.params.${name}`, current: params[name], whole: info.integer_params.includes(name) });
      }
    }
  }
  return out;
}

/** A starting range around the document's value: half to double, ten steps or so. */
export function defaultParam(path: string, current: number, whole: boolean): Param {
  if (whole) {
    const v = Math.round(current);
    return { path, start: Math.max(2, Math.floor(v / 2)), stop: 2 * v, step: Math.max(1, Math.round(v / 10)) };
  }
  return { path, start: current / 2, stop: current * 2, step: current / 4 };
}

function midpoint(start: string, end: string): string {
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return start;
  return new Date(a + (b - a) / 2).toISOString().slice(0, 10);
}

export function ExperimentPlanner({ document, onCreated, onClose }: Props) {
  const { selection, settings } = useWorkspace();
  const offered = useMemo(() => availablePaths(document), [document]);
  const [name, setName] = useState(`${document.name} surface`);
  const [params, setParams] = useState<Param[]>([]);
  const [objective, setObjective] = useState<Objective>('net_pnl');
  const [budgetRuns, setBudgetRuns] = useState<string>('2000');
  const [budgetSeconds, setBudgetSeconds] = useState<string>('');
  const [tolerance, setTolerance] = useState(0.15);
  const [screened, setScreened] = useState(false);
  const [data, setData] = useState<Selection>(selection);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const body: ExperimentBody | null = useMemo(() => {
    if (params.length === 0) return null;
    const runs = budgetRuns.trim() === '' ? null : Number(budgetRuns);
    const seconds = budgetSeconds.trim() === '' ? null : Number(budgetSeconds);
    return {
      name,
      strategy_id: document.id,
      data,
      settings,
      objective,
      surface: { parameters: params },
      budget: { runs, seconds },
      tolerance,
      seed: 1,
      blocks: screened ? SCREEN_BLOCKS : 0,
    };
  }, [name, document.id, data, settings, objective, params, budgetRuns, budgetSeconds, tolerance, screened]);

  useEffect(() => {
    if (!body) {
      setPlan(null);
      return;
    }
    let cancelled = false;
    setPlan(null);
    setError(null);
    const timer = setTimeout(() => {
      api
        .experimentPlan(body)
        .then((p) => !cancelled && setPlan(p))
        .catch((e: unknown) => !cancelled && setError(errorMessage(e)));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [body]);

  const add = (path: string) => {
    const found = offered.find((o) => o.path === path);
    if (!found || params.some((p) => p.path === path)) return;
    setParams((list) => [...list, defaultParam(found.path, found.current, found.whole)]);
  };
  const edit = (index: number, field: 'start' | 'stop' | 'step', raw: string) => {
    const value = Number(raw);
    if (!Number.isFinite(value)) return;
    setParams((list) => list.map((p, i) => (i === index ? { ...p, [field]: value } : p)));
  };
  const applyLever = (lever: ExperimentLever) => {
    if (lever.surface) setParams(lever.surface.parameters.map((p) => ({ ...p })));
    if (lever.budget) {
      setBudgetRuns(lever.budget.runs == null ? '' : String(lever.budget.runs));
      setBudgetSeconds(lever.budget.seconds == null ? '' : String(lever.budget.seconds));
    }
    if (lever.kind === 'shorten') setData((d) => ({ ...d, start: midpoint(d.start, d.end) }));
    if (lever.kind === 'coarser_timeframe' && lever.data_hint && (TIMEFRAMES as readonly string[]).includes(lever.data_hint)) {
      setData((d) => ({ ...d, timeframe: lever.data_hint as Timeframe }));
    }
  };
  const start = async () => {
    if (!body) return;
    setStarting(true);
    setError(null);
    try {
      const started = await api.createExperiment(body);
      onCreated(started.experiment_id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };
  const unused = offered.filter((o) => !params.some((p) => p.path === o.path));

  return (
    <div className="planner" id="experiment-planner">
      <div className="panel-title">
        New experiment on <b>{document.name}</b>
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="row">
        <label htmlFor="experiment-name">Name</label>
        <input id="experiment-name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
      </div>
      <div className="row">
        <label htmlFor="surface-add">Add parameter</label>
        <select
          id="surface-add"
          value=""
          onChange={(e) => {
            add(e.target.value);
            e.target.value = '';
          }}
        >
          <option value="">{unused.length ? 'choose a path…' : 'every path is on the surface'}</option>
          {unused.map((o) => (
            <option key={o.path} value={o.path}>
              {o.path} (now {num(o.current, 4)})
            </option>
          ))}
        </select>
        <span className="muted small">
          {params.length} of 10 · data {data.symbol} {data.timeframe} {data.start} → {data.end}
        </span>
      </div>
      {params.map((p, i) => (
        <div className="row" key={p.path} id={`surface-${i}`}>
          <input id={`surface-path-${i}`} value={p.path} readOnly style={{ flex: 1 }} aria-label={`parameter ${i + 1} path`} />
          <input id={`surface-start-${i}`} type="number" step="any" value={p.start} aria-label={`parameter ${i + 1} start`} onChange={(e) => edit(i, 'start', e.target.value)} />
          <input id={`surface-stop-${i}`} type="number" step="any" value={p.stop} aria-label={`parameter ${i + 1} stop`} onChange={(e) => edit(i, 'stop', e.target.value)} />
          <input id={`surface-step-${i}`} type="number" step="any" value={p.step} aria-label={`parameter ${i + 1} step`} onChange={(e) => edit(i, 'step', e.target.value)} />
          <button type="button" className="btn" id={`surface-remove-${i}`} onClick={() => setParams((list) => list.filter((_, k) => k !== i))}>
            ×
          </button>
        </div>
      ))}
      <div className="row">
        <label htmlFor="experiment-objective">Objective</label>
        <select id="experiment-objective" value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
          {OBJECTIVES.map((m) => (
            <option key={m} value={m}>
              {OBJECTIVE_LABELS[m]}
            </option>
          ))}
        </select>
        <label htmlFor="budget-runs">Budget runs</label>
        <input id="budget-runs" type="number" min={1} step={1} value={budgetRuns} onChange={(e) => setBudgetRuns(e.target.value)} />
        <label htmlFor="budget-seconds">seconds</label>
        <input id="budget-seconds" type="number" min={1} step={1} value={budgetSeconds} placeholder="none" onChange={(e) => setBudgetSeconds(e.target.value)} />
        <label htmlFor="experiment-tolerance">Tolerance</label>
        <input id="experiment-tolerance" type="number" min={0.01} max={1} step={0.01} value={tolerance} onChange={(e) => setTolerance(Number(e.target.value))} />
      </div>
      <div className="row">
        <label className="muted small">
          <input id="experiment-blocks" type="checkbox" checked={screened} onChange={(e) => setScreened(e.target.checked)} /> Screen across periods ({SCREEN_BLOCKS} blocks)
        </label>
      </div>
      <div className="plan" id="experiment-plan">
        {params.length === 0
          ? 'Add at least one parameter.'
          : plan
            ? `${surfaceLine({ parameters: params }, plan)} · ≈ ${formatSeconds(plan.estimate_seconds)} on ${plan.workers} workers at ${num(plan.ms_per_cell_bar * plan.bars, 1)} ms per cell (${priceLabel(plan)})` +
              (plan.blocks ? ` · ${evaluationsLine(plan)}` : '') +
              (plan.skipped ? ` · ${plan.skipped.toLocaleString()} skipped (${Object.keys(plan.skip_reasons).join('; ')})` : '')
            : error
              ? ''
              : 'Planning…'}
      </div>
      {error && (
        <div className="notice warn" id="experiment-error">
          {error}
        </div>
      )}
      {plan && plan.mode === 'sampled' && (plan.levers ?? []).length > 0 && (
        <div className="levers">
          <div className="small muted">Over budget. Ways back into scope (each re-plans):</div>
          {(plan.levers ?? []).map((lever) => {
            const index = lever.parameter ? params.findIndex((p) => p.path === lever.parameter) : 0;
            return (
              <button key={`${lever.kind}-${lever.parameter ?? ''}`} type="button" className={'btn' + (lever.fits ? ' btn-green' : '')} id={`lever-${lever.kind}-${Math.max(index, 0)}`} onClick={() => applyLever(lever as ExperimentLever)}>
                {leverLabel(lever as ExperimentLever)}
              </button>
            );
          })}
        </div>
      )}
      <div className="actions" style={{ display: 'flex', gap: 6 }}>
        <button type="button" className="btn btn-green" id="experiment-start" disabled={!plan || starting} onClick={start}>
          {starting ? 'Starting…' : plan ? `Start (${plan.mode}, ${plan.planned_runs.toLocaleString()} runs)` : 'Start'}
        </button>
      </div>
    </div>
  );
}
