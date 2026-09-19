# Operator dashboard

Current entry points: [Core](http://127.0.0.1:8000/core), [Triad](http://127.0.0.1:8000/triad), and [P2P](http://127.0.0.1:8000/p2p). The root URL opens Core. Core owns provider setup, global controls, work records, usage and diagnostics. Triad owns rotation, backlog, proposals, product reviews, journals, change lineage and jobs. P2P is a sparse human-directed shell. The retained WorkItem explorer is at `/day2`; generic research is at `/research`. See [current operations](CORE_EXTRACTION_OPERATIONS.md).

Agent summaries show observed provider status and models. Cycle controls distinguish REAL and SIMULATED and require both Core provider readiness and Triad's relay acceptance for real execution.

Git changes expose proposal, exact commit metadata, independent review and rollback preparation. Record inspectors show labeled sections, readable lists and local dates; identifiers and technical details remain available in expandable sections. The shared presentation covers the workspace, research, provider settings and older work-item explorer. WorkItem inspectors link lifecycle and graph relationships. Cycle summaries and timeline events come from persisted records, not sample UI activity. Provider health is persisted by probes; service health is queried live. Empty states remain explicit.

Operator access accepts the ignored bearer token into page memory. Authenticated controls pause/resume, stop work, disable/enable agents, deny/approve within-policy proposals, require human review, lower limits, run cycles and activate the kill switch. Reviewed merge and rollback require explicit operator actions; no UI control raises authority or enables trading. Local Qwen support remains pending independent review in the work explorer.

Dynamic content uses textContent; there are no external scripts, assets or analytics. Reads refresh every ten seconds. API tests cover authentication, forged origins/hosts and governance restrictions. DAY3_VERIFICATION.md records the actual browser and persistence checks.

Day 4 adds Jobs & recovery and Provider readiness. Cycle buttons now queue persistent work; queued cancellation requires operator authorization. Job detail shows the returned cycle and failure codes. Provider readiness exposes missing configuration/budget prerequisites and retained real-call evidence without credential values. Review metrics distinguish simulation and do not claim correctness.


## Day 4 research

Open `/research` for Dataset Catalog, Experiments, Results & comparison, Trade ledger, Data quality, and Provenance. The screens read canonical records and checksum-verified artifacts. LONG and SHORT retain separate capital curves. Null metrics display N/A. Mutations require the local operator token. The initial source is FIXTURE and reviews distinguish host verification from model activity.
