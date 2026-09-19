CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS triad;
CREATE TABLE IF NOT EXISTS core.schema_migrations (
  version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.work_items (
  id text PRIMARY KEY, mission_id text NOT NULL, status text NOT NULL,
  revision integer NOT NULL, payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('CREATED','VALIDATING','APPROVED','ASSIGNED','IN_PROGRESS',
    'AWAITING_REVIEW','CHANGES_REQUESTED','APPROVED_BY_REVIEWER','REJECTED','FAILED',
    'BLOCKED','COMPLETED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS core.orchestration_records (
  id text PRIMARY KEY, kind text NOT NULL, work_item_id text REFERENCES core.work_items(id),
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orchestration_records_work ON core.orchestration_records(work_item_id, kind);
CREATE TABLE IF NOT EXISTS core.work_events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  work_item_id text NOT NULL REFERENCES core.work_items(id),
  from_state text, to_state text NOT NULL, revision integer NOT NULL,
  detail text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(work_item_id, revision)
);
CREATE TABLE IF NOT EXISTS core.projection_outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL, entity_id text NOT NULL, payload jsonb NOT NULL,
  delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0, last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION core.protect_work_authority() RETURNS trigger AS $$
DECLARE field text;
BEGIN
  IF OLD.owner IS DISTINCT FROM NEW.owner THEN
    RAISE EXCEPTION 'Immutable assignment owner';
  END IF;
  IF NEW.payload ? 'owner' AND NEW.payload->>'owner' IS DISTINCT FROM NEW.owner THEN
    RAISE EXCEPTION 'Assignment payload owner does not match canonical owner';
  END IF;
  FOREACH field IN ARRAY ARRAY['work_item_id','mission_id','created_by','title','description',
    'work_type','authority_tier','allowed_tools','allowed_paths','forbidden_paths',
    'reasoning_budget','compute_budget','execution_permissions','risk_class','review_required',
    'reviewer','affects_money','affects_trading','alters_permissions','acceptance_criteria',
    'expected_outputs','input_context','parent_work_item_id','assigned_agent','routing_reason']
  LOOP
    IF COALESCE(OLD.payload->field, 'null'::jsonb) IS DISTINCT FROM COALESCE(NEW.payload->field, 'null'::jsonb) THEN
      RAISE EXCEPTION 'Immutable assignment field: %', field;
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS protect_work_authority ON core.work_items;
CREATE TRIGGER protect_work_authority BEFORE UPDATE ON core.work_items
  FOR EACH ROW EXECUTE FUNCTION core.protect_work_authority();
INSERT INTO core.schema_migrations(version) VALUES ('002_orchestration') ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW triad.schema_migrations AS SELECT * FROM core.schema_migrations;

CREATE OR REPLACE VIEW triad.work_items AS SELECT * FROM core.work_items;

CREATE OR REPLACE VIEW triad.orchestration_records AS SELECT * FROM core.orchestration_records;

CREATE OR REPLACE VIEW triad.work_events AS SELECT * FROM core.work_events;

CREATE OR REPLACE VIEW triad.projection_outbox AS SELECT * FROM core.projection_outbox;
