# Day 7 B1 — resource policy foundation

Builder /root. This bounded segment adds the host-owned resource decision service and durable append-only evidence. It is not yet wired to runtime/native executors; Phase2 is not complete.

Initial allocations: reasoning8192, input24000chars, output6144tokens, time480seconds,60tools. Five resource types, explicit threshold/request/extended/blocked records with actual UTC times. A grant requires fresh host-observed evidence, unchanged assignment identity/scope/permissions, active governance and existing cost reservation. The evidence callback is host-only; model claims are not ingested. Duplicate progress cannot be reused. At most8 automatic extensions per run, each at most its initial allocation. Larger/repeated-over-envelope requests and unapproved additional API cost require human review and block cleanly. Denial is terminal for this run; the historical failure is preserved. No automatic human approval or external-cost authority is introduced.

Progress, grants and state records use canonical host-only kinds. A per-run PostgreSQL advisory transaction lock prevents double grants. Existing daily/billing policy still applies. Repeated run IDs cannot reset allocations. Content fingerprints are stored rather than source text.

Root initial tests:10passed/1failed36.30s. Failure was a test ordering by random ID for states within one transaction; all states had explicit observed_at, now the test orders by that actual timestamp. Original test output preserved logs/day7-b1-root-tests.log. Corrected fresh evidence logs/day7-b1-root-tests-corrected.log/.exit. Runtime/default/native-executor wiring and lifecycle integration are next bounded segments, not claimed here.
