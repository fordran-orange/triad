# Day 6 Triad product framework independent QA

Final decision: **PASS** for the exact corrected framework and scoped Core Git
policy in `DAY6_PRODUCT_FRAMEWORK_FINAL_HASHES.json`.
Initial decision: **CHANGES_REQUIRED**. Independent reviewer `day6_qa_a`;
builder root. Review date: 2026-09-19. This is the bounded framework review,
not acceptance of an actual autonomous product improvement.

Baseline commit: `8927755b89aa1a240adedd96ab366f239124d19e` plus uncommitted
framework files. Exact SHA-256 identities are preserved in
`DAY6_PRODUCT_FRAMEWORK_INITIAL_HASHES.json`. No implementation edits by QA.

## Initial blocking findings

1. **P1 — Successful read-only provider calls cannot complete.**
   Development.call creates read-only assignments with no reviewer, then calls
   Orchestrator.journal with kind=review. That helper uses work.reviewer as the
   journal actor; JournalEntry rejects None. This breaks frontier inspections,
   independent QA and local synthesis after successful inference. Verified with
   a real routed read assignment and with a disposable full build/QA/merge flow.
2. **P1 — QA can inspect dirty bytes under the original commit identity.**
   Development.qa trusts fresh Git.verify sources without checking clean index/
   worktree, HEAD equality and equality to original build hashes. Changing a
   built artifact on disk reaches the QA dispatch labeled with the original
   change_commit. Bind exact build sources before QA and recheck before merge;
   fail closed on any modification, including staged or untracked changes.
3. **P2 — Extra required capabilities are silently ignored.**
   A proposal requiring native_x_access in addition to the two expected
   capabilities passes approve; call then routes only the hardcoded pair. Either
   route all required capabilities or reject unsupported extras explicitly.
4. **P2 — Failed build/QA lifecycle evidence is incomplete.**
   A provider build failure marks the WorkItem FAILED but has no canonical
   FAILED ImplementationRun. REQUEST_CHANGES and REJECT QA records both leave
   the builder WorkItem AWAITING_REVIEW. Retain failures as canonical runs and
   transition old assignments consistently before a new correction/QA run.

## Independent execution evidence

Commands used `.venv\\Scripts\\python.exe` with `TRIAD_INTEGRATION=1`:

```text
python -m pytest tests/test_day6_product_framework_qa.py tests/test_product_development.py -q
python -m pytest tests/test_day6_product_framework_qa.py -k "negative_qa or extra_unverified" -q
python -m ruff check tests/test_day6_product_framework_qa.py
python tools/check_package.py
```

First run: **4 failed, 7 passed**, 57.49 seconds; log
`logs/day6-product-independent-initial.log`. Additional adversarial run:
**3 failed, 5 deselected**, 28.83 seconds; log
`logs/day6-product-independent-extra.log`. Ruff passed. Clean installed-package
smoke passed; output is in `logs/day6-product-independent-package.log`, with
installed evidence at `C:/Users/fordr/AppData/Local/Temp/trading-core-package-drynlntg`.
An additional isolated import from that wheel's `installed` directory verified
Triad's development HTML and JavaScript routes return HTTP 200 with expected
content. This ran outside the checkout with `-I`, dummy settings and no app
lifespan/worker startup, using `data/temp/day6_product_package_qa.py`.

Eight independent tests were added. Fixtures use disposable PostgreSQL and real
isolated Git repositories/worktrees. Only the provider transport response is
stubbed; routing, authority, canonical storage, source checks and Git operations
are exercised. Fixture usage explicitly identifies independent QA fixture mode.
No production provider policy was changed; no production inference was invoked.

Denial checks pass for kill-before-build, product ownership, absent QA,
interrupted-build replay, legacy real-stage bypass, and unsafe paths. Current
contract/CLI/API/source boundaries preserve P2P, closed exchange and disabled
live trading. Product source documentation contains no human-preferred strategy
seed. Initial inspections see only a neutral host baseline, not implementation
source; include equal bounded actual product source in all independent contexts
or accurately limit the inspection claim to a baseline-document assessment.

## Browser evidence limitation

A no-worker/no-DB/no-provider preview was created at
`http://127.0.0.1:8007/triad/development` using
`data/temp/day6_product_qa_preview.py`. It serves populated, empty and controlled
failure fixtures, including HTML injection sentinel text and a merged artifact.
Its mode file is `data/temp/day6_product_qa_preview.mode`.

CUA in this QA agent returned `apps=[]` and `browsers=[]`. Creating an iab tab
returned `Browser is not available: iab`. Independent reviewer `day6_qa_c` also
reported unavailable browser surfaces. Therefore this review does **not** claim
actual browser, responsive-layout or console verification. Source uses
textContent/replaceChildren and read-only endpoints; that source inspection is
not a substitute for the required browser QA.

Correction requires a fresh independent test run and new exact file hashes.
Browser QA remains a separate outstanding acceptance gate.

## Correction run 1 — CHANGES_REQUIRED

The builder corrected the four initial groups, added equal actual product
source grants for all inspections, and corrected lifecycle UI states. Independent
tests expanded to staged, unstaged, untracked and post-QA source tampering.
Combined result: **1 failed, 21 passed** in 146.66 seconds
(`logs/day6-product-independent-correction.log`). Exact code snapshot:
`DAY6_PRODUCT_FRAMEWORK_CORRECTION1_HASHES.json`.

The full disposable flow now reached merge and found another **P1 runtime
blocker**: Development.merge constructed the required Review record without
its mandatory severity. This was independently observed after successful
separate QA; no merge occurred on that run.

## Correction run 2 — CHANGES_REQUIRED

The builder added the missing validated severity. Independent full-flow retry:
**1 failed** in 16.96 seconds
(`logs/day6-product-independent-correction2-happy.log`), exact implementation
hash in `DAY6_PRODUCT_FRAMEWORK_CORRECTION2_HASHES.json` (other files unchanged
from correction 1).

The retry performed the disposable Git merge, then failed the post-merge
byte-hash check because system Git `core.autocrlf=true` converted the reviewed
LF artifact to CRLF on checkout. The reviewed worktree file had 35 bytes,
0 CR and 3 LF, SHA-256
`f94c8b4fa20895766647b4bfdaae86cab1a9891505fb329d541a3297a6b26acc`.
The merged checkout had 38 bytes, 3 CR and 3 LF, SHA-256
`d77dae3908dcef969d6d66a62f2a02d4cce1004f2eacd60bba4292b3a1cd6e67`.
Both byte sequences were inspected directly in the disposable pytest-129
repository; this was not a guessed explanation.

**P1:** enforce a deliberate approved-artifact checkout policy before merging so
reviewed bytes remain the merged bytes; retain content-tamper rejection. The
current failure occurs after Git merge but before canonical ProductMerge,
requiring reconciliation. Do not mask it by removing hash assertions.

## Browser gate update

The root agent's CUA surface worked. Root performed the actual interactions;
independent reviewer `day6_qa_c` reviewed the captured observations and source.
The resulting UI-only verdict is PASS in `DAY6_PRODUCT_BROWSER_QA.md` with exact
hashes and explicit executor/reviewer provenance. Coverage includes eight views,
readable details/artifacts, injection as plain text, 390px layout and dialog,
empty/initial-outage/stale-snapshot states, corrected MERGED/FAILED badges and
clean console. This resolves the isolated fixture UI gate; live destination-link
checks remain a post-launch task, and backend approval still requires fixing
the merge byte invariant above.

## Correction run 3 and final independent approval — PASS

Core GitChanges.merge now supplies `core.autocrlf=false` and `core.eol=lf` only
for its approved merge command. It changes no global or repository Git setting;
raw SHA-256 comparisons remain intact. The independent full disposable flow
passed in 19.95 seconds under this machine's original autocrlf=true setting
(`logs/day6-product-independent-correction3-happy.log`).

Fresh broader independent regression: **60 passed** in 164.45 seconds
(`logs/day6-product-independent-final.log`). Command:

```text
python -m pytest tests/test_day6_product_framework_qa.py tests/test_product_development.py tests/test_architecture.py tests/test_day3.py tests/test_day6_qa_a.py tests/test_ownership_integration.py -q
```

This includes existing Core Git isolation, protected merge, exact rollback,
scope and stale-hash tests; canonical QA acceptance/rejection; product-private
storage/graph boundaries; and full product build/QA/merge plus correction flow.

Two final narrow compatibility/evidence corrections received new independent
affected-path tests after the broader run:

- Exact installed-transport directory roots are required in proposals, so a
  filename/descendant grant cannot be approved and then fail protocol dispatch.
  **5 passed**, 28.90 seconds (`logs/day6-product-independent-final-affected.log`).
- Independent product QA receives the same original source read grants as
  inspection, alongside exact staged artifact hashes/diff. Explicit source-
  grant and hash assertions, normal merge, correction/new-QA merge, read-call
  journal and exact-root denial tests: **5 passed**, 57.69 seconds
  (`logs/day6-product-independent-final-sourceqa.log`).

The final independent test file has fourteen cases. It verifies separate
builder/reviewer executors and WorkItems, real Git merge and served exact bytes,
staged/unstaged/untracked and post-QA tamper denial, kill-before-build, explicit
capability requirements, failed build records, failed QA state, correction
parent lineage, rejection of old QA for a new correction, and successful new QA
before corrected merge. Only inference is replaced by a controlled fixture;
actual provider acceptance remains the next execution phase.

Ruff passes for implementation and test files. Product configuration and its
packaged resource hashes match. The final manifest was captured after the
long-title mobile CSS correction and includes `app/trading_core/git_tools.py`.
Final wheel rebuild also passed; installed evidence:
`C:/Users/fordr/AppData/Local/Temp/trading-core-package-ke1x3yh_`.
The final wheel's Triad development HTML/JS routes passed the separate isolated
installed-asset check (`logs/day6-product-independent-package-final.log` and
`logs/day6-product-independent-package-assets-final.log`).
Browser-only approval and its honest executor/reviewer provenance are in
`DAY6_PRODUCT_BROWSER_QA.md`; both framework and UI are now independently
approved within this bounded scope.

No unresolved blocking finding remains. These checks do not claim a completed
real frontier inspection or product improvement, production worker launch,
live destination-link verification, or live trading capability. Those remain
the subsequent authorized acceptance work. Any new code correction requires
fresh independent QA for the affected revision.
