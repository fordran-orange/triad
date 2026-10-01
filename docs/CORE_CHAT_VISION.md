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

Core owns shared knowledge, Intake, provenance, provider capabilities, data
validation, execution services, and backtest computation. Aegis owns its research
and backtesting workspace and presentation. Chat coordinates these capabilities.
Triad continues autonomous product development under its established authority.

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
