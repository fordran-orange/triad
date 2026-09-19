# Day 7 regression corrections — final independent QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `eea65d393efc644f4b443914b26ce9023e4bec2e`.
Decision: **PASS** for the bounded regression compatibility corrections.

Independent execution from the frozen revision completed **7 passed in 34.83s**:
`logs/day7-regression-final-eea65d3.log`. Two dependency deprecation warnings did
not affect results. No additional implementation change was needed after the
legacy reasoning-request correction; the final revision changes two fixtures.

The repeated tests cover all five failures from the initial full regression:

- Raised runtime output allocation and wrong executor identity remain rejected.
  Legacy reasoning requests above the immutable grant require human approval.
- A deliberately enabled LOCAL daily cap stops the simulated cycle without a
  reset. The fixture also verifies that the default LOCAL cap is disabled.
- Qwen SUPPORT performs context-capacity introspection and then retains its compact
  summary/assumptions schema, 256 generation limit, disabled thinking, read-only
  request, local provenance and rejection of the old full response schema.
- A specialist's one-second time allocation yields structured resource blocking,
  zero extension and no successful Usage, within the bounded observed duration.
- Two concurrent paid-fallback requests admit exactly one reservation. The fixture
  uses $0.09 against a $0.06244 per-run estimate at its declared $10/M rates and
  6144 output reservation; it explicitly asserts that one request fits and two
  do not. Disabled-agent and global-kill overrides continue to reject routing.

The two additional independent tests cover immutable legacy grants of 512 and
8192: negative, zero, exact grant, grant+1, 2049 and 1,000,000 requests. Above-grant
requests never become grants; the full WorkItem remains unchanged. Wrong-agent
requests fail without creating a request record. No ResourceExtensionDecision or
Usage is created by these legacy request decisions.

The original full-run log (5 failed, 524 passed in 1208.59s) and the intermediate
335a8f4 independent run (5 passed, 1 failed due to the incomplete Qwen transport
mock) remain preserved. Their earlier CHANGES_REQUIRED report is unchanged.
The corrected mock now supplies the offline `/api/show` capacity response and
accepts the omitted optional timeout; generation and malformed-response checks
remain intact. This validates the mock against the new preflight rather than
bypassing the real context check.

Execution used the complete archive `logs/day7-regression-eea65d3`,
TRIAD_INTEGRATION=1, disposable PostgreSQL and scoped graph cleanup. The previous
full suite had finished before these runs. Root was notified immediately when
the DB slot became free for the final full regression. This PASS does not claim
that the later full regression has completed. Concurrent working-tree reports
and product documentation were excluded. No implementation edit, production
mutation/restart, provider call or paid API call was performed by this reviewer.
Exact source and evidence hashes are in `DAY7_REGRESSION_FINAL_QA_HASHES.json`.
