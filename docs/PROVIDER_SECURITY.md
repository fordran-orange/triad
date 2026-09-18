# Provider security and remaining isolation work

API keys are stored using Windows Credential Manager generic credentials scoped
to the current Windows account, under `Triad/AIProviders`. There is no plaintext
fallback, database credential field or frontend secret getter. Set/delete require
the existing operator token and origin checks. Validation errors omit input values.
API secrets are not supplied to context packets or the restricted tool gateway.

Loaded secrets and credential-like strings are redacted before persistence. CLI
authentication output is not copied to journals; only status categories are kept.
Login uses the vendor mechanism. No auth files, cookies or tokens are inspected.
Subprocess environments are allowlisted and exclude provider keys, operator tokens,
custom config locations, NODE_OPTIONS and PYTHONPATH.

The runtime still checks immutable assignments, authority, allowed paths, schema,
persisted policy, control epoch, token/compute/cost budgets, and review requirements.
Day 5 real cycles fail closed at the provider gate. No live trading is enabled.

**Critical remaining work:** the CLI harness must run behind a Triad-owned outer
filesystem/process/network boundary that also protects credentials from agent tools.
A vendor read-only flag, prompt, worktree or Windows Job Object is insufficient.
The current CLI execute method deliberately denies all WorkItems. There is no
operator switch to bypass it. Native capabilities are advertised but not granted.

Managed subprocess lifecycle tests cover exit, output cap, timeout, cancellation,
guard failure and setup failure. OS credential round-trip, frontend error redaction,
secret rejection in model context, fallback grants/budgets and gate tests are separate
from real provider acceptance. Passing these tests does not mean native isolation
or the frontier relay has been completed.
