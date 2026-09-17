CREATE TABLE IF NOT EXISTS triad.cycle_jobs (
 id text PRIMARY KEY,
 day date NOT NULL,
 mode text NOT NULL CHECK(mode IN ('REAL','SIMULATED')),
 status text NOT NULL CHECK(status IN ('QUEUED','RUNNING','COMPLETED','BLOCKED','CANCELLED','UNCERTAIN')),
 control_epoch integer NOT NULL,
 scheduled boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 finished_at timestamptz,
 worker_id text,
 result jsonb,
 failure_code text,
 UNIQUE(day,mode)
);
INSERT INTO triad.schema_migrations(version) VALUES ('004_jobs') ON CONFLICT DO NOTHING;
