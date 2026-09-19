# Day 8 daily API/UI — independent QA

Reviewer `/root/day6_qa_a`; builder `/root`.
Exact revision: `264cd8d12223598942b0781b6952a9243120c4d4`.
Decision: **CHANGES_REQUIRED** for two bounded UI findings.
Scope is the eight committed daily API/UI/navigation/package files. Separate
lifecycle, engineering and final deployed browser acceptance are excluded.

## Required findings

1. **P2 — Existing navigation pages contain corrupted text.** The Product,
   Development and Cycles HTML edits introduce UTF-8 mojibake, including `Â·`,
   `â€”` and `â€¦`. Actual HTTP response assertions reproduce the corruption on
   all three routes; these are valid UTF-8 bytes containing wrong characters,
   so strict decoding alone does not detect it. Restore the original punctuation
   and retain the new navigation without decoding/re-encoding corruption.
2. **P2 — A history failure misreports a successful schedule load.** The shared
   Promise.all catch always sets schedule status unavailable. A history-only
   failure after a successful schedule response overwrites the actual Disabled
   status with an unavailable message. Handle the two panels' load/error states
   independently so successful state remains visible and each error is located
   in the affected panel. Reproduced with the actual daily.js in a controlled
   Node DOM/fetch fixture, without a browser or production backend.

## Independent checks

Frozen git archive: `logs/day8-daily-ui-264cd8d`. The independent test was copied
into it; application imports use that snapshot. Commands and results:

- `.venv\Scripts\python.exe -m pytest logs/day8-daily-ui-264cd8d/tests/test_day8_daily_ui_qa.py -q`:
  **3 failed, 8 passed, two dependency warnings in 3.12s**, exit 1. All failures
  are the three mojibake routes. Logs `day8-daily-ui-independent-final-264cd8d`.
- Fixture HTTP verifies unauthenticated schedule mutation 401, untrusted origin
  403 even with the test key, valid authorized configuration 200, invalid body
  422 without writes, public history/schedule reads, readable service denial,
  and explicit 503 pending-feature routes. Authentication uses the real local
  operator dependency with an offline key; the lifecycle service is overridden.
- `node --check` on frozen daily.js passes. `node logs/day8-daily-ui-dom-qa.js`
  against that file checks all seven filters, case-insensitive model/area,
  empty history, total outage and literal rendering of injected markup. Ten
  checks pass; history-only failure assertion fails. Log:
  `logs/day8-daily-ui-dom-264cd8d.log`. The fixture throws on innerHTML writes
  and checks no localStorage/sessionStorage writes. Source review confirms text
  sinks and clearing the operator-key input after a successful save.
- Frozen `tools/check_package.py`: clean wheel build/install and existing Core,
  Aegis, config, SQL, HTML/JS/CSS smoke pass. Additional independent installed
  checks confirm byte identity for six affected assets/modules, daily HTML/JS
  routes 200 and both unbuilt readiness routes 503. Installed package:
  `C:/Users/fordr/AppData/Local/Temp/trading-core-package-x8ywzqga/installed`.
  Evidence `logs/day8-daily-ui-package-264cd8d.log` and
  `logs/day8-daily-installed-264cd8d.log`, exits 0.
- Independent Python test Ruff check passes after formatting and fixture-only
  cleanup. Earlier unformatted test output remains retained separately.

Hashes of all eight raw Git blobs, frozen bytes, tests and evidence are in
`DAY8_DAILY_UI_QA_HASHES.json`. No application changes, production writes,
provider calls or database suites were performed. TestClient never entered the
product lifespan, so no product worker started. The Node DOM fixture is a logic
check, not a rendered-browser/mobile/keyboard acceptance claim. Actual deployed
browser checks remain required after the foundation corrections pass.
