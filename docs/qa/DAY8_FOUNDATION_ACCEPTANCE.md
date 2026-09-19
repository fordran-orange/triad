# Day 8 combined foundation — independent acceptance

**PASS for the bounded foundation candidate `700cf7d1d5bec717a62e001639d9a44cae18ec35`.** Reviewer: `/root/day6_qa_a`, independent of the builder. This permits the next governed merge/deployment stage; it is not acceptance of the first real daily product cycle, live browser behavior, schedule activation or all of Day 8.

The candidate was clean before this report. Its app/tool/package implementation is byte-identical in Git to `2a8c0c2846eba2a4400cd6c93ea8d0c2e87b374e`; the last commit retains the independently tested scheduler tests and correction evidence. No app implementation was edited during this acceptance.

## Exact scope and independent evidence

All **26** changed app/tool/package files against `base/day7-complete` are covered. The manifest audit matches 23 current files to exact previously reviewed source hashes. The remaining two scheduler/cycle-history files are covered by the fresh dispatch correction, and the final development-page copy was reviewed directly and included in the fresh HTTP surface checks. Every changed Python implementation file passes Ruff.

| Foundation | Final independent source acceptance | Meaningful evidence |
| --- | --- | --- |
| Readiness | ef79fce / DAY8_READINESS_FINAL_QA | 36 passing cases; real bar projection, source availability, typed evidence, exact independent QA, session coverage and false-READY denial |
| Daily lifecycle / Store transaction | 6e1f3ae / DAY8_DAILY_FINAL_QA | 22 passing cases; completion, publication, ownership, epochs, immutable evidence and rollback |
| Daily API/UI/package | 939cf7d / DAY8_DAILY_UI_FINAL_QA | HTTP, Node DOM/error/filter/injection checks and installed-package checks; subsequent schedule fields reviewed separately |
| Isolated engineering | b43054b / DAY8_ENGINEERING_FINAL_QA | 51 passing cases plus two corrected independent fixture cases; mediation, fixed checks, paths, bytes and native boundaries |
| Revocable role/probe overlay | 5faaec9 / DAY8_ROLE_PROBE_FINAL_QA | 9 passing cases plus offline prechecks; immutable base role, exact capability/QA and original epoch |
| Scheduler | 6891f07 + 75126a3 / DAY8_SCHEDULER_FINAL_QA | 17 passing backend cases, DST and explicit schedule-zone display |
| Workflow / evidence refresh | add70c2 / DAY8_WORKFLOW_FINAL_QA | 9 passing cases in 181.31s; actual fixture Git/QA/merge/debrief pipeline, fresh correction, authoritative usage evidence and post-merge drift denial |
| Scheduled failure evidence | 67e4ee6 / DAY8_SCHEDULER_DISPATCH_QA | Fresh 15 passing cases in 61.07s; stopped/revoked attempts preserve blocked daily records, original epoch, no execution and no retry |

The audit checked 62 source/test manifest entries and 70 evidence references. Three historical references intentionally concern amended QA tests: the lifecycle test added after its source commit, the engineering test adapted to original RunAuthority, and the scheduler test updated for the newly required blocked-record semantics. All three exact older hashes match preserved test copies. These are documented in `logs/day8-foundation-evidence-exceptions.json`; no source mismatch was excused. Earlier negative QA reports and logs remain preserved.

## Combined seams checked

The real feature route must return 503 before product assets exist and 200 after a governed build installs them. The previous post-merge test incorrectly depended on missing checkout assets. Correction `11076fd` isolates both route states in temporary fixtures; the actual workflow verifier can now validate either state without always rejecting a successful feature build.

The final direct run, with **CORE_PROVIDER_MONITOR=0**, executed `python -m pytest tests/test_day8_daily_ui_qa.py tests/test_day7_surfaces.py -q -m "not integration"`: **13 passed, 1 deselected, 2 existing deprecation warnings in 3.30s**, exit 0. This covers API/auth fixtures, readable pages, strict UTF-8, missing/present feature assets and truthful product-shell copy. The development page now directs users to the governed Daily Debrief schedule while keeping live trading explicitly disabled. This copy no longer becomes false if the separately authorized schedule is later enabled.

The combined audit also found that failed scheduled dispatch must retain a daily CycleRecord even before workflow creation. The separately frozen correction run now proves current kill/pause/stale epoch/product pause and revoked prerequisite produce finished BLOCKED DAILY_PRODUCT evidence with no provider execution and no automatic retry. Legacy non-daily blocked callers retain their existing defaults.

Core remains generic: readiness and engineering are shared services; Triad owns lifecycle, schedule and product conclusions. The UI has authenticated schedule mutation and read-only evidence routes. The background worker does not bypass manual completion, immutable schedule identity, original epoch or the daily claim. Fixed feature paths remain isolated and bounded; model code does not gain host Git/shell authority or paid fallback. The new route/package seams preserve the unsupported/missing-feature state honestly.

## Evidence and limits

Agent B separately accepted the real Claude capability probe and exact proposed revocable role scope in DAY8_ENGINEERING_REAL_QA. That is evidence for the narrow governed capability-adoption step, not a completed product change or browser acceptance. This reviewer made no vendor calls or capability/schedule writes.

The earlier whole nonintegration collection recorded 362 passed and one stale Day7 product-badge assertion failure. That assertion was corrected to the reviewed Day8 copy, retaining no-live-account and no-real-market-readiness checks, and passes in the fresh direct run. The larger whole regression was still running against its frozen earlier collection when this bounded verdict was issued. **No final whole-suite or whole-Day-8 PASS is claimed here.** The builder must retain and resolve its actual result before final release acceptance.

One earlier preliminary surface run did not explicitly disable the Core provider-monitor lifespan and therefore may have performed an ordinary connection-health metadata refresh. No inference, login, authority, schedule or execution mutation was requested. The test now explicitly disables monitoring, and the final run above sets it off again. This report does not mislabel that preliminary run as guaranteed free of health-metadata side effects.

No production schedule activation, product-cycle execution, deployment, or browser operation was performed for this acceptance. Real Research Readiness generation, separate provider QA, exact governed product merge, post-merge verification, browser acceptance and a reviewed real debrief remain required before daily scheduling prerequisites are satisfied. Pending full regression and final live acceptance remain release gates.
