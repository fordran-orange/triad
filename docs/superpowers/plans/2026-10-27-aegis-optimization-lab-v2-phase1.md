# Aegis Optimization Lab v2, Phase 1: the Lab shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Optimization Lab page to the Aegis workstation: Screen B's layout with its regions bound to the experiment and optimizer endpoints that exist today, the Lab's selection store that survives sub-view navigation, `Expand Lab` from the compact dock, Screen H's six-step workflow strip, honest "not built" states for everything later phases bring, and the walk items that prove it at 1672 × 941 and 1440 × 900.

**Architecture:** A new `ui/src/lab/` folder. Pure TypeScript modules (`labStore.ts`, `trialWindow.ts`, `workflow.ts`, `catalog.ts`) hold every decision and are unit-tested under vitest's node environment; React components in the same folder render them and are proven by the Playwright walk (no DOM test environment exists). The workspace store gains a page `'optlab'` and a `Focus.lab` hand-off from the dock. No backend, engine, contract or dependency changes: the Lab reads `api.experiments / experiment / experimentReport / experimentCells / refineExperiment / job / optimizeMatrix` as they are.

**Tech Stack:** React 18, TypeScript, Vite 5, vitest (node, `src/**/*.test.ts` only), Playwright walk `tests/products/aegis/browser_workstation.py`. No new dependency.

**Spec:** `docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md` — §5 conventions and §5.2 (Screen B), §5.1 (the dock), §5.8 (Screen H sequencing), §5.9, §11 Phase 1, §12 (charting decision: DOM and SVG only in this phase), §15 rows 10 and 17, §16 R2; the brief `docs/superpowers/specs/2026-10-27-aegis-optimization-lab-v2-brief.md` §5 and §6.

## Global Constraints

- No new Python or JS dependency; `package.json` dependencies unchanged.
- No change under `app/products/aegis/*.py`, `app/trading_core`, `app/platform_host`, `app/products/triad`; `contracts.ts` unchanged, so `python tools/aegis_contracts.py --check` still passes.
- Base font 12 px; nothing below 11 px; status and secondary text ≥ 4.5:1 on `--panel` (the existing `--muted #7690a3` on `#0b1520` is ≈ 5.7:1 and is the only secondary colour used).
- Losing money is red, always; the existing `Heatmap` tones and `lowerIsBetter` rule are reused, never re-implemented.
- Every value the Lab shows comes from a response; no mock values; every unavailable control carries its reason as visible text or a `title`.
- Walk items 1–97 are untouched; the Lab items are appended as a delimited block whose numbers follow whatever precedes them (Mission 14's uncommitted items 98–102 may land first), with the plan's nominal numbers 103–106 and 126 noted in the titles.
- The compact dock keeps its ids and behaviour (walk items 1–97); it gains only `Expand Lab`, the aggregated label and the validation line.
- Lint through `bash tools/lint_aegis.sh` only (never a bare `ruff`); commit messages written with the Write tool and `git commit -F`, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Browser evidence for this phase comes from the Vite dev server of this checkout (`npm run dev` in `app/products/aegis/ui`, port 5181, API proxied to the running 8102 worker, which already carries Mission 14's code); the walk runs with `--base http://127.0.0.1:5181/aegis/ --only lab`. The 8102 worker is never restarted by this phase.

## Review Focus

1. **A job with fewer than three parameters** (the dock shows no axis selects when `axisChoices(job).length < 3`). Expected: `Expand Lab` still opens the Lab with `[job.fast_path, job.slow_path]` as the axes and the dock's metric. Test: `labStore.test.ts::OPEN_SOURCE from a two-parameter job`.
2. **An experiment without a report** (`latest_report` null, e.g. still running or never reported). Expected: the Importance tab says "no report yet", the KPI strip shows progress only, nothing throws. Test: walk Lab-3 asserts the text on a running experiment; `workflow.test.ts::no report`.
3. **An experiment that is running while the Lab shows it.** Expected: the context bar shows `PROVISIONAL · updates every 2 s`, the table re-fetches its window and the selection and pins survive the refresh. Test: `labStore.test.ts::ROWS_REFRESHED keeps selection and pins`.
4. **A focus that names a missing experiment or job** (deleted, or a stale link). Expected: the page shows `experiment not found: <id>` with the picker, never a blank page or an uncaught promise. Test: `labStore.test.ts::SOURCE_FAILED` and walk Lab-3's `#lab-source-error` probe.
5. **Keyboard shortcuts while typing.** Expected: `1`/`2`/`3`/arrows/Esc typed inside the catalog search box or any input never pin, move or clear; Esc with nothing to clear is a no-op, never a navigation. Test: `labStore.test.ts::ESCAPE with nothing to clear is identity`; the key handler ignores editable targets (walk Lab-2 types `1` in the search box and asserts no pin).

---

### Task 1: Page, navigation and the dock hand-off (workspace plumbing)

**Files:**
- Modify: `app/products/aegis/ui/src/state/workspace.tsx:15` (`Page`), `:18-24` (`Focus`)
- Modify: `app/products/aegis/ui/src/components/SideNav.tsx:3-13`
- Modify: `app/products/aegis/ui/src/App.tsx:95-121`
- Modify: `app/products/aegis/ui/src/styles.css` (append `.optlab-main`)
- Create: `app/products/aegis/ui/src/lab/OptLabPage.tsx` (a stub this task: `<div id="optlab-page">Optimization Lab</div>`)
- Test: `app/products/aegis/ui/src/state/workspace.test.ts`

**Interfaces:**
- Produces: `export type Page = 'charts' | 'lab' | 'library' | 'experiments' | 'optlab'`; `export interface Focus { …; lab?: LabFocus }` with `export interface LabFocus { source: string; axes?: [string, string]; metric?: string }` (`source` is `exp:<experiment_id>` or `opt:<job_id>`; parsed by Task 2's `parseSource`).
- Consumes: the existing `SET_PAGE { page, focus? }` and `CLEAR_FOCUS` actions, unchanged.

- [ ] **Step 1: Write the failing test** (append to `workspace.test.ts`)

```ts
it('opens the Optimization Lab with a lab focus and clears it', () => {
  const opened = reducer(initialState(), { type: 'SET_PAGE', page: 'optlab', focus: { lab: { source: 'opt:job-1', axes: ['a', 'b'], metric: 'mar' } } });
  expect(opened.page).toBe('optlab');
  expect(opened.focus?.lab?.source).toBe('opt:job-1');
  expect(reducer(opened, { type: 'CLEAR_FOCUS' }).focus).toBeNull();
});
```

- [ ] **Step 2: Run it to see it fail**

Run (from `app/products/aegis/ui`): `npm test -- src/state/workspace.test.ts`
Expected: FAIL with a type error on `'optlab'` / `lab` (tsc in vitest) or an undefined `lab`.

- [ ] **Step 3: Implement** the `Page` and `Focus` extensions, the `SideNav` entry `{ label: 'Optimization Lab', page: 'optlab', id: 'nav-optlab' }` placed after Experiments and before Paper Trade, the `App.tsx` branch `page === 'optlab' ? <section className="optlab-main"><OptLabPage /></section>` with `gridTemplateRows: 'minmax(0, 1fr)'` (add `'optlab'` to the existing `page === 'library' || page === 'lab'` condition), the CSS `.optlab-main{min-height:0;min-width:0;overflow:hidden}`, and the stub page.

- [ ] **Step 4: Run the tests and the build**

Run: `npm test` then `npm run build`
Expected: all vitest files PASS; `tsc --noEmit` clean; `vite build` succeeds.

- [ ] **Step 5: Commit**

```bash
git add app/products/aegis/ui/src/state/workspace.tsx app/products/aegis/ui/src/state/workspace.test.ts app/products/aegis/ui/src/components/SideNav.tsx app/products/aegis/ui/src/App.tsx app/products/aegis/ui/src/styles.css app/products/aegis/ui/src/lab/OptLabPage.tsx
git commit -F <message file>   # "Optimization Lab: page, nav entry and the dock's lab focus"
```

---

### Task 2: The Lab store (pure reducer, filter hash, source parsing)

**Files:**
- Create: `app/products/aegis/ui/src/lab/labStore.ts`
- Test: `app/products/aegis/ui/src/lab/labStore.test.ts`

**Interfaces (Produces):**

```ts
export type LabSource = { kind: 'exp' | 'opt'; id: string };
export function parseSource(text: string): LabSource | null;          // 'exp:<id>' | 'opt:<id>'; null otherwise
export function sourceText(source: LabSource): string;                // the inverse
export type LabView = 'monitor' | 'trials' | 'families' | 'variables' | 'walkforward' | 'lineage' | 'compare';
export type LabScope = 'combined' | 'long' | 'short';
export type LabMode = 'exact' | 'aggregate';
export type LabStat = 'best' | 'median' | 'mean' | 'worst';
export interface LabFilter { ranges: Record<string, [number, number]>; values: Record<string, number>; scope: LabScope; pass: string[]; status: string[] }
export type LabSelection = { trials: string[] } | { square: { x: number; y: number } } | null;
export type PinSlot = 'A' | 'B' | 'C';
export interface LabState {
  source: LabSource | null; sourceError: string | null; view: LabView; filter: LabFilter;
  axes: [string, string] | null; mode: LabMode; stat: LabStat; metric: string; objectives: string[];
  selected: LabSelection; pins: Partial<Record<PinSlot, string>>; cursor: { r: number; c: number } | null; maximized: boolean;
}
export type LabAction =
  | { type: 'OPEN_SOURCE'; source: LabSource; axes?: [string, string]; metric?: string }
  | { type: 'SOURCE_FAILED'; message: string }
  | { type: 'SET_VIEW'; view: LabView } | { type: 'SET_AXES'; axes: [string, string] } | { type: 'SET_MODE'; mode: LabMode }
  | { type: 'SET_STAT'; stat: LabStat } | { type: 'SET_METRIC'; metric: string } | { type: 'SET_SCOPE'; scope: LabScope }
  | { type: 'SET_RANGE'; path: string; range: [number, number] | null } | { type: 'FIX_VALUE'; path: string; value: number | null }
  | { type: 'SELECT_TRIALS'; ids: string[] } | { type: 'SELECT_SQUARE'; x: number; y: number } | { type: 'CLEAR_SELECTION' }
  | { type: 'PIN'; slot: PinSlot; trialId: string } | { type: 'UNPIN'; slot: PinSlot }
  | { type: 'MOVE_CURSOR'; dr: number; dc: number; rows: number; cols: number } | { type: 'ESCAPE' } | { type: 'SET_MAXIMIZED'; maximized: boolean }
  | { type: 'ROWS_REFRESHED' };
export const initialLabState: LabState;   // view 'trials', mode 'exact', stat 'best', metric 'net_pnl', scope 'combined', objectives ['net_pnl', 'max_drawdown']
export function labReducer(state: LabState, action: LabAction): LabState;
export function canonicalFilter(filter: LabFilter): string;            // sorted keys, ranges as [lo, hi] with lo ≤ hi
export function filterHash(filter: LabFilter): string;                 // FNV-1a 32-bit over canonicalFilter, 8 hex chars
export function activeFilterCount(filter: LabFilter): number;          // ranges + values + (scope !== 'combined') + pass + status
```

Rules the reducer enforces (each is a test): `OPEN_SOURCE` resets filter, selection, pins, cursor and `sourceError`, keeps `view`, and takes `axes` / `metric` when given; `SOURCE_FAILED` sets `sourceError` and clears `source`; `SET_VIEW` changes nothing but `view`; `SET_RANGE` with `null` removes the key, and a reversed pair is stored ordered; `SELECT_SQUARE` sets `selected = { square }`; `PIN` is refused (state returned unchanged) when `selected` is a square or the slot's id equals the given id, and A/B/C hold at most three distinct ids; `MOVE_CURSOR` clamps to `[0, rows-1] × [0, cols-1]` and starts at `(0, 0)` when `cursor` is null; `ESCAPE` clears all ranges and values when any exist, else sets `maximized = false` when true, else returns the same object (identity); `ROWS_REFRESHED` returns the same object (selection and pins survive; the action exists so the table can mark refreshes).

- [ ] **Step 1: Write the failing tests** in `labStore.test.ts`: one `it` per rule above, plus `parseSource('opt:j1')`, `parseSource('nonsense') === null`, `sourceText(parseSource('exp:e1')!) === 'exp:e1'`, `filterHash` equal for `{ranges: {a:[1,2], b:[3,4]}}` and `{ranges: {b:[3,4], a:[1,2]}}` and different once a bound changes, `activeFilterCount` of `initialLabState.filter` is 0 and of one range + scope long is 2, and the Review Focus items 1, 3 and 5.

- [ ] **Step 2: Run them to see them fail**: `npm test -- src/lab/labStore.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `labStore.ts`** with the signatures above. FNV-1a: `h = 0x811c9dc5; for each UTF-16 code unit: h ^= unit; h = Math.imul(h, 0x01000193) >>> 0`; hex-pad to 8.

- [ ] **Step 4: Run the tests**: `npm test -- src/lab/labStore.test.ts` → PASS.

- [ ] **Step 5: Commit** `app/products/aegis/ui/src/lab/labStore.ts` and its test: "Optimization Lab: the Lab store, its filter hash and source parsing".

---

### Task 3: Row windowing math

**Files:**
- Create: `app/products/aegis/ui/src/lab/trialWindow.ts`
- Test: `app/products/aegis/ui/src/lab/trialWindow.test.ts`

**Interfaces (Produces):**

```ts
export const ROW_HEIGHT = 22;
export const OVERSCAN = 10;
export const PAGE_LIMIT = 500;
export interface RowWindow { start: number; end: number; padTop: number; padBottom: number }  // rows [start, end), pads in px
export function windowRows(input: { total: number; scrollTop: number; viewportHeight: number; rowHeight?: number; overscan?: number }): RowWindow;
export function pageFor(window: RowWindow, limit?: number): { offset: number; limit: number };   // offset = window.start, limit = min(PAGE_LIMIT, end − start), never 0 unless total is 0
```

- [ ] **Step 1: Failing tests**: at `scrollTop 0`, `viewportHeight 440`, total 10,000 → `start 0`, `end 30` (20 visible + 10 overscan), `padTop 0`, `padBottom = (10000 − 30) × 22`; at the bottom (`scrollTop = 10000 × 22 − 440`) → `end === 10000`, `start === 10000 − 30`; the invariant `padTop + (end − start) × 22 + padBottom === total × 22` for 50 random inputs (seeded loop); `total 0` → `{0, 0, 0, 0}` and `pageFor` → `{ offset: 0, limit: 0 }`; `end − start ≤ visible + 2 × overscan`; `pageFor` caps `limit` at 500.
- [ ] **Step 2: Run to see failure.** `npm test -- src/lab/trialWindow.test.ts`
- [ ] **Step 3: Implement.** `visible = ceil(viewportHeight / rowHeight)`, `first = floor(scrollTop / rowHeight)`, `start = max(0, first − overscan)`, `end = min(total, first + visible + overscan)`.
- [ ] **Step 4: Run to pass.**
- [ ] **Step 5: Commit** "Optimization Lab: windowed row math for the trial table".

---

### Task 4: The workflow strip's step states and the parameter catalog's families

**Files:**
- Create: `app/products/aegis/ui/src/lab/workflow.ts`, `app/products/aegis/ui/src/lab/catalog.ts`
- Test: `app/products/aegis/ui/src/lab/workflow.test.ts`, `app/products/aegis/ui/src/lab/catalog.test.ts`

**Interfaces (Produces):**

```ts
// workflow.ts
export type StepState = 'live' | 'done' | 'disabled';
export interface WorkflowStep { key: 'define' | 'screen' | 'evaluate' | 'propose' | 'approve' | 'monitor'; label: string; state: StepState; reason?: string }
export const WORKFLOW_LABELS: Record<WorkflowStep['key'], string>;  // 'Define variables', 'Run screening', 'Evaluate importance and interactions', 'Review search-space proposal', 'Approve large sweep', 'Monitor results'
export function workflowSteps(input: { hasExperiment: boolean; hasReport: boolean }): WorkflowStep[];
// Phase 1: define = hasExperiment ? 'done' : 'live'; screen = 'disabled', reason 'screening experiments arrive in Phase 3';
// evaluate, propose, approve, monitor = 'disabled', reason 'available after Phase 4' (monitor: 'the Run Monitor arrives in Phase 5').

// catalog.ts
export interface CatalogEntry { path: string; side: 'long' | 'short'; family: string; field: string; start: number; stop: number; step: number; count: number }
export interface Family { key: string; label: string; side: 'long' | 'short'; entries: CatalogEntry[] }
export function parameterCount(p: { start: number; stop: number; step: number }): number;   // Math.floor((stop − start) / step + 1e-9) + 1, as surface.py
export function families(surface: Surface, spec: StrategySpec | null): Family[];            // grouped by side then indicator id ('levels' for stop_loss_pct / take_profit_pct); label 'long · ema (EMA 9)' from the spec's indicator kind and length when the spec is given, else 'long · ema'
export function searchFamilies(list: Family[], text: string): Family[];                      // case-insensitive substring over family label, path and field; empty text returns the list
```

- [ ] **Step 1: Failing tests.** `workflow.test.ts`: no experiment → `define` live and every other step disabled with a reason containing 'Phase'; with an experiment → `define` done; exactly six steps in the fixed order. `catalog.test.ts`: a surface of `long_side.indicators.ema.length 5–20/1`, `long_side.indicators.sma.length 20–100/5`, `long_side.stop_loss_pct 1–5/0.5`, `short_side.indicators.ema.length 5–20/1` → three families for long (`ema`, `sma`, `levels`) and one for short, counts 16, 17, 9, 16; `searchFamilies(list, 'stop')` keeps only `levels`; `parameterCount({start: 2, stop: 10, step: 1})` is 9 and the 0.5-step case has no floating-point off-by-one.
- [ ] **Step 2: Run to fail.** `npm test -- src/lab/workflow.test.ts src/lab/catalog.test.ts`
- [ ] **Step 3: Implement** both modules. Paths follow `surface.py:100-122`: `<side>_side.indicators.<id>.length|params.<name>` and `<side>_side.stop_loss_pct|take_profit_pct`.
- [ ] **Step 4: Run to pass.**
- [ ] **Step 5: Commit** "Optimization Lab: workflow step states and parameter families".

---

### Task 5: The Lab page: provider, sub-nav, context bar, KPI strip, catalog, centre tabs, trial table, rail

**Files:**
- Create: `app/products/aegis/ui/src/lab/labState.tsx` (`LabProvider`, `useLab()`, `useLabDispatch()` over `labReducer`), `LabSubNav.tsx`, `LabContextBar.tsx`, `LabKpiStrip.tsx`, `ParameterCatalog.tsx`, `LabCenter.tsx`, `TrialTable.tsx`, `IntelligenceRail.tsx`, `NotBuilt.tsx`, `LinkedChip.tsx`, `VariableIntelligence.tsx`, `WorkflowStrip.tsx`, `useLabKeys.ts`
- Modify: `app/products/aegis/ui/src/lab/OptLabPage.tsx` (replace the stub), `app/products/aegis/ui/src/styles.css` (append the Lab rules)

**Interfaces:**
- Consumes: Tasks 2–4; `api.experiments()`, `api.experiment(id)`, `api.experimentReport(id)`, `api.experimentCells(id, { offset, limit, sort, descending })`, `api.refineExperiment(id)`, `api.job(id)`, `api.optimizeMatrix(id, rows, cols, metric)`, `api.strategyDocument(id)`; `MainEffects` (`components/MainEffects.tsx:7`), `Heatmap` (`components/Heatmap.tsx:72`), `recommendationText` and `surfaceLine` (`experiments.ts`), `useWorkspace().focus.lab`, `useDispatch()` (`CLEAR_FOCUS` after adopting the focus).
- Produces (DOM contract for the walk): ids `#optlab-page`, `#lab-subnav` with `#lab-view-{monitor|trials|families|variables|walkforward|lineage|compare}`, `#lab-source` (a `<select>` of experiments newest first, plus the `opt:` entry when opened from the dock), `#lab-source-error`, `#lab-scope-{long|short|both}`, `#lab-metric` (`<select>` of the ten objectives), `#lab-regime` (text `Regimes: not in this strategy`), `#lab-events` (`Event windows: feed unavailable`), `#lab-partition` (`Partition: none (no partition on this experiment)` or `Partition: none (grid job)`), `#lab-status` (badge; while `running`/`queued` the text `PROVISIONAL · updates every 2 s`), `#lab-kpis` with `[data-kpi]` cells (`trials`, `valid`, `planned`, `coverage`, `best`, `failed`), `#lab-catalog` with `#lab-catalog-search`, `.family` with `.family-toggle`, `input[type=radio][name=lab-axis-x][data-path]`, `input[type=radio][name=lab-axis-y][data-path]`, `input[type=number].range-lo[data-path]` / `.range-hi[data-path]`, `#lab-tabs` with `button.lab-tab[role=tab]#lab-tab-{heatmap|interactions|parallel|pareto|importance|robustness}`, `#lab-center`, `.not-built` panels (text `<Name>: arrives in Phase <n> (plan §11)`), `#trial-table` with `thead th[data-sort]`, `tbody tr[data-trial]` (`.selected` on the selected row; `tabIndex=0`), `.trial-pad-top` / `.trial-pad-bottom` spacer rows, `#lab-pin-{A|B|C}` buttons and `#lab-pins` showing the pinned ids, `#lab-linked` (`Linked · k filters`, click lists them with `#lab-linked-clear`), `#lab-rail` with `#lab-findings`, `#lab-ai` (`AI explanations: Phase 8 · AI explains, it never decides`), `#lab-selected`, `#lab-gate` (`Strategy Gate: not built`), `#lab-provenance` with `#lab-copy-json`, `#lab-refine` (`Queue focused follow-up sweep`), `#workflow-strip` with `.workflow-step[data-key][data-state]` and a `title` holding the reason when disabled.

Behaviour (no code here; the plan fixes what, the implementer writes how):
- `OptLabPage` mounts `LabProvider`; on mount, if `focus.lab` is set it dispatches `OPEN_SOURCE` with `parseSource(focus.lab.source)`, `axes` and `metric`, then `CLEAR_FOCUS`; otherwise it lists experiments and opens the newest `done` one when none is open. Loading an `exp` source fetches the document, then the report when `latest_report` is set, then the strategy document name (fallback `spec.name`); a failure dispatches `SOURCE_FAILED` with `errorMessage(error)` and the picker stays usable. Loading an `opt` source fetches `api.job(id)`; its rows are `job.cells` (no paging), its heatmap is `api.optimizeMatrix(job_id, axes[0], axes[1], metric)` rendered by the existing `Heatmap` with the title `Aggregated: best of the rest` and `detail` showing `n` from `counts`; `#lab-refine` is disabled with `title="a grid job has no experiment to refine"`.
- While the source's status is `running` or `queued`, a 2-second interval re-fetches it (and the cells window) and dispatches `ROWS_REFRESHED`; the badge reads `PROVISIONAL · updates every 2 s`.
- `LabKpiStrip` reads `progress.cells_done` / `cells_planned`, the report's `valid_cells` and `null_objective_cells` when present (else `—`), `coverage = valid / planned` as a percentage, `best` from `report.recommendation` (else `—`), `failed` from `document.error ? 1 : 0`. Every `—` carries `title="no report yet"` or `"not in this job"`.
- `ParameterCatalog` shows `families(surface, spec)` (for an `opt` source: the job's two paths as one family per side), collapsible, searchable (Task 4), with the X / Y radios writing `SET_AXES` and the range inputs writing `SET_RANGE` on change (empty both → `null`).
- `LabCenter` tabs: Heatmap → `exp`: `<NotBuilt what="Exact slices and aggregated projections" phase={2} />`; `opt`: the dock's matrix as above. Interaction matrix → NotBuilt 3. Parallel coords → NotBuilt 2 ("the vertical slice"). Pareto → NotBuilt 3. Importance → `exp` with a report: `<MainEffects effects={report.main_effects} objective={report.objective} lowerIsBetter={report.objective === 'max_drawdown'} />` under a basis label `Aggregated from tested (median per value)`; without a report: `no report yet: recompute it on the Experiments page`; `opt`: NotBuilt 2. Robustness → NotBuilt 3. Each panel starts with the basis label from the plan's conventions where it shows data.
- `TrialTable`: `exp` rows from `api.experimentCells` using `windowRows` on the container's `scrollTop` / `clientHeight` and `pageFor`; columns `cell`, every surface path, `<scope>.<metric>` for the current scope and metric, `valid`; sort by header click (`sort`, `descending` to the API); row click → `SELECT_TRIALS [id]` where the trial id is `exp:<id>#<cell>`; keyboard: ArrowUp/Down move focus between rows and select; rendered `tr[data-trial]` count ≤ visible + 20 (walk Lab-4 counts them). `opt` rows: `job.cells` sorted client-side by the metric.
- `IntelligenceRail`: findings = `report.statement` and `recommendationText(report)` (or `no report yet`); the AI block; the selected trial card (params from the row, the four metrics for the scope); risk warnings `none computed in Phase 1`; `#lab-gate`; provenance (`strategy_hash`, `data` symbol/timeframe/range, `engine`, `id`) with `Copy JSON` (`navigator.clipboard.writeText` guarded; a textarea fallback); `#lab-refine` → `api.refineExperiment(id)` then `OPEN_SOURCE { kind: 'exp', id: child.id }`.
- `VariableIntelligence` (view `variables`): `WorkflowStrip` from `workflowSteps({ hasExperiment, hasReport })`, the catalog in status mode where every entry shows the chip `Active (default)` with `title="no screening evidence yet: all parameters Active (Phase 4)"`, the line `no screening evidence: all parameters Active`, and the rail.
- The other views (`monitor`, `families`, `walkforward`, `lineage`, `compare`) render one `NotBuilt` each naming its phase (5, 3, 6, 6, 5), still inside the layout with the context bar, so navigation never loses the store (Task 2 `SET_VIEW`).
- `useLabKeys` on `#optlab-page`: ignores events whose target is an `input`, `select`, `textarea` or `[contenteditable]`; Arrow keys → `MOVE_CURSOR` only when the heatmap tab shows a matrix (rows/cols known); Enter → `SELECT_SQUARE` at the cursor; `1`/`2`/`3` → `PIN` the single selected trial into A/B/C; Escape → `ESCAPE`.
- `LinkedChip` appears in the context bar and on every panel that reads the filter (`activeFilterCount(filter)`), with the listing and `Clear` (dispatching `SET_RANGE null` / `FIX_VALUE null` for each and `SET_SCOPE combined`).

CSS (append to `styles.css`): `.optlab-page{display:grid;grid-template-columns:150px minmax(0,1fr) 300px;height:100%;min-height:0}`, `.lab-subnav` (vertical, reuses `.nav`/`.nav.active` look), `.lab-main-col{display:grid;grid-template-rows:auto auto minmax(0,1fr);min-height:0}`, `.lab-context{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line)}`, `.lab-kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;padding:8px 12px;border-bottom:1px solid var(--line)}`, `.lab-body{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:0}`, `.lab-catalog{overflow:auto;border-right:1px solid var(--line);padding:8px}`, `.lab-center{display:grid;grid-template-rows:auto minmax(0,1fr) 220px;min-height:0}`, `.lab-tabs{display:flex;border-bottom:1px solid var(--line)}` reusing `.tab`, `.lab-panel{overflow:auto;padding:10px;min-height:0}`, `.trial-table{overflow:auto;border-top:1px solid var(--line)}` with `tr{height:22px}`, `.lab-rail{border-left:1px solid var(--line);overflow:auto;padding:10px;display:flex;flex-direction:column;gap:10px}`, `.not-built{padding:16px;color:var(--muted);border:1px dashed var(--line);border-radius:6px}`, `.workflow-strip{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}`, `.workflow-step{padding:6px 10px;border:1px solid var(--line);border-radius:5px}`, `.workflow-step[data-state=live]{border-color:var(--blue);color:var(--bright)}`, `.workflow-step[data-state=done]{color:var(--green)}`, `.workflow-step[data-state=disabled]{color:var(--muted);border-style:dashed}`, `.linked-chip{border:1px solid var(--line);border-radius:12px;padding:2px 8px;color:var(--muted)}`, `.status-chip{...}`, and `@media (max-width:1500px){.optlab-page{grid-template-columns:140px minmax(0,1fr) 260px}.lab-body{grid-template-columns:220px minmax(0,1fr)}}`. No font size below 11 px.

- [ ] **Step 1: Build the components** per the contract above (no unit tests: node vitest cannot render; the walk in Task 7 proves them).
- [ ] **Step 2: `npm run build`** → clean `tsc` and a successful `vite build`.
- [ ] **Step 3: Start the dev server** (`npm run dev` in the ui folder, port 5181; the 8102 worker must be up) and open `http://127.0.0.1:5181/aegis/`: Optimization Lab in the side nav, newest done experiment opened, every id above present (check with the browser's console: `['#lab-source', '#lab-gate', '#workflow-strip', '#trial-table'].map(s => !!document.querySelector(s))` after visiting Variable Intelligence).
- [ ] **Step 4: Commit** the `lab/` components and `styles.css`: "Optimization Lab: Screen B shell bound to the experiment endpoints, Screen H workflow strip".

---

### Task 6: `Expand Lab` and the honest labels on the compact dock

**Files:**
- Modify: `app/products/aegis/ui/src/components/OptimizationTab.tsx:166-260` (`OptimizationJobView`)

**Interfaces:**
- Consumes: `useDispatch()`; the component's `axes` state and its `metric`; `job.job_id`, `job.fast_path`, `job.slow_path`.
- Produces: `button#expand-lab-{side}` → `dispatch({ type: 'SET_PAGE', page: 'optlab', focus: { lab: { source: 'opt:' + job.job_id, axes: choices.length >= 3 ? axes : [job.fast_path, job.slow_path], metric } } })`; a `.sub` line under the heatmap `#dock-basis-{side}`: `Aggregated: best of the rest · empty = untested` (the dock keeps best-of-rest, Q5); `#dock-validation-{side}`: `Validation: no partition (grid job) · Strategy Gate: not built`.

- [ ] **Step 1: Implement** the three additions; the button sits in `.job-head` after the Cancel button, hidden when `library` is true (a library view has no page to go to).
- [ ] **Step 2: `npm test && npm run build`**; walk items 1–97's ids are untouched (grep the diff for removed ids: none).
- [ ] **Step 3: Commit** "Optimization dock: Expand Lab, the aggregated label and the validation line".

---

### Task 7: Walk items for the Lab (nominal 103–106, 126) and `--only lab`

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (`ITEMS` block appended after Mission 13's titles; a `LAB_BASE` constant; `--only` argument; a `run_lab()` method; the Lab block in `run()`)

**Interfaces:**
- Produces: `LAB_BASE = "1882c81"` (the merge of Mission 14 into this branch: nothing under Core may change after it); `parser.add_argument("--only", choices=["lab"], default=None)`; `Acceptance.run_lab(self, first: int)` registering six items numbered `first … first + 5` where `first = ITEMS.index(LAB_ITEMS[0]) + 1` and `LAB_ITEMS` is the appended block (so the numbers follow whatever precedes them); `main()` runs `acceptance.run_lab(first)` alone when `--only lab`, else `run()` then `run_lab(first)`; the report gains `"lab_only": bool` and `"lab_first_item": first`.
- Fixtures the Lab block makes for itself through `self.page.request` (so `--only lab` needs nothing from items 1–97): a small optimization (`POST api/optimize` on the built-in strategy, long side, `fast 5–7 step 1`, `slow 20–30 step 5`, QQQ 1h 2024-01-02 → 2024-03-28; wait for `done` via `GET api/optimize/{id}` with `wait_until`) and a small experiment (`POST api/experiments` with a two-parameter surface `long_side.indicators.ema.length 5–7/1 × long_side.indicators.sma.length 20–30/5`, `budget {runs: 9}`, same data; wait for `done`; `POST api/experiments/{id}/report` with `{}`), both named `lab-walk-<stamp>` and recorded in the report; they are left in the store like the walk's other fixtures.

The six items (titles in `LAB_ITEMS`, each starting with its nominal number):
1. `"(103) Expand Lab opens the Optimization Lab with the dock's axes and metric kept"`: Charts page → the Optimization tab (the walk's existing helper that opens it; grep `tab-optimization`), the long job selected, click `#expand-lab-long`; assert `#optlab-page` visible, `#lab-source` value `opt:<job_id>`, the Heatmap axes text contains the job's `fast_path` and `slow_path` labels, `#lab-metric` value equals the dock's metric.
2. `"(104) the Lab's sub-nav keeps the filter, the selection and the pins across Trial Lab → Parameter Families → Run Monitor → Trial Lab"`: open the experiment source via `#lab-source`; set `.range-lo[data-path="long_side.indicators.ema.length"]` to 6; click the first `tr[data-trial]`; click `#lab-pin-A`; type `1` into `#lab-catalog-search` and assert `#lab-pin-B` is empty (Review Focus 5); click `#lab-view-families`, `#lab-view-monitor`, `#lab-view-trials`; assert `#lab-linked` reads `Linked · 1 filter`, the same row is `.selected`, `#lab-pins` contains the pinned id.
3. `"(105) every unavailable Lab control says why: gate not built, regimes not in this strategy, event feed unavailable, no partition, later phases named"`: assert the texts of `#lab-gate`, `#lab-regime`, `#lab-events`, `#lab-partition`, `#lab-ai`; count `.not-built` across the six tabs and the five placeholder views ≥ 9, each matching `/Phase \d/`; `#lab-refine` enabled for the experiment and disabled with a `title` for the `opt:` source; a bogus `#lab-source` value `exp:does-not-exist` (set through the select's change handler via `page.select_option` on an injected option, or `page.evaluate` dispatching the store action if exposed as `window.__lab`) shows `#lab-source-error` containing `does-not-exist` (Review Focus 4).
4. `"(106) at 1672 × 941 and at 1440 × 900 no primary Lab control is clipped, every text is ≥ 11 px and secondary text keeps ≥ 4.5:1"`: for each size `page.set_viewport_size`, `page.screenshot(self.screenshot_path(f"lab-{w}x{h}"))` (not full-page), assert every element in `#lab-subnav button, #lab-source, #lab-scope-both, .lab-tab, #lab-pin-A, #lab-refine, #lab-catalog-search` has `boundingBox` with `x ≥ 0`, `y ≥ 0`, `x + width ≤ w`, `y + height ≤ h`; a `page.evaluate` walks `#optlab-page` text nodes for `parseFloat(getComputedStyle(el).fontSize) ≥ 11`; computes contrast of `.workflow-step[data-state=disabled]`, `.not-built` and `.sub` colour against their nearest opaque background (relative luminance per WCAG; the implementer writes the ~20-line JS) ≥ 4.5; `tr[data-trial]` count ≤ visible rows + 20; then restores `{1600, 1000}`.
5. `"(126) Variable Intelligence shows the six-step workflow strip with the later steps disabled and explained"`: `#lab-view-variables`; `#workflow-strip .workflow-step` count 6 with labels in `WORKFLOW_LABELS` order; first `data-state` in `{live, done}`; the other five `disabled` with `title` matching `/Phase \d/`.
6. `"governance unchanged since the Optimization Lab v2 plan (LAB_BASE) and the Lab items pass"`: `status` `human_directed` / `CLOSED` through the 8000 gateway as item 97 does; the DailySchedule disabled; `git diff --name-only LAB_BASE HEAD -- app/trading_core app/platform_host app/products/triad` empty and no pending changes there; every Lab item before this one PASS.

- [ ] **Step 1: Append `LAB_ITEMS`, `LAB_BASE`, `--only` and `run_lab`** following the item/`ITEMS` pattern (`browser_workstation.py:228-240`, `:4220-4262`).
- [ ] **Step 2: Run the Lab block** with the dev server up: `C:\Triad\.venv-aegis\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:5181/aegis/ --only lab` from this checkout, with `PYTHONPATH` set to `<worktree>\app;<worktree>\tests`. Expected: `6/6 PASS` for the Lab block, the report JSON under `logs/` with `lab_only: true`, and the two screenshots `logs/aegis-acceptance-<stamp>-lab-1672x941.png` and `-lab-1440x900.png`.
- [ ] **Step 3: Lint** `bash tools/lint_aegis.sh` → ok (the walk file is in scope).
- [ ] **Step 4: Commit** "Optimization Lab walk: Expand Lab, linked state, honest states, both widths, the workflow strip, governance".

---

### Task 8: Phase checks and the R2 hand-off

- [ ] **Step 1:** `npm test` (all files), `npm run build`, `python tools/aegis_contracts.py --check` (no contract change), `bash tools/lint_aegis.sh`, and the `--only lab` walk once more on the final build; record the walk report path and the two screenshot paths.
- [ ] **Step 2:** Compare the two screenshots with UX Pilot B (`ZaslUVrP3YsPnEfVCUmi`) and H (`VVOsme6275ULO1u0dISZ`) side by side (read-only `get-design-preview`), and write `logs/lab-phase1-r2.md`: what matches, what differs and why (Phase 1 shows DOM placeholders where later phases bring canvases), the walk summary line, the host.
- [ ] **Step 3: Commit** the note; hand over for checkpoint **R2** (Randall: the shell matches the approved designs, honest states, nothing clipped at either width).

## Self-review notes

- Spec coverage: §5.2 regions → Task 5; §5.1 dock additions → Task 6; §5.8 strip → Tasks 4–5; §11 Phase 1 tests (`labStore`, `trialWindow`, `workflowStrip`) → Tasks 2–4; walk 103–106 and 126 → Task 7; both widths → Task 7 item 4 and Task 8.
- Types used across tasks: `LabFocus` (Task 1) is parsed by `parseSource` (Task 2); `windowRows` / `pageFor` (Task 3) drive `TrialTable` (Task 5); `workflowSteps` (Task 4) drives `WorkflowStrip` (Task 5); `families` / `searchFamilies` (Task 4) drive `ParameterCatalog` (Task 5).
- Not in this phase: any `/lab` route, Parquet layout, `sharpe_trade`, canvases, the scratch worker (all Phase 2+); the dock's heatmap stays the DOM `Heatmap`.
