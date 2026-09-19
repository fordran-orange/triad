CREATE TABLE IF NOT EXISTS core.agent_instances (
 id text PRIMARY KEY,
 owner text NOT NULL CHECK(owner IN ('core','triad','p2p')),
 definition jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('ACTIVE','DISABLED','TERMINATED','EXPIRED')),
 expires_at timestamptz,
 parent_work_id text REFERENCES core.work_items(id),
 runs_reserved integer NOT NULL DEFAULT 0 CHECK(runs_reserved>=0),
 tokens_reserved integer NOT NULL DEFAULT 0 CHECK(tokens_reserved>=0),
 active_runs integer NOT NULL DEFAULT 0 CHECK(active_runs>=0)
);
CREATE TABLE IF NOT EXISTS core.agent_work_bindings (
 work_id text PRIMARY KEY REFERENCES core.work_items(id),
 agent_id text NOT NULL REFERENCES core.agent_instances(id)
);
CREATE OR REPLACE FUNCTION core.protect_agent_definition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.owner IS DISTINCT FROM OLD.owner OR
 NEW.definition IS DISTINCT FROM OLD.definition OR NEW.expires_at IS DISTINCT FROM OLD.expires_at OR
 NEW.parent_work_id IS DISTINCT FROM OLD.parent_work_id OR NEW.runs_reserved<OLD.runs_reserved OR
 NEW.tokens_reserved<OLD.tokens_reserved THEN RAISE EXCEPTION 'Immutable agent grant'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS protect_agent_definition ON core.agent_instances;
CREATE TRIGGER protect_agent_definition BEFORE UPDATE ON core.agent_instances FOR EACH ROW EXECUTE FUNCTION core.protect_agent_definition();
DROP TRIGGER IF EXISTS immutable_agent_binding ON core.agent_work_bindings;
CREATE TRIGGER immutable_agent_binding BEFORE UPDATE OR DELETE ON core.agent_work_bindings FOR EACH ROW EXECUTE FUNCTION core.immutable_intelligence_record();
INSERT INTO core.schema_migrations(version) VALUES ('011_agent_lifecycle') ON CONFLICT DO NOTHING;
