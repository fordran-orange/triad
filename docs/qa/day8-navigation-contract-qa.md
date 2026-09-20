# Day 8 exact navigation contract — independent correction QA

**PASS**, bounded correction at `81d0fe3028c10bc31471548c8ba39b7ee3641fe4`. Reviewer `/root/day6_qa_a`, independent of the builder. Only app/products/triad/daily_development.py changed in this revision.

The previous actual candidate `ae69046341975070a2ad3e895cb4482349f64a19` remains failed. Its retained EngineeringTestRun `df8713d0-4d92-4729-82fa-656e1e6a3925` reports exit1, AssertionError:/triad/product. Independently loaded both exact candidate assets from Git and matched their SHA-256 hashes to the recorded offline snapshot. Running the unchanged host-authored CHECK_SCRIPT over a disposable copy reproduces that precise failure. Replacing only href="/triad" with href="/triad/product" in the **test-only copy** makes the unchanged contract script pass. This is a causal regression check, not an autonomous product fix or acceptance of the candidate.

Fresh frozen execution: `logs/day8-navigation-qa-runner.py`, source extracted from exact81d0fe3 Git archive. **17 passed in9.33seconds**, exit0: two new independent seam cases plus the existing observed-assets regression suite. No vendor or database calls were used. The actual build method was executed with host dependencies stubbed to capture its AgentRunRequest and failure behavior. It supplies exact Product/Development/Cycles/Daily Debrief destinations and explicitly requires those destinations, while retaining prior correction context, exact two-file grants, CLAUDE implementation, propose_file_change-only tooling, original epoch and zero cost. A failed offline proof still raises, calls failed_build, and retains the final240 characters of trusted checker stderr.

The fixed CHECK_SCRIPT is byte-identical before/after correction and its SHA-256 remains `20e243e41df23d91dfe9a940e883d11f4e95db835f9a0296a9a836fa8dc5471d`. No acceptance check, path boundary, resource limit, QA gate or merge condition was relaxed. Source diff review confirms only explicit route context/objective and bounded diagnostic text changed.

Evidence: `logs/day8-navigation-independent.log`, `.exit`, `logs/day8-navigation-check-observations.json`, independent tests and frozen archive, with hashes in accompanying JSON. Original candidate files/worktree and failure record were not modified. All reviewer output remains under ignored logs; Git remains clean.

This PASS permits exact host correction governance and a fresh native attempt. It does not approve a feature merge, claim browser behavior, relabel either failed cycle or declare Day8 complete.
