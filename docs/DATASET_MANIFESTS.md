# Immutable dataset manifests

Every canonical/derived dataset has dataset_id/version, symbols, asset_class, resolution, UTC bounds, row count, provider/mode, raw_sources, canonical_paths, schema version, creation time, total checksum, per-file checksums, quality status, gaps, adjustment/timezone policy, creator, provenance, transformations, calendar version and bytes.

Versions hash normalized content (including recorded ingestion identity/time); separate ingestions can have different versions even when prices match. File hashes cover exact Parquet bytes; the aggregate checksum covers the stable mapping of paths to hashes. Files are exclusive-create and identifiers are host-generated. A manifest is published only after all canonical files exist and quality passes. PostgreSQL registration is a later auditable stage, not a distributed filesystem/database transaction.

Derived manifests reference parent_dataset and original raw metadata. Export the root-relative files with the JSON manifest to move a dataset to another application. No database server is needed to interpret or validate its archive.
