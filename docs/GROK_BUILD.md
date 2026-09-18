# Grok Build

Installed from official npm package `@xai-official/grok@1.0.34` in the Triad-local
prefix `C:\Triad\data\temp\provider-cli`. The vendor package can also manage its
own user-local executable under `.grok`; Triad does not inspect its credentials.
The version check returned `grok 1.0.34 (3736acbc8658)`.

Login explicitly uses `grok login --oauth`; logout uses the vendor command.
The supported CLI reference has no verified auth-status command in this adapter.
Consequently authentication/billing remain unverified even if login returns success.
This needs a supported metadata/inference validation path, not inspection of tokens.

Grok config can override environment authentication/billing. Removing XAI_API_KEY
alone is insufficient proof of subscription billing. Native execution is denied
until configuration isolation, billing provenance, structured output parsing and
the hard outer execution boundary are implemented and tested. The supplied-status
acceptance WorkItem and full relay have not run.

Official references: [CLI](https://docs.x.ai/build/cli/reference),
[enterprise authentication](https://docs.x.ai/build/enterprise),
and [installation](https://docs.x.ai/build/overview).
