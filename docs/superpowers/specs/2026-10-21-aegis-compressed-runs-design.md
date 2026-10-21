# Aegis Mission 11: compressed saved documents — design (2026-10-21)

## 1. Intent

The operator, after Mission 10 made ten-year 1-minute runs possible (38–42 MB each): "it looks like a
NAS drive is going to be needed soon". Before buying hardware, the saved results should take much
less disk, with nothing else about them changing. Asked how many missions remain and offered this as
the recommended next one: "do it".

Success: a document saved from now on is several times smaller on disk; every reader (the Library,
compare, Load, the Runs drawer, trash and restore, the acceptance) works unchanged; result hashes are
untouched (they are computed from the result, never from file bytes); documents saved before this
mission still read.

## 2. Decisions (the operator: "yes" to the four recommendations, 2026-10-21)

1. **Scope:** every document the run repository saves through its one write path — runs,
   optimizations, walk-forwards, strategies, experiments and studies — is written compressed. The
   summary sidecars (`<id>.summary.json`, read on every listing), `trash.json`, the Library's
   annotations, `preferences.json`, experiment reports, study window records and every Parquet file
   stay as they are.
2. **Existing files are not converted.** Plain `<id>.json` documents keep reading, forever. A
   document that is saved again (an experiment advancing, a strategy edited) is written compressed and
   its plain predecessor removed, exactly as any save replaces the previous version today; a document
   nobody saves again stays as it is. Converting the existing 1.04 GB would be a migration of retained
   data: only on a later, explicit request, as its own reviewed step.
3. **gzip, level 6** (Python's standard library; no new package). `mtime=0`, so the same document
   always compresses to the same bytes.
4. **Naming:** `<id>.json.gz`. A reader looks for `<id>.json.gz` first, then `<id>.json`.

## 3. Measurements (the operator's runs, 2026-10-21)

| Run | Plain | gzip 1 | gzip 6 | Write / read at 6 |
|---|---|---|---|---|
| typical (1h, two years) | 1.43 MB | 0.37 MB | 0.33 MB (4.3×) | 58 ms / 6 ms |
| ten-year 15m (format 1) | 25.75 MB | 6.05 MB | 5.30 MB (4.9×) | 1.0 s / 0.08 s |
| ten-year 1m (format 2) | 38.35 MB | 6.80 MB | 5.34 MB (7.2×) | 0.94 s / 0.11 s |
| largest (161,754 1m bars, format 1) | 66.66 MB | 15.06 MB | 13.24 MB (5.0×) | 2.4 s / 0.25 s |

509 saved runs hold 1.04 GB today; compressed they would hold about 0.2 GB.

## 4. Design

### 4.1 Writing

`JsonRunRepository._save` serializes the document exactly as today (`json.dumps(payload,
sort_keys=True, allow_nan=False)`), compresses the UTF-8 bytes with `gzip.compress(…,
compresslevel=6, mtime=0)`, writes them to `<id>.json.gz.tmp` and swaps the temporary file into place
with the existing retrying `replace`. Only then, if a plain `<id>.json` exists, it is removed (a
crash in between leaves both; the compressed one is the newer and wins every read, and the next save
removes the plain one). The sidecar is written after the document, plain, as today.

The C encoder stays in use (`json.dumps`, not a streaming `json.dump`, whose pure-Python encoder is
several times slower on a ten-year run); the transient cost is the JSON text, its bytes and the
compressed bytes, about twice a run's file size, well below the run's own 111 MB in memory.

### 4.2 Reading and finding a document

One helper finds a document in a folder: `<id>.json.gz` if it exists, else `<id>.json`, else none.
Every place that finds a document by name uses it: the getters (`_get`, `read_document`), the listing
of documents without a sidecar (each document counted once, whichever form it has), the trash
(`_item_paths`, `_stranded`, `move_to_trash`, `restore_from_trash`, `heal_trash`, `list_trash`,
`read_trashed`, `erase_from_trash`), and the deletes of experiments, studies and strategies. Reading a
`.gz` document decompresses and parses it; a corrupt one raises `ValueError` like a torn plain file.

### 4.3 Moving between live and Recently deleted

An item's pieces move together, whichever form its document has; a restore puts back the document it
finds. A clash check ("an item with id … exists") counts either form on the live side.

### 4.4 Not changed

The hashes (`result_hash`, `strategy_hash`, data hashes), the envelopes' content and fields, the API
(responses are JSON as before), the summaries, the Library index and its cached blocks, the slim-run
format of Mission 10, and where the store lives.

## 5. Acceptance

- Items 79, 82 and 83 read saved files through one helper that handles both forms (item 82's
  "under 1 MB" applies to the file on disk; its uncompressed size is also reported).
- New items:
  - **87:** a run saved now is `<id>.json.gz`, several times smaller than its JSON, reads back with
    its recorded hash (item 22's run keeps `cdbc9abd2238…`), and a run saved before the mission
    (plain) still opens in the Library; delete → Recently deleted → restore of a compressed run keeps
    its hash and its form.
  - **88:** governance unchanged since this mission's plan, and items 1–86 still pass.

## 6. Verification

- Tests first:
  - a document saved and read back is equal, its file is `.json.gz` and decompresses to the exact
    JSON a plain save wrote;
  - a plain document still reads;
  - saving again over a plain document leaves only the compressed one;
  - both forms present: the compressed one is read and listed once;
  - trash, restore, heal, erase and the three deletes with compressed documents;
  - a corrupt `.gz` reads as a torn file;
  - the listing's legacy path summarizes a compressed document without a sidecar.
- The sizes above re-measured on a fresh ten-year 1m run and on item 22's run; save and open times
  recorded.
- Milestone QA and a whole-branch review at the end, as for every mission (a change to how retained
  documents are written).

## 7. Out of scope

Converting existing documents; compressing sidecars, annotations, preferences, reports, study window
records or Parquet; changing any hash; moving the store (a NAS); pruning old runs.
