# F: market and historical data integration

The retained local canonical store is a configured neutral Historical Data integration. Requests distinguish real/fixture data, symbols, one-minute resolution, exact session coverage, required volume, quality, license use and cost. Eligibility verifies retained hashes and requested bars; incomplete/unknown real-data licensing is excluded. Multiple datasets require explicit selection and are never silently combined.

A trusted reviewed-adapter ingestion extension passes raw bytes through retained artifacts, adapter normalization, existing neutral quality checks, canonical one-minute Parquet and manifests. Integration/request/time/symbols/resolution/coverage/normalization/license/quality provenance is retained. Source mode must match request mode. Paid data remains blocked pending separately reviewed reservation support; no silent fallback. No vendor connection is claimed. Fixture tests exercise the actual pipeline without outside account calls.

Only Core/shared DatasetManifest records are exposed as neutral data. Product-private records remain excluded; host-only ingestion/candidate adoption has no arbitrary adapter HTTP endpoint.
