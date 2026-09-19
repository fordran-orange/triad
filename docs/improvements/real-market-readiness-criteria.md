# Real-Market Research Readiness Criteria (Proposed)

Status: proposed criteria only. No provider access, data acquisition, experiment or trading authority is claimed.

Current state: INSPECTION_BASELINE.md reports the market provider unavailable, so all real-data evidence below is **unverified**. Existing ingestion, quality and provenance infrastructure is reported; strategy evidence is fixture-backed with no validated out-of-sample performance.

## 1. Provider provenance
- Evidence: named provider, dataset version, retrieval record, terms of use.
- Rule: approve only if every item is documented; otherwise reject.

## 2. Session coverage
- Evidence: expected versus observed sessions and instruments, with gaps listed.
- Rule: approve if gaps are enumerated and within an agreed limit; otherwise request changes.

## 3. Data quality
- Evidence: quality-check report covering duplicates, missing values and outliers.
- Rule: approve if there are no unresolved critical findings; otherwise reject.

## 4. Reproducibility
- Evidence: dataset hash, configuration and code revision that reproduce identical outputs.
- Rule: approve only if an independent rerun matches; otherwise reject.

## Scope boundary
Passing all four criteria shows data readiness only. Strategy performance needs separate out-of-sample validation.
