// The Lab's data layer on `/aegis/api/lab` (Phase 2). It wraps the Phase 1 source hook, which keeps the experiment
// list, the open source with its report and strategy name, the 2 s refresh and the grid job's own matrix, and adds
// the query layer: the source's summary (on open, and on every refresh tick while it runs), an experiment's matrix
// for the axes, mode, stat, metric, filter and slice in view, and `query`, through which every panel asks for its
// own view. An answer to a filter that is no longer the store's is dropped; a failed query leaves its message for
// the panel's X state, whose Retry asks again. The components only render what this returns.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { LabEnvelope, LabMatrix, LabQueryBody, LabQueryView, LabSummary } from '../results';
import { useLab } from './labState';
import { sourceText, type LabState } from './labStore';
import { exactFixed, expMatrixKey, isCurrentHash, optBody, queryBody } from './labQuery';
import { useLabSource, type TrialRow } from './useLabSource';

/** An answer with the time it arrived (the envelope's snapshot carries no clock): the provisional labels read it. */
export type Stamped<T> = T & { receivedAt: string };

export interface ExpMatrixState {
  /** The `expMatrixKey` this state answers (or is loading); null when no matrix is asked for. */
  key: string | null;
  envelope: Stamped<LabEnvelope<LabMatrix>> | null;
  loading: boolean;
  error: string | null;
}

export const NO_EXP_MATRIX: ExpMatrixState = { key: null, envelope: null, loading: false, error: null };

const now = () => new Date().toISOString();

/** The selected trial's parameters, when one trial of `source` is selected and its row is known: the exact slice
 *  centres on it (§7.1). */
function selectedParams(lab: LabState, knownRows: Record<string, TrialRow>, source: string | null): Record<string, number> | null {
  const selected = lab.selected;
  if (source === null || selected === null || !('trials' in selected) || selected.trials.length !== 1) return null;
  const id = selected.trials[0];
  const row = id.startsWith(`${source}#`) ? knownRows[id] : undefined;
  if (row === undefined) return null;
  const params: Record<string, number> = {};
  for (const [path, value] of Object.entries(row.params)) if (typeof value === 'number' && Number.isFinite(value)) params[path] = value;
  return params;
}

export function useLabQuery() {
  const base = useLabSource();
  const lab = useLab();
  const { loaded, tick, knownRows } = base;
  const labRef = useRef(lab);
  labRef.current = lab;
  const source = lab.source ? sourceText(lab.source) : null;
  // Only a source that opened asks /lab: a failed open (a bogus id) never does.
  const ready = source !== null && loaded !== null && `${loaded.kind}:${loaded.id}` === source;
  const side = loaded?.kind === 'opt' ? loaded.job.side : null;
  const sideRef = useRef(side);
  sideRef.current = side;

  /** One view of the store's filter for the open source. An `opt:` source is asked on its job's side, with the job's
   *  paths as the worker names them. Null when the answer no longer fits the store (another source, another filter);
   *  a refusal or a transport error rejects, for the panel's X state. */
  const query = useCallback(async <T>(view: LabQueryView, extra?: Partial<LabQueryBody>): Promise<Stamped<LabEnvelope<T>> | null> => {
    const asked = labRef.current;
    if (asked.source === null) return null;
    const src = sourceText(asked.source);
    let body = queryBody(asked, view, extra);
    if (asked.source.kind === 'opt') {
      const jobSide = sideRef.current;
      if (jobSide === null) return null; // the job has not loaded: its side is not known yet
      body = optBody(body, jobSide);
    }
    const envelope = await api.labQuery<T>(src, body);
    const latest = labRef.current;
    if (latest.source === null || sourceText(latest.source) !== src || !isCurrentHash(envelope, latest)) return null;
    return { ...envelope, receivedAt: now() };
  }, []);

  // The summary: on open, on every refresh tick while the source runs (its status, its counts and the picker's
  // status label move with it) and on Retry.
  const [summary, setSummary] = useState<Stamped<LabSummary> | null>(null);
  const [summaryError, setSummaryError] = useState<{ source: string; message: string } | null>(null);
  const [summaryRetry, setSummaryRetry] = useState(0);
  const summarySeq = useRef(0);
  const summaryAsked = useRef<string | null>(null);
  useEffect(() => {
    const mark = ready ? `${source}|${tick}|${summaryRetry}` : null;
    if (mark !== null && summaryAsked.current === mark) return; // React's development double-run of the same ask
    summaryAsked.current = mark;
    const mine = ++summarySeq.current;
    if (!ready || source === null) return;
    api
      .labSummary(source)
      .then((found) => {
        if (mine !== summarySeq.current) return; // a newer ask owns the summary
        setSummary({ ...found, receivedAt: now() });
        setSummaryError(null);
      })
      .catch((e: unknown) => mine === summarySeq.current && setSummaryError({ source, message: errorMessage(e) }));
  }, [ready, source, tick, summaryRetry]);
  const currentSummary = summary !== null && summary.source === source ? summary : null;
  const retrySummary = useCallback(() => setSummaryRetry((n) => n + 1), []);

  // An experiment's matrix for what the heatmap shows: the axes (both on its surface), the mode, the stat, the
  // metric, the filter and, in exact mode, the §7.1 slice. A grid job's heatmap keeps the Phase 1 matrix.
  const [expMatrix, setExpMatrix] = useState<ExpMatrixState>(NO_EXP_MATRIX);
  const [matrixRetry, setMatrixRetry] = useState(0);
  const matrixSeq = useRef(0);
  const matrixAsked = useRef<string | null>(null);
  const paths = loaded?.kind === 'exp' ? loaded.document.surface.parameters.map((p) => p.path) : [];
  const axes = lab.axes !== null && lab.axes[0] !== lab.axes[1] && paths.includes(lab.axes[0]) && paths.includes(lab.axes[1]) ? lab.axes : null;
  const fixed = axes !== null && lab.mode === 'exact' ? exactFixed(selectedParams(lab, knownRows, source), currentSummary?.spec_values ?? null, axes, lab.filter.values) : null;
  const matrixKey = ready && source !== null && axes !== null && (lab.mode === 'aggregate' || fixed !== null) ? expMatrixKey(source, lab, fixed) : null;
  useEffect(() => {
    const mark = matrixKey === null ? null : `${matrixKey}|${tick}|${matrixRetry}`;
    if (mark !== null && matrixAsked.current === mark) return;
    matrixAsked.current = mark;
    const mine = ++matrixSeq.current;
    if (matrixKey === null) {
      setExpMatrix(NO_EXP_MATRIX);
      return;
    }
    // A refresh of the same matrix keeps it on screen while it updates; another key drops the old one.
    setExpMatrix((m) => (m.key === matrixKey ? { ...m, loading: true, error: null } : { ...NO_EXP_MATRIX, key: matrixKey, loading: true }));
    query<LabMatrix>('matrix', lab.mode === 'exact' ? { fixed } : {})
      .then((envelope) => {
        if (mine === matrixSeq.current && envelope !== null) setExpMatrix({ key: matrixKey, envelope, loading: false, error: null });
      })
      .catch((e: unknown) => mine === matrixSeq.current && setExpMatrix({ key: matrixKey, envelope: null, loading: false, error: errorMessage(e) }));
    // The key stands for the source, the axes, the mode, the stat, the metric, the filter and the slice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matrixKey, tick, matrixRetry]);
  const retryMatrix = useCallback(() => setMatrixRetry((n) => n + 1), []);

  return {
    ...base,
    summary: currentSummary,
    summaryError: summaryError !== null && summaryError.source === source ? summaryError.message : null,
    retrySummary,
    expMatrix: expMatrix.key === matrixKey ? expMatrix : { ...NO_EXP_MATRIX, key: matrixKey, loading: matrixKey !== null },
    retryMatrix,
    query,
  };
}

export type LabQueryData = ReturnType<typeof useLabQuery>;
