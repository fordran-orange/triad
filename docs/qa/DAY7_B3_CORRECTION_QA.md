# Day 7 B3 HTTP evidence correction — independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact implementation: `711477196e2f24892b728c6d9e4f05e9bf32f3b4`.
Decision: **CHANGES_REQUIRED**.

The original failure-provenance defect on `862e59a` is fixed: the direct HTTP
provider and HTTPTransport wrapper retain actual model, input/output counters,
and valid reasoning measurements when output exhaustion blocks a run. The
wrapper propagates evidence in its `finally` block. Independent Runtime tests
confirm known counters are preserved, boolean or absent failure counters remain
unknown, incomplete output produces no AgentRunResult, and there is no retry.
The original `DAY7_B3_QA.md` and its hash manifest remain unchanged.

Two completed-response measurement issues remain within the requested invalid
measurement/no-false-completion checks:

1. **MEDIUM — sanitized reasoning is overwritten.** `measured_response` correctly
   converts invalid reasoning values to null, but the successful OpenAI and xAI
   branches assign the unvalidated response value back to `reasoning_tokens`.
   Independent OpenAI response tests return a valid structured result while
   preserving `-1`, `True`, and `"111"` as reasoning measurements. Runtime only
   checks nonnegative exact integers for allocation enforcement, then writes the
   raw adapter field into Usage, so the invalid measurement can survive into
   canonical evidence. Preserve the validated value rather than overwriting it.
2. **MEDIUM — boolean token counters are accepted as measurements.** The completed
   HTTP input/output checks use `isinstance(value, int)`; Python includes booleans
   in that test. Valid structured responses with `input_tokens=True` or
   `output_tokens=True` are accepted. Runtime's successful-use validation has the
   same predicate, unlike its corrected failed-use recovery. Require exact integer
   counters consistently, reject invalid completed usage, and keep invalid
   evidence unknown. The boolean weakness predates this correction but directly
   affects the measurement-validation boundary reviewed here.

All provider responses were offline fixtures; there were no network/provider
requests, production changes, service restarts, or implementation edits. Tests
used a full committed archive at `logs/day7-b3-7114771`, including committed
configuration, migrations and fixtures. Only the independent correction test
file was copied into it. Agent A's DB probes had finished before these DB tests.

Evidence:

- `logs/day7-b3-independent-7114771.log`: **15 passed, 3 failed in 28.98s**. The
  three failures were an initial QA fixture error: the fake completed OpenAI
  response omitted the `output_text` type and failed body validation. Two boolean
  cases in that run consequently passed for the wrong error; they are not used as
  acceptance evidence. The original fixture is retained at
  `logs/day7-b3-correction-qa-initial.py`.
- After correcting the response shape and requiring a usage-specific error,
  `logs/day7-b3-invalid-measurement-proof.log` records **5 failed in 2.35s**:
  three raw reasoning values and two boolean token counters. These are the
  implementation failures supporting this verdict.
- Passing independent tests include the original direct blocked-usage regression,
  three wrapper Runtime cases (valid, boolean, absent input evidence), migration
  authority/idempotence, input admission, distinct reasoning/output allocations,
  cancellation, Ollama sizing, no duplicate HTTP invocation, and no successful
  result record for incomplete responses.

Exact source/test/evidence hashes are bound in
`docs/qa/DAY7_B3_CORRECTION_QA_HASHES.json`. Fresh independent QA is required after
correction. This review does not accept later cycle/integration work.
