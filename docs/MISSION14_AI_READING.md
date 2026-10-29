# Mission 14: AI reading for the strategy builder (2026-10-26 → 28)

Branch `aegis/ai-reading`, cut from `main` at `0117490` (not merged; merging stays the operator's
answer). Design: `docs/superpowers/specs/2026-10-26-aegis-ai-reading-design.md` (`01f9b9f`; §9 the
Grok amendment, `98a3d47`, with QA's known limits, `a004e80`). Plan:
`docs/superpowers/plans/2026-10-26-aegis-ai-reading.md` (`0117490`, six tasks). `AI_READING_BASE` =
`0117490`. Tasks 1–5 and the Grok amendment were built on Opus 5.5; the acceptance and this record
on Fable 5.1.

Not product work only: the mission adds a Core contract (the product reasoning route) and a
credential (the per-product key), so independent milestone QA and a whole-branch review are
required before merge (`AGENTS.md`). The Grok amendment (`a004e80`) and the provider Test budget
(`042d5c9`) each had their own independent QA; the branch as a whole has not had its milestone QA
or review yet. Nothing under `app/platform_host/` or `app/products/triad/` changed. Exchange CLOSED;
Triad suspended; `DailySchedule` `c99fa831` disabled; live trading disabled.

Core changed since the plan commit in seven files (walk item 102 names each). Mission 14's five:
`app/trading_core/api.py` (one `include_router` line), `product_reasoning_api.py` (new),
`product_reasoning.py` (new), `settings.py` (the key setting) and `intelligence/routing.py`
(`Routing.evaluate`, the amendment). Two merged from `main` while the mission was built, each
governed there: `runtime.py` (the Codex strict-schema fix `c6c1149`, merged in `e1b2452`) and
`providers/verification.py` (the Grok provider Test budget `5f625e2` and `042d5c9`, merged in
`57bcb34`). No Core chat, routing policy, provider configuration, Ollama or ledger shape changed; no
paid API fallback.

## Intent (operator, 2026-10-25/26)

"now how do we make the text entry better.. it doesnt know words like up, down, exit... it needs
more reasoning." The phrase reader reads a fixed vocabulary, so "crosses up", "drops back", "exit
when it falls back" mid-sentence or "it" were refused.

Decisions: "1, but use it to grow 3" (the phrase reader reads first; when it refuses, the AI
through Core reads the sentence; accepted AI readings grow the phrase reader); learned on Apply
("a"), listed and removable; a provider selector beside the text line, Claude the default,
remembered ("a" = option 1), no silent substitution; triggered automatically on a refusal ("1"); a
local Qwen ("D") is the destination, not this mission; the Core contract ("1"): a gateway route for
product readings behind a key Core issues to the product's worker, read-only, no tools, the
product's chosen provider, records owned by the product. Design sections 1–4 "yes". Amendment
2026-10-27: "grok should be an option if available", then "add Grok to the Mission 14 selector,
shown only when Core says it's available".

## The probe

The installed `qwen3:4b` through Ollama (Core holds it as a SUPPORT-only, maintenance-only
provider) on this laptop (16 GB RAM, i7-1255U, no discrete GPU): 30–126 s per sentence, 0 of 3
right, over ten minutes with thinking on. So the cloud CLIs through Core now; every accepted
reading is kept as an example (`data/aegis/phrases/examples.jsonl`) so a local model can be
measured on them later.

## What was built

| Commit | Task | What |
|---|---|---|
| `975964d` | 1 | `POST /api/core/products/{product}/reasoning` beside the chat's router; a product's worker presents its own key (`aegis_product_key`, ≥ 32 characters, compared in constant time), never the operator token: unknown product 404, no key issued 503, another product's key 403, anything else 401; the key opens no operator route; bounded request (provider, instructions ≤ 20,000, input 1–2,000, output schema ≤ 8,000 characters of JSON). `tools/issue_product_key.ps1 -Product aegis [-Rotate]` writes a random 48-character key into `.env` and never prints it |
| `4027afc` | 2 | `trading_core.product_reasoning`: a reading runs exactly as the chat runs a reply (a store lease per product, 409 while one runs; a read-only work item owned by the product; routing to exactly the named provider; usage in the ledger); a failed, blocked or acting run is `provider_failed` (502) with no other provider asked; not JSON or not the product's shape is `malformed_answer` (502); 120 s at most (504, the run keeps its lease and is recorded when it ends) |
| `6e7c445` | 1 | The key script uses `RandomNumberGenerator.Create().GetBytes`, which Windows PowerShell 5.1 has (the operator's first run failed before writing; `.env` was unchanged) |
| `39c3102` | 3 | The phrase reader applies learned phrases first (whole words, any case, longest first, never overlapping; refusals still underline the operator's words); `grammar_text()` writes the reader's language from its own tables; `products.aegis.learned` keeps every applied AI reading as an example and learns a substitution only when the substitutions together explain the rewrite and that one is context-free; a newer meaning replaces an older; Remove |
| `34132c1` | 4 | `POST /aegis/api/strategies/read` reads with the phrase reader first, then asks Core's route (the product key from Core's settings; instructions carry the grammar, the strategy's indicators, the rules and the newest 20 examples); the reader checks the rewrite; a refusal keeps the reader's message and spans and adds why the AI could not; the `reader_provider` preference; `/phrases/learn`, `/phrases/learned` (list, delete) |
| `2e4fb12` | 5 | The builder: the provider selector, "Reading with Claude…" with Cancel, "Read as", "Read by Claude · model · tokens", "Couldn't express", the refusal's AI line, Learned phrases with Remove, learning on Apply |
| `e1b2452` | — | `main` merged in: the Codex strict-schema fix (`c6c1149`, `a1c314a`), so Core restarted from the branch keeps Codex routable |
| `72e6917` `9135349` `be73833` `98a3d47` `a004e80` | §9 | Grok: `GET …/reasoning/providers` (Core's routing evaluated through the new `Routing.evaluate`, nothing recorded); the worker's `/aegis/api/phrases/providers`; the selector offers only providers Core can route now, "none available" with Recheck, `ai: false` when none; the amendment and its QA fixes |
| `57bcb34` | — | `main` merged in: the Grok provider Test budget (`5f625e2`, `042d5c9`) |
| (the record commit) | 6 | Items 96 (updated), 98–102; the earlier governance items name the seven Core files; this record and the evidence |

## The measured reading

Item 98, one real reading by Claude through Core of "buy when 9 ema crosses up 30 sma, exit when it
crosses back down": the preview after **17.6 s** ("Reading with Claude…" meanwhile), `claude-opus-5[1m]`,
7,671 + 831 tokens, rewritten as "buy when 9 ema crosses above 30 sma; exit when 9 ema crosses
below 30 sma" and read as "Long entry: EMA 9 crosses above SMA 30. Exit: EMA 9 crosses below SMA
30", nothing left unexpressed. The two earlier readings of the evening, same rewrite: 19.0 s
(7,605 + 873 tokens, the second walk) and 28.8 s (7,499 + 951, the trial of items 98–102 alone).

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261029T022254Z.json`: **102/102 PASS, no page errors**, 16.6
minutes (the third full walk of the evening; the first two, 82/102 and 98/102, are rulings 12–15
and stay under `logs/`).

- **96** (updated): "buy when vwap crosses 30 sma" now goes to the AI after the reader's refusal:
  the refusal still names and underlines `vwap`, and under it "Claude's rewrite could not be read:
  there is nothing to read" (Claude expressed nothing of it); nothing applied, the hash unchanged.
- **98:** "Reading with Claude…", then "Read as: buy when 9 ema crosses above 30 sma; exit when 9
  ema crosses below 30 sma"; "Read by Claude · model · tokens"; Apply and Save: entry EMA 9 crosses
  above SMA 30, exit EMA 9 crosses below SMA 30; "Learned: crosses up → crosses above".
- **99:** the learned list shows "crosses up → crosses above" with its sentence, time and Claude;
  "buy when 9 ema crosses up 30 sma" is then read by the phrase reader (`read_by` "phrases", no
  provenance, no thinking state).
- **100:** Remove through the list; the same sentence shows "Reading with Claude…" again; Cancel
  shows nothing and keeps the text.
- **101:** Codex chosen, saved in the preferences and shown after a reload; back to Claude; the save
  mode as found.
- **102:** governance since `0117490`: Core changed only in the seven files named above, nothing
  under the platform host or Triad, `.env` ignored by git; exchange CLOSED; the schedule disabled;
  items 1–101 pass.

A trial of items 98–102 alone before the walk passed 98–101; 102 failed there only on its count of
101 earlier items, by design.

## Rulings

Each with its cost if wrong:

1. Task 1: a product key is compared in constant time and opens only its product's reasoning
   route; the operator routes refuse it. Cost: none.
2. Task 2: a run that claims an action, a file, a command or a test, or is reported blocked, is
   `provider_failed` with no other provider asked. Cost: a reading refused that a retry might have
   answered.
3. Task 2: past 120 s the caller gets 504 while the run keeps its lease and is recorded when it
   ends; a new reading meanwhile is 409. Cost: a wait after a Cancel.
4. Task 3: a "," or "and" followed by an opener starts a new clause ("buy when …, sell when …").
   Cost: none.
5. Task 3: a substitution is learned only when all the AI's substitutions together explain its
   rewrite and that one is context-free ("crosses up" → "crosses above" yes; "it" → "9 ema" no).
   Cost: fewer phrases learned.
6. Task 4: every test client reads with a stand-in Core; no test reaches the gateway. Cost: none.
7. Task 5: the thinking state appears after 400 ms (the phrase reader answers well within); Cancel
   aborts the request, Core finishes and records the run. Cost: none.
8. Amendment: a provider is offered only while Core's routing would assign the reading to it now;
   with none offered a sentence is read with `ai: false`. Known limits: a paused product, a CLI
   logged out after its proof, a reading already running. Cost: a provider offered and then refused.
9. Task 6: the walk's "no Core change" items name the two Core fixes merged from `main` as well as
   Mission 14's five files, each attributed to its commit, rather than the plan's four. Cost: the
   allowance is wider than the plan wrote; it is exact and attributed.
10. Task 6: the save preference was found as "kept" (the plan's constraint said "every"; the
    Mission 13 walk had left "every", so it was set afterwards, not by this mission); item 101
    asserts only that the selector leaves the mode untouched. Ruling 12 says what the walk does
    about it. Cost: none.
11. Task 6: the walk needs Docker Desktop (Postgres), Core, both workers and the product key; the
    session found Docker stopped after a machine restart and started it, after which the Core
    supervisor recovered Core and both workers on its own. Cost: none.
12. Task 6: a first full walk found the worker in "kept" mode and ran 82/102: the runs of items 22, 39 and 54 were never saved, so the Library items 70–76,
    82, 84 and 87 and every governance item after them failed, and item 16's title locator also
    matched the "NOT KEPT" badge ("…unsaved runs…"). The walk now switches a worker found in
    "kept" mode to "every" before item 1 and says so (item 85 ends in "every" anyway), and item
    16's locator is exact. Cost: a walk changes the operator's save mode, as item 85 already did.
13. Task 6: item 98 reloads the page before opening its strategy: the Lab's list was loaded before
    the strategy existed, so the row was not there to click (item 93 reloads for the same reason).
    Cost: none.
14. Task 6: `wheel_until` allows 30 batches, not 15: on the busy machine of the first walk (Windows
    telemetry and memory compression each on most of a core after the restart) item 83's zoom-in
    ran out of batches; in isolation it needs one batch (2.3 s), and the helper returns as soon as
    the condition holds. Cost: a failing zoom takes 50 s to fail instead of 25.
15. Task 6: a second full walk ran 98/102: item 92 read the builder's blocks right after Ctrl+Z,
    when the status already said Ready but React Flow had not yet drawn the restored RSI block
    (93, 97 and 102 followed from it). The check now waits up to 10 s for the block, as the
    deletion's own check already did. Cost: none.

## Left in the operator's store

Made by the trial and the three walks, kept (nothing deleted): the strategies "AI reading
20261029T013507Z" (the trial), "AI reading 20261029T013910Z" (the first walk, created but never
read), "AI reading 20261029T020444Z" and "AI reading 20261029T022254Z" (the second and third
walks, each with its applied reading); three accepted readings in
`data/aegis/phrases/examples.jsonl` (product data by design); no learned phrase remains (item 100
removes the one each walk teaches); each walk's usual items ("Operator sentence", "stop surface",
"breakout surface", the Library's throwaways). The save mode is "every", as item 85 leaves it.

## Verification

- Core: `tests/test_core_product_reasoning.py` with `TRIAD_INTEGRATION=1`: 14 passed (53 s).
- UI: vitest 150 passed in 22 files; the production build (tsc + vite) clean.
- Lint: the Aegis scope clean (`ruff check` and `format --check`).
- Identity: every saved strategy document's hash recomputed after the walks
  (`builder_identity.py hashes`): 55 strategies, 0 changed.
- `tools\verify.ps1` on the branch after the walks: lint and format clean; inventory core 597, triad 1,058, aegis 561; all three scopes green (core 410 passed / 187 skipped; triad 634 / 424 with 209 subtests; aegis 560 / 1); the foundation audit passed every check up to "Wrong Git branch", where it stops on a branch by design (415 s).
