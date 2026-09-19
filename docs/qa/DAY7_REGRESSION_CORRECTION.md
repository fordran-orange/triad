# Full regression compatibility correction

The first complete Day 7 regression exposed four older expectations. Root build
removes the remaining hardcoded 2,048 ceiling from the legacy reasoning-request
decision. Requests within the immutable WorkItem allocation remain allowed;
increases still require human approval and never modify the WorkItem. Runtime
request-budget and identity guards are unchanged.

Three fixtures are aligned with independently reviewed Day 7 behavior: explicitly
enable the local daily cap when testing cap exhaustion; expect the new 480-second
unbound transport default while preserving Qwen's compact schema/256 output; and
expect a structured resource denial when a one-second specialist reaches its
ceiling. The latter additionally asserts initial TIME=1, zero extension granted,
no successful Usage and a bounded observed duration.

The initial full-run failure evidence remains in logs/day7-full-regression.log.
Fresh independent affected QA and the final full regression are required.
