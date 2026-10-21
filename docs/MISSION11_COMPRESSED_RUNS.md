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

## Deferred and noted for the review

- Converting the 509 existing plain runs (1.04 GB → about 0.2 GB) is not done (decision 2).
- A save of a ten-year 1m run takes about 0.8 s longer than a plain save.
