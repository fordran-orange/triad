# Day 6 product framework — independent browser QA

Final verdict: **PASS for the fixture UI, by independent review of root-host browser evidence and UI source**. Reviewer: independent delegated agent `/root/day6_qa_c`. Base revision: `8927755b89aa1a240adedd96ab366f239124d19e`; exact accepted UI, fixture and evidence hashes are in `DAY6_PRODUCT_BROWSER_QA_FINAL_HASHES.json`. Initial hashes remain in `DAY6_PRODUCT_BROWSER_QA_HASHES.json`. Actual browser execution was performed on the root host; this is not a claim that the delegated reviewer executed browser actions. Execution provenance and limitations are explained below. This verdict does not approve the broader product workflow or real provider run.

The isolated preview was identified at `http://127.0.0.1:8007/triad/development`, process 17992, using `data/temp/day6_product_qa_preview.py`. Source inspection confirms this is a fixture-only application with no worker, database, credentials or provider calls. The optional `.mode` file was absent, so the fixture defaults to populated. The reviewer did not change fixture modes, implementation, or production state.

The browser surface that worked during Core C is no longer available to this delegated agent. The supported CUA inventory returned `{apps:[], browsers:[]}`. Attempts to create the preview tab using the previously working browser `1` and the named `iab` both failed with “Browser is not available.” The root agent and workflow QA agent were notified. No screenshot, browser execution, console check, layout check or interaction pass is claimed.

## Read-only source observations

Eight views exist in the HTML and JavaScript: current product state, product map, capability inventory, improvement backlog, selected improvement, build and QA, specialist agents, and development journal. Primary model-supplied strings are inserted with `textContent`; structured evidence uses the existing Core record renderer. Merged artifact content is inserted as text with wrapping, not executable HTML. Empty/error/last-snapshot messages are implemented. These are source observations only and do not substitute for browser acceptance.

## Required remaining actual-browser checks

1. Exercise all eight views with populated fixtures and inspect readable evidence.
2. Read the merged artifact dialog; confirm the literal script and image/onerror sentinels remain text and no injected elements execute.
3. Check browser console, default layout and 390px responsive layout with no horizontal overflow.
4. Set `data/temp/day6_product_qa_preview.mode` to `empty`, reload, and check empty state; set it to `failure`, reload, and check service error. Also exercise failure after a populated snapshot to verify the stale-snapshot notice. Restore populated afterward.
5. Bind the resulting browser evidence to the actual reviewed file hashes, and rerun affected checks after any correction.

These requested fixture checks have now been completed on the root host and their resulting evidence independently reviewed below. The original delegated-browser availability failure is retained for transparency.

## Independent review of root-host browser evidence

The root host has a functioning browser connection and performed the actual CUA interactions. Its condensed observations are recorded in `logs/day6-product-browser-root.json`, naming browser1/tab7 and the preview URL. Content export was unavailable. This reviewer read that evidence and independently checked the corresponding current UI source; the reviewer did not execute those browser actions and did not directly receive screenshot image files. Screenshot inspection is therefore attributed to the root executor.

The supplied actual-browser observations cover all eight views, readable selected-proposal detail, merged artifact text, literal image/script sentinels (zero rendered images), empty metrics/Build-and-QA state, and absence of console warnings/errors. At 390×844 the reported document width is 375 and the open dialog's client/scroll widths both365. Root inspected dashboard/dialog screenshots and reset the viewport. The current source applies wrapping to all h2 headings, including artifact paths, consistent with that result.

Root detected initial-outage loading text remaining visible and corrected it; fresh supplied DOM observations show explicit charter/evidence-unavailable messages without stale Loading text. Source independently confirms this correction. Root also detected a hard-coded QA-required badge on a merged build. Source now derives each build's status by matching `implementation_id` to its merge/latest QA, and separately renders failure records. Fixture identifiers now support a meaningful browser regression of that correction.

The two final correction checks are now present in the evidence file and pass independent review:

- `fresh_badges`: after reload, matching `fixture-build` displays CLAUDE build MERGED, the separate failed attempt displays FAILED, CODEX QA displays PASS WITH OBSERVATIONS, and the governed merge displays MERGED. Source matches on implementation ID and keeps failed attempts distinct.
- `retained_outage`: after populated mode changes to controlled 503, the normal 20-second refresh explicitly reports “Displaying the last available snapshot”; populated cards and their previous timestamp remain. Console warning/error output remains empty. Source retains the previous data on a failed fetch and changes only the notice.

The final mode file is restored to `populated`. The corrected initial-outage state, long artifact-title wrapping, and truthful merged/failed badges resolve the identified UI issues. No remaining fixture UI findings require a change. The final hash manifest binds the exact HTML, JavaScript, shared renderer/CSS, preview fixture and root browser evidence reviewed here.

Live destination navigation remains separate post-launch verification because the isolated fixture intentionally does not serve those applications. The main workflow QA agent must combine this UI evidence review with its independent execution/security/merge tests; this limited UI verdict alone is not a product-framework acceptance or completion verdict.
