# Day 7 C — CycleRecord independent QA

**CHANGES_REQUIRED** at exact implementation revision `7f560ee13169b58d805c5e9c9ba23aba0b55ae84`. Independent reviewer `/root/day6_qa_a`, builder `/root`, 2026-09-19. No implementation changes, production writes/backfill, provider inference or service restart were performed.

## Required corrections

1. **P2 — failed historical product inspections become IN_PROGRESS.** `CycleHistory.capture` computes terminal status from ProductMerge, legacy Cycle or ProductBuildFailure only. A genuine FAILED inspection WorkItem with `failure_reason=DeadlineExceeded` and its original ProductCycle produces a rollup containing that failure but status IN_PROGRESS. Day 6 inspection failures precede ProductBuildFailure and must remain visibly terminal. Derive terminal status from the relevant canonical work/failure evidence, without converting active unrelated work or later successful recovery into failure.
2. **P2 — re-capture supersedes a blocked record with an apparently active one.** After `history.blocked`, a plain `history.capture` sees only the cycle anchor; it excludes the existing CycleRecord and ignores the anchor's terminal status when constructing failures. `list()` selects the new IN_PROGRESS snapshot, hiding the known failure code, blocked timestamp and gate result. Preserve explicit terminal facts and their original timestamps when refreshing a snapshot, and preserve unknown historical fields rather than inventing them. Append-only storage alone does not preserve truthful latest-state reporting.
3. **P2 — early product-run failure loses known identity.** `Development.run` creates an anchor before `_run`, but a failure before ProductCycle creation is captured as ROTATION/UNKNOWN. The actual product wrapper knows this is PRODUCT_BUILD/REAL. The independent hook probe calls the real wrapper with a controlled early ProviderError and reproduces this incorrect identity. Pass or persist known cycle type/mode at initiation; still keep the real failure record and zero execution authority on the anchor.
4. **P2 — provider usage loses its canonical WorkItem linkage.** The rollup SQL filters using `day3_records.work_item_id` but does not select it. Runtime Usage payloads intentionally store that association in the column, as Ledger.get/records normally reconstruct it. Rollup provider_runs/subscription_usage consequently omit the WorkItem ID. Select and preserve the authoritative column relationship when materializing source evidence. The independent test uses Ledger.put(work_id=...) exactly as Runtime does and verifies the association is currently lost; API billing exclusion of Aegis data passes.
5. **P2 — legacy rotation proposals are omitted.** Source review shows `Cycles.evaluate_proposal` writes canonical kind `Proposal` and associates it with the WorkItem, while capture accepts only ProductProposal and ImprovementProposal for proposals/selection. These records are fetched but then omitted from the proposal collection, leaving known legacy proposal evidence out of the required cycle view. Include the actual legacy schema and use explicit approval/selection evidence rather than assuming every last proposal was selected. This finding is from the direct writer/reader mismatch, not a separately executed regression.

The first four findings have separate failing independent regressions in `tests/test_day7_cycle_qa.py`. Corrections require a fresh independent run.

## Exact revision and execution

Created `logs/day7-c-qa-exact-7f560ee.zip` with git archive and extracted it to `logs/day7-c-qa-exact-7f560ee`. Tests execute that source via `logs/day7-c-qa-run.py`, with TRIAD_INTEGRATION=1, snapshot PYTHONPATH/TRADING_HOME and provider monitoring disabled. Database credentials pass only in the child environment. PostgreSQL and graph fixtures remain disposable/namespaced. Concurrent B3 edits are excluded. All archived app files were checked byte-for-byte against the test snapshot; the additional independent test is separately hashed.

Command: `.venv\Scripts\python.exe logs/day7-c-qa-run.py day7-c-independent tests/test_cycle_history.py tests/test_day7_cycle_qa.py`.

Result: **4 passed, 4 failed, 2 existing TestClient deprecation warnings in 20.84s**, exit 1. Log and exact exit marker: `logs/day7-c-independent.log`, `logs/day7-c-independent.exit`.

The three builder cases passed independently. They cover historical legacy blocked evidence, repeated identical capture, gate-blocked WorkItem authority, cross-product exclusion, build/QA/merge linkage, correction identification and recovery relationships. The additional passing independent case verifies GET `/triad/api/cycles` performs no record/work mutation; HTML/JS routes serve successfully; repeated identical recovery linking is idempotent; and original CycleRecord payloads remain unchanged while a recovery relationship is appended. Billing assertions in the failing provenance case pass before reaching the lost WorkItem assertion: Aegis's 99-unit cost is excluded, the Triad API amount remains 0.25, and subscription usage remains token evidence.

Ruff check of the independent regression file: **PASS**, `logs/day7-c-qa-lint.log` and `.exit`. Implementation and evidence hashes are in `DAY7_C_QA_HASHES.json`.

## UI and acceptance limitations

Source uses textContent for cycle values and the shared readable record renderer, with local timestamp formatting. HTTP fixture smoke covers route delivery and read-only behavior, not actual browser rendering, mobile layout or live history. The live backend still runs earlier reviewed code; browser acceptance and production historical backfill are deferred until this correction gate passes. This verdict does not claim completed Phase 4 or approve other Day 7 segments.
