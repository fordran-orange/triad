# Day 7 B3 — final independent correction QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact implementation revision: `6217f60462193f6bc65fd65af44218ce2bef562d`.
Decision: **PASS** for the bounded B3 defaults, migration, HTTP/resource and
routing scope. No B3 implementation finding remains open.

The original CHANGES_REQUIRED reports for `862e59a` and `7114771`, their hash
manifests, and the failed test logs remain unchanged. This is a fresh correction
review, not a replacement of that history.

## Corrections verified

- HTTP output exhaustion retains available actual model, input/output counters
  and valid reasoning counts before validating termination status. Direct
  HttpProvider and HTTPTransport-to-Runtime paths retain this evidence when blocked.
- Failed responses with absent or boolean counters remain unknown, while their
  reported model identity is preserved. No incomplete response becomes an
  AgentRunResult, and no automatic retry is issued.
- Successful response parsing retains the sanitized reasoning value. Negative,
  boolean and string reasoning measurements remain null.
- Both successful HTTP and Runtime usage validation require exact integer token
  counters. Boolean input/output counters cannot be accepted as valid measurements.
- Independent offline parity checks verify blocked-response evidence for OpenAI,
  Claude, Grok and Ollama. All four retain the expected measured counters and
  actual model while making exactly one generation invocation; Ollama's explicit
  `think=False` is recorded as zero reasoning.

## Repeated resource and migration boundaries

The new initial defaults remain 8192 reasoning, 24000 input characters, 6144
output tokens, 480 seconds and 60 tool operations. Reasoning and output remain
independent. Tests repeat immutable versioned migration 013, preservation of
legacy static definitions/historical evidence, one-time legacy default overlay,
custom operator limits and cost controls, idempotence, and matching packaged SQL.

Runtime tests repeat governed larger-context admission before provider invocation,
review-required context rejection with zero provider calls, distinct reasoning
extension, prompt cancellation with late-response rejection, Ollama context
capacity admission, and immutable WorkItem scope. Routing tests repeat capability,
privacy, identity, authority and live-policy boundaries, including admission above
the initial context allocation and rejection above the physical ceiling.

## Evidence and limits

- `logs/day7-b3-independent-6217f60.log`: **31 passed in 91.55s**, with
  `TRIAD_INTEGRATION=1`. Files: `test_day7_b3_qa.py`,
  `test_day7_b3_correction_qa.py`, `test_resource_defaults.py`,
  `test_resource_http.py`, and `test_intelligence_routing.py`.
- `logs/day7-b3-provider-parity-6217f60.log`: **4 passed in 1.86s** from the new
  independent `test_day7_b3_provider_evidence_qa.py`.
- Tests used a full committed `git archive` at `logs/day7-b3-6217f60`, with source,
  configuration, SQL and fixtures frozen to the reviewed revision. Only the new
  QA-only provider-parity test was copied into it. Later uncommitted cycle or
  integration changes are excluded. DB runs were coordinated with other reviewers.
- Provider responses were offline fixtures. Database writes were limited to
  disposable fixtures, with their scoped graph cleanup. This reviewer did not edit
  implementation, upgrade production, restart services, or make paid provider calls.

This PASS satisfies independent QA for B3 and migration 013's tested behavior.
It does not claim that production migration/deployment has occurred, validate an
unverified rollback to old validators, or accept separately reviewed Cycle/D/E
work. Vendor-specific native reasoning-control limitations remain as documented
in the build report; unknown measurements are not invented.

Exact source, test and log hashes are in `docs/qa/DAY7_B3_FINAL_QA_HASHES.json`.
