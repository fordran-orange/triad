# Day 8 precheck — independent QA

Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19.
Decision: **PASS for the bounded Day 8 starting baseline and readiness precheck**.
Exact starting revision: `7cf1089672b69301fd58ccd92080af1bdc0ae67e`.
This permits the separately reviewed Day 8 implementation work; it is not Day 8
completion, engineering-capability approval, or permission to enable scheduling.

## Baseline and retained evidence

Read the Day 8 user brief and repository AGENTS.md. Independently verified clean
`main` before report creation and the annotated `base/day7-complete` tag peeling
to this exact HEAD. Its final acceptance candidate is
`eeaa2520284e8be6e2d498c6f0f7a735227632d7`; the final descendant preserves the
independent acceptance report. Recomputed all **290 source hashes and 119
retained evidence hashes**, with zero mismatches. The accepted evidence archive
hash matches, all 119 members pass ZIP CRC checks, and the manifest SHA remains
`05852123d4f87b1fd0bd03872f5515941cbe9bf29b9e0aece2fc6c290222ec99`.

Independently loaded and typed the canonical final Day 7 ImplementationRun
`83a47959-ed1b-4bae-a428-fd757f064f7c` and QARun
`277456a1-ffe9-4d2e-babc-0abcd01d10c1` in a read-only transaction. Ownership,
matching reviewed candidate, linked IDs, separate reviewer and PASS agree with
the retained final governance evidence.

Reviewed `DAY8_PRECHECK.md` and its fresh targeted regression: **23 passed,
two dependency warnings, 51.92 seconds**, exit 0. The earlier five-pass,
18-skipped invocation is disclosed and not used as integration acceptance.
Retained final Day 7 full regression remains **535 passed, five warnings,
1145.97 seconds**, exit 0, with its exact log hash verified. This reviewer did
not rerun either suite. Kill/cancellation, finite resource extensions, scope,
timestamps, CycleRecord, registry and data behavior rely on the accepted
independent segment tests plus the disclosed fresh targeted run. No live kill
switch exercise or provider generation was performed.

## Fresh independent read-only checks

At 22:14–22:15 UTC, ten HTTP destinations returned 200, including Core,
Integrations, Triad Product, Development, Cycles, Aegis, provider settings and
Research. Both direct product worker health endpoints returned healthy. Core,
PostgreSQL, TimescaleDB 2.25.2, Neo4j, Ollama and Git reported UP. Codex,
Claude, Grok and local Qwen were ONLINE with the same model identities reported
by the builder; provider gate PASS and active runs zero. These are current
readiness observations, not new inference or persistent-availability guarantees.

Read-only SQL independently confirmed migrations 012/013, current epoch 2,
kill/paused false, no queued/running cycle jobs and disabled local/subscription
daily execution caps. Configuration keeps scheduling disabled. Aegis reports
INACTIVE, human-directed, exchange CLOSED and zero work. Integration discovery
reports local canonical AVAILABLE, both broker shells disabled/unconfigured,
live execution DENIED and paid fallback NEVER_AUTOMATIC.

Loaded all **12 neutral local manifests** through the existing local adapter;
all validate, all canonical file checksum entries match, and every manifest is
explicitly FIXTURE/LABTEST. Four retained BacktestRun records and two Experiment
records exist. Historical reproducibility is supported by the hash-verified
Day 7 data/backtest regression; no new production experiment or real-market
coverage is claimed. Existing cycle history retains one completed Day 6 mission
and two blocked older cycles with timestamps; unknown historical fields remain
unknown.

## Evidence and limits

Commands: `.venv\Scripts\python.exe logs/day8-independent-precheck.py` and
`.venv\Scripts\python.exe logs/day8-independent-state.py`, both exit 0.
Their JSON outputs preserve the selected nonsecret observations. Report/input
and fresh evidence hashes are in `DAY8_PRECHECK_QA_HASHES.json`.

Fresh UI checks here verify route delivery and readable JSON service state,
not a newly executed interactive browser walkthrough. The accepted unchanged
Day 7 browser evidence remains attributed to its actual root-host executor and
independent reviewer. Day 8 UI changes require their own browser acceptance.

No implementation change, production write, migration, control toggle, external
acquisition, inference or scheduling action was performed by this reviewer.
No critical baseline blocker was found. The builder correctly identifies the
unimplemented executable readiness evaluator, bounded engineering extension,
reviewed debrief and full product scheduler as Day 8 work still requiring
separate implementation and independent QA gates.
