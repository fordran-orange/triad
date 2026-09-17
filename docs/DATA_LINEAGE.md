# Research lineage

Neo4j projects metadata only: DataSource -> RawDataset -> NORMALIZED_INTO -> Dataset; base Dataset -> DERIVED_INTO -> higher-timeframe Dataset; Dataset -> USED_BY -> Experiment; Experiment -> USES_STRATEGY -> Strategy and SUPPORTED_BY -> Commit; BacktestRun -> PART_OF -> Experiment; run -> HAS_REVIEW -> ResearchReview. DatasetVersion links exact versions to datasets. WorkItems retain policy/journal/handoff/review edges. No candles enter the graph.

ResearchFinding becomes a Claim with SUPPORTED_BY and CONTRADICTED_BY BacktestRun edges, retaining conflicts without majority voting. Hypothesis lifecycle is distinct from run outcomes. The reproducibility finding is narrowly supported for one fixture; it says nothing about strategy profitability in markets.

PostgreSQL is authoritative. Its transactional outbox makes graph and Markdown views retryable. UI provenance traces the selected result through original code, dataset manifest, raw file and checksums, rather than displaying a decorative graph.
