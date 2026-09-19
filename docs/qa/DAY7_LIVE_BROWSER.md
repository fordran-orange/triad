# Day 7 live browser observations

Observer: `/root` using the Codex in-app browser; independent acceptance reviewer
audits this evidence separately. These are actual loopback pages after deployment
of application56e4f96/helper120f328, not source-only render assertions.

- `/launch`: all six destination links visible; Core, Triad and Aegis separated;
  early product and inactive lineage labels explicit. Services-not-started-by-page
  explanation visible.
- `/core/integrations`: initial loading state resolves to Schwab and Robinhood
  NOT CONFIGURED and Local Canonical Store AVAILABLE. No broker connection/order
  buttons are presented. Category selection leaves only the local historical
  source. SPY real coverage query returns “No matching retained coverage” plus
  readable source-exclusion detail control. It does not download anything.
- Schwab details: headings and paragraphs for capabilities, requirements, status,
  transport and times; no raw JSON dump. Created/updated shown as local CDT with
  canonical UTC disclosure. Closing returns focus to its launching button.
- `/triad/cycles`: three canonical cards. Completed REAL Day6 shows Claude builder,
  independent QA, merge445f16661152,1733.1s,LOCAL/SUBSCRIPTION billing and a recorded
  debt resolution. Earlier failures remain on the completed mission's card.
  Historical REAL gate failure remains BLOCKED with credentials/model failures and
  recovery link day6-product-20260919. The other blocked card remains SIMULATED.
  Blocked filter returns only those two cards. Inspect opens readable evidence
  with TRIAD_PROVIDER_GATE_FAILED and historical UTC/local timestamps. Escape
  dismisses the dialog successfully.
- `/triad/product`: EARLY PRODUCT SHELL; no account/order/portfolio/strategy claim
  and no Core administration controls. Links open development and cycles.
- `/triad/development`: loading resolves to three frontier inspections, four
  candidates, one independent QA and one merged improvement. Existing mission,
  proposal, builder/QA and journal navigation remain available.
- `/aegis`: human-directed/inactive/preserved,0assignments,Exchange closed.
- `/core`: work cards populate and shared control/kill-switch affordances remain
  available. No production kill toggle was performed for demonstration.
- `/settings/ai-providers`: provider gate PASS, current evidence, all four Ready.
  Subscription and Qwen daily caps off; API policy/fallback NEVER preserved.
  CLI signed-in/WorkItem/inference evidence remains readable.
- Browser console inspection after these interactions returned no error/warning
  entries. One initial label locator mismatch was resolved using the observed
  combobox accessibility role; no application change was needed.

Installed-package and adversarial HTTP/source tests are separate evidence; this
browser pass does not claim mobile emulation, synthetic DOM injection or a forced
production outage. Existing isolation/kill/error-boundary tests cover those
server authority paths in disposable fixtures.

Desktop shortcut's actual resolved target uses Windows packaged-app LocalCache:
`C:/Users/fordr/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Triad/Launch.html`.
The previous target bytes are backed up. The final target and reviewed launch HTML
share SHA256 `e6acf764e607d34484718b23256d3b5730d0dd8aa1b02072d90c48c593e1ee24`.
See logs/day7-desktop-launch-actual.json. Browser verification used the legitimate
app `/launch` route; no bypass of the earlier file-URL preview restriction occurred.

Initial services probe observed `/aegis`503 during worker startup and is retained
with exit1 in logs/day7-final-services.log. The settled rerun is exit0:
logs/day7-final-services-settled.log. All routes/services and4providers pass; gate
PASS,0active runs,Aegis0work/exchange CLOSED.
