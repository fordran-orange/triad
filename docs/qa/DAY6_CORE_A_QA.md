# Day 6 Core A independent QA

Final decision: **PASS** for the corrected Core A files identified in
`DAY6_CORE_A_QA_FINAL_HASHES.json`. Initial decision: **CHANGES_REQUIRED**.
Reviewer: independent QA agent `day6_qa_a`; builder: root agent.
Date: 2026-09-19. Scope is Core segment A only, with no UI.

## Exact reviewed revision

Base HEAD: `7603807ad7402462425fc15e9946d839dd89e106` on
`codex/day6-intelligence`, plus the uncommitted Core A files. Exact SHA-256
hashes of every reviewed file and the added independent tests are preserved in
`DAY6_CORE_A_QA_INITIAL_HASHES.json`; tracked baseline diff is preserved in
`DAY6_CORE_A_QA_INITIAL_TRACKED.patch`. Untracked implementation files are
identified by their complete hashes, not by the baseline commit alone.

Reviewed: `intelligence/{contracts,records,quality,capabilities}.py`, package
initializer, Ledger initialization, migration 010 and identical packaged copy,
builder tests, AGENTS.md, and Day 6 execution documentation. Read surrounding
provider verification, scope/ownership and storage code to assess integration.
No implementation files were changed by QA.

## Initial required corrections (resolved below)

1. **P1: product callers can manufacture accepted independent QA.**
   `Quality.review` accepts a product-scoped `Records` instance and permits its
   caller to assert `HOST_INDEPENDENT_QA` with arbitrary identity strings and no
   observed independent run. Worse, `Records.append("QARun", ...)` bypasses the
   QARun validator entirely: a product can append a PASS with empty tests and
   empty evidence, and `Quality.require_pass` accepts it. The intended host-only
   ingestion boundary must be enforced, including direct append paths and typed
   read validation, before the product lifecycle can trust this gate. This is
   reproducible through the scoped public service; it does not require direct
   database access or hostile Python plugins.
2. **P2: ordinary unverified providers crash runtime discovery.**
   `discover_runtime` calls `.get` on `snapshot["workitem"]` when that value is
   None. Provider refresh/invalidation explicitly produces this shape. An unused
   or invalidated provider should be skipped without preventing discoveries for
   other providers; incomplete proof should fail closed.
3. **P2: passing observations are omitted from QualityDebt.**
   PASS_WITH_OBSERVATIONS with a nonempty `findings` tuple creates no debt unless
   the caller also copies the observation into `optional_improvements`. Preserve
   all non-blocking observations as debt (or enforce a structured classification
   that prevents an accepted observation from being silently omitted).

## Executed evidence

Environment: `.venv\\Scripts\\python.exe`, `TRIAD_INTEGRATION=1`. Integration
fixture creates and drops a disposable PostgreSQL database for each test; no
provider inference or paid API calls were made.

Commands:

```powershell
$env:TRIAD_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests/test_intelligence_capabilities.py tests/test_day6_qa_a.py tests/test_architecture.py -q
.\.venv\Scripts\python.exe -m ruff check tests/test_day6_qa_a.py app/trading_core/intelligence tests/test_intelligence_capabilities.py
```

First combined run: **3 failed, 12 passed** (`logs/day6-qa-a-initial.log`).
Additional direct-append adversarial run: **4 failed, 3 passed**
(`logs/day6-qa-a-adversarial.log`). Final combined result: **4 failed, 12 passed**
in 24.84 seconds, retained in `logs/day6-qa-a-final-initial.log`. Ruff passed.

The seven added independent tests cover null verification snapshots, forged
host QA, malformed direct QA append, atomic rollback when mirror/outbox writing
fails, rejection of TEST_FIXTURE proofs, correction invalidation of prior QA,
and retention of observations. Existing tests independently rerun ordinary
governed adoption, exact capability-digest binding, stale/self-review rejection,
latest failing verdict, append-only SQL protection, and product ownership.

SQL mirrors have identical SHA-256 hashes. Architecture checks pass, preserving
Core/product import independence. Runtime discovery makes no unearned native X,
web or shell claim in the reviewed code. Browser, dynamic-agent lifecycle,
routing, product build/merge and full Day 6 acceptance are outside this segment.

## Independent correction QA

The builder corrected the three findings. QA inspected the actual corrected
code and reran the combined integration and architecture command independently.
First corrected run: **16 passed** in 22.15 seconds
(`logs/day6-qa-a-correction-1.log`). The builder then added typed canonical
evidence revalidation and clarified that the local privacy claim describes the
transport's hard-pinned loopback path; that additional change received a new run.

Final independent run: **17 passed** in 28.55 seconds
(`logs/day6-qa-a-final.log`); Ruff passed. This includes eight independent tests,
four builder capability tests, and five architecture tests. Exact final file
hashes are in `DAY6_CORE_A_QA_FINAL_HASHES.json`. SQL copies still match.

Observed corrections:

- Null workitem proof now skips discovery safely.
- Scoped callers cannot append canonical builds, QA, quality debt or capability
  versions; scoped Quality.review is denied explicitly. Both scoped exploit
  tests now use a legitimate host-ingested Triad build as setup, retaining the
  attempted malicious product review/append and rejection assertions.
- require_pass revalidates canonical build and QA contracts. A new independent
  malformed-host-evidence test confirms an empty-evidence PASS cannot authorize.
- Non-blocking findings in PASS_WITH_OBSERVATIONS are retained as deduplicated
  QualityDebt alongside optional improvements.
- Prior passing QA remains unusable for a correction, fixture QA cannot publish
  truth, and failed mirror writing still rolls back the canonical insert.

No blocking finding remains in this bounded segment. Existing Starlette/httpx
and AnyIO deprecation warnings appeared; no assertions were weakened. Core's
host ingestion remains trusted to attest an actually observed independent run;
these checks do not claim an external identity provider or cryptographic agent
attestation. Later product integration must continue using that host boundary.

Any later implementation correction invalidates this approval for the affected
files and requires another independent QA run. This report does not approve
Day 6 stages B/C, the UI, provider inference, or the product build/merge cycle.
