# B3 HTTP usage correction

The independent B3 failure-provenance regression is fixed: HttpProvider captures reported actual model and token measurements immediately after receiving a body, before incomplete/malformed validation. HTTPTransport forwards that evidence even when execute raises. Runtime preserves valid measured usage for failed HTTP and native calls. Unknown or invalid values remain unknown; incomplete output remains blocked and never retried automatically.

Root independent probes: 2 passed in 9.36 seconds, logs/day7-b3-correction-root.log. Fresh independent QA required. Original CHANGES_REQUIRED evidence retained.
