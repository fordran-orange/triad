# Day 4 review corrections

All six findings from the read-only review are addressed. Original experiments, datasets and result files are retained as historical evidence; the corrected engine receives a new experiment and source identity.

| Finding | Correction | Regression evidence |
|---|---|---|
| Source hash depends on checkout line endings | Normalize CRLF to LF and record lf-v1 format | LF/CRLF hashes match; changing code changes the hash; committed-byte comparison |
| Exit gaps missing from MAE/MFE | Incorporate the exit open before removing a position; exclude later exit-bar prices | Long/short adverse/favorable 50% gaps; future exit-bar extremes ignored |
| Optional derived fields copied from first minute | Sum complete trade counts; compute volume-weighted VWAP; null for missing required data/zero volume | Weighted example, missing values and zero-volume cases |
| Completed-looking artifacts after late failure | Start RUNNING, atomically replace status files, gate completion and transact work/run/journal updates; reconcile caught failures to FAILED | Inject failure after completion files are written; database, work, manifest and event log all become FAILED; result files survive |
| Concurrent or failed review leaves extra verdict | One database transaction for metadata, canonical review/journal, work transitions and outbox; stale revisions roll back | Inject failure after verdict insert; concurrent submissions leave exactly one accepted review |
| Failed sweep runs lose association | Explicit attempts retain parameters, errors and run IDs; pre-run validation failures are NOT_STARTED | Timed-out run remains linked; invalid variant retains parameters without a phantom run |

Tests: tests/test_lab_review_fixes.py and tests/test_lab_failure_integration.py, plus the existing pipeline tests. Targeted verification: 15 passed. Final full suite: **189 passed, 0 failed, 0 errors, 0 skipped**, 226.47 seconds. Two existing upstream TestClient deprecation warnings remain. Evidence: logs/day4-fixed-tests.xml. Ruff check/format, pip dependency consistency and secret exclusion audit passed.

## Operational limits

No production fault injection, budget reset, model inference or trading was performed. Fault tests use disposable databases and temporary artifact directories. Database transactions cannot atomically commit filesystem writes across machine failure; disk/process failure still requires reconciliation. If failure status cannot be written, PostgreSQL records StatusPublicationError. Portable validation rejects non-COMPLETED manifests. Historical pre-fix experiments retain their original hashes and metrics; they are not relabeled as corrected results.

## Source identity

Corrected engine commit: c435860. Normalized source SHA256: `87a163516772026db13548438f7c3fa6fc3e4f4f129d14a939d334a2247907bd`. Direct comparison against the committed Git blobs matches the working checkout, in addition to the LF/CRLF regression test. No source validation bypass was added.

## Corrected reproducibility mission

Experiment: `dd65e98a-49e4-412e-8aae-45da28926439`. Base dataset: `951b3c6c-84fc-4c68-ae12-e17cdd679d1c`. Code commit: `c435860330f8bfb95e356e56207a059a6c858d14`. Hash format: `lf-v1`.

| Run | Runtime seconds | Peak tracked Python bytes | Status |
|---|---:|---:|---|
| 890c7e56-c213-448f-a077-03ac7ef9472e | 26.109 | 16590829 | COMPLETED |
| 867f0a98-af2d-471f-8273-cdf3eddf555f | 25.656 | 16464779 | COMPLETED |

Both runs have identical deterministic content SHA256 `92fa86ba7608ba1cee91cca0dfb7e4b9c1df0a5355b525b6d3b51e761921b8e8`. Each has 118 trades and 2,340 equity observations, split into LONG and SHORT portfolios. Both host reviews returned ACCEPT_RESULT in HOST_VERIFIER_NOT_MODEL mode; no cloud-model or human review is fabricated. The smooth original fixture still has the same outputs; the new gap-specific regressions establish the corrected excursion behavior.

The six new FIXTURE datasets contain 1,170 / 234 / 78 / 39 / 21 / 3 rows at 1m / 5m / 15m / 30m / 1h / daily, all quality PASS. Old datasets/runs remain unchanged. Both corrected runs passed the standalone Python/Parquet reader with hashes verified and no Triad services needed by that reader.

Neo4j verification: one raw-to-base edge, five base-to-derived edges, one dataset-to-experiment edge, one experiment-to-commit edge, two run links, two reviews and two finding-evidence links. Projection pending/errors: zero. Backend, PostgreSQL, TimescaleDB, Neo4j and Ollama are up; model budget totals remain unchanged.

Reproduce the corrected experiment:

```powershell
.venv\Scripts\python.exe tools/research.py run dd65e98a-49e4-412e-8aae-45da28926439
```

Evidence: logs/day4-fixed-tests.xml, logs/research-demo.json and logs/day4-research-verification.json. Prior reports are retained with `.before-review-fixes` in their filenames. No original runtime dataset or experiment artifact was replaced. Exact final HEAD and clean working-tree evidence are captured by the final verifier after documentation commit. All six findings are closed; Day 5 has not started.
