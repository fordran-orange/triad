# Day7 B1 correction — explicit host-only construction

Independent QA reproduced a product-scoped constructor bypass of canonical resource evidence protections. ResourceSession now rejects any scoped ledger before creating an unscoped Records service or recording anything. Runtime wiring must construct it only inside the trusted host execution path after validating the canonical assignment and persisted policy. No public model-facing observation/grant endpoint exists. Original CHANGES_REQUIRED report and failing regression evidence are retained.

Root validation uses both the original11tests and independent4adversarial regressions. Fresh independent correction QA is required. The concurrent timestamp segment remains separate and is not part of this correction.
