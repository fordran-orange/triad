// The Lab's data loading: the experiment list for the picker, the open source (an experiment with its report and
// strategy name, or an optimization job), the 2-second refresh while it runs, the job's two-axis matrix, and the
// rows the table handed over for the selection card (kept by the provider, with the rest of what the Lab remembers
// between visits). The components only render what this returns.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { ExperimentDocument } from '../contracts';
import { axisChoices, axisLength, tooManySquares } from '../optimizer';
import { METRICS, OBJECTIVES, type AxisMatrix, type ExperimentReport, type ExperimentSummary, type JobStatus, type LabPage, type Metric } from '../results';
import { useDispatch, useWorkspace } from '../state/workspace';
import { families, parameterCount, type CatalogEntry, type Family } from './catalog';
import { handOverBody, matchTrialByParams, optRowFromLab } from './labQuery';
import { useLab, useLabDispatch, useLabMemory } from './labState';
import { parseSource, sourceText, type LabSource } from './labStore';

/** A job status as the worker sends it: the TS type leaves out a few fields the provenance block shows. */
export type OptJob = JobStatus & { strategy_hash?: string; engine?: string };

export type LoadedSource =
  | { kind: 'exp'; id: string; document: ExperimentDocument; report: ExperimentReport | null; strategyName: string }
  | { kind: 'opt'; id: string; job: OptJob };

/** One trial as the table shows it and the rail's card reads it. */
export interface TrialRow {
  /** `exp:<experiment id>#<cell>` or `opt:<job id>#<index in job.cells>`. */
  id: string;
  /** `cell 94` or `#3`. */
  label: string;
  params: Record<string, number | null>;
  /** exp: every `<scope>.<metric>` column; opt: the job side's metrics by name. */
  values: Record<string, number | null>;
  valid: boolean | null;
}

export interface MatrixState {
  /** The `matrixKeyOf` this state answers (or is loading): the job, the pair and the metric. Null without a pair. A
   *  state whose key is not the current one is stale (the pair or the metric just changed) and is never drawn. */
  key: string | null;
  matrix: AxisMatrix | null;
  loading: boolean;
  error: string | null;
  /** Why no matrix is drawn (one axis, too many squares); null when one can be. */
  notice: string | null;
}

export const NO_MATRIX: MatrixState = { key: null, matrix: null, loading: false, error: null, notice: null };

/** The key of a job's matrix: `<job id>|<rows path>|<cols path>|<metric>`, or null without a pair or a metric. */
export function matrixKeyOf(jobId: string, axes: [string, string] | null, metric: Metric | null): string | null {
  return axes && metric ? `${jobId}|${axes[0]}|${axes[1]}|${metric}` : null;
}

/** The job's matrix state when it answers the job, pair and metric in view, else NO_MATRIX: a matrix built for
 *  another pair or metric (its request still on the way) is never drawn under this one's labels nor walked by the
 *  keyboard. The job's heatmap and the Lab's keys both read the matrix through this one check. */
export function currentMatrix(data: Pick<LabData, 'loaded' | 'matrix' | 'optAxes' | 'optMetric'>): MatrixState {
  const job = data.loaded?.kind === 'opt' ? data.loaded.job : null;
  if (job === null) return NO_MATRIX;
  return data.matrix.key === matrixKeyOf(job.job_id, data.optAxes, data.optMetric) ? data.matrix : NO_MATRIX;
}

export function isLive(status: string): boolean {
  return status === 'running' || status === 'queued';
}

export function statusOf(loaded: LoadedSource): string {
  return loaded.kind === 'exp' ? loaded.document.status : loaded.job.status;
}

/** Whether the open source is still running (queued or running): what a panel on the 30 s rule asks again for. */
export function sourceLive(loaded: LoadedSource | null): boolean {
  return loaded !== null && isLive(statusOf(loaded));
}

export function isCurrent(loaded: LoadedSource | null, source: LabSource | null): loaded is LoadedSource {
  return loaded !== null && source !== null && loaded.kind === source.kind && loaded.id === source.id;
}

const finiteOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** The trial row of the job's cell at `index` (in the order the status sent its cells), as the table lists it. */
export function optRow(job: OptJob, index: number): TrialRow {
  const cell = job.cells[index];
  return {
    id: `opt:${job.job_id}#${index}`,
    label: `#${index}`,
    params: { ...cell.params },
    values: Object.fromEntries(Object.entries(cell.metrics).map(([k, v]) => [k, finiteOrNull(v)])),
    valid: null,
  };
}

/** The parameters a job varied, in plan order (the matrix may pair any two of them). */
export function jobPaths(job: JobStatus): string[] {
  const choices = axisChoices(job);
  if (choices.length >= 2) return choices;
  return [job.fast_path, job.slow_path].filter((p) => typeof p === 'string' && p !== '');
}

/** The pair the job's matrix shows: the store's axes when both belong to the job, else the job's own rows and
 *  columns. Null for a one-parameter job. */
export function effectiveOptAxes(job: JobStatus, axes: [string, string] | null): [string, string] | null {
  const paths = jobPaths(job);
  if (paths.length < 2) return null;
  if (axes && axes[0] !== axes[1] && paths.includes(axes[0]) && paths.includes(axes[1])) return axes;
  if (job.fast_path && job.slow_path && paths.includes(job.fast_path) && paths.includes(job.slow_path)) return [job.fast_path, job.slow_path];
  return [paths[0], paths[1]];
}

/** The metric the job's matrix is asked for: one of the optimizer's four. */
export function optMetric(job: JobStatus, metric: string): Metric {
  return (METRICS as string[]).includes(metric) ? (metric as Metric) : job.objective;
}

/** The parameter catalog of a source: an experiment's surface as families per side and indicator; a job's varied
 *  parameters as one family for its side (its paths are the job's own, without the side prefix). */
export function sourceFamilies(loaded: LoadedSource): Family[] {
  if (loaded.kind === 'exp') return families(loaded.document.surface, loaded.document.spec);
  const { job } = loaded;
  const planned = (job.side === 'long' ? job.strategy.long_side : job.strategy.short_side)?.optimization ?? [];
  const key = `${job.side}:job`;
  const entries: CatalogEntry[] = [];
  for (const path of jobPaths(job)) {
    const p = planned.find((o) => o.path === path);
    const values = path === job.fast_path ? job.fast_values : path === job.slow_path ? job.slow_values : [];
    if (p) entries.push({ path, side: job.side, family: key, field: path, start: p.start, stop: p.stop, step: p.step, count: parameterCount(p) });
    else if (values.length > 0) {
      const step = values.length > 1 ? values[1] - values[0] : 0;
      entries.push({ path, side: job.side, family: key, field: path, start: values[0], stop: values[values.length - 1], step, count: values.length });
    }
  }
  return entries.length === 0 ? [] : [{ key, label: `${job.side} · grid job (${entries.length} parameters)`, side: job.side, entries }];
}

async function fetchSource(source: LabSource, previous: LoadedSource | null): Promise<LoadedSource> {
  if (source.kind === 'opt') return { kind: 'opt', id: source.id, job: (await api.job(source.id)) as OptJob };
  const document = await api.experiment(source.id);
  const report = document.latest_report !== null && document.latest_report !== undefined ? await api.experimentReport(source.id) : null;
  let strategyName = document.spec.name;
  if (previous?.kind === 'exp' && previous.id === source.id) strategyName = previous.strategyName;
  else {
    try {
      strategyName = (await api.strategyDocument(document.strategy_id)).name;
    } catch {
      // the strategy document is gone or unreadable: the experiment's pinned spec still names it
    }
  }
  return { kind: 'exp', id: source.id, document, report, strategyName };
}

export function useLabSource() {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { session, knownRows, rememberRow, optSources, addOptSource } = useLabMemory();
  const { focus } = useWorkspace();
  const workspaceDispatch = useDispatch();
  const [experiments, setExperiments] = useState<ExperimentSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<LoadedSource | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [matrix, setMatrix] = useState<MatrixState>(NO_MATRIX);
  const loadedRef = useRef<LoadedSource | null>(null);
  loadedRef.current = loaded;

  const key = lab.source ? sourceText(lab.source) : null;

  const reloadList = useCallback(() => {
    api
      .experiments()
      .then((items) => {
        const usable = items.filter((item) => typeof item.id === 'string' && item.progress);
        usable.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0)); // newest first
        setExperiments(usable);
        setListError(null);
      })
      .catch((e: unknown) => setListError(errorMessage(e)));
  }, []);
  useEffect(reloadList, [reloadList]);

  // A deep link from the dock's Expand Lab: open what it names, with its axes and metric, on Trial Lab with the
  // panel restored (the store outlives the page, so it would otherwise land on whatever view the Lab was left on),
  // then consume it. Its selected configuration waits in the session until the job has loaded (the post-load
  // effect below selects it).
  useEffect(() => {
    const handed = focus?.lab;
    if (!handed) return;
    session.current.adopted = true;
    const source = parseSource(handed.source);
    session.current.handed = source && handed.selected ? { source: sourceText(source), params: handed.selected } : null;
    if (source) {
      dispatch({ type: 'OPEN_SOURCE', source, axes: handed.axes, metric: handed.metric });
      dispatch({ type: 'SET_VIEW', view: 'trials' });
      dispatch({ type: 'SET_MAXIMIZED', maximized: false });
    } else dispatch({ type: 'SOURCE_FAILED', message: `${handed.source}: not a Lab source (exp:<id> or opt:<id>)` });
    workspaceDispatch({ type: 'CLEAR_FOCUS' });
  }, [focus, dispatch, workspaceDispatch, session]);

  // Nothing handed over and nothing open: once the first list arrives, open the newest finished experiment. The
  // session remembers it was done, so a return to the page never opens one over the source in view.
  useEffect(() => {
    if (session.current.autoOpened || experiments === null) return;
    session.current.autoOpened = true;
    if (session.current.adopted || lab.source !== null || lab.sourceError !== null) return;
    const newest = experiments.find((item) => item.status === 'done');
    if (newest) dispatch({ type: 'OPEN_SOURCE', source: { kind: 'exp', id: newest.id }, metric: newest.objective });
  }, [experiments, lab.source, lab.sourceError, dispatch, session]);

  // Load the open source. A failure clears it and says why; the picker stays usable.
  useEffect(() => {
    setLoaded(null);
    setRefreshError(null);
    setMatrix(NO_MATRIX);
    const source = key === null ? null : parseSource(key);
    if (source === null) return;
    if (source.kind === 'opt') addOptSource(source.id);
    let cancelled = false;
    fetchSource(source, null)
      .then((next) => !cancelled && setLoaded(next))
      .catch((e: unknown) => !cancelled && dispatch({ type: 'SOURCE_FAILED', message: `${key}: ${errorMessage(e)}` }));
    return () => {
      cancelled = true;
    };
  }, [key, dispatch, addOptSource]);

  // While it runs, re-fetch it every 2 s; the table re-fetches its window on the tick.
  const live = loaded !== null && isLive(statusOf(loaded));
  useEffect(() => {
    if (!live || key === null) return;
    const source = parseSource(key);
    if (source === null) return;
    let cancelled = false;
    let pending = false;
    const timer = setInterval(() => {
      if (pending) return; // the previous refresh is still on its way
      pending = true;
      fetchSource(source, loadedRef.current)
        .then((next) => {
          if (cancelled) return;
          setLoaded(next);
          setRefreshError(null);
          setTick((t) => t + 1);
          dispatch({ type: 'ROWS_REFRESHED' });
        })
        .catch((e: unknown) => !cancelled && setRefreshError(errorMessage(e)))
        .finally(() => {
          pending = false;
        });
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [live, key, dispatch]);

  // Once a source has loaded, make the store's axes and metric ones it has (a picked source keeps what it can), and
  // select the trial the dock handed over: the job's `/lab` trial with exactly its parameters (none matching: no
  // selection). The dock lists the job's best cells, so its index is not a trial number: the worker is asked.
  const loadedKey = loaded ? `${loaded.kind}:${loaded.id}` : null;
  useEffect(() => {
    if (loaded === null) return;
    const handed = session.current.handed;
    session.current.handed = null; // the first source to load consumes it: the handed job, or one picked over it
    if (loaded.kind === 'opt') {
      const axes = effectiveOptAxes(loaded.job, lab.axes);
      if (axes && (lab.axes === null || axes[0] !== lab.axes[0] || axes[1] !== lab.axes[1])) dispatch({ type: 'SET_AXES', axes });
      if (!(METRICS as string[]).includes(lab.metric)) dispatch({ type: 'SET_METRIC', metric: loaded.job.objective });
      if (handed !== null && handed.source === loadedKey) {
        const { side } = loaded.job;
        api
          .labQuery<LabPage>(handed.source, handOverBody(handed.params, side))
          .then((envelope) => {
            const now = loadedRef.current;
            if (now === null || `${now.kind}:${now.id}` !== handed.source) return; // another source since
            const row = matchTrialByParams(envelope.rows, handed.params, side);
            if (row === null) return;
            const trial = optRowFromLab(row, side);
            rememberRow(trial); // as a row click does: the selection card reads it
            dispatch({ type: 'SELECT_TRIALS', ids: [trial.id] });
          })
          .catch(() => undefined); // the worker could not say which trial it is: no selection, as with no match
      }
    } else {
      const paths = loaded.document.surface.parameters.map((p) => p.path);
      const fits = lab.axes !== null && lab.axes[0] !== lab.axes[1] && paths.includes(lab.axes[0]) && paths.includes(lab.axes[1]);
      if (!fits && paths.length >= 2) dispatch({ type: 'SET_AXES', axes: [paths[0], paths[1]] });
      if (!(OBJECTIVES as string[]).includes(lab.metric)) dispatch({ type: 'SET_METRIC', metric: loaded.document.objective });
    }
    // Only when a new source arrives: later axis and metric choices are the operator's.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedKey]);

  // The job's matrix for the pair and metric in view: each square the best of the rest, built on the worker.
  const job = loaded?.kind === 'opt' ? loaded.job : null;
  const axes = job ? effectiveOptAxes(job, lab.axes) : null;
  const metric = job ? optMetric(job, lab.metric) : null;
  const matrixKey = job ? matrixKeyOf(job.job_id, axes, metric) : null;
  const progressMark = job ? `${job.cells_done ?? job.progress.done}|${job.status}` : null;
  useEffect(() => {
    if (job === null) return;
    if (axes === null || metric === null || matrixKey === null) {
      setMatrix({ ...NO_MATRIX, notice: 'one axis: no matrix (the job varied fewer than two parameters)' });
      return;
    }
    const tooMany = tooManySquares(axisLength(job, axes[0]), axisLength(job, axes[1]));
    if (tooMany) {
      setMatrix({ ...NO_MATRIX, key: matrixKey, notice: tooMany });
      return;
    }
    let cancelled = false;
    // A refresh of the same matrix keeps it on screen while it updates; another pair or metric drops the old one.
    setMatrix((m) => (m.key === matrixKey ? { ...m, loading: true, error: null, notice: null } : { ...NO_MATRIX, key: matrixKey, loading: true }));
    api
      .optimizeMatrix(job.job_id, axes[0], axes[1], metric)
      .then((found) => !cancelled && setMatrix({ key: matrixKey, matrix: found, loading: false, error: null, notice: null }))
      .catch((e: unknown) => !cancelled && setMatrix({ key: matrixKey, matrix: null, loading: false, error: errorMessage(e), notice: null }));
    return () => {
      cancelled = true;
    };
    // The key and the progress mark stand for the job, the pair and the metric.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matrixKey, progressMark]);

  return {
    experiments,
    listError,
    reloadList,
    loaded: isCurrent(loaded, lab.source) ? loaded : null,
    loading: lab.source !== null && !isCurrent(loaded, lab.source),
    refreshError,
    tick,
    optSources,
    knownRows,
    rememberRow,
    matrix,
    optAxes: axes,
    optMetric: metric,
  };
}

export type LabData = ReturnType<typeof useLabSource>;
