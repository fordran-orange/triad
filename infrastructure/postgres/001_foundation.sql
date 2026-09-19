CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS triad;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS triad;
CREATE TABLE IF NOT EXISTS core.candles_1m (
  timestamp timestamptz NOT NULL,
  symbol text NOT NULL,
  open numeric(38,12) NOT NULL,
  high numeric(38,12) NOT NULL,
  low numeric(38,12) NOT NULL,
  close numeric(38,12) NOT NULL,
  volume numeric(38,12) NOT NULL CHECK (volume >= 0),
  source text NOT NULL,
  ingested_at timestamptz NOT NULL,
  data_version text NOT NULL,
  provenance_id text NOT NULL,
  PRIMARY KEY (timestamp, symbol, source, data_version),
  CHECK (high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
  CHECK (extract(epoch from timestamp)::numeric % 60 = 0),
  CHECK (ingested_at >= timestamp)
);
SELECT create_hypertable('core.candles_1m', 'timestamp', if_not_exists => TRUE);
CREATE TABLE IF NOT EXISTS core.datasets (
  id text PRIMARY KEY, manifest_path text NOT NULL, sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS core.experiments (
  id text PRIMARY KEY, status text NOT NULL, dataset_id text REFERENCES core.datasets(id),
  created_at timestamptz NOT NULL DEFAULT now(), specification jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS core.events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(), kind text NOT NULL, payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS core.metrics (
  timestamp timestamptz NOT NULL, experiment_id text REFERENCES core.experiments(id),
  name text NOT NULL, value double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS core.operational_state (
  key text PRIMARY KEY, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
-- Schemas only: no broker connection, order submission, or execution worker exists.
CREATE TABLE IF NOT EXISTS core.orders (
  id text PRIMARY KEY, mode text NOT NULL CHECK (mode = 'simulation'),
  status text NOT NULL, details jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.positions (
  id text PRIMARY KEY, mode text NOT NULL CHECK (mode = 'simulation'),
  details jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW triad.candles_1m AS SELECT * FROM core.candles_1m;

CREATE OR REPLACE VIEW triad.datasets AS SELECT * FROM core.datasets;

CREATE OR REPLACE VIEW triad.experiments AS SELECT * FROM core.experiments;

CREATE OR REPLACE VIEW triad.events AS SELECT * FROM core.events;

CREATE OR REPLACE VIEW triad.metrics AS SELECT * FROM core.metrics;

CREATE OR REPLACE VIEW triad.operational_state AS SELECT * FROM core.operational_state;

CREATE OR REPLACE VIEW triad.orders AS SELECT * FROM core.orders;

CREATE OR REPLACE VIEW triad.positions AS SELECT * FROM core.positions;
