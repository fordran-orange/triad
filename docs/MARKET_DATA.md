# Market data architecture

MarketDataProvider defines fetch_bars, capabilities, supported resolutions/asset classes and health. The first adapter is local-engine-fixture-v1, mode FIXTURE, symbol LABTEST. No real provider connection or licensed history is claimed. Raw JSON uses explicit America/New_York offsets; normalized timestamps use UTC. The tiny three-session dataset is architecture-test input, not research alpha.

Raw bytes and a source/request/checksum sidecar are exclusively created under data/raw/<job-id>/. Canonical historical bars live in partitioned Parquet under data/canonical/asset_class=equity/symbol=LABTEST/year=2026/month=09/<dataset-id>/. PostgreSQL holds metadata and operational history; candles are not copied into Neo4j. data/manifests/<dataset-id>.json is the portable catalog entry.

Ingestion stages are persisted as IngestionJob, RawDataset, QualityReport and DatasetManifest records. Failed quality prevents canonical publication; original bytes survive. recover-ingestion <job-id> reprocesses checksum-verified retained raw into a new dataset without altering the original. A crash can leave unpublished files; only catalogued manifests authorize use. Graph projection failures remain in the durable outbox for retry.

Catalogue API supports symbol filtering; records expose provider, timeframe, dates, version and quality. Experiment records identify exact datasets. Adapter/legal-account selection is deferred until explicitly configured; no large archive was downloaded.
