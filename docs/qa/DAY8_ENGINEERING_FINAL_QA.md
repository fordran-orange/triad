# Day 8 engineering foundation — final independent correction QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `b43054bb704c36ea53b380b5b65041258aa94333`.
Decision: **PASS** for the bounded Core engineering foundation correction.

Both previously reported issues are resolved. The broker derives original hashes
from its captured input, and NativeRun.finish supplies those observed FileChanges
after checking model-reported path/content equality. An existing asset can now be
staged in Docker and applied by the host with the correct original hash. A missing
or forged model-supplied hash cannot replace the observed hash. Unstaged contents
still fail closed. EngineeringGit.verify now repeats the aggregate byte-ceiling
check before its result can support QA or merge.

## Independent execution

- `logs/day8-engineering-correction-b43054b.log`: **51 passed, 2 failed in 32.04s**.
  All 16 previous engineering cases and the adjacent native-agent regression
  tests passed. Both failures were in the new QA-only unit fixture: it used
  nonexistent AgentRunResult status `IMPLEMENTED`, so model validation rejected
  it before exercising the target code. The initial test is preserved at
  `logs/day8-engineering-correction-qa-initial.py`.
- Correcting only that fixture status to `CODE_CHANGE`,
  `logs/day8-engineering-correction-native-proof.log`: **2 passed in 0.49s**.
  These tests cover missing/forged original hashes and unstaged content rejection.
- Both independent QA test files pass Ruff. There is no remaining implementation
  failure in this bounded run; the original CHANGES_REQUIRED report is unchanged.

Passing scope includes exact/protected path handling, unchanged legacy text
restrictions, native catalog/tool restrictions, missing/forged request grants,
product-scoped canonical-write denial, disable/stale epoch enforcement,
hardlink/stale-source/baseline-move rejection, actual Docker staging, fixed check
identity/snapshot binding, read-only check execution and guarded cancellation.
The native regression also repeats Claude/Grok protocol and measured-evidence
checks without vendor inference.

The full source came from `logs/day8-engineering-b43054b`, a complete git archive.
Tests used TRIAD_INTEGRATION=1, disposable PostgreSQL with scoped graph cleanup,
temporary Git repositories and offline Docker. Reviewer C released the DB slot
before this run; root was notified immediately afterward. Concurrent workflow
integration changes were excluded from execution.

No implementation edit, production mutation, provider inference, registry
adoption or real executable-capability verification was performed by this
reviewer. This foundation PASS does not yet approve the product workflow or claim
that Claude's new engineering capability is VERIFIED. The real isolated probe,
independent review of its evidence and governed capability adoption remain later
gates. Host workflow callers must still bind canonical grants, current guards,
exact candidate/QA evidence and protected merges as designed. Exact source and
evidence hashes accompany this report in `DAY8_ENGINEERING_FINAL_QA_HASHES.json`.
