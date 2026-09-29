# Provider reconciliation — separate independent correction QA

**PASS for the seven exact files bound in reconcile-provider-independent-qa.json.** Reviewer /root/day6_qa_a; builder /root/day6_qa_b. Source reviewed in C:/Triad/data/temp/reconcile-stabilization-20260929, pending combined integration commit. This is a scoped provider verdict, not approval of unreviewed launcher or other integration changes.

## Original finding and correction

Initial provider source returned AVAILABLE after a fresh detect() reported UNAVAILABLE or DETECTION_FAILED if subscription authentication and a cached isolated-readiness result were true. The actual-method offline reproduction is retained at logs/reconcile-provider-health-failure-probe.json, with initial exact source hashes in logs/reconcile-provider-initial-qa.json. Initial verdict was CHANGES_REQUIRED.

The correction now rejects every non-INSTALLED or non-VERIFIED executable before probing authentication/readiness, retaining distinct NOT_FOUND and VERSION_MISMATCH messages. The existing Grok unknown-authentication test now explicitly supplies installed/verified detection so it tests unknown login rather than an unrelated missing fixture executable. Its prior failing log is retained.

## Fresh independent execution

99 passed,2 existing dependency warnings in14.08seconds, exit0. Command used repository Python, isolated-checkout app/tests on PYTHONPATH and CORE_PROVIDER_MONITOR=0:

`python -m pytest tests/test_provider_reconcile.py tests/test_provider_control.py tests/test_native_agents.py tests/test_codex_executor.py C:/Triad/logs/test_reconcile_provider_independent.py -q -m "not integration"`

All7 final file hashes match the builder's corrected frozen manifest. Ruff passes changed Python and node --check passes the actual inline provider UI JavaScript. No inference, real login/logout, production database mutation or package installation was performed by this reviewer.

The tests cover durable prefix priority; legacy prefix and stale-PATH desktop discovery; explicit Node discovery; native Claude without Node; missing Node/script; broken preferred installation without silently substituting a desktop executable; supported executable with missing login; mismatch refresh invalidating old proof; unsupported versions remaining VERSION_MISMATCH rather than falsely signed out; exact existing Claude isolated implementation; Codex remaining read-only; forged context workspace not enabling implementation; and legacy AUTH_FAILED schema compatibility. Native executor regressions repeat isolation, observed tool/evidence and result-validation behavior. No unproven shell/network/MCP capability is advertised by the fallback UI.

Unknown/missing usage is not accepted as numeric-zero successful subscription evidence: the separate runtime correction restores exact previously reviewed runtime behavior and the unsafe autonomous transport interception is absent. No inference was run to create new telemetry claims. Actual local version/auth observations supplied by the builder say Codex0.158.0-alpha.2.1 is signed into ChatGPT while the reviewed executor supports0.155.0-alpha.2.6; this is a compatibility blocker, not evidence the user needs to sign in again. Tests substantiate that state distinction; this reviewer did not repeat real authentication commands.

## Installer behavioral acceptance

The exact PowerShell installer was executed in three disposable fixture repositories with a fake npm command. Success, nonzero package-manager exit and missing package entry point all produced the expected outcome. Captured arguments prove the fixed three vendor package versions and repository-local data/provider-cli prefix. No global install, PATH change or auth-file operation is in the script. Successful output is withheld if npm fails or expected entry points are absent. Evidence: logs/reconcile-provider-installer-independent.json and runner.py. These are actual PowerShell control-flow checks with a stub package manager, not real package downloads. Root separately confirmed registry availability and may perform the already authorized pinned installation; actual executable/auth/isolation verification remains a post-install gate.

The UI distinguishes missing/unsupported installation from login and preserves optional API-token controls separately. Syntax and source/fixture checks are accepted here; no interactive browser rendering is claimed. Final combined regression, startup, actual provider verification and independent integration QA remain parent-owned gates before merging/deployment.
