# Aegis Optimization Lab v2 — UX Pilot Prompt and Claude Implementation Brief

**Prepared:** 2026-10-27  
**Status:** UX Pilot screens A/B/C/D/E/F/G completed; UX Pilot's dedicated **Screen H — Variable Intelligence & Search-Space Design** is prepared on the same canvas and awaits `Start generating` and review. **No implementation authorized by this brief.**  
**Product contract:** UI/UX first. Design the boxes and interactions; then implement functionality to fit the approved experience.
**Superseding design principle (2026-10-27):** **Aegis must identify, rank, explain, and selectively explore meaningful parameters and interactions, while preserving the ability to investigate any valid combination manually.** It must not exhaustively visualize every variable pair by default, or permanently eliminate parameters based only on weak observed marginal importance.

## 1. Purpose and boundaries

Replace the *limitations* of Aegis's two-parameter optimization analysis—not the existing Aegis visual identity—with a research-grade, high-dimensional Optimization Lab capable of making 5–20 variables understandable, beginning with roughly 10 HA-MQI variables, and **navigating up to 1,000,000 evaluated trial configurations without rendering them all directly**.

The present optimization surface is a two-axis heatmap (e.g. Fast MA × Slow MA), a metric selector, and a Top-10 table docked below the chart. Keep this as the compact view. Expand into a full center-workspace Optimization Lab on demand.

**Locked visual baseline:** the accepted 1672 × 941 dark navy workstation screenshot and the editable UX Pilot AegisQuant design: https://uxpilot.ai/a/ui-design?page=lTHZGNbkbJqGnXSWW4IR . This is a reference from earlier work; the project link has not been re-verified in this session. Preserve chart-dominant density, compact top command bar, narrow navigation, thin separators, contextual left rail, right intelligence rail, docked analysis/results, persistent KPI/status strip. No marketing cards, giant spacing, unrelated redesign, or generic dashboard.

Keep the existing modes—Chart Analysis, Strategy Editing, Experiment Comparison, Backtest Review, AI Investigation—and add/expand Optimization Lab as an integrated mode. Do not replace Core, Aegis's backtest engine, the vector node engine, experiment store, or the deterministic Strategy Gate.

### Revised primary research workflow

The highest-level optimization workflow is now:

1. **Define candidate strategy dimensions:** expose every typed indicator, filter, execution, temporal, and long/short parameter, with structurally valid ranges/dependencies.
2. **Screen structural and empirical relevance:** deterministically identify truly inactive/unreachable parameters; statistically estimate conditional and main effects with uncertainty across the explored ranges.
3. **Investigate selected interactions:** prioritize high-value and uncertain pairs/higher-order combinations, including weak individual variables with strong joint effect. Do not require 190 miniature pair plots when 20 variables exist.
4. **Approve a versioned search-space proposal:** distinguish active, investigate, deprioritized, excluded, and temporarily frozen parameters; preserve reasons, evidence, manual overrides, and the ability to reactivate a variable.
5. **Allocate exploration/refinement budget:** use up to one million appropriately sampled fast trial evaluations, then selectively run realistic execution-aware and walk-forward tests. Display effective dimensionality and coverage, not a false exhaustive-space promise.
6. **Re-screen and validate:** variable relevance is scoped to strategy, range, instrument, regime, data and time. Periodically reconsider deprioritized variables using research/selection data. Do not use untouched final OOS to repeatedly refine the variable set.

**Key distinction:** searching for parameter *values* in a fixed strategy is the first product slice. Searching for the best *strategy structure* (turning indicators/filters on/off or changing dependencies) is a separately versioned future capability. Do not silently change strategy semantics during parameter screening.

## 2. UX Pilot generation prompt — paste as one complete prompt

> **Generate a high-fidelity DESKTOP design for Aegis Optimization Lab v2, an advanced multivariable trading-strategy optimization workstation.** Match the accepted Aegis screenshot and editable AegisQuant design pixel-faithfully in visual language: 1672×941 canvas, dark navy/charcoal background, fine hairline dividers, small typography, dense professional data controls, muted cyan/blue and restrained amber/green/red status accents. No giant cards, web-site navigation, sparse dashboard layout, decorative 3D graphs, or whimsical styling. It must look like an integrated screen of the existing Aegis application.
>
> **Create three coherent related views, not three unrelated dashboard designs:**
>
> **Screen A — Compact Optimization Dock:** Preserve the price chart as dominant, with strategy settings in context, bottom optimization dock displaying a selectable two-parameter heatmap, objective dropdown, exact-slice/aggregated indicator, trial count, progress, validation badge, compact Top-10 result table, and a clear `Expand Lab` action. Right intelligence rail continues showing findings, warnings, provenance, and suggested actions.
>
> **Screen B — Expanded Optimization Lab (primary):** Use the center workspace for linked multivariate research. Top context toolbar includes strategy/experiment, dataset, frequency, regime/market window, direction (Long / Short / Both, with independent scoring), sample partition (Train / Validation / Out-of-Sample), objective(s), and run status. Left contextual rail contains a searchable parameter catalog (~10 HA-MQI/EWO/RocketRSI settings), parameter ranges, fixed/filtered variables, selected X/Y dimensions, slice mode, and saved filter presets. Main central canvas displays a large interactive parameter-performance heatmap and a selectable secondary view: parameter interaction matrix, parallel coordinates with brushing, risk/return Pareto frontier, importance/sensitivity, or stability/robustness neighborhoods. Use compact tabs or split panes that keep the main visualization dominant. Along the bottom, a dense sortable virtualized trials table supports filtering, pinning, and A/B comparison. Right intelligence rail has: findings, warnings, validation status, candidate explanation, coverage/sample size, provenance, and suggested next investigation. Include a persistent compact KPI/status strip. Make source-of-truth states visible: `Tested`, `Aggregated from tested`, `Interpolated estimate`, `Untested`, `In Sample`, `Out of Sample`. Never imply a smooth surface where only sparse tests exist.
>
> **Screen C — Candidate Investigation / Comparison:** Show two or three pinned parameter configurations, full variable profiles, risk-adjusted metrics, equity curves, drawdown, distributions of trades, regime/temporal-window splits, and independent long/short breakdown. A selected cell or result in any visualization synchronizes highlights, selected candidate, parameter inspector, charts, and table. Include an action to queue a focused local follow-up sweep and a distinct `Send to Validation` action, not `Deploy`.
>
> **Interaction detail:** Selecting a heatmap cell selects actual trial IDs; in aggregated mode show distribution, count, and contributing trials rather than inventing a single exact configuration. Brush a range on any parallel axis and the heatmap, table, Pareto plot, and counts update coherently. Clicking a high-performing region shows nearby *actually tested* neighbors, their spread, and whether the region has enough coverage for a plateau assessment. Pin candidate A/B, compare their train and out-of-sample performance, then save the comparison to an experiment. Do not show fabricated performance data as production results: label all mock metrics `DEMO` or `Illustrative`.
>
> **Design for realistic usage:** Initial 400-combination sweeps and later 10,000+ trial histories; hundreds of parameter values, categorical and numeric parameters, uneven/random/adaptive sampling, long/short asymmetric logic, temporal windows, and multiple objectives (profit, drawdown, Sharpe, stability, OOS performance). Support loading/partial/empty/error states, keyboard selection, accessible contrast and chart legends, concise hover tooltips, pinned view presets, provenance/version badges, and a screen at 1672×941 without hidden primary controls. Avoid generic 3D scatter or an overwhelming default 10-axis spaghetti display—parallel coordinates belongs in a focused subview with density/filter controls.
>
> **Deliverables:** High-fidelity designs A/B/C, a concise interaction/state specification, responsive behavior for slightly smaller desktop widths, and clear component naming. The user must review the designs before any implementation.

## 3. Claude Code tasking brief

### Mission

Implement **only after an explicit human review of both the UX Pilot design and Claude's implementation plan**. First inspect the *actual current repository*, preserve existing work, and make an evidence-based plan. Aegis is product-first and UI-first; do not turn this into a backend architecture rewrite.

### Mandatory stage gates

**Gate 0 — Read-only reconnaissance (authorized now):**

1. Inspect repository branch/status, AGENTS.md / CLAUDE.md instructions, UI structure, chart and optimization components, trial schema, optimization limits, results API, experiment storage, strategy definitions, and current tests. Do not assume a component exists because this brief names it.
2. Locate and view the accepted Aegis design and any produced UX Pilot Lab v2 output. If the new UX design is unavailable, **stop before implementation**, report what is missing, and provide a proposed UI-only plan contingent on design review.
3. Inventory reusable UI/chart packages (including current chart engine) and numerical analysis packages; avoid rebuilding standard charting primitives. Map existing code to intended interaction boxes.

**Gate 1 — Written implementation plan for review (required):**

Produce `AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md` in the repository, including:

- Current-state audit: exact components, routes, APIs, trial storage, known limits, reuse opportunities, risks, and existing user modifications.
- Side-by-side UI map: approved UX Pilot screen/component → current component or planned React component → data source → event/interaction contract → empty/loading/error state.
- Proposed data model for each trial: stable ID; typed/versioned parameter vector; search method; strategy/data/engine/execution versions; objective metrics; IS/validation/OOS split; long/short; regime/window; timestamps; fees/slippage; run result hash; coverage metadata.
- Algorithms for exact slicing, aggregated projections, pairwise interaction, sensitivity/importance, robustness neighborhoods, Pareto selection, and linked filtering. Define assumptions, minimum trial support, confidence/coverage thresholds, and methods to avoid presenting estimates as observed data.
- **Screen H first-class UI/data contract:** dependency-based structural relevance, uncertainty-aware empirical importance, interaction screening without exhaustive pair enumeration, parameter status transitions, manual override/reactivation, temporarily frozen versus excluded semantics, versioned search-space proposals, and estimated search-budget effects. All state changes must carry evidence/provenance.
- A **one-million-trial readiness section** detailing durable trial indexing/partitioning, server-side filtering and aggregation, background jobs, progressive results, virtualized rows, downsampled/density plotted series, drilldown, interactive latency budgets, cancellation/resume, failure/duplicate handling, and memory/resource benchmarks. Do not assume one million vector evaluations equals one million complete costed backtests.
- A **staged compute funnel** differentiating fast exploratory evaluation, focused local refinement with execution costs, walk-forward/fold validation, and final untouched OOS confirmation. Specify selection boundaries preventing OOS leakage and repeated tuning.
- Explicit UI maps for supplemental screens D/E/F/G/**H** and restored historical Aegis modes (Backtest Review, Compare, Optimization Lab, Provenance), including experiment-lineage navigation and trade-level forensic inspection. **Screen H is the upstream entry point before a large optimization run**, not a separate decorative dashboard.
- Incremental implementation phases with touched files, migration needs, dependency choices, performance/resource budgets, test cases, screenshots, rollback and compatibility strategy.
- Clear scope exclusions and any unresolved questions that materially affect UI behavior or calculation meaning.
- Specific acceptance criteria and proposed reviewer checkpoints.

**Hard stop:** Present the plan and the UX Pilot designs to Randall for review. State exactly: **`PLAN REVIEW REQUIRED — DO NOT IMPLEMENT UNTIL RANDALL APPROVES.`** Do not start writing React code, schemas, backtest logic, migrations, or library integrations, even if the plan looks complete. Revision to the plan is allowed; implementation requires an explicit approval after review.

**Gate 2 — Implementation (only after approval):** Implement the approved phases, UI shell and interactions first, then data wiring, then optional analytical extensions. Preserve current Aegis navigation and chart stack. Keep work testable and reversible. No live-trading integration changes. No rewriting the Strategy Gate.

**Gate 3 — Deterministic QA and visual acceptance:** Compare screenshots to UX Pilot output at 1672×941; verify keyboard/mouse behaviors, all linkages, honest data-state labeling, data count consistency, version provenance, empty/loading/error paths, performance with representative 400-trial and 10,000-trial sets, and metric parity with existing trusted calculations. Require accepted tests before calling done.

### Core views and behavior

**A. Compact dock:** X/Y axis and metric selectors, heatmap, Top-10, progress, explicit slice versus aggregation status, and Expand Lab. Preserve existing chart/inspector and KPI strip.

**B. Full Lab:**

- Linked heatmap with test-count cell overlays, a selected metric, and X/Y controls.
- Exact slice = all other parameters fixed to specified values; no observed cell when no trial matches.
- Aggregated projection = summary across matching tested trials (min/median/mean/max selectable), always show `n`, dispersion, filtering context, and warnings for confounding/uneven sampling. Aggregated cells are not exact runnable strategies.
- Parameter interaction matrix and detailed pair view; incomplete combinations stay visibly incomplete.
- Parallel coordinates with brush/reorder/focus and color by selected outcome; manageable default variable set, top/bottom/pinned line highlighting, optional density mode.
- Risk/return/Pareto view distinguishing non-dominated observed candidates from others and allowing multiple selected objectives.
- Parameter importance/sensitivity with methodology and coverage caveats; rankings are conditional on explored ranges and sampler behavior.
- Stability/plateau inspection using tested neighbors only, controlled neighborhood definitions by variable type, count and dispersion; rank robust candidates separately from best single-point winners.
- Virtualized trial table with variable columns, sortable numeric metrics, all filters shared, pinned A/B/C comparison and export of selected candidate metadata.

**C. Candidate investigation:** synchronized equity, drawdown, trades, risk, execution-cost, long/short, temporal-window, regime, and train/OOS comparisons, with consistent data splits. Clicking any view selects/highlights the same stable trial IDs.

**D. Intelligence rail:** deterministic summaries and AI explanations separated visibly. AI can recommend next sweeps and interpret results, but **cannot** change gate verdicts or declare deployment eligibility. Strategy Gate independently recomputes metrics from raw trades and validates version matching.

### Essential semantics and pitfalls

- Preserve independent long and short entry/exit logic and scores; do not assume they are mirrored.
- Temporal windows include open/close, FOMC, earnings and other event windows when data exists; distinguish unavailable windows from neutral results.
- Avoid look-ahead/leakage, unguarded repeated tuning on OOS, and ranking one-off max-profit anomalies as robust.
- **No automatic empirical permanent exclusions.** A parameter with negligible observed main effect may be conditionally important through interactions (e.g., EWO and RocketRSI acting together). Screen by structural dependencies, then targeted interaction experiments and uncertainty; ensure user-accessible overrides.
- A deterministic structural exclusion requires a provable dependency/activation explanation (e.g., disabled branch or unreferenced parameter for the approved strategy version). Empirical low importance means only *deprioritized under an explicit evaluation scope*, never a universal fact.
- Treat correlated/aliased inputs, categorical guards, narrow regime triggers, nonlinear thresholds and higher-order interactions carefully. An importance ranking trained on a biased adaptive sampler is conditional on that sampling distribution.
- Distinguish *search space size*, *scheduled trials*, *completed trials*, *unique combinations*, *invalid trials*, and *filtered/visible trials*.
- Do not synthesize trials, smooth untested cells into fact, conflate averaged cells with precise configurations, or fabricate example P&L without DEMO labeling.
- Use the existing vectorized engine when available; a UI upgrade is not an authorization to replace it or to claim a 200–500% speedup without benchmark evidence.
- Heavy analytic views should not block the chart or command surface; worker/background computations or incremental rendering require profiling and review.
- A one-million-trial query must not send one million raw chart marks or DOM table rows to the client. Every chart must document whether it shows exact tested points, bins, aggregates, an explicitly sampled subset, or estimates; display contributing counts and filtering scope.
- Record separately: total possible configurations, scheduled, attempted, completed, unique, duplicate, invalid, failed, refined, validation candidates, filtered, and visible counts. Never label all trial counts as equivalent full backtests.
- Build uncertainty-aware convergence displays and robust-region membership without claiming that the highest trial or a smooth interpolated ridge is validated alpha. Run-selection decisions remain reproducible.
- Preserve strategy edits' invalidation of validation status; use strategy/data/execution/gate policy hashes where available.
- Do not install GS Quant, Optuna, Plotly, or a new optimizer merely because their reference visualizations are useful. Any dependency adoption requires compatibility, benchmark, licensing, and maintenance review in the plan.

### Acceptance test scenarios (must be enumerated in the plan)

1. Reference 30-SMA/9-EMA crossover: small exhaustive grid, known selection and linked view consistency.
2. HA-MQI ten-variable sweep: sparse 400-trial and dense 10,000+ samples, filters and axes changed repeatedly without incorrect cell counts.
3. Exact slice with no matching trials: visibly empty, no interpolation pretending to be a tested point.
4. Aggregated cell with many trials: median and distribution shown, and users cannot pass an aggregate cell as an executable candidate.
5. Sharp single best trial versus stable neighboring cluster: stability analysis distinguishes them without making profitability promises.
6. Train versus out-of-sample: distinct metrics and selection rules, no OOS leakage into optimization objective unless explicitly designed and reviewed.
7. Long/short asymmetric parameters and event windows: separate results and accurate filtering.
8. A/B/C pinned trials: identical IDs/values/metric versions in table, heatmap, parallel plot, performance charts, and exported comparison.
9. Duplicate/failed/partial trials, unavailable indicator data, broken metrics, and run cancellation.
10. Validation remains blocked until deterministic Strategy Gate checks; no AI override.
11. One-million-trial synthetic dataset: indexed server-side filter/sort/paginate, density/aggregate chart updates, concurrent run-progress updates, memory ceiling, UI responsiveness, and no million-node rendering. Document cold/warm timings and test hardware; set pass thresholds in approved plan.
12. Million-trial status reconciliation: scheduled/completed/unique/failed/duplicate/invalid/visible totals, partial snapshots, resumability, cancellation, and retry idempotency.
13. Four-stage research/validation funnel: fast vector stage versus execution-aware replay, walk-forward folds, and untouched OOS boundaries; leakage and improper candidate promotion must fail tests.
14. Parameter family and interaction navigation with 20 mixed-type variables: expand/collapse, search, trellis views, brushing, linked selections, chart maximization, and count-preserving drilldown.
15. Experiment lineage and provenance: parent sweep -> focused child sweep -> trial -> candidate, version/hash matching, stable filters after navigation, and restored trade-log inspection.
16. Full walk-forward matrix, regime by temporal-window breakdown, long/short partition, sealed-OOS lock explanation, and deterministic validation status consistency.
17. Visual QA: labels readable at target canvas, minimum contrast for status/secondary text, keyboard use, and no critical controls clipped at 1672×941 or slightly narrower desktop.
18. **Structural relevance tests:** truly inactive branch or unreferenced parameter is excluded with code/data dependency evidence; an active parameter is never excluded due to an incorrect static heuristic.
19. **Interaction trap:** a synthetic XOR-style two-variable fixture with zero/weak marginal effects but strong joint effect must survive screening into targeted interaction investigation. Include a conditional HA-MQI/EWO/RocketRSI-like fixture.
20. **Evidence and status transitions:** Active/Investigate/Deprioritized/Excluded/Frozen have deterministic versioned reasons, provenance, manual restore, warnings and correct trial counts; excluded versus frozen are not conflated.
21. **Search-space reduction budget:** effective dimensions and theoretical combination counts recompute correctly after status/value changes, with clear labeling that reduced Cartesian space is not an actual number of trials saved under a sampler.
22. **Scope/time stability:** variable status derived on one regime, range, dataset or strategy version is invalidated/reassessed when those change; untouched final OOS never drives repeated variable elimination.

## 4. Required handoff order

1. UX Pilot screens A/B/C (Compact Optimization Dock, Expanded Lab, Candidate Compare) and D/E/F/G (Million-Run Monitor, Multidimensional Families, Walk-Forward Validation, Experiment Lineage) have been generated. UX Pilot completed a read-only critique of A/B/C. **New screen H (Variable Intelligence & Search-Space Design) is prepared but awaits the user clicking `Start generating` in UX Pilot.** Randall reviews all eight screens and requests corrections before approving the UI contract. Page: https://uxpilot.ai/a/ui-design?page=lTHZGNbkbJqGnXSWW4IR .
2. Claude performs only read-only repository reconnaissance and writes the detailed implementation plan.
3. Claude stops and requests Randall's explicit plan approval, incorporating the approved UX Pilot visuals.
4. After approval, Claude implements the phased UI-first plan and reports deterministic QA plus visual comparisons.

**Do not treat this brief itself as approval to implement.**

## 5. UX Pilot re-evaluation findings (2026-10-27) and binding corrections

Read-only first-party UX reviews of the A/B/C designs returned the following issues. These are **review findings, not proof that the mockup implements one-million-run scale**:

| Screen | Finding | Mandatory design-plan response |
| --- | --- | --- |
| Expanded Lab | Illegible base text; a flat variable list hits a 20-variable wall | Improve typography/contrast; collapsible searchable parameter families |
| Expanded Lab | Missing experiment provenance and unclear linked chart interactions | Parent/child sweep breadcrumb; visible cross-filter state/linked icon |
| Compact Dock | Two-axis grid is insufficient as the sole multi-variable context | Small-multiples/trellis entry point and fast Expand Lab navigation |
| Compact Dock | No convergence history or walk-forward matrix | Linked convergence preview and Walk-Forward entry/tab |
| Candidate Compare | Text/status contrast and million-trial drilldown inadequate | Full-view maximization, readable states, sample-count context |
| Candidate Compare | Sealed OOS unclear; walk-forward not explicit | Lock tooltip/dialog explaining unsealing implications; separate full walk-forward view |

**Scope clarification:** Keep the A/B/C screens and preserve the existing workstation shell. D/E/F/G supplement them. The supplemental UX Pilot prompt includes:

- **D — Million-Run Optimization Command Center:** staged job pipeline, progressive batch progress, convergence, coverage, throughput/ETA with uncertainty, worker health, failures/retries, snapshots and job versions.
- **E — Multidimensional Exploration / Parameter Families:** search/collapse up to 20 variables, full-size linked parallel coordinates and interaction trellis, accurate aggregated/sampled views, tested-neighbor stability and family-to-trial drilldown.
- **F — Walk-Forward & Robustness:** train/validation/OOS timeline matrix, fold metrics, regime × session windows, independent long/short, costs, distribution, OOS decay and gate evidence.
- **G — Experiment Lineage & Forensics:** parent/child sweep and candidate lineage, saved state/filters, version hashes/seeds, trade evidence and immutable provenance.

### Million-run UX and data truth contract

1. **One million refers to evaluated trial configurations.** Report separately the number of fully replayed execution-aware backtests. Do not hardcode a particular refinement/validation funnel ratio.
2. Keep every completed trial queryable by stable ID. Use backend indexes/columnar summaries/bounded query results and virtualized client lists as appropriate to the actual codebase. No million-row DOM render.
3. Use partial progressive summaries that update consistently as jobs run. Show provisional result state and snapshot time; completion is not implied by a live best-so-far curve.
4. Parameter neighborhoods, interaction importances, and family groupings must use documented, reproducible definitions and show sample counts and selection bias warnings for nonuniform searches.
5. Grouping and screen navigation must preserve a single selection/filter state and deterministic result/provenance linkages across all eight views.
6. Million-run performance requirements should be benchmarked and proposed in Claude's plan using the actual Ragnarok/target compute/storage environments, not invented from the UX mockup.

### Updated plan review checklist

Before implementation approval, Randall must be able to answer **yes** to each:

- All eight UX views (A–H) reviewed and aligned with the locked original screenshot.
- One-million-trial user journeys shown from job start to investigation, convergence, refinement, walk-forward, candidate comparison, provenance and validation.
- The trial query/rendering architecture has measurable latency, memory and throughput acceptance criteria.
- The plan explicitly separates vectorized exploratory calculations from costed replays and final validation.
- Variable selection/relevance is evidence-backed, revisable, and scope/version aware; low individual importance does not automatically erase interactions. Any valid pair remains manually explorable even if hidden from default ranking.
- The implementation map ties every approved UI box/interaction to a real data source and deterministic QA test.
- The plan contains no unreviewed migration, replacement of existing chart/backtest engine, or change to Strategy Gate authority.

**Final required stop line:** `PLAN REVIEW REQUIRED — DO NOT IMPLEMENT UNTIL RANDALL APPROVES.`

## 6. Screen H — Variable Intelligence & Search-Space Design (new upstream UX contract)

**State:** UX Pilot generation prepared on the existing Aegis page; actual high-fidelity design must be generated and reviewed before Claude plan approval. This section is the authoritative interaction requirement and supersedes any interpretation of earlier text that *every pair must be exhaustively tested or displayed*.

### Purpose

Make effective dimensionality and variable relevance first-class research objects. Aegis should direct the million-trial budget toward the best-supported regions and unresolved interactions while keeping every legitimate parameter available for investigation.

### Screen layout and interactions

| Region | Required content and behavior |
| --- | --- |
| Top context | Strategy and search-space version, instrument/data/regime/time window, direction, dataset partition, defined vs effective dimensions, run/seed/engine hashes, available exploratory budget |
| Left parameter catalog | Searchable/collapsible indicator families; each typed/ranged variable marked **Active**, **Investigate**, **Deprioritized**, **Excluded**, or **Frozen for current sweep**; clear conditional dependency badge and manual restore/pin controls |
| Center overview | Ranked main/conditional influence with uncertainty, sample coverage and evaluation method; projected combination-space comparisons explicitly distinguished from measured trials |
| Center interaction explorer | Ranked meaningful and uncertain pairs (and selected higher-order tests); linked bivariate trellis and inspect-on-click. Manual **Explore any valid pair** mode remains available even if not in default ranking |
| Center proposal/impact | Side-by-side original vs candidate search space, dimensions, frozen values, reasons, unresolved interaction risks, tested performance/coverage; versioned **Propose Search Space** and **Review Before Apply** actions |
| Bottom evidence table | Contributing trial IDs, split, ranges, sample/coverage, status, outcome, proposed future trials; click-to-filter and preserve linked selections |
| Right intelligence/evidence rail | Why each variable received its status; deterministic proof or empirical method, scope, uncertainty, interaction warnings, contradictory evidence, re-screen triggers, provenance, focused-test suggestions |

**Important conceptual distinctions:**

- **Defined** = user-tunable parameter exists in strategy.
- **Active** = currently in broad search.
- **Investigate** = unresolved or interaction-sensitive; targeted trials required.
- **Deprioritized** = lower exploration priority in an evidence-scoped study, not disproven relevance.
- **Excluded** = out of the current search set; structurally excluded only when deterministically proven, otherwise explicitly user-approved research decision with reversible provenance.
- **Frozen** = strategy still uses a fixed value; not equivalent to deleting/disabling the indicator.
- **Effective dimensions** = variables actively varied in a specified experiment; the definition and counts are shown alongside scope.

### Structural and empirical screening contract

1. Start with a dependency graph of the strategy definition to detect provably dead/disabled branches, duplicate aliases and invalid configurations. Never claim static irrelevance from mere lack of observed P&L change.
2. Use representative research/selection data and explicitly scoped importance methods. Display confidence/uncertainty and warn on correlated variables, nonuniform/adaptive samples, insufficient trials and regime dependence.
3. Preserve interaction discovery for low-main-effect variables: at least targeted checks or an explicit unresolved-risk label before deprioritization. Higher-order interactions remain possible even if pairwise screens look weak.
4. Reconsider rankings as new data/regimes/search ranges arrive. Record re-entry reasons. Do not use the final sealed OOS confirmation set to recursively decide which variables to keep.
5. Show computational-budget estimates for the reduced set, but do not promise a speedup or trials saved before actual benchmarks.
6. AI can propose and explain variable actions; deterministic code supplies evidence and policy checks. Human review controls major search-space or strategy-structure changes; Strategy Gate remains independent.

### Mandatory Screen H plan-review questions

- What exact evidence supports each structural exclusion and how is it reproducible?
- How will the design protect weak-main-effect, strong-joint-effect interactions from premature elimination?
- What algorithm prioritizes pair/higher-order investigations and how are uncertainty and sampler bias exposed?
- Which variables are frozen versus excluded, and is the strategy definition unchanged?
- Can Randall restore or manually inspect any valid pair in one or two interactions without losing current filters?
- How do proposed changes affect search-space versioning, historical trials, cache keys, experiment lineage and the million-run budget?
- What QA proves that a variable-selection change does not silently alter OOS usage or deployment eligibility?

**Screen H is part of the required UX-first plan review, not authorization to code.**
