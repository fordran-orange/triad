# Day 7 A2 correction 1

Corrects both findings in DAY7_A2_QA.md against f6a6f9c. Context now tests owner membership in the canonical lineage without trying to canonicalize shared/unknown incoming records; those records are skipped just as before the rename. Legacy P2P context remains visible to Aegis and foreign Triad context stays excluded. Aegis HTML is strict UTF-8, including new status separators; all changed text files were checked for valid UTF-8.

Validation: independent QA-authored regressions plus alias/migration/architecture/ownership tests: **24 passed, 2 existing deprecation warnings, 20.01s**, exit0 (logs/day7-a2-correction2-tests.log/.exit). Ruff on corrected Python/regressions passed. The prior extra affected-consumer regression completed **49 passed** in175.46s. New independent correction QA is required; old CHANGES_REQUIRED remains preserved. Production restart and live acceptance are still pending.
