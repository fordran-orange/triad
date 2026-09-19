# Day 7 D/E — final independent QA

Verdict: **PASS** for the external integration registry, candidate governance and truthful broker shells on exact revision `56e4f96cd9ab43a319302edb694897d75143237a`.

Reviewer: independent delegated agent `/root/day6_qa_c`. Reviewed implementation was exported with `git archive`; imports were asserted to resolve inside the frozen archive rather than the changing repository. `DAY7_DE_FINAL_QA_HASHES.json` binds the exact registry/contracts/adapters/record-boundary source and independent tests. No implementation files were edited by QA.

## Fresh verification

- `logs/day7-de-qa-final.log`: **21 passed in35.68seconds**, with disposable PostgreSQL integration fixtures enabled. Command wrapper: `logs/day7_de_qa_typed_runner.py`, invoking `tests/test_external_integrations.py` and `tests/test_day7_de_qa.py` against the archived source.
- `logs/day7-de-qa-typed-unit.log`: preceding non-DB pass, **10 passed, 11 deselected in2.64seconds**.
- Ruff passes for the independent test file. Only existing FastAPI/Starlette dependency deprecation warnings appear.
- The DB run began after root released the shared test slot and finished before agent B's F run. No external account calls, authentication, live orders, production integration writes or implementation changes occurred.

## Findings resolved

**DAY7-DE-001:** adoption rejects unrelated product-owned or unbound QA. Positive adoption succeeds only with the reviewed Core build, exact candidate/definition fingerprint and matching linked IDs/commit. Independently varied wrong evidence, hash, candidate, build and commit links are rejected. Replay is denied. The shared current-adoption validator accepts the current reviewed definition, rejects an unreviewed changed definition, and rejects the original after deprecation.

**DAY7-DE-002:** a candidate cannot complete through an unrelated implemented capability. Requested capability coverage and provider/category matching are enforced; the original negative probe remains passing.

**DAY7-DE-003:** public transports now use a restricted typed contract. The prior URL userinfo/query, uppercase scheme, whitespace prefix, X-API-Key/header, private_key, signing_key and secret_key probes are rejected. Canonical connection writes validate the public metadata contract; malformed stored definitions and connection overlays are quarantined before shared catalog exposure. All original failing probes pass unchanged in their required outcome.

## Boundaries preserved

Product candidate/use records remain private across Triad/Aegis ownership. Active assignment identity is required; self-approval and reserved-kind writes are rejected through both canonical Records and legacy Ledger. Direct SQL mutation of immutable candidate records fails. Concurrent duplicate lifecycle transitions yield one accepted decision.

Schwab and Robinhood remain unconfigured shells. Read/auth/disconnect entry points fail closed even under synthetic overclaimed metadata; health makes no successful account/network claim. Place/cancel/replace always deny. The existing distinction between documented vendor interfaces and locally implemented capabilities remains intact; official-source research is retained in the original report.

## Preserved history and scope

`DAY7_DE_QA.md` and the INITIAL/CORRECTION/METADATA hash manifests retain all earlier CHANGES_REQUIRED verdicts and failures from090ed96,0b1a26e and18fbe6a. They are not overwritten or reclassified as passes. This fresh verdict supersedes them only for the exact source/test hashes in `DAY7_DE_FINAL_QA_HASHES.json`.

No remaining D/E finding requires a change. This acceptance covers the generic registry/contracts, sanitized metadata, candidate adoption and shell behavior; F data-acquisition execution, GHI HTTP/UI integration and other Day7 work retain their separate independent QA requirements.
