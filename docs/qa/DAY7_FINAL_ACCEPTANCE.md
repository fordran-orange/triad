# Day 7 — final independent release acceptance

**PASS** for exact candidate `eeaa2520284e8be6e2d498c6f0f7a735227632d7`,
tree `070c2ba6063f172b0f07069b27696afcc4e83e71`.
Reviewer `/root/day6_qa_c`, independent from builder/operator `/root`, 2026-09-19.
No blocking finding remains for the authorized Day 7 scope.

## Exact candidate and completed regression

Independently confirmed the exact HEAD and clean working tree before adding this
report. Application/configuration/infrastructure/tools remain unchanged from the
independently accepted `eea65d393efc644f4b443914b26ce9023e4bec2e` correction.
The later independent regression test is included in the executed final snapshot.

Reviewed the finished complete run, `logs/day7-final-full-regression.log`, and its
zero exit file: **535 passed, 5 warnings in 1145.97 seconds**, with no skips or
failures. Root executed that full suite; I independently audited its result and
source/evidence binding instead of rerunning a concurrent database suite. The
five warnings are two dependency deprecations and three duplicate proxy OpenAPI
operation IDs. These disclosed nonblocking warnings were not suppressed.

Independently recomputed every entry in `DAY7_ACCEPTANCE_MANIFEST.json`:

- **290 source files** match their frozen actual-byte hashes, including application,
  configuration, SQL, tools and tests. The exact file map equals the pre-run
  snapshot. Recomputing its sorted JSON aggregate gives
  `278debeb40dfcab583392d9f8e0b223a031d6b238171ca1dceb8d12b9e30a74e`.
- **119 retained evidence files** match their recorded raw-byte hashes.
- The evidence ZIP contains all 119 entries, passes CRC validation and each
  archived entry matches the manifest. Archive SHA-256 is
  `f115858be0c1ed39a0721516f1b3ad867501b8805e445958cf45ad10f92ad673`.

The manifest SHA-256 is
`05852123d4f87b1fd0bd03872f5515941cbe9bf29b9e0aece2fc6c290222ec99`.
The archive is `backups/day7-final-evidence-20260919T2154.zip`.
Earlier five-failure full regression, intermediate correction failures and all
bounded negative QA decisions remain preserved; their corrected cases have fresh
independent PASS evidence and pass the final complete run.

## Scope, recovery and operating acceptance

Read `docs/DAY7_REPORT.md` against the final reports and raw evidence. It accurately
separates implemented foundations, unavailable broker functionality, retained
historical failures, definitions-only readiness resolution and future work.
The earlier independent audits remain part of this final decision:

- `DAY7_FINAL_EVIDENCE_AUDIT.md` maps A–I and timestamp/deployment corrections to
  independent exact-revision QA. Original ownership, metadata, adoption, resource,
  cycle and deployment defects have retained failing evidence and fresh corrections.
- `DAY7_LIVE_ACCEPTANCE_QA.md` independently verifies migration 013, preserved
  historical full rows (168 intelligence, 91 artifact-owner and 101 WorkItem rows),
  all 228 original artifact hashes, the BLOCKED REAL cycle and separate recovery,
  immutable original OPEN debt plus exact-byte definitions-only resolution, and
  the actual Windows desktop shortcut target and launcher hash.
- The pre-final PostgreSQL restore rehearsal is corroborated by independent
  read-only checks of its retained database, original IDs and row hashes. The
  graph logical backup parses with 5,250 unique nodes, 2,556 edges and no dangling
  endpoints. No additional Neo4j restore rehearsal is claimed.
- `DAY7_RELEASE_PRECHECK_QA.md` independently verifies all 32 canonical build/QA
  pairs, matching owners/commits/latest independent decisions, 245 unique pinned
  source blobs and 123 installed-package file byte matches. It also records the
  corrected-backend restart and fresh read-only service/provider checks.
- Clean-wheel route/resource smoke and historical data/backtest regression have
  zero exits. Historical experiment content and source provenance are preserved.
  The final complete suite includes architecture, kill, cancellation and product
  failure-isolation boundaries using disposable fixtures.

Current readiness evidence shows Core and both product workers healthy, all four
providers ONLINE, gate PASS and zero active provider runs. This is readiness and
retained execution evidence, not newly executed model inference. Aegis remains
inactive/human-directed/preserved with exchange CLOSED. Broker entries remain
disabled and NOT_CONFIGURED; order authority and automatic paid fallback remain
denied. No scheduled autonomy or next product cycle is enabled.

## Browser provenance and limits

Actual browser interaction in `DAY7_LIVE_BROWSER.md` was performed by `/root`;
I independently reviewed its observations and corroborated deployed content and
assets through read-only HTTP/data checks. The builder additionally confirmed
the actual tool observation titled “Verify launchpad fits the current narrow
panel”: `/launch` had clientWidth **304**, scrollWidth **304**, and all six links
width **200**; `/core/integrations` likewise had clientWidth/scrollWidth **304**.
This later narrow-panel observation was omitted from the earlier browser report
but is explicitly preserved here with its operator provenance. No viewport
override or file-URL restriction bypass was used.

The browser work is a bounded smoke covering navigation/loading/filtering/readable
details/keyboard dismissal/focus return and narrow layout. It is not described as
exhaustive mobile, forced-outage or synthetic browser-injection testing; separate
independent fixtures cover input/authorization and server failure boundaries.
No independent browser execution by this reviewer is claimed.

## Release disposition

The exact candidate is accepted for the final authorized host release. I reviewed
the prepared, unexecuted `logs/day7-release-governance.py`: it pins this candidate,
requires a clean evidence-only descendant containing only the two final QA files,
rechecks the 290 source and 119 evidence hashes and full-suite exit, applies the
existing Core ledger guard, and records typed revision-bound independent QA with
`Quality.require_pass`. It checks main ancestry and absent completion tag; it does
not itself change Git references.

The builder may now commit only this report and its companion hash manifest,
execute that final Core governance gate, and perform the separately planned
compare-and-swap fast-forward of main, switch to the identical accepted HEAD and
annotated `base/day7-complete` tag. Recheck source/evidence bytes and clean status
afterward. Any implementation change invalidates this acceptance for the affected
revision. This report does not claim those final governance/ref/tag actions have
already occurred and authorizes no remote push, broker connection or new product
execution. QA added only these two final acceptance files.
