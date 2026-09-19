-- Additive lineage rename. Immutable owners, payloads, IDs and times stay intact.
-- Legacy p2p schema/artifacts remain available for historical provenance.
CREATE SCHEMA IF NOT EXISTS aegis;
CREATE TABLE IF NOT EXISTS core.product_aliases (
 alias text PRIMARY KEY,
 canonical_product text NOT NULL,
 migration_version text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT now(),
 CHECK(alias <> canonical_product)
);
INSERT INTO core.product_aliases(alias,canonical_product,migration_version)
 VALUES ('p2p','aegis','012_aegis_lineage') ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM core.product_aliases
                WHERE alias='p2p' AND canonical_product='aegis'
                  AND migration_version='012_aegis_lineage') THEN
  RAISE EXCEPTION 'Conflicting product lineage alias';
 END IF;
END $$;
DROP TRIGGER IF EXISTS immutable_product_alias ON core.product_aliases;
CREATE TRIGGER immutable_product_alias BEFORE UPDATE OR DELETE ON core.product_aliases
 FOR EACH ROW EXECUTE FUNCTION core.immutable_intelligence_record();

-- Widen validation for the new spelling without updating immutable rows.
ALTER TABLE core.intelligence_records DROP CONSTRAINT IF EXISTS intelligence_records_owner_check;
ALTER TABLE core.intelligence_records ADD CONSTRAINT intelligence_records_owner_check
 CHECK(owner IN ('core','triad','p2p','aegis'));
ALTER TABLE core.agent_instances DROP CONSTRAINT IF EXISTS agent_instances_owner_check;
ALTER TABLE core.agent_instances ADD CONSTRAINT agent_instances_owner_check
 CHECK(owner IN ('core','triad','p2p','aegis'));

-- Mutable controls transfer conservatively: a paused lineage stays paused.
-- Run once; later explicit operator resume must not be undone by startup.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM core.schema_migrations WHERE version='012_aegis_lineage') THEN
  INSERT INTO core.product_controls(product,paused)
   SELECT 'aegis',bool_or(paused) FROM core.product_controls
   WHERE product IN ('aegis','p2p') HAVING count(*)>0
   ON CONFLICT(product) DO UPDATE SET paused=EXCLUDED.paused;
  INSERT INTO core.product_stops(product,work_id)
   SELECT 'aegis',work_id FROM core.product_stops WHERE product='p2p'
   ON CONFLICT DO NOTHING;
  INSERT INTO core.schema_migrations(version) VALUES ('012_aegis_lineage');
 END IF;
END $$;
