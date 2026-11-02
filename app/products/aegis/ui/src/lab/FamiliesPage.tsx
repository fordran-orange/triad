// Screen E: Parameter Families (spec §5.5). The family tree of the parameters on the left (search, counts, brushes, the filters
// in force), and in the centre the scope breadcrumb, the full-size parallel coordinates (aggregated or a stratified sample),
// the trellis of the top pairs, the importance and interaction strength, the robust neighbourhood map of a pair, and the
// drill-down of the square picked in the trellis. One shared filter links them all, and none of them filters on the client: the
// worker does, and the drill-down's table is the worker's `page` of the Lab's filter plus the square, whose total the page
// shows beside the square's n (§7.8: they are equal by construction, and the page says so, or says that they differ). The picked
// square is the Lab's (`familiesPick` in its store), so leaving the page does not lose it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import { DASH } from '../format';
import type { LabPage, LabSnapshot } from '../results';
import { AssumptionsLine } from './AssumptionsLine';
import { drillCheck, pickFilter, rangeText, type TrellisPick } from './familiesModel';
import { ImportanceView } from './ImportanceView';
import { NeighbourhoodMap } from './NeighbourhoodMap';
import { ParallelCoords } from './ParallelCoords';
import { ParameterCatalog } from './ParameterCatalog';
import { ScopeBreadcrumb } from './ScopeBreadcrumb';
import { Trellis } from './Trellis';
import { TrialTable, type ScrollMemory, type TrialSort } from './TrialTable';
import { filterLines } from './labQuery';
import { useLab, useLabDispatch } from './labState';
import { filterHash, sourceText } from './labStore';
import { LabError } from './NotBuilt';
import { axisLabel } from './parallelBundles';
import { useAskMark } from './useAskMark';
import type { LabQueryData } from './useLabQuery';
import { sourceFamilies, sourceLive, type TrialRow } from './useLabSource';

/** The square's n beside the table's total, and whether they agree (§7.8): both exact numbers as attributes, for the walk. Each
 *  was read at a snapshot; on a running source they can differ, and then the two are not compared (`data-match` is empty). */
export function DrillCheck({ squareN, squareSnapshot, total, tableSnapshot }: { squareN: number; squareSnapshot: LabSnapshot | null; total: number | null; tableSnapshot: LabSnapshot | null }) {
  const check = drillCheck(squareN, squareSnapshot, total, tableSnapshot);
  const match = check.match === null ? '' : String(check.match);
  return (
    <div className="drill-check" id="lab-families-drill-check" data-match={match}>
      square n{' '}
      <b id="lab-families-drill-n" data-n={squareN}>
        {squareN.toLocaleString('en-US')}
      </b>{' '}
      · table total{' '}
      <b id="lab-families-drill-total" data-total={total ?? ''}>
        {total === null ? DASH : total.toLocaleString('en-US')}
      </b>{' '}
      · <span className="drill-verdict" id="lab-families-drill-verdict">{check.text}</span>
    </div>
  );
}

/** The contributing trials of the picked square: the worker's `page` of the Lab's filter plus the square. Its total is read
 *  on its own (a page of one row) and printed beside the square's n; the table below pages the same filter. The total is asked on
 *  the 30 s rule, like the pairs it is compared with (`useAskMark`), and keeps the snapshot it was read at. */
function Drilldown({
  data,
  pick,
  sort,
  onSort,
  onSelect,
  memory,
}: {
  data: LabQueryData;
  pick: TrellisPick | null;
  sort: TrialSort;
  onSort: (sort: TrialSort) => void;
  onSelect: (row: TrialRow) => void;
  memory: ScrollMemory;
}) {
  const lab = useLab();
  const { loaded, query } = data;
  const source = loaded ? sourceText(loaded) : null;
  const filter = useMemo(() => (pick === null ? null : pickFilter(lab.filter, pick)), [lab.filter, pick]);
  const key = source === null || filter === null ? null : [source, lab.metric, filterHash(filter)].join('|');
  const askMark = useAskMark(key, sourceLive(loaded));

  const [retry, setRetry] = useState(0);
  const [answer, setAnswer] = useState<{ key: string; total: number; snapshot: LabSnapshot | null } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const seq = useRef(0);
  const asked = useRef<string | null>(null);
  useEffect(() => {
    const mark = key === null ? null : `${key}|${askMark}|${retry}`;
    if (mark !== null && asked.current === mark) return; // React's development double-run of the same ask
    asked.current = mark;
    const mine = ++seq.current;
    if (key === null || filter === null) return;
    query<LabPage>('page', { filter, offset: 0, limit: 1 })
      .then((envelope) => {
        if (mine !== seq.current || envelope === null) return; // a newer ask owns the total, or the filter moved on
        setAnswer({ key, total: envelope.total, snapshot: envelope.snapshot });
        setFailure(null);
      })
      .catch((e: unknown) => mine === seq.current && setFailure({ key, message: errorMessage(e) }));
    // The key stands for the source, the metric and the drill-down's filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, askMark, retry]);
  const total = answer !== null && answer.key === key ? answer.total : null;
  const tableSnapshot = answer !== null && answer.key === key ? answer.snapshot : null;
  const error = failure !== null && failure.key === key ? failure.message : null;

  if (pick === null || filter === null)
    return (
      <div className="lab-drill" id="lab-families-drill" data-total="" data-n="" data-match="">
        <div className="families-title">Contributing trials</div>
        <AssumptionsLine panel="drill" />
        <div className="lab-empty" id="lab-families-drill-empty">
          {pick !== null ? 'the picked square lies outside the filter: it holds no trial' : 'pick a trellis square to see the trials in it'}
        </div>
      </div>
    );
  const lines = filterLines(filter);
  const match = drillCheck(pick.n, pick.snapshot, total, tableSnapshot).match;
  return (
    <div className="lab-drill" id="lab-families-drill" data-total={total ?? ''} data-n={pick.n} data-match={match === null ? '' : String(match)}>
      <div className="families-title">Contributing trials</div>
      <AssumptionsLine panel="drill" />
      <div className="sub" id="lab-families-drill-square">
        {axisLabel(pick.axes[0])} = {rangeText(pick.rows)} · {axisLabel(pick.axes[1])} = {rangeText(pick.cols)}
      </div>
      <DrillCheck squareN={pick.n} squareSnapshot={pick.snapshot} total={total} tableSnapshot={tableSnapshot} />
      {error !== null && <LabError id="lab-families-drill-error" message={`The table's total is unavailable: ${error}`} onRetry={() => setRetry((n) => n + 1)} />}
      <div className="sub" id="lab-families-drill-filter" title="the Lab's filter plus the square: what the worker was asked for">
        defining filter: {lines.join(' · ')}
      </div>
      <div className="drill-table">
        <TrialTable data={data} sort={sort} onSort={onSort} onSelect={onSelect} memory={memory} filter={filter} />
      </div>
    </div>
  );
}

export function FamiliesPage({
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
  const lab = useLab();
  const dispatch = useLabDispatch();
  const { loaded, loading } = data;
  const list = useMemo(() => (loaded ? sourceFamilies(loaded) : null), [loaded]);

  // The picked trellis square, kept as the filter that defines it, is the Lab's: leaving the page does not lose it, and another
  // source (which has other pairs) or the filter's Clear takes it away.
  const pick = lab.familiesPick;
  const choose = useCallback((next: TrellisPick) => dispatch({ type: 'SET_FAMILIES_PICK', pick: next }), [dispatch]);
  // The neighbourhood map shows the pair of the picked square, else the pair the heatmap is on.
  const axes = pick !== null ? pick.axes : lab.axes;

  return (
    <div className={'lab-body' + (lab.maximized ? ' maximized' : '')}>
      {/* Maximize hides the tree and does not unmount it: its search text and collapsed families survive a Restore. */}
      <ParameterCatalog list={list} mode="families" loading={loading} parameters={data.summary?.parameters ?? null} hidden={lab.maximized} />
      <div className="lab-families" id="lab-families" data-maximized={lab.maximized ? 'true' : 'false'}>
        <div className="families-toolbar">
          <ScopeBreadcrumb data={data} />
          <button
            type="button"
            className="btn btn-ghost lab-maximize"
            id="lab-families-maximize"
            aria-pressed={lab.maximized}
            title={lab.maximized ? 'Restore the parameter tree (Esc)' : 'Give the panels the whole body (Esc restores)'}
            onClick={() => dispatch({ type: 'SET_MAXIMIZED', maximized: !lab.maximized })}
          >
            {lab.maximized ? 'Restore' : 'Maximize'}
          </button>
        </div>
        {loaded === null ? (
          <div className="lab-empty" id="lab-families-empty">
            {loading ? 'Loading…' : 'No source open: choose one in the context bar.'}
          </div>
        ) : (
          <>
            <section className="families-section" id="lab-families-parallel-section">
              <div className="families-title">Parallel coordinates</div>
              <div className="families-parallel">
                <ParallelCoords data={data} />
              </div>
            </section>
            <section className="families-section" id="lab-families-trellis-section">
              <div className="families-title">Trellis of the top pairs</div>
              <Trellis data={data} pick={pick} onPick={choose} />
            </section>
            <section className="families-section" id="lab-families-importance-section">
              <div className="families-title">Importance &amp; interaction strength</div>
              <ImportanceView data={data} />
            </section>
            <section className="families-section" id="lab-families-neighbourhood-section">
              <div className="families-title">Robust neighbourhood</div>
              <NeighbourhoodMap data={data} axes={axes} />
            </section>
            <section className="families-section" id="lab-families-drill-section">
              <Drilldown data={data} pick={pick} sort={sort} onSort={onSort} onSelect={onSelect} memory={memory} />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
