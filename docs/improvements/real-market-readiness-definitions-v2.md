# Real-market readiness definitions v2

Status: proposed, documentation only; NOT EXECUTABLE. These definitions close the ambiguity noted by Day6 QA. They do not authorize data acquisition, enable a gate, establish real-market readiness or validate a trading strategy.

## Preserved source and debt

The original reviewed artifact remains unchanged: `docs/improvements/real-market-readiness-criteria.md`, SHA256 `d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9`. Source QualityDebt: `6402c739-cc23-4e07-9beb-2157e538ff4c`; original QA `b797f54a-dd17-4402-946e-9cbb97aa7cac`. Resolution must be appended with independent review evidence; never rewrite the original artifact or OPEN debt record.

## Expected coverage and acceptable gaps

Before evaluating observations, record the requested symbols, exchange, timezone, regular-session calendar version, inclusive start/exclusive end, one-minute resolution and expected session/minute set for EACH symbol. The expected set must contain at least one scheduled session and one expected bar for every requested symbol. Empty symbols, an empty interval, a holidays-only/weekend-only range, or an unspecified calendar cannot pass by vacuous comparison.

The proposed tolerance is zero missing expected regular-session bars and zero entirely missing expected sessions. Every expected symbol/session/minute must be represented exactly once. Legitimate exchange closures and published shortened sessions belong in the versioned calendar, not in an undocumented gap allowance. An unexplained suspension or provider outage remains a gap; accepting a different tolerance needs a separately reviewed configuration/version and explicit evidence. No forward-filling or synthetic bars may conceal missing coverage.

## Critical data-quality finding

A finding is critical if it prevents faithful interpretation, coverage or reproduction: invalid/nonfinite prices; impossible OHLC ordering; negative or missing required volume; missing required symbol/time/price values; duplicate or conflicting symbol/timestamps; unaccounted session gaps; wrong timezone/interval meaning; unexpected session bars; symbol/source mismatch; failed artifact hashes; unsupported source mixing; missing licensing/provenance; or unresolved outliers whose cause has not been verified against source/exchange evidence. Zero volume alone is not an error when explicitly supplied by the source. Corporate-action anomalies cannot be treated as validated merely because adjustment is unsupported.

No unresolved critical finding is acceptable. Enumerated noncritical observations require a recorded rationale and independent reviewer acknowledgement. The definition does not invent a universal numeric outlier threshold: the outlier method, parameters, reference evidence, findings and disposition must be specified and reviewed for the dataset before the check counts as completed.

## Completed checks and evidence

A completed quality report must identify dataset version and hashes, normalizer version, calendar/request, execution time and implementation revision. For every requested symbol and session, record results for schema/required values, finite/valid OHLCV, duplicate/conflicting timestamps, ordering, expected coverage, timezone/session alignment, source consistency, outlier review and file integrity. Record provider/license provenance and independent reproducibility checks separately.

Each required check must be explicitly COMPLETED with a result and evidence. PENDING, SKIPPED, NOT RUN, unknown, empty checks, failed execution, zero expected bars or missing reports are NOT a pass. No unresolved critical findings, positive nonempty expected coverage and a completed independent rerun are all necessary. A failed condition blocks readiness rather than being averaged into a score.

## Boundary

These definitions remain a specification for a future reviewed executable gate. Even a future passing data-readiness assessment would require separate out-of-sample strategy validation, operational risk controls and explicit trading authority before live use.
