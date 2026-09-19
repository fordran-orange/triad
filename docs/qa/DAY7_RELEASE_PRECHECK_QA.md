# Day 7 release precheck — independent canonical/live audit

Reviewer `/root/day6_qa_c`, separate from builder `/root`, 2026-09-19.
**PASS for this bounded audit at `96652c2bc2f9e4c7bc692c67bdd7b2dbedb56117`.**
The final integrated regression and release-candidate review remain pending.

Reviewed `DAY7_REGRESSION_FINAL_QA.md`: the final `eea65d3` correction has seven
passing independent cases, including the legacy immutable reasoning allocation
and corrected context-capacity/paid-reservation fixtures. Earlier full-suite and
intermediate failures remain retained. There is no app/configuration/infrastructure
or tool change from `eea65d3` to this audited HEAD; later files preserve QA evidence.

## Canonical records verified directly

In one read-only production transaction, independently loaded all **32** recorded
ImplementationRun/QARun pairs: 30 pinned segment entries plus two regression
entries. Typed contracts validate; each pair has the expected product owner,
matching implementation/reviewed commit and linked IDs, a separate reviewer,
HOST_INDEPENDENT_QA execution mode and the expected latest decision. Original
starts remain null and retrospective ingestion is stated explicitly.

Canonical decisions preserve **13 PASS, 18 CHANGES_REQUIRED and one historical
PASS_WITH_OBSERVATIONS**. The timestamp observation has its separate later PASS
entry; old failures are not relabelled as successes. All pinned reports and
manifest hashes still match, and **245 unique revision/path Git blobs** match the
frozen plan. That unique count intentionally differs from repeated per-entry
comparisons in the separate ingestion review.

Evidence: `logs/day7-final-canonical-audit.py`, `.json` and `.exit` (0). An initial
audit-only assertion incorrectly assumed every segment was Core-owned. It stopped
on a legitimately Triad-owned segment; the corrected audit checks each pinned
owner. The initial output/exit are retained as
`day7-final-canonical-audit-initial.log` and `.exit`. This was an audit-script
assumption, not a production implementation failure or a change to ownership.

## Post-restart and installed package

At **21:40:07Z**, independently checked seven main deployed destinations: all
return 200. Core, PostgreSQL, TimescaleDB, Neo4j, Ollama and Git report UP. All four
providers are ONLINE, gate PASS, and active provider runs zero. Aegis remains
human-directed/INACTIVE/PRESERVED, with exchange CLOSED and zero assignments.
Evidence: `logs/day7-independent-postrestart.json`.

Reviewed root's successful final restart, release-service and clean-wheel logs.
Independently compared **123** installed Python/configuration/SQL/HTML/JS/CSS files
from `trading-core-package-ql8zbp9q/installed` against the current reviewed checkout;
all are byte-identical. Evidence:
`logs/day7-final-independent-installed-bytes.json`. This comparison supplements
the builder's installed route smoke; it does not claim a second package install.

Reviewed root's final data/backtest regression with exit 0: 151 older baseline
artifacts and 59 older work IDs remain preserved, migration up/down/up passes in
its fixture, and both retained deterministic experiments retain their content
hash while preserving different historical source fingerprints. This narrower
older-baseline count does not replace the independent pre-final backup comparison
of 228 artifacts and 101 original WorkItems in `DAY7_LIVE_ACCEPTANCE_QA.md`.

No database suite, production write, inference, account access, restart or
implementation edit was performed by this reviewer. Browser evidence remains
attributed to root's supported session and retains its disclosed smoke-test scope.

## Release gate still open

The final complete suite is active. Require its successful finished output and
exit status, the updated final Day 7 report and exact candidate commit, followed
by independent candidate acceptance and the final canonical Core governance
record before merge/tag. This precheck is not the release-candidate PASS and must
not be used to claim the running full suite has completed.
