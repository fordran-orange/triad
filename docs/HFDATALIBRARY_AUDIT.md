# HFDataLibrary local archive audit — 2026-09-19

The three archives were successfully decoded and retained, but are **not suitable
for publication under Core's current canonical contract**. All three have
Core-owned `DatasetManifest` records with `quality_status=FAIL`. No canonical
Parquet was created, no data was repaired, and no execution settings changed.

## Files and safe decompression

Only SPY, QQQ and ITOT archive names were searched. The relevant files are at
`C:\Triad`; all three extracted files already existed. Each gzip was decompressed
to a bounded temporary file, read through EOF to validate gzip integrity, and
SHA-256 compared with the existing extraction. All matched exactly. Existing
files were reused without overwriting. All six originals remain unchanged.

| Source under C:\Triad | Destination under C:\Triad | Compressed bytes | Uncompressed bytes | Result |
|---|---|---:|---:|---|
| SPY_1m_10y.parquet.gz | SPY_1m_10y.parquet | 20,601,644 | 26,345,945 | Existing file identical; no errors |
| QQQ_1m_10y.parquet.gz | QQQ_1m_10y.parquet | 20,377,960 | 25,818,150 | Existing file identical; no errors |
| ITOT_1m_10y.parquet.gz | ITOT_1m_10y.parquet | 9,475,607 | 12,130,203 | Existing file identical; no errors |

Independent copies of the compressed and extracted raw files, extraction logs,
all hashes, per-day coverage, every missing minute, anomaly CSVs, and detailed
results are retained in:

`C:\Triad\data\raw\HFDataLibrary\20260919T233952760505Z\`

The machine-readable entry point is `report.json`. Empty anomaly CSVs mean the
OHLC/null/duplicate/negative-value checks found no affected rows, not that there
are no coverage or session issues. Daily CSVs include these session differences.

## Format and interpretation

All three files are Parquet with the same seven columns:

| Column | Arrow type | Interpretation |
|---|---|---|
| datetime | timestamp[ns], no timezone | Vendor-documented Eastern Time |
| Open, High, Low, Close | double | One-minute OHLC prices |
| Volume | int64 | Vendor-documented shares traded |
| source | large_string | `pitrading` or `iex`, retained as upstream provenance |

There is no symbol column. Symbol identity comes from the user-supplied uppercase
ETF filename and has no independent embedded authentication. Timestamps display
as `YYYY-MM-DD HH:MM:SS`; all fall on minute boundaries. For analysis only, they
were localized to `America/New_York`, with ambiguous/nonexistent times rejected,
then compared in UTC. Raw files were not normalized or rewritten. A naive column
cannot prove its original UTC offsets or exclude every possible timezone error.

The [vendor dictionary](https://hfdatalibrary.com/pages/dictionary) identifies
Eastern Time and adjusted prices. The
[methodology](https://hfdatalibrary.com/pages/docs) documents split/dividend
adjustment and a source splice. The exact downloaded version, adjustment factors,
and start-versus-end interval label are not authenticated by these local files.
No claim of unadjusted prices is justified.

The observed source changes from PiTrading through 2022-03-04 to IEX from
2022-03-07. Per-source row counts and endpoints are in `report.json`. The
[upstream repository](https://github.com/elkassabgi/hfdatalibrary) explains that
the later segment reflects IEX activity rather than the consolidated market.
Consequently, missing minutes can reflect absent venue trades; they must not be
silently filled or treated automatically as corrupted prices.

## Measured coverage

All datasets begin **2016-09-19 09:30:00 Eastern (13:30 UTC)**. Coverage uses full
first-to-last trading dates, not just the first and last observed intraday minute.
The isolated audit calendar is `exchange_calendars 4.13.2`, XNYS, left-inclusive
and close-exclusive. Holidays, exceptional closures and early closes are included.
Each symbol has all **2,514 expected trading dates**. The complete regular-session
grid has **976,680 expected one-minute bars** per symbol.

| Symbol | Last timestamp Eastern | Last UTC | Total rows | Regular rows | Missing regular bars | Regular coverage | Post-close rows |
|---|---|---|---:|---:|---:|---:|---:|
| SPY | 2026-09-18 15:59 | 2026-09-18 19:59 | 950,529 | 950,493 | 26,187 | 97.318774% | 36 |
| QQQ | 2026-09-18 15:55 | 2026-09-18 19:55 | 947,519 | 947,456 | 29,224 | 97.007822% | 63 |
| ITOT | 2026-09-18 15:54 | 2026-09-18 19:54 | 627,060 | 627,060 | 349,620 | 64.203219% | 0 |

There are no premarket rows and no rows outside the descriptive regular/extended
session windows. The post-close rows are classified using actual calendar closes,
including half-days; they do not constitute broad extended-hours coverage.
No expectation of a continuous extended-hours grid was imposed on these files.

## Quality and publication decision

All three datasets have zero duplicate timestamps, out-of-order records, invalid
OHLC relationships, negative or zero prices, negative or zero volume, null/nonfinite
or malformed rows, off-minute timestamps, DST-localization failures, unexpected
source labels, and source-boundary inconsistencies. Every Parquet row group was
decoded and total rows agreed with Parquet metadata. No complete expected session
is missing. Missing intraday bars and post-close records are retained and reported.

Core's current `Bar` contract permits only `UNADJUSTED` and `REGULAR`, while its
quality gate requires complete regular-session grids. Its calendar supports only
2026 and its archive loader enforces small research limits (default 5,000 rows,
2 MB; configurable maximum 20,000 rows, 10 MB). The full ten-year archives do not
meet these conditions. Changing those policies silently would misrepresent these
data or bypass existing governance.

**Canonical outputs: none.** There is no canonical-file hash because there is no
canonical file. Failed manifests use `hf.raw.parquet.v1` to describe retained raw
schema, empty canonical paths/checksums, and an explicit null canonical-file hash
in provenance. They do not claim `triad.ohlcv.v2` compliance. Raw gzip and payload
hashes, inclusive observed coverage endpoints, quality results, audit code hash,
normalization version `none`, provenance and source references are preserved.

Future publication requires a reviewed Core extension for adjusted datasets,
historical calendars, sparse/session-aware coverage and bounded partition access,
plus confirmation of vendor version and timestamp interval labels. That extension
should use the existing
`data/canonical/asset_class=equity/symbol=.../year=.../month=.../<dataset_id>/`
layout and preserve upstream source separately from canonical
`source=HFDataLibrary`. It must supply timestamp, symbol, open, high, low, close,
volume, source, ingested_at, dataset_version and provenance_id without filling,
dropping, sorting or adjusting records silently.

## Manifests and Core registration

Created in `C:\Triad\data\manifests\`:

- `hf-spy-20260919T233952760505Z.json`
- `hf-qqq-20260919T233952760505Z.json`
- `hf-itot-20260919T233952760505Z.json`

All validate against the existing Core `DatasetManifest` model. Registration used
Core `Ledger.put`, retaining Core ownership and the projection outbox. Each was
read back and found through `LocalCanonicalStore.manifests()`. These are failed
retained datasets, excluded by Core's quality eligibility check. No new provider
was enabled, no Triad-private storage route was created, and Aegis was untouched.

The [vendor terms](https://hfdatalibrary.com/pages/terms) describe CC BY 4.0 with
attribution. Upstream PiTrading/IEX terms also apply, as recorded in the manifests.
The local download's license/vintage evidence was not supplied. This audit records
the available notices and does not grant additional data rights.

## Validation, reproduction and Git

Builder validation: two extraction-safety tests passed, covering existing identical
and conflicting destinations, corrupt gzip, expansion ceiling, source preservation
and temporary-file cleanup. Ruff checks passed. Independent QA evidence is retained
separately in `C:\Triad\logs\hfdatalibrary-independent-qa.json`.

Base Git revision: `32bb237d0fe9906c528c7dc17a70c5f6601f853f`.
The initial working tree was clean. No commit was made. The intended Git changes
are these three new files:

- `tools/audit_hfdatalibrary.py`
- `tests/test_hfdatalibrary_audit.py`
- `docs/HFDATALIBRARY_AUDIT.md`

Runtime raw files, manifests, audit dependencies and QA logs are ignored by existing
repository rules. No runtime dependency lock or application configuration changed.
The working tree is dirty with the new files above. Authoritative database changes
are the three failed DatasetManifest records and their Core projection-outbox events.

The audit tool documents the isolated calendar dependency installation and accepts
`--register` for failed-manifest registration. Re-running creates a fresh evidence
directory and manifest IDs; it does not overwrite earlier evidence. Without that
flag it creates local retention evidence and manifests only.
