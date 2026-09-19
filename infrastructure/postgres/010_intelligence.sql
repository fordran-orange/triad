CREATE TABLE IF NOT EXISTS core.intelligence_records (
    id text PRIMARY KEY,
    kind text NOT NULL,
    owner text NOT NULL CHECK (owner IN ('core','triad','p2p')),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS intelligence_kind_owner ON core.intelligence_records(kind, owner, created_at);
CREATE OR REPLACE FUNCTION core.immutable_intelligence_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Intelligence evidence is append-only'; END $$;
DROP TRIGGER IF EXISTS immutable_intelligence ON core.intelligence_records;
CREATE TRIGGER immutable_intelligence BEFORE UPDATE OR DELETE ON core.intelligence_records
FOR EACH ROW EXECUTE FUNCTION core.immutable_intelligence_record();
INSERT INTO core.schema_migrations(version) VALUES ('010_intelligence') ON CONFLICT DO NOTHING;
