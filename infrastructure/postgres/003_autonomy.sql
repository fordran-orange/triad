CREATE TABLE IF NOT EXISTS triad.autonomy_control (
 id integer PRIMARY KEY CHECK (id=1), payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS triad.day3_records (
 id text PRIMARY KEY, kind text NOT NULL, work_item_id text,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS day3_records_kind ON triad.day3_records(kind, created_at DESC);
CREATE TABLE IF NOT EXISTS triad.autonomy_daily (
 day date PRIMARY KEY, changes integer NOT NULL DEFAULT 0,
 reserved_cost numeric NOT NULL DEFAULT 0, reserved_tokens bigint NOT NULL DEFAULT 0,
 reserved_seconds integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS triad.improvement_slots (
 day date NOT NULL, agent text NOT NULL, work_item_id text NOT NULL,
 PRIMARY KEY(day,agent)
);
CREATE TABLE IF NOT EXISTS triad.cycle_slots (
 day date NOT NULL, mode text NOT NULL, cycle_id text NOT NULL, PRIMARY KEY(day,mode)
);
INSERT INTO triad.schema_migrations(version) VALUES ('003_autonomy') ON CONFLICT DO NOTHING;
