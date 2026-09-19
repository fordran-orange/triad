# Day 8 engineering probe / role rollout — independent preexecution QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact revision: `8eb62ce20c3a8ef03ba649a81288176dd70abeb4`.
Decision: **CHANGES_REQUIRED**. The production probe was not executed.

## Required correction

**HIGH — approved role adoption cannot complete against the real schema.**
The positive disposable-DB path passes exact implementation QA, matching markers,
current VERIFIED/AVAILABLE capability and matching provider/model/transport, then
fails at `adopt_ui_role()`'s UPDATE of `core.agent_instances.definition`.
`core.protect_agent_definition()` correctly raises `Immutable agent grant`.
Use a reviewed, append-only version/adoption overlay (or equivalent preservation
of the immutable base), not a weakened or disabled trigger. Effective reads and
routing must apply only the validated narrow grant; existing tools, paths, tier,
budgets and historical base definition must remain unchanged.

## Probe review finding

**MEDIUM — selection rationale is not backed by a current registry read.**
`day8_engineering_probe.py` records that Claude has a verified text-proposal
substrate and Grok writing is degraded, but it never calls Capabilities.current()
or retains current capability version IDs. It reads the transport model/proof,
then proposes the new CLAIMED capability. Consult and retain the actual current
provider/model/transport capability evidence for this explicit evaluation plan.
This must remain a capability-evaluation exception, not a fabricated ordinary
route or a prematurely VERIFIED engineering capability.

The source otherwise keeps the probe exact-file, operator-initiated, zero-cost,
controlled by the normal epoch/grant/runtime checks, requires actual native
proposal-call evidence and fixed offline checks, and leaves work awaiting separate
QA without merging or adopting a capability. This review does not certify any
real provider result, since no inference was performed.

## Evidence

`logs/day8-role-independent-8eb62ce.log`: **2 failed in 10.61s**.
The first is the implementation failure described above. Before reaching that
failure, the same fixture demonstrates rejection of absent QA, absent rollout QA
marker, unverified capability, wrong-model capability, restricted capability,
product-scoped rollout/record ingestion and wrong implementation commit.
The second initial failure is a QA setup error: an attempted role mutation was
itself blocked by the immutable-definition trigger. That behavior is correct and
is not a second product defect. The original test is preserved at
`logs/day8-role-qa-initial.py`; the QA test was corrected to assert immutability.
The isolated rerun `logs/day8-role-immutability-proof.log` passed **1 test in
4.31s**, confirming that the protected base definition remains unchanged.

Execution used the complete frozen archive `logs/day8-role-8eb62ce`,
TRIAD_INTEGRATION=1, disposable PostgreSQL and scoped graph cleanup. No production
definition, capability, WorkItem or service was changed. No vendor or paid call
was made. Root was notified of the blocker before any production probe. Source
and evidence hashes are recorded in `DAY8_ROLE_PROBE_QA_HASHES.json`.
