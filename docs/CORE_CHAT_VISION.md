# Core chat and Aegis product direction

This is the operator's agreed long-term direction, recorded from the conversation
in which they asked that it be remembered. Read it before planning or changing
Core chat, Intake, historical memory, provider routing, or Aegis research. Future
explicit operator corrections can revise this direction; preserve what changed
and why. This document records goals, not a claim that all capabilities exist or
a standing instruction to execute every example.

## The operator goal

The operator wants a Jarvis-like experience: local knowledge first, one interface
to connected provider models for reasoning, generation, and development, and
persistent memory of the whole process. Core chat is the conversational workspace
for understanding projects, exploring improvements, making decisions, and
initiating authorized work. Do not reduce the intended product to a read-only
chatbot, a document search box, or a single-provider interface. The current
read-only chat is a delivery stage, not the final ceiling.

Start with local conversations, requirements, decisions, code, screenshots,
designs, datasets, experiments, and results. Identify uncertainty or missing
evidence before seeking outside information. Support explicit provider choice
and capability-based routing across connected models. Prove each capability;
do not assume that chat access also supplies image generation, development tools,
or access to a provider's conversation archives. Preserve provider, model, usage,
and source provenance. Existing credential, billing, and execution authority
remain applicable.

## Intake and memory

Intake is the common front door and evidence record for text, files, conversation
archives, and supported connectors. Preserve originals, attribution, available
timestamps, attachments, capture scope, omissions, ownership, stable identities,
and revisions. Receiving material does not itself authorize execution.

Native Core conversations should be saved automatically. External conversations
enter through Intake. Both should support retrieval of specific passages and
evidence-backed summaries. Preserve the distinctions between an exploration,
assistant suggestion, proposed decision, adopted decision, rejected or superseded
idea, and actual implemented result. An archived command or approval remains
historical evidence. Import time must not override the original chronology.

Log the operator request, retrieved context, model contributions, generated
artifacts and their versions, feedback, decisions, tests, deployment, and results
with links between them. Respect project-private knowledge and existing sharing
boundaries. A bounded context window should not erase retained history.

## Design and generation acceptance scenario

The operator's example: "show me our intended gui and highlight what gaps exist
from what's built."

Core should retrieve the history of UI design reasoning, alternatives, decisions,
and later corrections; inspect the current code and deployed interface; and
produce an annotated graphic comparing the intended GUI with what is actually
built. Identify gaps and cite evidence. Distinguish an approved design from an
old mockup, a proposal, or an assumption.

If the operator asks for a render of an improvement, use an available capable
generation model with the project context and reference artifacts. Retain the
render, prompt, provenance, explanation, revisions, and operator feedback in
memory. Generating a concept does not adopt or deploy it. A subsequent explicit
"build that" should resolve the exact artifact and revision and initiate work
under the project's existing authority.

## Research and backtesting acceptance scenario

The operator's example: "run a 5 year backtest on NVDA using HA-MQI on an hourly
chart. vary the lookback window from 6 to 12, increment by 1 each run. cluster the
results and give me your report and recommendation."

Eventually chat should resolve the saved strategy definition, date range, data,
sessions, costs, and execution assumptions, asking only about consequential
unknowns. Validate inputs and execute seven comparable runs with lookbacks 6,
7, 8, 9, 10, 11, and 12. Analyze outcomes and stability, group similar results
where the evidence supports it, and present charts, a report, and an evidence-
based recommendation with uncertainty. Do not force statistical conclusions from
seven observations or silently optimize unspecified parameters.

Preserve strategy and dataset versions, configuration, run results, analysis,
recommendations, and later operator decisions so follow-ups can refer to exact
experiments. This example defines a future acceptance scenario; no NVDA backtest
was requested for immediate execution in this discussion.

## Responsibilities and direction

The operator clarified on 2026-09-30: Triad and Aegis share Core, not each other.
They are independent consumers of Core, with independent product direction.
This corrects any earlier suggestion that Triad builds Aegis by default or that
Triad's Alpaca use must wait for Aegis backtesting work.

Core owns shared infrastructure: memory, data, rules, integrations, Intake, chat,
provenance, provider capabilities, validation, and generic execution and backtest
services. Shared infrastructure preserves product ownership and access boundaries;
it does not automatically share private strategies, conclusions, or credentials.

Triad is the autonomous experiment. It can use capabilities already provided by
Core, including a future Alpaca connection, but must build its own product tools,
strategies, workflows, and spaces wherever Core does not supply them. Deciding
what to build is part of the experiment. Preserve its established autonomy.

Each daily development provider should implement its own perceived highest-value
product change, informed by current Core interfaces, prior outcomes and meaningful
alternatives. No fixed operator feature list replaces that judgment. Review should
assess product value as well as correctness; completed shell polish is not proof
that no useful product work remains. Carry initiatives and next steps across days.
The operator subsequently requested a lower advisory effort target for Codex while
retaining its daily turn, scope and ability to exceed that target when needed.

On 2026-10-03 the operator clarified that the missing application is the priority:
separate calculators and CSV tools do not constitute a trading platform. Triad
must maintain its own evolving application structure, versioned concepts and
contracts, component producers/consumers, connected user workflows, and the next
missing connection across runs. Its agents choose and revise architecture and
priorities; this is not an operator feature checklist. Every proposed increment
must explain its place in that application and verify adopted connections with
integration tests. Browser behavior requires executed browser evidence. Existing
tools may be adopted, adapted, deferred or replaced based on evidence.

The operator agreed to five-minute idle scheduling checks, deadline wake-up at
09:00 local time, immediate wake for submitted work and independent monitoring
and execution locks. Known lock contention before any work begins is waiting;
retry only the same identity after proving the prior process stopped, current
authority still applies and no work began. Unknown execution is not replay
authority. Reporting failures should not cause completed product work to rerun.

Aegis is the operator-directed platform. Its priorities, design, tools, and
workspaces follow the operator's decisions and do not depend on Triad's roadmap
or outputs. The operator may explicitly choose to adopt selected Triad work
later, but that is optional, not an architectural dependency or automatic flow.
Chat coordinates authorized capabilities without merging product ownership.

The operator reports an Alpaca account ready for future integration, configured
for paper trading only. The shared connection belongs in Core; product-specific
tools and spaces belong to each consumer. Triad and Aegis may use it independently.
Account availability is not evidence of an implemented integration or an
instruction to connect it, place orders, or enable live trading now.

The operator explicitly wants to begin Aegis with backtesting and views Vela as
a promising way to avoid building the chart interface entirely from scratch.
Bounded Aegis charting and backtesting-interface work is the intended next scope;
this updates the earlier blanket Aegis feature freeze. Verify Vela's exact
project, capabilities, license, and integration requirements before adopting it.
Keep a chart adapter boundary. Use existing Core computation and appropriate UI
architecture rather than assuming a React migration or a new backtest engine.

Most work remains focused on Triad and Core. Live trading and the closed exchange
remain outside this direction. MC-OS provider integration remains deferred.
Ollama remains maintenance-only. Existing failed raw market-data archives do not
become canonical or research-eligible merely because a chart can display them.

## Delivery stages

Stage 1 extends the existing deployed chat and typed Intake with reliable
archives, idempotent submissions, revisions, safe formatting, source-linked
historical retrieval, and evidence-backed decision history. Establish links
between conversation, intent, artifacts, and actual project state. A small Vela
demonstration can begin the Aegis backtesting interface with clearly labeled
fixtures when eligible data is unavailable.

Later stages add broader archive connectors, visual comparison and generation,
capability-based routing, and conversational development and research execution.
Keep the full vision while delivering small, independently verified milestones.
Avoid new routine human approval gates for Triad's already-authorized product
work. This direction does not start tomorrow's build, enable paid APIs, change
service configuration, or grant live-trading authority.

## Operator corrections

### 2026-10-09 — Aegis product-first build mode; Triad intentionally suspended

The operator confirmed on 2026-10-09 that Aegis is now in product-first build mode and
that Triad is intentionally suspended: its autonomous improvement game does not run while
Aegis is built, and it resumes later with Aegis as a base to work with. This supersedes
"Most work remains focused on Triad and Core" above and the earlier statement that the
Aegis planning direction "does not start that build". Scheduled autonomy was disabled by
`DailySchedule` record `c99fa831` on 2026-10-09; re-enabling it requires an explicit
operator decision through the operator route. The product-first rules live in `AGENTS.md`
(risk-based QA for reversible Aegis work; independent QA and Core governance still
mandatory for live-money, secrets, destructive and shared-contract changes). Unchanged:
Aegis is human-directed, exchange stays CLOSED, live trading stays disabled, Core imports
neither product, the Jarvis vision and the two acceptance scenarios above remain the goal.
Record: `CORE_STATE_AUDIT.md`, `docs/MISSION1_QUIET_GREEN_BASELINE.md`,
`docs/MISSION2_RECONCILE_AND_ADOPT.md`.

### 2026-10-13 — Core stays the shared substrate; dependency isolation, not separate Core environments

The operator corrected a drift on 2026-10-13: Core is the shared substrate and remains one
codebase and one runtime.

```
Core
├── providers
├── memory / knowledge
├── storage / provenance
├── shared runtime
└── product hosting / support
      ├── Aegis
      └── Triad — suspended
```

Product isolation is in code, contracts and dependencies, never in duplicate Core
installations. Not to be created: a separate Aegis Core, duplicate Core databases, duplicate
provider environments, a parallel runtime, a second orchestration stack, or separate
infrastructure for cleanliness; any environment-level change needs a measured blocker surfaced
before implementation. After reading the brief the operator approved three dependency
environments (`.venv` for Core and the gateway, `.venv-triad`, `.venv-aegis`, built from lock
files over the same `app/` tree) and `tools\verify.ps1`, with two requirements: every collected
test has explicit ownership, and a wrong or default `pytest` cannot show a misleading partial
green. Testing follows blast radius: ordinary Aegis edits run the Aegis, architecture and
isolation tests and the checks for the touched code; milestones run everything; shared Core
changes run the relevant Core tests immediately. The rule now lives in `AGENTS.md`. Record:
`docs/MISSION7_DEPENDENCY_ENVIRONMENTS.md`.
