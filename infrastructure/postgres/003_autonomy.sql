CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS triad;
CREATE TABLE IF NOT EXISTS core.autonomy_control (
 id integer PRIMARY KEY CHECK (id=1), payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS core.day3_records (
 id text PRIMARY KEY, kind text NOT NULL, work_item_id text,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS day3_records_kind ON core.day3_records(kind, created_at DESC);
CREATE TABLE IF NOT EXISTS core.autonomy_daily (
 day date PRIMARY KEY, changes integer NOT NULL DEFAULT 0,
 reserved_cost numeric NOT NULL DEFAULT 0, reserved_tokens bigint NOT NULL DEFAULT 0,
 reserved_seconds integer NOT NULL DEFAULT 0
);
INSERT INTO core.schema_migrations(version) VALUES ('003_autonomy') ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW triad.autonomy_control AS SELECT * FROM core.autonomy_control;

CREATE OR REPLACE VIEW triad.day3_records AS SELECT * FROM core.day3_records;

CREATE OR REPLACE VIEW triad.autonomy_daily AS SELECT * FROM core.autonomy_daily;
