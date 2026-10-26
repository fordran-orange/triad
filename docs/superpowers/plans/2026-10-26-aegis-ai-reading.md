# Aegis AI Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the phrase reader refuses a sentence, a model through a new read-only Core route rewrites it into the reader's language; the reader checks it; applying it teaches the reader the substitutions.

**Architecture:** Core gains `POST /api/core/products/{product}/reasoning`, behind a per-product key, running the chat's governed provider path with the product as owner. The Aegis worker reads with the phrase reader (learned phrases applied first), asks Core only on a refusal, validates the rewrite with the same reader, and keeps examples and learned phrases as its own data. The builder adds a provider selector, an AI-reading state, the rewrite and provenance in the preview, and a Learned phrases list.

**Tech Stack:** Python 3.12, FastAPI, Pydantic (Core `.venv`, Aegis `.venv-aegis`), Postgres for Core integration tests; React 18, TypeScript, vitest; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-26-aegis-ai-reading-design.md`

## Global Constraints

- Core changes only in: `app/trading_core/settings.py` (the key setting), `app/trading_core/product_reasoning.py` (new), `app/trading_core/product_reasoning_api.py` (new), `app/trading_core/api.py` (one `include_router` line), `tools/issue_product_key.ps1` (new), and Core tests. No change to Core chat, routing policy, provider configuration, Ollama or the ledger's shape; no paid API fallback. This list is `MISSION14_CORE_FILES` in the walk.
- Core is credentials and a shared contract: Core tests run in every Core task (`TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <paths>`, written `CORE`; the full path with `TRIAD_INTEGRATION=1`); independent milestone QA and a whole-branch review are required before merge.
- Never print, log or commit a key or secret. The issuing script runs only after the operator says yes.
- Values: instructions ≤ 20,000 chars; input 1–2,000 chars; output schema ≤ 8,000 chars of JSON; one reading at a time per product; 120 s limit; 20 examples in the instructions; key ≥ 32 chars (the script writes 48); default provider `CLAUDE`.
- Exact error reasons: `provider_failed`, `malformed_answer`; HTTP 401 / 403 / 409 / 422 / 502 / 503 / 504 as spec §4.1.
- Aegis tests: `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider <paths>` (`PYTEST`); UI `npm --prefix app/products/aegis/ui test` and `run build`; lint `bash "$TEMP/claude/C--Triad/022ed4b7-ef3f-4cba-b67b-3929564904e2/scratchpad/lint_aegis.sh" fix` for Aegis files and `.venv/Scripts/python.exe -m ruff check` / `format` on the named Core files only (never a bare ruff).
- Commits: message by the Write tool, `git -c core.hooksPath=NUL commit -F`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Every sentence of `tests/test_aegis_phrases.py`'s Mission 13 table reads exactly as before. Exchange CLOSED; the save preference stays "every".

## Review Focus

1. The product key presented on an operator route (`/api/core/conversations`, `/api/core/intake`): refused, never accepted as operator authority. Test in Task 1.
2. A model answer that claims an action, a file, a command or a test, or a run reported BLOCKED: `provider_failed`, nothing returned to the product. Test in Task 2.
3. A learned `from` that is part of a longer word ("cross" inside "crosses") or overlaps another learned phrase: whole words only, longest first. Test in Task 3.
4. Cancel, then a new sentence while Core is still finishing the first reading: Core answers 409; the builder says a reading is still finishing and keeps the text. Test in Task 4.
5. An AI reading with a non-empty `unsupported`: shown in the preview, and Apply applies only what was read. Test in Task 5.

---

### Task 1: The Core route, its key and its refusals

**Files:**
- Modify: `app/trading_core/settings.py` (`aegis_product_key: SecretStr = SecretStr("")`)
- Create: `app/trading_core/product_reasoning_api.py`
- Modify: `app/trading_core/api.py` (include the router beside the conversation router)
- Create: `tools/issue_product_key.ps1`
- Test: create `tests/test_core_product_reasoning_api.py` (`pytestmark = pytest.mark.core`)

**Interfaces:**
- Produces: `PRODUCT_KEYS = {"aegis": "aegis_product_key"}`; `require_product_key(product: str, authorization: str, engine) -> str` (the product; HTTP 401 / 403 / 503); `ReasoningRequest(provider: Literal["CODEX","CLAUDE","GROK"], instructions: str [≤20,000], input: str [1–2,000], output_schema: dict [≤8,000 chars JSON])`; `ReasoningFailed(reason: str, status: int)`; the route `POST /api/core/products/{product}/reasoning` calling a dependency `reasoner()` that returns an object with `reason(product: str, request: ReasoningRequest) -> dict` (Task 2 supplies the real one).

- [ ] **Step 1: Write the failing tests** (no database: the `reasoner` dependency is overridden with a fake, the engine's settings with a key of 48 `k`s): `test_a_missing_or_wrong_key_is_401`; `test_another_products_key_is_403` (a second key entry added to `PRODUCT_KEYS` for the test); `test_no_key_issued_is_503`; `test_the_product_key_opens_no_operator_route` (Review Focus 1: `GET /api/core/conversations` and `/api/core/intake` with the product key → 401); `test_requests_out_of_bounds_are_422` (instructions 20,001 chars, input 0 and 2,001, schema over 8,000 chars, unknown provider); `test_a_good_request_returns_the_reasoners_answer`; `test_reasoning_failures_keep_their_status` (`ReasoningFailed("provider_failed", 502)`, `("malformed_answer", 502)`, 409, 504 → those statuses with `{"detail": {"reason": ...}}`).
- [ ] **Step 2: Run** `CORE tests/test_core_product_reasoning_api.py`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** the setting, the key check (constant-time compare; a key shorter than 32 means not issued), the request model and the route.
- [ ] **Step 4: Write `tools/issue_product_key.ps1 -Product aegis [-Rotate]`:** writes `AEGIS_PRODUCT_KEY=<48 random URL-safe chars>` into `.env` when absent (replaces only with `-Rotate`), prints only "issued" / "already issued", never the value. Do not run it.
- [ ] **Step 5: Run** the Step 2 command, then `CORE tests/test_core_conversation.py tests/test_core_api*.py` (whatever Core API tests exist, by `ls tests/test_core_*`). Expected: PASS. Lint the Core files. Commit "Mission 14 Task 1: the Core route for product readings and its key".

### Task 2: The governed run behind the route

**Files:**
- Create: `app/trading_core/product_reasoning.py`
- Modify: `app/trading_core/product_reasoning_api.py` (the real `reasoner`)
- Test: create `tests/test_core_product_reasoning.py` (`pytestmark = [pytest.mark.core, pytest.mark.integration]`, the `engine` fixture of `test_day3_integration`, `Runtime.execute` monkeypatched as `test_core_conversation` does)

**Interfaces:**
- Consumes: Task 1's `ReasoningRequest`, `ReasoningFailed`.
- Produces: `ProductReasoning(records: Records).reason(product: str, request: ReasoningRequest) -> {"output": dict, "provenance": {provider, model, transport, billing_source, input_tokens, output_tokens, run_id, work_item_id}}`; `check_shape(value, schema) -> bool` (object types, required keys, string / number / array / object property types).

- [ ] **Step 1: Write the failing tests:** `test_a_reading_returns_the_json_and_its_provenance` (the fake run returns `summary='{"rewrite": "buy when …", "substitutions": [], "unsupported": ""}'`; the work item is COMPLETED and owned by the product; usage recorded); `test_a_failed_or_acting_run_is_provider_failed` (Review Focus 2: an exception, status BLOCKED, and a result with `files_changed`, `actions_taken`, `commands_executed`, `tests_run` or a proposal each → `provider_failed`; the work item FAILED; no other agent asked); `test_a_malformed_answer_is_refused` (not JSON; missing `rewrite`; `substitutions` not a list); `test_one_reading_at_a_time` (a held lease → 409); `test_the_request_asks_for_no_tools` (the captured `AgentRunRequest` has no tools, no paths, read permission only, the product's provider as `agent_id`); `test_check_shape` (unit, no database).
- [ ] **Step 2: Run** `TRIAD_INTEGRATION=1 CORE tests/test_core_product_reasoning.py`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** after `Conversations.reply`'s pattern: a store lease `core-product-reasoning-<product>`; `WorkItem(owner=product, work_type="review", authority_tier=0, allowed_tools=(), allowed_paths=(), execution_permissions=("read",), review_required=False, …)`; `Requirements(role="REVIEW", capabilities=("structured_output",), preferred_agent=provider, billing_sources=("SUBSCRIPTION",), reason="Product selected the provider; no silent substitution")`; an objective that puts only the JSON answer in `summary`; the 120 s limit around `runtime.execute` (a worker thread with a timeout → 504; the run is recorded when it ends); completion or failure recorded on the work item as the chat does.
- [ ] **Step 4: Run** the Step 2 command and Task 1's tests. Expected: PASS.
- [ ] **Step 5: Measure, with the operator's yes.** Ask the operator to approve running `tools/issue_product_key.ps1 -Product aegis`; run it; the gateway builds its settings per request (`service()` makes an `Orchestrator` each time), so it should see the key at once; if it does not, ask the operator to restart the gateway; post one reading with the key from a scratch script to `http://127.0.0.1:8000/api/core/products/aegis/reasoning` with provider `CLAUDE`, and record the seconds and the provenance (never the key). Expected: a 200 with provenance; the seconds written to the ledger.
- [ ] **Step 6: Lint, commit** "Mission 14 Task 2: product readings run on Core's governed provider path".

### Task 3: Learned phrases in the phrase reader

**Files:**
- Modify: `app/products/aegis/phrases.py` (exported vocabulary; `grammar_text()`; `read(text, strategy, learned=None)`)
- Create: `app/products/aegis/learned.py`
- Test: `tests/test_aegis_phrases.py`, create `tests/test_aegis_learned.py`

**Interfaces:**
- Produces: `phrases.KNOWN_WORDS: frozenset[str]` (every word the reader knows); `phrases.grammar_text() -> str` (built from `OPENERS`, `KIND_WORDS`, `OUTPUT_WORDS`, `PRICE_WORDS`, the comparisons and the level phrases); `phrases.read(text, strategy, learned: list[tuple[str, str]] | None = None) -> Reading` (learned applied first; unread spans on the original text); `learned.LearnedPhrases(root: Path)` with `list() -> list[dict]`, `pairs() -> list[tuple[str, str]]`, `examples(limit=20) -> list[dict]`, `learn(text: str, rewrite: str, substitutions: list[dict], provenance: dict, strategy: StrategySpec) -> list[dict]` (the entries kept), `remove(identifier: str) -> None`; files `data/aegis/phrases/learned.json` and `examples.jsonl`.

- [ ] **Step 1: Write the failing tests.** In `test_aegis_learned.py`: `test_crosses_up_is_learned`; `test_a_pronoun_mapping_is_not_learned` ("it" → "9 ema"); `test_a_known_word_is_never_learned_over` ("close" → "open"); `test_a_substitution_absent_from_the_text_is_dropped`; `test_the_kept_set_must_reproduce_the_reading` (a substitution that changes the sides is dropped); `test_a_newer_meaning_replaces_the_older`; `test_remove`; `test_every_applied_reading_is_kept_as_an_example` (also when nothing is learned); `test_examples_are_the_newest_twenty`. In `test_aegis_phrases.py`: `test_learned_phrases_are_read_before_the_grammar` ("buy when 9 ema crosses up 30 sma" with `[("crosses up", "crosses above")]`); `test_learned_phrases_are_whole_words_longest_first` (Review Focus 3: "cross" never matches inside "crosses"; "crosses back down" wins over "crosses back"); `test_unread_spans_point_at_the_original_words`; `test_grammar_text_names_every_kind_and_opener`.
- [ ] **Step 2: Run** `PYTEST tests/test_aegis_learned.py tests/test_aegis_phrases.py`. Expected: FAIL (no module / no parameter).
- [ ] **Step 3: Implement.** Substitution on the lowercased text with `\b`-bounded matches, longest `from` first, non-overlapping, building an offset map from the rewritten text back to the original for `Unread` spans. `learn` applies spec §4.3's four rules in order, then writes both files atomically (tmp + replace, as `preferences.py` does).
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS, with the Mission 13 table unchanged. LINT, commit "Mission 14 Task 3: the phrase reader learns phrases".

### Task 4: AI reading in the worker

**Files:**
- Create: `app/products/aegis/core_client.py`, `app/products/aegis/ai_reading.py`
- Modify: `app/products/aegis/phrases.py` (`Reading` gains `read_by`, `rewrite`, `substitutions`, `unsupported`, `provenance`, all defaulted), `app/products/aegis/preferences.py` (`reader_provider`), `app/products/aegis/api.py` (the read route; `GET /phrases/learned`, `POST /phrases/learn`, `DELETE /phrases/learned/{id}`; the `get_core_reasoning` dependency)
- Test: create `tests/test_aegis_ai_reading.py`; `tests/test_aegis_api.py`; `tests/test_aegis_preferences.py`

**Interfaces:**
- Consumes: Task 1's route; Task 3's `LearnedPhrases`, `grammar_text`, `read(..., learned=)`.
- Produces: `core_client.CoreReasoning(base="http://127.0.0.1:8000", key: str)` with `reason(provider, instructions, input, output_schema) -> dict` and `CoreReadingError(status: int, reason: str)`; `ai_reading.OUTPUT_SCHEMA`; `ai_reading.instructions(strategy, examples) -> str`; `ai_reading.read_with_ai(text, strategy, provider, client, examples) -> Reading`; `Preferences.get()` adds `reader_provider`; `Preferences.set(save_runs=None, reader_provider=None)`; read route body `{"text", "strategy", "provider"?}`.

- [ ] **Step 1: Write the failing tests** (a fake client): `test_the_reader_reads_first_and_core_is_not_asked`; `test_a_refusal_goes_to_the_chosen_provider` (the instructions carry the grammar, the side's indicator ids and the examples; the answer carries `read_by: "ai"`, the rewrite, substitutions, provenance); `test_an_unreadable_rewrite_is_422_with_the_rewrite`; `test_unsupported_is_passed_on`; `test_core_errors_pass_through_with_their_reason` (`provider_failed` → 502 "Claude could not read this: …"; 503 → "AI reading is not set up"; Review Focus 4: 409 → "a reading is still finishing"); `test_the_provider_is_remembered` (preferences); `test_learn_list_and_remove_routes`; and the Mission 13 read-route test still passes.
- [ ] **Step 2: Run** `PYTEST tests/test_aegis_ai_reading.py tests/test_aegis_api.py tests/test_aegis_preferences.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** The client posts with `Authorization: Bearer <Settings().aegis_product_key>` and a 125 s timeout; an empty key raises `CoreReadingError(503, "not issued")` without a request. The route: phrases first (with `LearnedPhrases.pairs()`), then `read_with_ai` on `Unread`.
- [ ] **Step 4: Run** the Step 2 command and the whole Aegis suite. Expected: PASS. LINT, commit "Mission 14 Task 4: the worker reads with the AI when the phrase reader cannot".

### Task 5: The builder

**Files:**
- Modify: `app/products/aegis/ui/src/components/builder/PhraseBar.tsx`, `app/products/aegis/ui/src/api/client.ts`, `app/products/aegis/ui/src/builder/apply.ts` (`Reading` fields), `app/products/aegis/ui/src/styles.css`
- Create: `app/products/aegis/ui/src/components/builder/LearnedPhrases.tsx`, `app/products/aegis/ui/src/builder/reading.ts`, `app/products/aegis/ui/src/builder/reading.test.ts`

**Interfaces:**
- Consumes: Task 4's routes.
- Produces: `readingLines(reading) -> { rewrite: string | null; readBy: string; unsupported: string | null }`; `api.readText(text, strategy, provider)`, `api.learn(entry)`, `api.learned()`, `api.removeLearned(id)`, `api.setReaderProvider(p)`. Ids: `#reader-provider`, `#phrase-thinking`, `#phrase-cancel-ai`, `#phrase-rewrite`, `#phrase-read-by`, `#phrase-unsupported`, `#learned-open`, `#learned-list`, `#learned-<id>`, `#learned-remove-<id>`.

- [ ] **Step 1: Write the failing tests** (`reading.test.ts`): `readingLines` for a phrase-reader reading (no rewrite line, "read by the phrase reader"), an AI reading ("Read by Claude · <model> · <in>+<out> tokens"), and one with `unsupported` (Review Focus 5: shown; `applyReading` applies the sides as given). Run UI tests. Expected: FAIL.
- [ ] **Step 2: Implement** `readingLines`, the selector (remembered through the worker's preferences), the thinking state with Cancel (an `AbortController`), the preview lines, the learn post after an AI reading is applied, and the Learned phrases list with Remove.
- [ ] **Step 3: Run** UI tests and build; restart the Aegis worker; in headless Chromium type a sentence the reader refuses and check the thinking state, the preview lines and the learned entry, with the key issued in Task 2. Expected: PASS; the reading applied; the entry listed.
- [ ] **Step 4: Commit** "Mission 14 Task 5: the builder reads with the AI and lists learned phrases".

### Task 6: Acceptance and the record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (`MISSION14_CORE_FILES`, `AI_READING_BASE`; items 46, 60, 76, 81, 86, 88, 90 and 97 accept exactly `MISSION14_CORE_FILES` as the Core change; items 98–102)
- Create: `docs/MISSION14_AI_READING.md`; `docs/evidence/aegis-acceptance-<stamp>.json`

**Interfaces:**
- Consumes: every id above.

- [ ] **Step 1: Write items 98–102** in `ai_reading()`, after item 97: 98 a real Claude reading of "buy when 9 ema crosses up 30 sma, exit when it crosses back down" (thinking state, rewrite and read-by lines, Apply, the sides); 99 "crosses up" listed as learned, and "buy when 9 ema crosses up 30 sma" then read by the phrase reader with no provider (`read_by == "phrases"`); 100 Remove it, and the same sentence goes to the provider again (stopped with Cancel); 101 the selector set to Codex is remembered across a reload, then set back to Claude; 102 governance: Core changed since `AI_READING_BASE` only in `MISSION14_CORE_FILES`, nothing under `app/platform_host` or `app/products/triad`, exchange CLOSED, DailySchedule disabled, items 1–101 PASS.
- [ ] **Step 2: Update the earlier governance items** to allow exactly `MISSION14_CORE_FILES`.
- [ ] **Step 3: Trial** items 98–102 alone, then the full walk. Expected: 102/102, no page errors. Copy the evidence.
- [ ] **Step 4: `tools\verify.ps1`** on the branch, plus `TRIAD_INTEGRATION=1 CORE tests/test_core_product_reasoning.py`, the UI tests and build. Expected: green; stops at "Wrong Git branch" by design.
- [ ] **Step 5: Write the record** (intent, decisions, the probe, what was built, the measured reading time, rulings, verification) and commit "Aegis: Mission 14 acceptance and the record".
