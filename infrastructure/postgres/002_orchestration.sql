CREATE TABLE IF NOT EXISTS triad.schema_migrations (
  version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS triad.work_items (
  id text PRIMARY KEY, mission_id text NOT NULL, status text NOT NULL,
  revision integer NOT NULL, payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('CREATED','VALIDATING','APPROVED','ASSIGNED','IN_PROGRESS',
    'AWAITING_REVIEW','CHANGES_REQUESTED','APPROVED_BY_REVIEWER','REJECTED','FAILED',
    'BLOCKED','COMPLETED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS triad.orchestration_records (
  id text PRIMARY KEY, kind text NOT NULL, work_item_id text REFERENCES triad.work_items(id),
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orchestration_records_work ON triad.orchestration_records(work_item_id, kind);
CREATE TABLE IF NOT EXISTS triad.work_events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  work_item_id text NOT NULL REFERENCES triad.work_items(id),
  from_state text, to_state text NOT NULL, revision integer NOT NULL,
  detail text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(work_item_id, revision)
);
CREATE TABLE IF NOT EXISTS triad.projection_outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL, entity_id text NOT NULL, payload jsonb NOT NULL,
  delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0, last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION triad.protect_work_authority() RETURNS trigger AS $$
DECLARE field text;
BEGIN
  FOREACH field IN ARRAY ARRAY['work_item_id','mission_id','created_by','title','description',
    'work_type','authority_tier','allowed_tools','allowed_paths','forbidden_paths',
    'reasoning_budget','compute_budget','execution_permissions','risk_class','review_required',
    'reviewer','affects_money','affects_trading','alters_permissions','acceptance_criteria',
    'expected_outputs','input_context','parent_work_item_id','assigned_agent']
  LOOP
    IF OLD.payload->field IS DISTINCT FROM NEW.payload->field THEN
      RAISE EXCEPTION 'Immutable assignment field: %', field;
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS protect_work_authority ON triad.work_items;
CREATE TRIGGER protect_work_authority BEFORE UPDATE ON triad.work_items
  FOR EACH ROW EXECUTE FUNCTION triad.protect_work_authority();
INSERT INTO triad.schema_migrations(version) VALUES ('002_orchestration') ON CONFLICT DO NOTHING;
