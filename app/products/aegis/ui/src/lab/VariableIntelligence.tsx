import { AssumptionsLine } from './AssumptionsLine';
import { NotBuilt } from './NotBuilt';
import { ParameterCatalog } from './ParameterCatalog';
import { TrialTable, type ScrollMemory, type TrialSort } from './TrialTable';
import type { LabQueryData } from './useLabQuery';
import { sourceFamilies, type TrialRow } from './useLabSource';
import { WorkflowStrip } from './WorkflowStrip';

/** Screen H in Phase 1: the whole six-step workflow (only Define works yet), every parameter of the source with its
 *  status, and the trials as the evidence table (plan §8.3). Nothing has been screened, so every parameter is Active
 *  by default; Phase 4 brings the evidence. */
export function VariableIntelligence({
  data,
  sort,
  onSort,
  onSelect,
  memory,
}: {
  data: LabQueryData;
  sort: TrialSort;
  onSort: (sort: TrialSort) => void;
  onSelect: (row: TrialRow) => void;
  memory: ScrollMemory;
}) {
  const { loaded, loading } = data;
  return (
    <>
      <WorkflowStrip hasExperiment={loaded?.kind === 'exp'} hasReport={loaded?.kind === 'exp' && loaded.report !== null} />
      <div className="lab-body">
        <ParameterCatalog list={loaded ? sourceFamilies(loaded) : null} mode="status" loading={loading} />
        <div className="lab-center no-tabs">
          <div className="lab-panel">
            <div className="lab-line" id="lab-variables-status" title="screening blocks are on the experiment planner; the evidence and statuses arrive in Phase 4">
              no screening evidence: all parameters Active
            </div>
            <AssumptionsLine panel="variables" />
            <NotBuilt what="Influence, interactions and search-space proposals" phase={4} />
          </div>
          {loaded ? (
            <TrialTable key={`${loaded.kind}:${loaded.id}`} data={data} sort={sort} onSort={onSort} onSelect={onSelect} memory={memory} />
          ) : (
            <div className="lab-trials">
              <div className="lab-empty">{loading ? 'Loading trials…' : 'No source open: choose one in the context bar.'}</div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
