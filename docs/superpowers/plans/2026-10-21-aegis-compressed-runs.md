# Aegis Mission 11: compressed saved documents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every document the Aegis run repository saves is written as `<id>.json.gz` (gzip level 6), every reader finds either form, and nothing else about saved results changes.

**Architecture:** One file holds the change: `app/products/aegis/runs.py`. Its `_save` writes the compressed document atomically and removes a plain predecessor. A module function `document_path` finds a document in either form, and every getter, listing, trash, restore, heal, erase and delete path uses it. The acceptance gains a helper that reads either form and two items.

**Tech Stack:** Python 3.12 standard library `gzip`/`json`, pytest under `TRIAD_PYTEST_SCOPE=aegis`, Playwright acceptance (`tests/products/aegis/browser_workstation.py`).

**Spec:** `docs/superpowers/specs/2026-10-21-aegis-compressed-runs-design.md` (d2efa69)

## Global Constraints

- gzip `compresslevel=6`, `mtime=0`; the document's name is `<id>.json.gz`; readers look for `<id>.json.gz` first, then `<id>.json`.
- The bytes compressed are exactly today's `json.dumps(payload, sort_keys=True, allow_nan=False)` encoded UTF-8 (the C encoder; no streaming `json.dump`).
- Plain: `<id>.summary.json` sidecars, `trash.json`, `library/annotations.json`, `preferences.json`, experiment reports, study window records, every Parquet file.
- Existing plain documents are never converted, except that a save of that document replaces it with the compressed form.
- No hash, envelope field, API response or summary changes. No new package.
- Nothing under `app/trading_core`, `app/platform_host` or `app/products/triad` changes; Exchange CLOSED.
- Lint only through the scope script; tests only with `TRIAD_PYTEST_SCOPE=aegis` on `.venv-aegis`.

## Review Focus

1. **Both forms present** (a crash between writing `<id>.json.gz` and removing `<id>.json`): the compressed one is read, the item is listed once, and a delete moves both pieces. Task 1 `test_both_forms_read_the_compressed_one`.
2. **An item trashed in plain form before the mission and restored after it, and a compressed one trashed and restored:** each keeps its form and its hash. Task 1 `test_trash_and_restore_keep_each_form`.
3. **A corrupt `.json.gz`:** it reads as a torn file (`ValueError`), and a listing without its sidecar skips it rather than failing. Task 1 `test_a_corrupt_compressed_document_reads_as_torn`.
4. **A document saved many times** (an experiment's progress, a pooled optimization's time-budgeted saves): exactly one document file remains, compressed. Task 1 `test_saving_again_leaves_one_compressed_document`.
5. **The acceptance reading files by name** (items 79, 82, 83): they read either form. Task 2 `run_file`/`document_json` and the trial of items 79–88.

---

### Task 1: Compressed documents in the run repository

**Files:**
- Modify: `app/products/aegis/runs.py`: `_save`, `_read`, `_get`, `_list`, `_item_paths`, `_stranded`, `move_to_trash`, `restore_from_trash`, `heal_trash`, `list_trash`, `read_trashed`, `erase_from_trash`, `delete_experiment`, `delete_study`, `delete_strategy`.
- Test: `tests/test_aegis_runs.py` (new tests). Existing tests that open documents by their `.json` name move to `document_path`: `tests/test_aegis_runs.py:34`, `tests/test_aegis_library.py:529,550,561`, `tests/test_aegis_strategies.py:118`, `tests/test_aegis_api.py:1114`.

**Interfaces:**
- Produces:
  - `runs.COMPRESS_LEVEL = 6`;
  - `runs.document_path(folder: Path, identifier: str) -> Path | None`: `<id>.json.gz` if it is a file, else `<id>.json` if it is a file, else None;
  - `JsonRunRepository._read(path)` decompresses when the name ends in `.gz`; a corrupt gzip stream raises `ValueError`.

- [ ] **Step 1: Write the failing tests** in `tests/test_aegis_runs.py`:
  - `test_a_saved_document_is_compressed_and_reads_back_equal`:
    - `save_run(env)` leaves `runs/<id>.json.gz` and no `runs/<id>.json`;
    - `gzip.decompress(file) == json.dumps(env, sort_keys=True, allow_nan=False).encode()`;
    - bytes 4–8 of the file are zero (`mtime=0`);
    - `get_run` equals `env`, and the sidecar is plain JSON.
  - `test_a_plain_document_still_reads`: a hand-written `runs/old.json` with no sidecar is served by `get_run` and listed by `list_runs`.
  - `test_saving_again_leaves_one_compressed_document` (Review Focus 4): over a plain `x.json`, `save_experiment` three times leaves only `experiments/x.json.gz`.
  - `test_both_forms_read_the_compressed_one` (Review Focus 1):
    - `x.json` (old content) and `x.json.gz` (new content) side by side: `get_run` returns the new content;
    - `list_runs` lists `x` once;
    - `move_to_trash` moves both, and `restore_from_trash` brings both back.
  - `test_a_corrupt_compressed_document_reads_as_torn` (Review Focus 3): garbage bytes in `y.json.gz` make `get_run` raise `ValueError`, and `list_runs` without its sidecar still returns the other runs.
  - `test_trash_and_restore_keep_each_form` (Review Focus 2):
    - a compressed run and a plain run go through `move_to_trash`, `list_trash`, `read_trashed` and `restore_from_trash`; each keeps its file form and its `result_hash`;
    - a stranded compressed document heals (`heal_trash`), and `erase_from_trash` removes a compressed item;
    - restoring over a live item in either form refuses with `FileExistsError`.
  - `test_deletes_take_either_form`: `delete_experiment`, `delete_study` and `delete_strategy` remove a compressed document and a plain one; each raises `KeyError` when neither form exists.
- [ ] **Step 2: Run** `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_runs.py`. Expected: the new tests FAIL; a save still writes `<id>.json`, and `document_path`/`COMPRESS_LEVEL` are not importable.
- [ ] **Step 3: Implement** in `runs.py`:
  - **`_save`:** writes `gzip.compress(json.dumps(...).encode("utf-8"), compresslevel=COMPRESS_LEVEL, mtime=0)` to `<id>.json.gz.tmp`, swaps it in with `_retry(tmp.replace)`, then removes a plain `<id>.json` with `_retry(unlink)`. The sidecar is written afterwards, plain, as today.
  - **`_read`:** gunzips `.gz`. Map `gzip.BadGzipFile`, `EOFError` and `zlib.error` to `ValueError`.
  - **Every by-name lookup** listed under Files uses `document_path`.
  - **`_list`'s legacy pass:** covers `*.json.gz` (its identifier is the name less `.json.gz`) and counts an identifier once.
  - **`_item_paths`:** includes both forms when both exist.
  - **The clash checks** in `move_to_trash`/`restore_from_trash` count either form.
  - **Existing tests:** move the ones that open documents by name to `document_path`/`_read`.
- [ ] **Step 4: Run** the whole Aegis scope: `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider`. Expected: PASS, every hash test unchanged. Then the lint script.
- [ ] **Step 5: Commit** "Aegis runs: saved documents are compressed (gzip)".

### Task 2: Acceptance and the record

**Files:** `tests/products/aegis/browser_workstation.py` (helpers, items 79/82/83, new items 87–88, `COMPRESSED_BASE` = this plan's commit), `docs/MISSION11_COMPRESSED_RUNS.md`, `docs/evidence/aegis-acceptance-<stamp>.json`.

**Interfaces:**
- Consumes: Task 1's file naming (`<id>.json.gz`, plain `<id>.json` still possible).
- Produces:
  - `Acceptance.run_file(run_id)` returns the document path in either form;
  - `Acceptance.document_json(folder, identifier) -> dict` reads either form (gunzip when `.gz`).

- [ ] **Step 1: Write the items:**
  - **79:** reads the optimization through `document_json`.
  - **82:** reads item 22's run through `document_json`; "under 1 MB" applies to the file on disk, and the uncompressed size is reported.
  - **83:** reports the file size on disk.
  - **87:**
    - item 22's run file is `.json.gz` and at least 3× smaller than its JSON, with hash `cdbc9abd2238…`;
    - a run saved before the mission (plain, `created_at` before `MISSION11_STARTED`) still opens in the Library;
    - a fresh compressed run of the identical request goes delete → Recently deleted → restore through the Library page and keeps its form and its hash.
  - **88:** governance unchanged since `COMPRESSED_BASE`, and items 1–86 still pass.
- [ ] **Step 2: Restart the worker detached** (WMI), trial items 79–88 alone against the store (as for Mission 10), then the full walk. Expected: 88/88, no page errors. Copy the evidence.
- [ ] **Step 3: Measure** the saved sizes of item 22's run and the ten-year 1m run from the walk (file on disk vs uncompressed JSON) and their save times. Run `tools\verify.ps1` on the branch (it stops at the main-branch check by design), then vitest and the build.
- [ ] **Step 4: Write `docs/MISSION11_COMPRESSED_RUNS.md`** (intent, decisions, measurements before/after, acceptance, verification, rulings) and commit "Aegis: Mission 11 acceptance and the record".
