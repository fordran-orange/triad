# Mission 11: compressed saved documents (2026-10-21)

Branch `aegis/compressed-runs`, cut from `main` at `caf1caa` (not merged; merging stays the
operator's answer). Design: `docs/superpowers/specs/2026-10-21-aegis-compressed-runs-design.md`
(`d2efa69`). Plan: `docs/superpowers/plans/2026-10-21-aegis-compressed-runs.md` (`caf1caa`, two
tasks). `COMPRESSED_BASE` = `caf1caa`. Built natively on Opus 5.5 ("native").

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 88); no package or environment change. Exchange CLOSED; Triad suspended;
`DailySchedule` `c99fa831` disabled.

## Intent (operator, 2026-10-20/21)

- "it looks like a nas drive is going to be needed soon", after Mission 10 made ten-year 1-minute
  runs possible (38–42 MB each).
- "how many planned mission left" → the backlog, compressing saved runs recommended first → "do it".
- Decisions on the design: "yes" to the four recommendations:
  1. every document the run repository saves is compressed;
  2. existing documents are not converted;
  3. gzip level 6;
  4. files are named `<id>.json.gz`.

## What was built

| Commit | Task | What |
|---|---|---|
| `d2efa69`, `caf1caa` | — | The design and the plan (on `main`) |
| `9fe40fb` | 1 | Every document the run repository saves (runs, optimizations, walk-forwards, strategies, experiments, studies) is today's JSON, gzip-compressed at level 6 with `mtime` 0, swapped in whole as `<id>.json.gz`; a plain predecessor is removed only after, so a crash in between leaves both and the compressed one wins. `document_path` finds a document in either form, and the getters, the listing, the trash moves, restore, heal, erase and the three deletes all use it; a corrupt `.gz` reads as a torn file. Sidecars, `trash.json` and every other small file stay plain |
| `505c4a7` | 2 | Found by the acceptance trial: `PUT /preferences` answered 500 when Windows refused to swap `preferences.json` while another request read it (and a read at that moment fell back to "every"); the swap and the read now retry like the run store, each writer with its own temporary file |
| `f43bee3` | 2 | Acceptance: items 79, 82 and 83 read documents in either form; items 87–88; item 85 reports its first error and always restores "Save every backtest" |
| (the record commit) | 2 | This record and the evidence |

## Measured (QQQ, the operator's store)

| What | Plain JSON | On disk now | Save / open |
|---|---|---|---|
| Item 22's run (1h, two years) | 553,521 bytes | 78,014 bytes (7.1×) | — |
| A ten-year 1m run (947,519 bars, 72,498 markers) | 38.35 MB | 5.34 MB (7.2×) | 1.37 s to save (0.55 s plain), 0.48 s to open |
| The store after the walk | 509 plain documents, 1.04 GB, untouched | 36 compressed, 24.8 MB | — |

The 509 runs saved before this mission stay plain until saved again (decision 2); converting them
would bring the store from 1.04 GB to about 0.2 GB and is a separate, explicit step.

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261021T114240Z.json`: **88/88 PASS, no page errors**, 811 s.
Items 1–86 are the Mission 3–10 walk, passing (79, 82 and 83 now read either form):

- **87:** item 22's run is `.json.gz`, 78,014 bytes against 553,521 as JSON (7.1×), hash
  `cdbc9abd2238…`. A plain run from before the mission (`21930eba`, 2026-10-20 17:45) opens in the
  Library. A fresh compressed run of the same request was deleted to Recently deleted, where it
  stayed compressed, and restored through the page with its hash.
- **88:** governance unchanged since `caf1caa`; items 1–86 pass.

Before the full walk, items 79 and 82–88 ran alone against the store three times:
- 5/8 first: item 85 met the preferences race above, and 87–88 failed because it left the worker in
  "kept";
- then 3/3 for items 83–85, and 8/8 with the fix.

## Verification

- `tools\verify.ps1` on the branch (2026-10-21, after the walk): lint and format passed; inventory
  core 557, triad 1,058, aegis 447; all three scopes green (core 386 / 171 skipped; triad 634 / 424
  with 209 subtests; aegis 446 / 1). It stopped at the "Wrong Git branch" check, by design.
- UI: 17 vitest files, 115 cases (unchanged); the build succeeds.

## Rulings

1. Task 1: two of the new tests pass before the implementation by design: one pins today's plain
   reading, and the deletes test only bites once saves compress.
2. Task 2: the preferences race is a Mission 10 bug outside this plan. It was fixed in scope because
   both the acceptance and an operator switching the mode during a backtest meet it. Item 85 always
   restores "every". Cost if wrong: none; the fix only adds retries.

## Milestone QA and whole-branch review (Fable 5.1, read-only, at `eb6bedf`)

The operator chose Fable 5.1 for both.

**QA: PASS_WITH_OBSERVATIONS, no defect.** Recomputed independently:
- A new save matches byte for byte (re-compressing the inflated text reproduces the file) and keeps
  its hash (`cdbc9abd2238…`). Sizes: 7.1× for item 22's run, 7.5× for a ten-year 1m run.
- Every route over plain documents works: the API, the Library (list, open, equity, compare plain
  against compressed), Load from the drawer, and the plain-only optimization, walk-forward, strategy,
  experiment and study.
- A temporary repository seeded with real documents passed 76 of 76 checks (both forms, corrupt
  files, trash, restore, heal, erase, deletes, clashes).
- A 40-second hammer of the preference switch (918 writes, 1,552 reads, 215 backtests) answered no
  error and no wrong mode.
- Aegis scope 446/1, vitest 115, `tsc` clean, governance unchanged.

The QA saved runs `3b5359d6` and `bba0e913` and a strategy "QA M11 compressed v2"
(`qa-m11-compressed`) in the store, and deleted nothing.

**Review: "Yes", 0 Critical, 0 Important, 6 Minor.** Re-graded by their effect on the operator, whose
store holds paused experiments saved before this mission: minors 1 and 2 became one Important
finding. Resuming such an experiment makes its first save replace the plain document. A held or
already-removed plain file failed the whole save (the job reads "failed"), and a read racing that
save answered 500.

## Fix pass (the operator: "go ahead with the fixes")

| Commit | Fix |
|---|---|
| `f80b455` | Removing the superseded plain document is best effort: logged and left for the next save, never failing the save. A read that loses its plain file to a concurrent first save looks again and reads the compressed one. Tests `test_the_first_save_over_a_plain_document_never_fails_on_its_predecessor` and `test_a_read_racing_the_first_save_finds_the_new_document` failed first. |

After the fix: Aegis scope 448 passed, 1 skipped. The walk again:
`docs/evidence/aegis-acceptance-20261021T163458Z.json`, **88/88 PASS, no page errors**, 852 s.
`tools\verify.ps1` on the branch after the fix: lint and format passed; inventory core 557, triad
1,058, aegis 449; all three scopes green (core 386 / 171 skipped; triad 634 / 424 with 209
subtests; aegis 448 / 1); it stopped at the main-branch check, by design.

## Deferred minors

- Two concurrent saves of one document share `<id>.json.gz.tmp` (as `<id>.json.tmp` did before).
- `preferences.py` imports the private `_retry` from `runs.py`.
- A comment in `runs.py` ("one JSON file per document under strategies/") predates the compressed
  form.
- Item 85 loses its first error if restoring the mode itself fails.
- With two writers at once, PUT /preferences answers the store's state, which the other may have
  changed.
- A re-saved id whose old copy is in Recently deleted keeps its sidecar in the trash folder after a
  restore, and the next delete refuses (Mission 9 behaviour, unchanged).
- GET /runs/{id} of a ten-year 1m run takes about 3.7 s, almost all of it serializing the response.

## Deferred and noted for the review

- Converting the 509 existing plain runs (1.04 GB → about 0.2 GB) is not done (decision 2).
- A save of a ten-year 1m run takes about 0.8 s longer than a plain save.

## Merged (2026-10-21)

The operator answered "merge yes": `main` fast-forwarded from `caf1caa` to `b7fdc9f` (Mission 11's
seven commits on top of its spec and plan). `tools\verify.ps1` on `main` exited 0: lint and format
passed; inventory core 557, triad 1,058, aegis 449; core 386 passed / 171 skipped, triad 634 / 424
with 209 subtests, aegis 448 / 1; "all three scopes green".
