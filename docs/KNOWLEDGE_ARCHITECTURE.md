# Hybrid Knowledge Graph / Brain

| Store | Canonical responsibility |
|---|---|
| Neo4j | Relationships, provenance, claims, experiments, strategies, decisions and lineage |
| PostgreSQL / TimescaleDB | Structured facts, operational state, metrics, events, experiments, orders, positions, working time series |
| Parquet + manifests | Portable retained one-minute market data and derived artifacts |
| Obsidian vault | Human notes, intent, synthesis, navigation and review |

Obsidian is not the canonical database. Notes link to stable IDs and manifests.
An experiment's structured parameters/results live in PostgreSQL; the same stable ID
in Neo4j connects the experiment to claims, datasets, artifacts and decisions.

Graph labels: Dataset, Source, Claim, Experiment, Strategy, Decision, Artifact.
Relationships: Dataset-DERIVED_FROM→Dataset; Dataset-INGESTED_FROM→Source;
Experiment-USES→Dataset; Experiment-TESTS→Claim; Artifact-PRODUCED_BY→Experiment;
Decision-SUPPORTED_BY→Artifact; Strategy-MOTIVATED_BY→Claim.
Claims should carry status (proposed/supported/refuted), uncertainty, author and time.
Relationships should carry provenance ID and creation time. Unique ID constraints
are applied by `tools/init_graph.py`; no strategy or claim records are preloaded.

Cross-store writes will need an outbox/event-based reconciliation mechanism; no
distributed atomicity is claimed. Dataset manifests and file hashes anchor lineage.
Avoid storing large candle arrays or complete Parquet payloads in the graph.
