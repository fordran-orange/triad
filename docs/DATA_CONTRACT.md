# Canonical market data v2

Retained base resolution is 1-minute OHLCV. Bar and DatasetManifest JSON schemas are exported under control-plane/research. The earlier Day 1 v1 contract remains compatible as historical code; this lab uses triad.ohlcv.v2 explicitly.

Required fields: timestamp, symbol, open/high/low/close/volume, source, source_symbol, timezone, exchange, asset_class, ingested_at, dataset_version, provenance_id. Optional trade_count and vwap are nullable; adjustment_status=UNADJUSTED, session=REGULAR and currency=USD are explicit supported assumptions. Floating-point prices are stored consistently for this fixture engine; monetary decimal rounding/tick-size exchange semantics are future work.

Timestamp is an aware UTC interval start, aligned to a minute. bar_end is exclusive and is the earliest point at which that completed bar is available to a strategy. Source timezone metadata survives normalization. Positive finite prices, nonnegative volume, coherent OHLC bounds and valid identifiers are enforced. Derived bars carry base_bar_count and partial bucket flags. Incomplete dataset buckets are not accepted by the backtest engine.

Parquet includes schema metadata and UTC timestamp types. Dataset source/version and file hashes prevent silent replacement. Unadjusted data avoids introducing future corporate-action adjustments; splits, dividends and adjusted total-return studies are unsupported rather than inferred.
