# Day 7 F — independent data integration QA

Reviewer `/root/day6_qa_b`; builder `/root`.
Exact implementation: `fd7f8d0e2cf2fae22f8d26fcbfe01acff9abbb77`.
Decision: **CHANGES_REQUIRED**.

The complete fixture ingestion pipeline and neutral/product-private dataset
separation pass. Independent adversarial checks reproduce six required fixes
(seven failing parameterized cases):

1. **HIGH — current registry revocation is ignored.** Ingestion checks `enabled`
   and `configured` on the original adapter object, then checks only status,
   connection and capability in the current canonical registry. Appending a
   current definition with either `enabled=false` or `configured=false` still
   permits acquisition through the stale adapter object. Respect the current
   registry state before any acquisition, and recheck it at operation boundaries.
2. **HIGH — a stop does not prevent the next symbol fetch.** When the global kill
   switch is activated after the first completed symbol, ingestion calls the
   adapter for the second symbol and only then checks the epoch. The offline
   reproduction records calls `['LABTEST', 'SECOND']` after a stop between them.
   Guard before each external operation, retaining checks after it and before
   publishing authoritative results. The test does not issue actual network calls.
3. **HIGH — contradictory fixture provenance can qualify as REAL.** A historical
   Core manifest whose mode is changed to REAL, while its retained raw-source
   metadata and Parquet mode remain FIXTURE, is returned as eligible for a REAL
   request. Verify consistent source, manifest and artifact modes. This is a
   contradictory-metadata validation test using a trusted fixture insertion,
   not a demonstrated product-to-Core ownership exploit or real-market claim.
4. **MEDIUM — license use is matched against malformed strings.** An adapter
   returning `allowed_uses='not-for-research'` passes the check for requested use
   `research` because Python performs substring membership. Require a validated
   collection of exact permitted uses before ingestion and local eligibility.
5. **MEDIUM — corrupt raw provenance remains integrity-eligible.** Modifying the
   retained source bytes after successful ingestion leaves the dataset listed as
   eligible with a hashes-checked quality claim. Only canonical-file checksums are
   currently verified. Validate retained raw source paths/checksums and mode
   alongside canonical artifacts, or reject integrity-incomplete candidates.
6. **MEDIUM — normalization failures orphan raw evidence from their record.** If
   normalization raises after raw preservation, the FAILED DataAcquisition record
   omits the retained raw artifact path/checksum/ID. The bytes and metadata exist,
   but the acquisition failure has no direct immutable link to them. Preserve the
   current raw-artifact reference in failed-attempt provenance, including failures
   before a canonical dataset is published.

## Evidence

`logs/day7-f-independent-fd7f8d0.log`: **7 failed, 2 passed in 29.82s**, with
`TRIAD_INTEGRATION=1`, covering `tests/test_integration_data.py` and independent
`tests/test_day7_f_qa.py`. All failures support the findings above; no test harness
failure occurred. The QA-only test file passes Ruff.

Passing coverage includes the actual raw-preservation → normalization → quality →
Parquet → manifest pipeline; recorded source/license/provenance metadata; exact
session coverage; mode/paid-acquisition denial for normal requests; explicit
selection when multiple datasets are eligible; rejection of corrupted canonical
files; Core/shared-only discovery; exclusion of a Triad-private dataset from an
Aegis-scoped catalog; host-only ingestion; and nonempty-session requirements.

The review used a full frozen archive at `logs/day7-f-fd7f8d0`, including source,
configuration, SQL and fixtures. Only the independent QA file was copied into it.
Database writes were confined to disposable fixtures and their scoped graph
cleanup. All providers were local synthetic adapters; no broker/account/vendor
network call, paid data request, production write, migration, service restart or
implementation edit was performed by this reviewer. DB execution waited until
the other reviewers' runs finished.

This report does not accept the D/E predecessor or later UI work independently
owned by other reviewers. Source, test and evidence hashes are preserved in
`docs/qa/DAY7_F_QA_HASHES.json`. Fresh independent correction QA is required before
F acceptance.
