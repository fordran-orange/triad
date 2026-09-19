# Day 7 B3 — independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact implementation revision: `862e59aca92bb6de313861d581fa2df21b007a84`.

## Revision 1 — CHANGES_REQUIRED

### Required correction: preserve measured HTTP failure usage

When an HTTP provider reports output exhaustion, `HttpProvider.execute` calls
`output_threshold` before extracting usage and actual-model metadata. The
exception then reaches Runtime, whose failed-call measured-usage recovery only
handles CLI evidence. An incomplete HTTP response that explicitly reports its
actual model and usage is therefore recorded as unknown.

The independent offline reproduction supplies an OpenAI response with model
`observed-fixture-model`, 42 input tokens, 6144 output tokens, and 111 reasoning
tokens. The canonical Usage record instead has `usage_known=false`, zero input
and output tokens, and null reasoning/model metadata. The provider was simulated;
no network request or billable operation occurred.

Severity: MEDIUM. This loses actual failed-attempt provenance needed to assess
resource thresholds and consumption. Conservative cost reservation still applies;
this is not a demonstrated cost-authority bypass. Resource blocking, the durable
extension request, and the absence of automatic retry work correctly. Capture
validated available HTTP usage/model metadata before inspecting termination
status, and retain that evidence on failed/blocked Runtime paths. Keep missing
or invalid counters unknown, and do not accept incomplete output as a successful
result. Apply equivalent handling to supported HTTP provider response shapes.

### Independently tested behavior

- New initial WorkItem/request defaults, distinct reasoning/output allocations,
  and zero daily API spending authority.
- Versioned 013 migration preserves the original static definition and historical
  records, applies the legacy default overlay, preserves custom operator limits
  and cost controls, is idempotent, and rejects policy UPDATE/DELETE.
- The packaged and source 013 migration copies match.
- Requested routing regressions, including context above the initial allocation,
  preserved product-private routes, live provider-policy rechecks, denied
  unauthorized capability/role/path selections, and the physical context ceiling.
- Runtime permits a governed 26,000-character context extension before invoking
  the fake provider; a 55,000-character context requires review and makes zero
  provider calls. Original WorkItem scope remains unchanged.
- Measured reasoning can extend independently of output allocation after new
  host-observed progress.
- HTTP output exhaustion persists a review request and makes no second provider
  invocation; cancellation returns promptly and rejects a late response.
- Ollama refuses insufficient model context capacity before generation and sizes
  a supported context above 4096 without silent truncation.

### Evidence and scope

Tests ran with `TRIAD_INTEGRATION=1` from a full `git archive` of `862e59a`, including
source, configuration, SQL and fixtures at `logs/day7-b3-862e59a`. Only the
independent QA tests were copied into this snapshot. The live checkout's later
cycle work is excluded. Provider behavior is faked; PostgreSQL writes are confined
to disposable databases and graph cleanup to their fixture IDs. No production
upgrade, records/configuration change, service restart, or implementation edit was
performed by this reviewer. Agent A's B2 DB run finished before these tests began.

- `logs/day7-b3-independent-862e59a.log`: **21 passed, 1 failed in 77.92s**. The
  failure was a QA fixture mistake: the Ollama test supplied an unsupported
  PROPOSE role. No implementation assertion failed in this initial batch.
- The QA fixture was corrected to SUPPORT with the supported compact response.
  `logs/day7-b3-http-evidence-probe.log`: **1 passed, 1 failed in 5.74s**; corrected
  Ollama sizing passes and the new measured HTTP failure-evidence probe fails.
- `logs/day7-b3-http-evidence-values.log`: **1 failed in 6.69s**, with explicit
  persisted zero/unknown usage values attached to the failing assertion.
- Original initial QA test text is retained at `logs/day7-b3-qa-initial.py`.
  Current QA-only test file `tests/test_day7_b3_qa.py` passes Ruff.

Builder historical test results and transient fixture timeout remain separate
evidence; these independent results do not replace them or claim a fresh broad
suite pass. Exact source and evidence hashes are preserved in
`docs/qa/DAY7_B3_QA_HASHES.json`. A corrected implementation requires fresh
independent QA before acceptance.
