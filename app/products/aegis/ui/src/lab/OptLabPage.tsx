import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ExperimentDocument } from '../contracts';
import { FamiliesPage } from './FamiliesPage';
import { IntelligenceRail } from './IntelligenceRail';
import { LabCenter } from './LabCenter';
import { LabContextBar } from './LabContextBar';
import { cursorDims } from './labHeatmapModel';
import { LabKpiStrip } from './LabKpiStrip';
import { useLab, useLabDispatch } from './labState';
import { sourceText, type LabView } from './labStore';
import { LabSubNav } from './LabSubNav';
import { NotBuilt } from './NotBuilt';
import { ParameterCatalog } from './ParameterCatalog';
import type { TrialSort } from './TrialTable';
import { useLabKeys } from './useLabKeys';
import { useLabQuery } from './useLabQuery';
import { currentMatrix, sourceFamilies, type TrialRow } from './useLabSource';
import { VariableIntelligence } from './VariableIntelligence';

/** The views a later phase builds: each one says what it is and when it arrives, inside the same layout. */
const PLACEHOLDERS: Record<Exclude<LabView, 'trials' | 'variables' | 'families'>, { what: string; phase: number }> = {
  monitor: { what: 'Run Monitor', phase: 5 },
  walkforward: { what: 'Walk-Forward & Robustness', phase: 6 },
  lineage: { what: 'History, Lineage & Forensics', phase: 6 },
  compare: { what: 'Candidate Compare', phase: 5 },
};

const METRIC_ORDER: TrialSort = { column: null, descending: true };

/** The Optimization Lab page (plan §5.2, Screen B, with Screen H's workflow strip): one store for every view. The
 *  store's `LabProvider` sits above the app's page switch, so a trip to another page and back keeps the source, the
 *  filter, the selection and the pins. */
export function OptLabPage() {
  const lab = useLab();
  const dispatch = useLabDispatch();
  const data = useLabQuery();
  const [sort, setSort] = useState<TrialSort>(METRIC_ORDER);
  const memory = useRef({ key: '', top: 0 });
  const key = lab.source ? sourceText(lab.source) : null;
  // A new source, side scope or metric starts in the metric's order, best first: a sort on a column the new scope or
  // metric hides would otherwise stick.
  useEffect(() => setSort(METRIC_ORDER), [key, lab.filter.scope, lab.metric]);

  const { loaded, expMatrix } = data;
  // The keys walk the matrix the Heatmap tab draws: an experiment's /lab matrix, or a grid job's own, read through
  // the same key check its heatmap uses.
  const job = currentMatrix(data);
  const shown = loaded?.kind === 'exp' ? expMatrix.envelope : job.notice === null ? job.matrix : null;
  const onKeyDown = useLabKeys(lab.view === 'trials' && lab.tab === 'heatmap' ? cursorDims(shown) : null);
  const list = useMemo(() => (loaded ? sourceFamilies(loaded) : null), [loaded]);

  const select = (row: TrialRow) => {
    data.rememberRow(row);
    dispatch({ type: 'SELECT_TRIALS', ids: [row.id] });
  };
  const refined = (child: ExperimentDocument) => {
    data.reloadList();
    dispatch({ type: 'OPEN_SOURCE', source: { kind: 'exp', id: child.id }, metric: child.objective });
  };

  let body: ReactNode;
  if (lab.view === 'trials') {
    body = (
      <div className={'lab-body' + (lab.maximized ? ' maximized' : '')}>
        {!lab.maximized && <ParameterCatalog list={list} mode="controls" loading={data.loading} />}
        <LabCenter data={data} sort={sort} onSort={setSort} onSelect={select} memory={memory} />
      </div>
    );
  } else if (lab.view === 'variables') {
    body = <VariableIntelligence data={data} sort={sort} onSort={setSort} onSelect={select} memory={memory} />;
  } else if (lab.view === 'families') {
    body = <FamiliesPage data={data} sort={sort} onSort={setSort} onSelect={select} memory={memory} />;
  } else {
    const placeholder = PLACEHOLDERS[lab.view];
    body = (
      <div className="lab-body single">
        <div className="lab-panel">
          <NotBuilt what={placeholder.what} phase={placeholder.phase} />
        </div>
      </div>
    );
  }

  return (
    <div className="optlab-page" id="optlab-page" tabIndex={0} onKeyDown={onKeyDown}>
      <LabSubNav />
      <div className={'lab-main-col' + (lab.view === 'variables' ? ' with-strip' : '')}>
        <LabContextBar data={data} />
        <LabKpiStrip data={data} />
        {body}
      </div>
      <IntelligenceRail data={data} onRefined={refined} />
    </div>
  );
}
