# Day 8 Core readiness — second independent correction QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Revision `108acfe56e297dfbc40153223606a2b33b26c036`.
Decision: **CHANGES_REQUIRED**. Prior failures remain preserved.

The 34-case readiness suite now passes (two dependency warnings, 5.50s), including
all previously reported empty aggregate/session evidence and metadata cases.
However, a targeted nested-evidence probe found that a supposedly resolved
outlier with `{"resolved": true, "evidence": "   "}` still produces full READY.
`outlier_findings` remains an untyped tuple of dictionaries, and the completion
validator accepts truthy whitespace instead of actual resolution evidence.
This is the remaining instance of the same incomplete-evidence defect. Require
nonblank, structurally valid evidence for each resolved finding; the top-level
outlier reference does not replace the required evidence of its disposition.

Added `blank_resolved_outlier_evidence` to the independent regression. Focused
result: **1 failed, 29 deselected**, two warnings, 2.06s. Command:
`.venv\Scripts\python.exe -m pytest logs/day8-readiness-108acfe/tests/test_day8_readiness_qa.py -q -k blank_resolved_outlier`

Frozen git archive excludes later engineering/lifecycle changes. Retained logs:
`logs/day8-readiness-independent-108acfe.log` (34 passed), and
`logs/day8-readiness-outlier-108acfe.log` (one failed), each with exit file.
Hash evidence: `DAY8_READINESS_CORRECTION2_QA_HASHES.json`.
No implementation, production, provider, database or browser action was taken.
