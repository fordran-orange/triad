# Aegis Mission 14: AI reading for the strategy builder — design (2026-10-26)

## 1. Intent

The operator, after Mission 13: "now how do we make the text entry better.. it doesnt know words
like up, down, exit... it needs more reasoning". The phrase reader reads a fixed vocabulary, so
"crosses up", "drops back", "exit when it falls back" mid-sentence or "it" are refused.

Success: a sentence the phrase reader cannot read is read by a model through Core, reasoned into the
reader's own language and checked by the reader; the operator applies it; and what was learned makes
the next such sentence instant, with no model call.

## 2. Decisions (the operator, 2026-10-25/26)

1. **"1, but use it to grow 3."** The phrase reader reads first; when it refuses, the AI through Core
   reads the sentence; accepted AI readings grow the phrase reader.
2. **Learned on Apply ("a").** The substitutions an applied AI reading used are kept as learned
   phrases, listed, removable.
3. **Provider ("a" = option 1).** A selector beside the text line: Codex, Claude or Grok, default
   Claude, remembered. No silent substitution.
4. **Trigger ("1").** Automatically, when the phrase reader refuses.
5. **A local Qwen ("D") is the destination, not this mission.** A probe of the installed `qwen3:4b`
   (Ollama; Core holds it as a SUPPORT-only, maintenance-only provider) on this laptop (16 GB RAM,
   i7-1255U, no discrete GPU) took 30–126 s per sentence, 0 of 3 right, and over 10 minutes with
   thinking on. This mission keeps every accepted reading as an example, so a local model can later
   be measured on them; adding it is a later Core decision.
6. **The Core contract ("1").** A Core gateway route for product readings, behind a key Core issues
   to the product's worker; read-only, no tools, the product's chosen provider, records owned by the
   product.
7. Design sections 1–4 each approved "yes" in chat.

## 3. Today

- The phrase reader (`products.aegis.phrases.read`) parses a fixed grammar; `POST
  /aegis/api/strategies/read` answers `{sides, reading, defaults}` or 422 with the unread spans.
- Core runs a model only for its own chat (`trading_core.conversation`): a read-only `WorkItem`
  through `Routing`, `ExecutionServices.start_work`, `runtime.execute(AgentRunRequest)` with
  `required_output_schema = AgentRunResult` (the answer in `summary`, at most 8,000 characters),
  the provider the operator chose (`CODEX`, `CLAUDE`, `GROK`; subscription billing, no paid API
  fallback), usage in the ledger. Its routes require the operator token.
- No product can ask Core for a model reading. The Aegis worker loads Core's whole `.env` when it
  builds `Store(scope="aegis")` (operator token included); separating that is a separate task
  (chip `task_1efcb8c1`), not this mission.
- Core has not changed since Mission 5; walk items 46, 60, 76, 81, 86, 88, 90 and 97 assert no
  change under `app/trading_core` since their missions.

## 4. Design

### 4.1 The Core route

`POST /api/core/products/{product}/reasoning` on the gateway, scoped to one product.

- **Key.** Core settings gain one key per product, starting with `aegis_product_key` (`.env`
  `AEGIS_PRODUCT_KEY`), at least 32 characters. `tools/issue_product_key.ps1 -Product aegis` writes
  a random 48-character key if none exists (it refuses to replace one unless `-Rotate`) and never
  prints it; the mission asks the operator before running it. The worker sends
  `Authorization: Bearer <key>`. A key opens only its own product's reasoning route; the operator
  routes refuse it.
- **Request.** `{"provider": "CODEX" | "CLAUDE" | "GROK", "instructions": ≤ 20,000 chars,
  "input": 1–2,000 chars, "output_schema": a JSON object of ≤ 8,000 chars}`.
- **Run.** The chat's governed path with the product as owner: a read-only work item (authority tier
  0, no tools, no paths, read permission only), routing to exactly the provider asked for
  ("Product selected the provider; no silent substitution"), an `AgentRunRequest` whose objective
  asks for the JSON answer in `summary`. Core parses `summary` as JSON and checks it against the
  product's schema (types and required fields). One reading at a time per product (a store lease);
  120 seconds at most.
- **Answer.** `{"output": <the JSON>, "provenance": {provider, model, transport, billing_source,
  input_tokens, output_tokens, run_id, work_item_id}}`. Core records the work item (completed or
  failed) and the usage, owned by the product. No chat message or Intake record is written.
- **Errors**, each with a short reason: 401 missing or wrong key; 403 a key for another product;
  422 a request out of bounds; 409 a reading already running; 502 `provider_failed` (the run
  failed, blocked or claimed any action, file, command or test) with no other provider tried; 502
  `malformed_answer` (not JSON, or not the product's shape); 503 no key issued; 504 past 120 s.

### 4.2 Reading in Aegis

- The worker's `POST /aegis/api/strategies/read` takes `{"text", "strategy", "provider"?}` (provider
  defaulting to the remembered one). The phrase reader reads first, with learned phrases applied
  (4.3). If it reads the text, the answer is as today plus `"read_by": "phrases"`.
- If it refuses, the worker asks Core. Its instructions: the reader's grammar, generated from the
  reader's own vocabulary tables (so they cannot drift); the side's current indicator ids; the 20
  most recent accepted examples (sentence → rewrite); the rule to answer only in the grammar, repeat
  operands instead of pronouns, and list what it could not express. The output schema:
  `{"rewrite": str, "substitutions": [{"from": str, "to": str}], "unsupported": str}`.
- The phrase reader reads the rewrite. If it reads, the answer adds `"read_by": "ai"`, the
  provenance, `rewrite`, `substitutions` and `unsupported`. If not, 422 with the reader's message,
  the rewrite and the provider; nothing is offered to apply. A Core error passes through as its own
  message ("Claude could not read this: …"), with nothing substituted.
- Aegis preferences gain `reader_provider` (default `CLAUDE`) beside `save_runs`.

### 4.3 Learning and examples

- **Apply.** When an AI reading is applied, the builder posts it to `POST /aegis/api/phrases/learn`
  (`text`, `rewrite`, `substitutions`, provider, model, run id). The worker always keeps the example
  (`data/aegis/phrases/examples.jsonl`).
- **A substitution becomes a learned phrase only when:**
  1. its `from` words appear in the text (whole words, any case) and its `to` is words the reader
     knows;
  2. its `from` contains no word the reader already knows (openers, kinds, outputs, price words,
     comparisons, level words, "and", "or"), so a learned phrase never changes a sentence the reader
     already understood;
  3. its `to` brings in no operand its `from` lacks (no indicator, number or price word), so
     context-bound readings ("it" → "9 ema") are not learned;
  4. with the kept substitutions applied to the text, the phrase reader produces exactly the sides
     the rewrite produced.
- **Store.** `data/aegis/phrases/learned.json`: `{id, from, to, learned_at, example, provider}`. A
  newer meaning for the same `from` replaces the older. `GET /aegis/api/phrases/learned` lists them;
  `DELETE /aegis/api/phrases/learned/{id}` removes one (saved strategies are untouched).
- **Use.** The phrase reader applies learned phrases before reading: longest `from` first, whole
  words, any case; refusals still underline the operator's original words (an offset map).

### 4.4 The builder

- Beside the text line: the provider selector (`#reader-provider`) and "Learned phrases"
  (`#learned-open`).
- While the AI reads: "Reading with Claude…" (`#phrase-thinking`) with Cancel; Cancel stops waiting
  (Core finishes and records the run; its answer is discarded).
- The preview adds "Read as: <rewrite>" (`#phrase-rewrite`), "Read by Claude · model · tokens"
  (`#phrase-read-by`) and "Couldn't express: …" (`#phrase-unsupported`) when not empty; Apply and
  Ctrl+Z as now; an applied AI reading is posted to learn.
- The Learned phrases list (`#learned-list`): "crosses up → crosses above", its example sentence,
  date and provider, and Remove (`#learned-remove-<id>`).

## 5. Verification

- **Core** (core scope, `Runtime.execute` faked as the chat's tests do): the key refusals (missing,
  wrong, another product's, on an operator route); bounds; one at a time; a failed, blocked or
  acting run → `provider_failed` with no substitution; a malformed answer; the time limit; a good
  answer with its provenance, and the work item and usage recorded as the product's.
- **Aegis** (fake Core client): reader first; AI only on refusal; the rewrite checked; an unreadable
  rewrite shown with its reason; `unsupported` passed on; the remembered provider; each learning
  rule ("crosses up" learned, "it" → "9 ema" refused, a known word refused, the whole-sentence
  check); learned phrases applied before reading with spans on the original words; newest wins;
  Remove; every sentence of the Mission 13 table reads exactly as before.
- **UI:** vitest for the preview states, the selector and the learn call; type check and build.
- **Browser acceptance, items 98 onward:** one reading by Claude, for real, through Core ("buy when
  9 ema crosses up 30 sma, exit when it crosses back down"): applied; "crosses up" listed as
  learned; the same phrasing then read by the phrase reader with no provider; Remove; the selector
  remembered; governance (Core changed only in this mission's files; exchange CLOSED; items 1–97
  pass). Each walk uses one real Claude reading; that item fails if Claude is unavailable.
- **Milestone:** `tools\verify.ps1` (all three scopes), the frontend tests, the browser acceptance;
  independent milestone QA and a whole-branch review (required: a Core contract and a credential).

## 6. Boundaries

- Core changes: the reasoning route and its module, the per-product key setting and issuing script,
  and their tests. No change to Core chat, routing policy, provider configuration, Ollama or the
  ledger's shape; no paid API fallback.
- Aegis holds only its product key (read from Core's settings as it reads them today). Learned
  phrases and examples are Aegis-owned product data.
- The engine, the strategy model and saved strategies are unchanged. Exchange CLOSED; live trading
  disabled.
- Earlier walk items that assert no Core change since their missions name this mission's Core files
  as the one expected change.

## 7. Out of scope

A local Qwen provider; streaming answers; the AI building blocks directly (it only writes the
reader's language); separating product workers' secrets (chip `task_1efcb8c1`).

## 8. Risks

- **Provider latency.** A subscription CLI run may take tens of seconds; the first Core task
  measures it, and the 120-second limit and Cancel bound the wait.
- **A plausible misreading.** The reader's check, the "Read as" line and Apply-only-by-the-operator
  are the guard; learning rule 4 keeps a misread phrase from generalising silently, and Remove
  undoes it.

## 9. Amendment 2026-10-27: Grok, offered only while available

**Operator:** "grok should be an option if available", then "add Grok to the Mission 14 selector,
shown only when Core says it's available". The build had narrowed decision 3's Codex/Claude/Grok
to Claude and Codex; this restores Grok and applies one rule to all three.

- **Core.** `GET /api/core/products/{product}/reasoning/providers`, behind the same product key,
  answers `{"providers": [{"provider": "CLAUDE" | "CODEX" | "GROK", "available": bool}]}`.
  Available means Core's routing would assign the product's reading to that provider right now: the
  reading's own work item and requirements (shared helpers in `product_reasoning.py`, so the check
  and a reading cannot drift) through `Routing.evaluate`, which `create` reuses and which records
  nothing. A reading itself is unchanged: an unavailable provider is still refused, never
  substituted.
- **Worker.** GROK is accepted in read requests and as the remembered `reader_provider`.
  `GET /aegis/api/phrases/providers` gives each provider's id, name and availability; when Core
  cannot say (no key issued, Core not answering) none is available and `message` says why.
- **Builder.** The selector (`#reader-provider`) lists only the available providers, fetched on load
  and whenever it gets focus. The remembered provider is shown when offered, else the first offered
  (the remembered choice is not overwritten until the operator picks). With none offered it shows
  "none available" (`#reader-provider-none`, Core's reason as its title) and Recheck
  (`#reader-provider-recheck`). A Grok reading reads "Read by Grok · model · tokens".
- **Grok's availability** depends on its provider Test passing: it was failing because the
  compatibility check allowed 1,024 output tokens and grok-4.7 answers with 1,028–1,937; that budget
  fix is a separate Core change (branch `core/grok-test-budget`).
- **Acceptance.** Item 101 (selector set to Codex, remembered across a reload) needs Codex
  available when the walk runs; a Grok item belongs in the walk once Grok is routable.
