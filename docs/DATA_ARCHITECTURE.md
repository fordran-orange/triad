# Portable market data

Canonical retained base resolution is **one-minute OHLCV**. Parquet with Zstandard
compression is the primary portable archive; databases hold working subsets.
Never discard the one-minute archive when deriving higher timeframes.

| Field | Type | Meaning |
|---|---|---|
| timestamp | UTC timestamp, microseconds | Inclusive start of one-minute interval; minute aligned |
| symbol | string | Namespace-qualified instrument identifier; mapping version belongs in manifest |
| open/high/low/close | decimal(38,12) | Exact prices; high/low bound open and close |
| volume | decimal(38,12), nonnegative | Source volume; units documented in manifest |
| source | string | Provider or synthetic-fixture identifier |
| ingested_at | UTC timestamp | When the record was ingested |
| data_version | string | Immutable dataset/version identifier |
| provenance_id | string | Join key to manifest and graph evidence |

The Python contract and generated JSON schema validate timezone, minute alignment,
OHLC ranges, finite decimals and volume. A duplicate key is
`(timestamp, symbol, source, data_version)`. Different providers are not silently merged.
Corrections produce a new version, not an overwrite. Negative prices are permitted;
instrument-specific price rules belong in a later instrument contract.

Stages: raw provider evidence → canonical validated 1m → derived timeframes.
Suggested partitions: `symbol=<encoded-id>/year=YYYY/month=MM/part-<id>.parquet`.
Raw payloads and temp files are not the long-term source of truth. Store manifests
in `data/manifests`, recording SHA-256, row count, min/max timestamps, schema version,
provider, volume units, adjustment policy, timezone/calendar, transformation code
revision, parent dataset IDs and provenance ID. An example lives in
`data/manifest.example.json`; local manifests and market data are ignored by Git.

Future resampling uses first open, maximum high, minimum low, last close, summed
volume. Group by instrument/source/version; use UTC interval starts plus an explicit
market calendar. Incomplete windows must be flagged, never silently filled. Handle
sessions, DST, holidays, corporate actions and missing minutes explicitly. Preserve
parent version/hash and transformation revision for every derived artifact.
Aggregation is a documented contract on Day 1, not an implemented ingestion engine.
Tests write tiny synthetic files only; no market history is downloaded.
