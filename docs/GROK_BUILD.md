# Grok Build

Installed from official npm package `@xai-official/grok@1.0.34` in the Triad-local
prefix `C:\Triad\data\temp\provider-cli`. The vendor package can also manage its
own user-local executable under `.grok`; Triad does not inspect its credentials.
The version check returned `grok 1.0.34 (3736acbc8658)`.

Login explicitly uses `grok login --oauth`; logout uses the vendor command.
Authentication uses the supported ACP `initialize` and `authenticate` methods,
selecting `cached_token` only. Triad requires `auth_mode=Oidc`, a subscription tier,
and `backend_billed=false`; only these metadata checks are retained. No vendor
credential file is opened or copied. Subscription sign-in is now verified.

The isolated adapter pins `1.0.34 (3736acbc8658)`. Each run uses a dedicated empty
temporary working directory and leader socket. A vendor configuration inventory
rejects unrelated hooks, plugins, MCP and LSP integrations. Session profiles remove
skills, project instructions, extra tools and MCP dispatch. Triad verifies the
actual catalog is exactly `read_file` (reviews), plus `search_replace` for proposals.
CLI `--tools` alone did not restrict the ACP session in a no-inference probe; the
session profile and catalog gate are mandatory.

Both ACP filesystem capabilities are advertised so the vendor routes file tools
through Triad. Every callback checks session identity, exact supplied paths or
approved proposal directories, current authority, and tool-call limits. Actual
file operations run in the offline Docker sandbox. Terminal and unrelated ACP
requests are denied. Temporary workspace memory is not supplied as task context;
no repository or authentication files are mounted into the executor.

Structured results are validated against the normal Triad contract. Usage comes
from aggregate ACP `usage.modelUsage`, including all prompt rounds, rather than
the sibling last-call counters. Incomplete usage or missing tool evidence fails
the run. File changes must match staged sandbox proposals and require review.

Real read-only README acceptance passed on 2026-09-18 using `grok-4.6`, after
fixing bounded stream backpressure and Windows cleanup timing. Earlier failed
proofs remain in the ledger. See DAY5A_VERIFICATION.md. The full reviewed relay
and fresh standalone connection checks remain pending. No paid API fallback is enabled.

Official references: [CLI](https://docs.x.ai/build/cli/reference),
[enterprise authentication](https://docs.x.ai/build/enterprise),
and [installation](https://docs.x.ai/build/overview).
