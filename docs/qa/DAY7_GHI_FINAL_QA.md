# Day 7 G/H/I — final independent QA

**PASS** at exact revision `56e4f96cd9ab43a319302edb694897d75143237a`. Independent reviewer `/root/day6_qa_a`, builder `/root`, 2026-09-19. Previous `DAY7_GHI_QA.md` CHANGES_REQUIRED evidence remains intact.

The Core ValueError handler now recognizes internal Pydantic ValidationError and returns a fixed readable message plus field locations/error types. Actual HTTP credential-reflection regression passes: rejected metadata is not persisted, and no synthetic credential marker or raw input_value appears in the response. Ordinary authentication and review safeguards remain enforced.

## Independent results

- Exact-snapshot non-DB command: `.venv\Scripts\python.exe logs/day7-ghi-final-qa-run.py day7-ghi-final-nondb tests/test_day7_surfaces.py tests/test_day7_ghi_qa.py -m "not integration"`: **3 passed, 2 deselected in 4.85s**.
- Same files with `-m integration`, label `day7-ghi-final-db`: **2 passed, 3 deselected in 8.90s**. Covers missing token/untrusted origin/host rejection, sequential candidate review, denial of direct IMPLEMENTED status, unchanged connection catalog after approval, read-only matching and absence of unsupported configure/order routes. The DB slot was reserved after F completed; disposable fixtures only.
- `.venv\Scripts\python.exe logs/day7-ghi-final-exact-56e4f96/tools/check_package.py`: **PASS**, clean wheel installation outside the checkout. Core/Aegis/product/development/cycle/integration/launch routes, HTML/JS/CSS, configuration and migration resources load from the installed package.
- Independent installed-byte comparison: **14 assets and migration resources match the tested snapshot**, including Cycle/Integration/Launch/Product UI, shared record renderer and SQL 010/011/012/013. Evidence: `logs/day7-ghi-final-installed-bytes.json`.

Test logs have corresponding `.exit` files and the same two existing TestClient deprecations. No live provider inference, production DB changes, restart, desktop copying or implementation edits were performed.

## H/I and exact artifact preservation

The original Day 6 readiness artifact still has SHA256 `d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9`. The strict hash test passes. As documented in the initial report, git archive performs line-ending conversion, so the fixture's original document was restored from the exact committed blob before this strict test; real source was never modified. The v2 document provides explicit coverage tolerances, critical findings, nonempty/completed evidence and independent rerun definitions, while remaining proposed and non-executable. It does not establish market readiness or trading authority. The final hash manifest binds the reviewed definition bytes to this revision.

Launch surfaces clearly separate Core, early product shell, development, cycles and inactive Aegis. The product shell contains no Core administration links or unsupported readiness claims. Integration source renders provider/candidate values as text through the shared readable renderer, does not persist operator tokens in browser storage and does not expose unimplemented connection/order controls.

## Provenance and limits

Fresh archive `logs/day7-ghi-final-exact-56e4f96.zip` and its extracted snapshot are isolated from subsequent changes. All app bytes match the archive; exact Git blob hashes and archive/test/package evidence are in `DAY7_GHI_FINAL_QA_HASHES.json`. The independent test file is included in this committed snapshot. Credentials for disposable fixtures are passed through child environment variables without logging values.

PASS covers G/H/I's bounded implementation, HTTP fixture and clean package checks. Actual browser/mobile/keyboard/injection/outage interaction and deployed route/desktop-file checks remain final acceptance work. Separate QA owns registry/data authorization and the proposed deployment-evidence helper; this report does not authorize that helper or claim production debt resolution has occurred.
