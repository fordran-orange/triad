# Core / Triad reconciliation — September 29, 2026

This stabilization joins the preserved Day 8 branch (`f556cae`) and the later
Milestone 1 commits on `main` (`517260f`). The combined implementation is
`beea93c53c7d36e70906fb4695ca475e7a064fd3`, followed by the independently reviewed
graph correction at `e3750a5ef36dbe2d724cfcf5ba2ae84d16c196b7` and provider outage
recovery correction at `c2da56d16e6e031fc34cd025ca4bd7345cf8695d`. Local `main`
contains both histories and these reviewed fixes. Core and Triad were restarted
from the merged source. The original branch histories, Day 8
reports, QA reference context, failed cycles and isolated candidates are retained.
This is not Day 8 completion or proof of unrestricted autonomous engineering.

## Reconciled behavior

- Provider discovery prefers a dedicated, version-pinned installation under
  `C:\Triad\data\provider-cli`. Installed fallback locations also work with an
  outdated service PATH. Missing installations, incompatible versions, unknown
  authentication, quota errors and actual execution failures have distinct states.
- Codex's desktop update changed its path/version. The dedicated compatible CLI
  is installed and reuses its existing ChatGPT login. Claude and Grok also use
  dedicated compatible subscription CLIs. API paths remain separately configured;
  no paid API fallback or new credentials were enabled.
- Qwen's existing model store is `C:\AI\Models\Ollama`. Ollama was stopped; its
  executable and Qwen3 4B model were present. Starting the existing server restored
  its API. The supervisor preserves that location and checks Ollama even while
  Core's own liveness endpoint is healthy. No model was moved or downloaded.
- A temporary Ollama outage now preserves successful setup verification at the
  same endpoint while reporting the current failure. Malformed version responses
  also persist an unavailable state. Recovery with the same identity reuses the
  evidence; a real endpoint or version change still requires fresh verification.
- The added direct-host CLI runner and automatic Git entry points bypassed
  canonical authority and independent QA. They now reject execution. The local
  proof launcher delegates to the established Runtime/WorkItem/isolated build/QA
  path. An ordinary Git worktree is not presented as a filesystem sandbox.
- Protected-path checks cover shared Core authority, non-Triad products, runtime
  data, credentials, dependencies and instructions, including Windows case/path
  aliases. Reviewed product text and exact granted UI assets still work.
- The existing independent QA reference bundle and Day 8 build dispatch are
  preserved. Normal product work uses its existing machine gates; the explicit
  operator emergency/human-review control is not silently removed.
- Post-merge recovery creates an auditable Git revert, verifies the prior tree,
  and restarts services. It refuses a changed/dirty baseline. Timeouts and failed
  health checks cannot be reported as a successful deployment.
- `run_milestone1.ps1` defaults to local startup checks. `-RunCycle` explicitly
  runs the existing governed bounded product proof; `-NoMerge` retains its reviewed
  candidate. It neither silently fetches new code nor upgrades Python packages.
  Remote changes must be reviewed separately. Broader tools still need verified
  isolation and capability adoption; they are not granted by this launcher.
- Immutable readiness Markdown uses LF in Windows checkouts, preserving its
  established byte hashes without editing its content.
- Retained failed market-data manifests no longer block the graph update queue
  when their raw archives have no normalized identity. Their graph entries retain
  REAL/FAIL, with no invented raw IDs or normalization links. Canonical dataset
  projection remains strict. This does not normalize or make the archives eligible.
- The dedicated vendor CLI dependency directory is ignored by Git.

## Validation and evidence

Scoped independent reviews are retained in `docs/qa/reconciliation-20260929`:
provider fixes (99 tests), governance/runtime fixes (107 tests), milestone wrapper
and actual disposable Git recovery (17 tests), and Ollama/Windows supervision
(10 tests plus live model discovery). The Windows task was subsequently registered
and independently checked: current interactive user, limited privileges, canonical
production script, logon and indefinite five-minute triggers. Manual and scheduled
runs returned success. Reboot/logoff behavior was not tested. CI includes the new
focused tests.

The first complete unit selection passed **465 tests**, with 291 integration tests
deselected and five pre-existing warnings. An initial worktree run exposed two
missing-runtime-configuration failures and the immutable-document CRLF issue;
those results are retained alongside the corrected full run. Tests use the
candidate source with the configured runtime home explicitly supplied. After the
graph correction, the complete unit selection passed **476 tests**. Its 11 new
regressions also passed again after an import-spacing-only lint correction, and
Ruff passed across application, tests and tools.

Fresh installed wheels from both the combined source and final code revision
`e3750a5` passed independent verification: 131 package files match,
27 HTTP route checks pass, SQL and static resources are present, and the installed
QA-reference generator works. This was an offline smoke check, not a database
or provider test.

All four providers passed real connection and bounded-work verification from the
combined source: Grok `grok-4.7`, Claude `claude-sonnet-5`, Codex `gpt-6-astra`, and
local Ollama `qwen3:4b`. Claude's first bounded-work response was rejected with
`NativeResultViolation`; one fresh unchanged retry passed. Both canonical results
and measured usage are retained. No paid API fallback was used.

The full database integration run finished with **288 passes and three failures**:
missing journal export, a projection retry `KeyError`, and empty work lineage.
All 312 frozen source hashes remained unchanged during that run. The failures
exposed the blocked failed-manifest projection queue. The correction passed
independent offline tests. The reviewed replay delivered all **11,813** queued
updates in 24 batches, with no errors. All three retained dataset records and raw
file checksums were unchanged, and their graph entries remain Core-owned REAL/FAIL
with zero normalization links. The independent correction run then passed **all
23 tests** across the complete Day 2, product-ownership and laboratory integration
files, including all three former failures. This is a focused correction rerun;
the original 291-test failure report is retained rather than relabeled as a clean
full rerun. Most integration
fixtures use disposable databases; legacy Day 2 uses the live database and cleans
up its exact synthetic records.
Connection/authentication checks alone are not used as proof of model execution.

After deployment, all eight fresh connection/read-only WorkItem checks passed:
two each for Codex, Claude, Grok and Qwen. They used the dedicated compatible CLI
paths and the existing local model. The live provider gate passed, all four
providers were ONLINE and no test calls remained active. These checks recorded
94,275 input and 3,692 output tokens; there were no paid API calls or retries in
this deployment batch. Earlier failures remain in their original evidence.

The final outage correction passed **63 focused tests**, including 11 independent
adversarial cases, and Ruff. Independent QA initially found four malformed-response
failures at `2cf1166`; those were corrected before deployment and the failures are
retained. A broad unit run at that intermediate revision was interrupted when the
finding arrived, so no full-suite pass is claimed for it. The earlier 476-test
baseline pass and final focused correction checks are separate results. A fresh
installed wheel from final code `c2da56d` again passed all 131 file checks and 27
route checks. No application source changed during final documentation work.

A bounded live outage test on deployed `c2da56d` stopped only the verified Ollama
server, refreshed its status, and observed OFFLINE/UNAVAILABLE with the original
two proof IDs retained. The installed supervisor restored it; a fresh status check
returned ONLINE with the same proof IDs and Qwen model digest. Core's process was
unchanged. The recovery required zero inference calls, downloads or sign-ins.

Browser acceptance confirmed live Core and Triad dashboards, labeled permissions
and diagnostics, the journal record reader, the proposals empty state, and provider
settings with correct subscription login/readiness and separate unconfigured API
connections. This was representative UI acceptance, not every interactive workflow.

Before deployment, PostgreSQL and 281 local artifacts were backed up to
`backups/reconcile-20260929T162405Z/`; archived artifacts were checked against
their source hashes. This backup did not relocate raw data or credentials.

## Preserved scope and remaining work

Aegis remains inactive and human-directed, with exchange closed and no product
work. Scheduled product development remains disabled. The SPY/QQQ/ITOT archives
remain REAL/FAIL and ineligible, pending the separately deferred data-contract work.
No broker or live-trading authority was added.

Day 8's product candidate still needs its documented response-validation correction,
fresh independent QA, governed merge, browser acceptance and reviewed Daily Debrief.
No `base/day8-complete` tag is created by this stabilization. A connection verification
is not a completed autonomous product cycle.

The configured GitHub remote returned “Repository not found” during fetch.
Reconciliation uses the branches already present locally; remote synchronization
is not claimed. No credentials were reset or reset credits redeemed.
