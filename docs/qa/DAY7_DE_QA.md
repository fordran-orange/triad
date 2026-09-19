# Day 7 D/E — independent QA

Verdict: **CHANGES_REQUIRED** on exact revision `090ed96b1793bc8cf1855bebe260f27345df1a5f`. Reviewer: independent delegated agent `/root/day6_qa_c`; builder `/root` was not its sole verifier. The reviewed source came from a Git archive of that revision, with imports asserted to resolve inside the archive rather than the changing checkout. `DAY7_DE_QA_INITIAL_HASHES.json` records the archive path, source hashes and independent test hash. No implementation files were edited.

## Required changes

### DAY7-DE-001 — HIGH: integration adoption borrows unrelated QA

`ExternalIntegrationRegistry.mark_implemented` accepts any passing implementation/QA pair at the supplied commit. It does not require Core ownership or evidence covering this exact integration candidate and definition revision. An unrelated Triad typography build with passing QA successfully marks a Core integration candidate IMPLEMENTED. The commit check proves the unrelated build was reviewed, not that this adapter/candidate was reviewed.

Require a Core-owned implementation, revision-bound independent QA, and evidence binding the approved candidate and exact registered integration definition/capability update. Preserve those links in the adoption record. The independent reproducer is `test_unrelated_qa_cannot_mark_integration_implemented`.

### DAY7-DE-002 — MEDIUM: an unrelated implemented capability completes the candidate

The adoption check accepts any IMPLEMENTED capability for the matching provider. A candidate requesting HISTORICAL_BARS succeeds when the definition has only ACCOUNT_READ implemented and explicitly marks HISTORICAL_BARS UNAVAILABLE. Require coverage of the approved requested capability set, or an explicit reviewed narrowing of that candidate before implementation can complete. Reproducer: `test_different_capability_cannot_complete_candidate`.

### DAY7-DE-003 — HIGH: shared metadata accepts and returns credential-shaped values

`IntegrationRecord` permits URL userinfo, credential query parameters and arbitrary nested transport dictionaries. A definition containing synthetic password material in an endpoint and `transports.api_key` is accepted and returned verbatim by the product-visible catalog. Generic known-secret rejection does not recognize a newly entered arbitrary credential. No real secret was used in this test.

Reject or sanitize credential-bearing URL components and credential-shaped metadata fields through the public metadata contract and catalog boundary, including stored malformed/legacy definitions. Retain extensible non-secret metadata without exposing account credentials. Reproducer: `test_shared_catalog_never_exposes_credential_shaped_metadata`.

## Independent verification and retained evidence

- `logs/day7-de-qa-initial.log`: **3 failed, 7 passed in 16.97 seconds**. The three failures above are preserved; the remaining builder and independent checks passed. Frozen runner: `logs/day7_de_qa_runner.py`; tests: `tests/test_external_integrations.py` plus `tests/test_day7_de_qa.py`.
- `logs/day7-de-qa-shell.log`: separate shell-only run, **4 passed, 6 deselected in 2.30 seconds**.
- Product-owned candidates remain hidden from Aegis; mismatched actors/owners, self-approval and reserved-kind writes through both Records and legacy Ledger are rejected. Direct SQL mutation of the canonical candidate is rejected by the immutable-record trigger.
- Concurrent identical lifecycle decisions produce exactly one accepted transition and one decision record. Candidate proposals/approval do not install an adapter. Order-use requests are explicitly denied and retain product ownership.
- All implemented shell read/auth/disconnect entry points fail closed, including after synthetic metadata is deliberately changed to claim IMPLEMENTED/configured/enabled. Health remains explicitly unconfigured and disconnected. Place/cancel/replace always raise PermissionError. The independent shell test disallows network connection attempts; no external account/authentication calls were made.
- DB tests used disposable PostgreSQL fixtures and were sequenced after agents B and A to avoid overlapping their focused runs. No production registry or provider setting was mutated. Ruff passes for the new independent test file.

## Truthful interface research

Read-only public official documentation independently supports the metadata distinctions. Robinhood documents an official Trading MCP endpoint and account-specific access boundaries in its [Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/); its [agent trading documentation](https://robinhood.com/us/en/support/articles/trading-with-your-agent/) lists equities, options and crypto tools. The separate [Crypto Trading API](https://robinhood.com/us/en/support/articles/crypto-api/) remains a distinct interface. These vendor capabilities are not proof of local implementation or authentication. The shells correctly make no such local claim and do not invent a verified SDK.

Schwab's [official Trader API discussion](https://www.schwab.com/learn/story/ways-ai-trading-tools-help-increase-efficiency) describes market data, account information and trading integration. The shell appropriately leaves endpoints, entitlements, authentication and every local capability unverified. No advertised vendor order capability overrides Core's unconditional live-order denial.

## Acceptance

The shell scope is appropriately limited, but the candidate-to-implementation evidence boundary and metadata confidentiality are not ready for acceptance. Grouped corrections require a new independent QA run on their exact revision, preserving this failed evidence. No passing D/E verdict is issued here.
