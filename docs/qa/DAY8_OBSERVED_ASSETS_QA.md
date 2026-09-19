# Day 8 observed-asset finalization correction

**Verdict: PASS** for implementation revision `7c78acb093c1b2488c1df56336e9723edda3059f`. Independent reviewer: `/root/day6_qa_b`. Reviewed and executed from a frozen Git archive, separate from the concurrent full regression of the earlier revision. No implementation edits, PostgreSQL fixtures, production writes, vendor calls or restarts were performed.

## Preserved failure and correction

`logs/day8-first-build-failure.json` preserves the first feature build's NativeProposalEvidenceMismatch failure after two isolated tool writes. The failed work is not reclassified as successful by this QA. The correction removes the redundant model-generated second copy of executable asset contents only for Claude's Core exact-file engineering profile. The provider must return empty `files_changed`; Core reconstructs the final change list from its bounded broker snapshot. Any nonempty second payload is rejected, including an exact duplicate.

The product implementation prompt and explicit capability-probe prompt now agree with that output contract. The legacy text-proposal prompt and Grok behavior retain exact reported-versus-staged content matching. The flag is set by `ClaudeRun.execute(exact_files=...)`; the production transport obtains those exact files from the canonical `grant_for` check. It is not a model-supplied result flag.

## Independent evidence

Command was the isolated archive runner `logs/day8_observed_qa_runner.py`, using the repository virtual environment and `TRIAD_INTEGRATION=1`. Result: **63 passed in 20.85 seconds** in `logs/day8-observed-independent-7c78acb.log`.

Included suites: new `tests/test_day8_observed_assets_qa.py`, existing `tests/test_native_agents.py`, `tests/test_engineering.py`, and `tests/test_day8_engineering_correction_qa.py`.

New adversarial cases verify:

- Actual offline read and write become the exact returned asset when the final result has empty `files_changed`, with observed original SHA-256 and recorded tool evidence.
- Empty results without staged changes produce no invented files.
- Matching duplicate, conflicting content and forged protected-path final payloads are all rejected with NativeDuplicateAssetPayload.
- Ungranted sibling tool writes are denied before container invocation and produce no changes.
- Missing original-file read evidence remains a failure; completing read evidence preserves the host-derived original hash.
- The final authority callback still rejects a revoked epoch before returning any reconstructed result.
- Unobserved result claims/actions/tests/commands/permission requests remain rejected.
- Legacy exact payload matching and separate prompt instructions remain enforced.

The regression suites additionally cover actual offline broker operations, revoked tool authority, scoped paths, native catalog restrictions, usage evidence, Claude and Grok protocol fixtures, fixed approved checks and observed original-hash behavior. These are local/offline and fixture-provider tests, not real paid or subscription inference.

## Acceptance boundary

No actionable implementation defect was found. Broker writes remain proposals; this correction grants neither host file application nor Git merge authority. Existing original-read, result-validation, exact-grant, scope, epoch and subsequent Core Git/check/QA gates remain applicable. The new output contract still needs a repeat real Claude probe and independent review of its canonical evidence before adopting this implementation into the active Core path and resuming the product cycle. This report does not approve the failed feature candidate or replace the real product's independent provider QA.
