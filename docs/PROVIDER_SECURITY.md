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

The credential-free [offline tool sandbox](ISOLATED_EXECUTION.md) now provides
real container isolation for explicitly supplied snapshots and approved tool
commands. It has no host mounts or network access. Codex read-only reviews now
use a version-pinned remote exec-server and host-mediated protocol. Its login and
reasoning app server remain trusted host infrastructure; credentials are not
transferred to the executor. Claude and Grok now use a bounded file broker for offline reads and staged text
proposals. No native host shell, Git or network tools are exposed. See that document
for the exact trust model.

**Trust boundary:** vendor login/inference harnesses run on the trusted host; model
file tools execute through a Triad-owned Docker boundary without credentials.
A vendor read-only flag, prompt, worktree or Windows Job Object is insufficient.
Unsupported CLI work is denied. Only the documented snapshot/read/proposal routes
are implemented; live acceptance is still required.
There is no operator switch to bypass the remaining isolation requirements.

Managed subprocess lifecycle tests cover exit, output cap, timeout, cancellation,
guard failure and setup failure. OS credential round-trip, frontend error redaction,
secret rejection in model context, fallback grants/budgets and gate tests are separate
from real provider acceptance. Passing these tests does not establish provider inference, acceptance or the
frontier relay.
