# C: canonical cycle history and UI

Adds Core CycleRecord contract and trusted append-only snapshots, Triad-owned evidence collection, preserved legacy blocked cycles, explicit recovery/supersession links, and /triad/cycles with readable details/local timestamps. Cross-product records are excluded at the SQL boundary. HTTP GET is read-only. Historical rollup is an explicit host backfill after QA; original Cycle/ProductCycle/failure evidence is never rewritten. Missing historical timestamps or control epochs remain null. A historical cycle without a parent receives a newly dated evidence-anchor WorkItem, explicitly identified as historical ingestion, with no tools or execution authority.

New provider-gate rejections retain a blocked canonical record and zero-authority parent WorkItem; product-build completion/failure captures a snapshot. Larger rotations are captured after completion. Snapshots use source-content hashes for idempotency; separate relationship records leave failure status untouched. UI includes actual build/QA/merge, failures, usage, debt, duration and mode.

Root: 3 integration tests passed in 9.03 seconds. Independent QA required before deployment/backfill.
