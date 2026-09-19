# Day 7 G/H/I — independent QA

**CHANGES_REQUIRED** for G's API error boundary at exact revision `a536683d4c7ae3ea56c8e754b7a4d32aa7ac156a`. Reviewer `/root/day6_qa_a`, separate from builder `/root`, 2026-09-19. H/I source, HTTP shell and preserved-document checks pass within the limitations below; no live browser/deployment acceptance is claimed.

## Required correction

**P2 — rejected candidate metadata is reflected through the internal Pydantic error handler.** POST `/api/core/integrations/candidates` first validates CandidateInput, then constructs IntegrationCandidate inside the endpoint. Its public-metadata validator rejects credential-bearing URLs, but this raises a Pydantic ValidationError caught by the existing generic ValueError handler, which returns `str(exc)`. The HTTP response contains `input_value` and user input, including a credential prefix. A short synthetic URL password is echoed completely. The existing RequestValidationError handler correctly strips inputs; apply equivalent safe handling to this internal validation path. Return a concise, readable error without raw input, credential fragments or Pydantic implementation details.

The regression executes the actual Core HTTP route, operator authentication, model validation and exception handling. It substitutes only the persistence dependency and checks it is never called, so malformed metadata is not stored. All credentials used in this probe are explicit nonproduction fixtures. No secret from the real environment was used in it.

## Tests and scope

Fresh git archive at `logs/day7-ghi-exact-a536683.zip`, extracted to its matching folder. Runner `logs/day7-ghi-qa-run.py` sets snapshot TRADING_HOME/PYTHONPATH, TRIAD_INTEGRATION=1 and provider monitoring off. Database tests use the established disposable fixture; no production mutation/restart/backfill/inference. Concurrent corrections to other segments are excluded.

- Command suffix `day7-ghi-independent tests/test_day7_surfaces.py tests/test_day7_ghi_qa.py`: **4 passed, 1 failed in 11.97s**. The only initial failure was the document hash fixture issue explained below. Passing tests cover shell delivery, missing-auth rejection, untrusted-origin rejection, candidate review lifecycle, forbidden direct implementation status, absence of configure/order routes, host restriction, denied live execution and unchanged catalog after approval. Markup-like candidate names remain data; source renders them via textContent rather than HTML.
- Strict document hash rerun `day7-ghi-readiness-rerun tests/test_day7_ghi_qa.py -k readiness`: **1 passed, 2 deselected** after restoring the exact committed document blob inside the fixture.
- Expanded actual HTTP validation boundary `day7-ghi-error-reflection tests/test_day7_ghi_qa.py -k rejected_metadata`: **1 failed, 2 deselected in 4.09s**, raw input_value returned.
- Short synthetic HTTP password confirmation `day7-ghi-error-reflection-confirmed tests/test_day7_ghi_qa.py -k rejected_metadata`: **1 failed, 2 deselected**, credential marker returned. This non-DB test supersedes the initial too-long-marker probe, which missed truncated input reflection; the stronger assertion is retained.
- Ruff on the independent test file passes. All pytest runs emit the same two existing TestClient deprecations.

Commands use prefix `.venv\Scripts\python.exe logs/day7-ghi-qa-run.py`; matching log labels under logs have `.log` and `.exit`. Independent tests: `tests/test_day7_ghi_qa.py`. Exact implementation blobs, archive and executed evidence are hashed in `DAY7_GHI_QA_HASHES.json`.

## H/I readiness and launch review

`real-market-readiness-definitions-v2.md` explicitly remains proposed/non-executable. It defines nonempty expected coverage per symbol, zero unexplained missing regular-session bars/sessions, explicit critical-finding categories and dispositions, completed checks/evidence and independent reproduction. Empty, skipped or unknown evidence cannot pass. Trading/strategy authority is not implied. Canonical debt resolution is still a later reviewed append, not performed by this QA.

The original Day 6 artifact is byte-for-byte unchanged in base/day6-complete, a536683 and the working tree: SHA256 `d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9`. Git archive converted its LF bytes to CRLF (archive SHA `482c2c983385c5c606de5dc9d3b9178a73db321825c5211516411414a27eaf98`), causing the initial fixture failure. Restoring only that fixture document from `git show a536683:<path>` makes the strict SHA test pass without changing its assertion or the real artifact. Detailed read-only provenance: `logs/day7-ghi-readiness-hash-provenance.json`.

Launch routes distinguish Core, early Triad product shell, development/cycles and inactive Aegis; the product shell has no Core administration links and makes no market-readiness claim. Absolute loopback launch links are suitable for the eventual desktop copy. No desktop file was copied or executable behavior added by QA. Integration UI exposes no unimplemented login/configure/order controls; local catalog checks are labelled distinctly. Operator token is only in page memory, not local/session storage. Matching is labelled read-only, never acquisition.

Source review verifies dynamic textContent/shared-readable-renderer paths, but does not substitute for actual browser injection, mobile, outage and keyboard testing. Final live browser checks, packaged assets and desktop-copy equality remain deployment acceptance tasks after correction. Other integration data/registry implementation verdicts belong to their separate QA reports.
