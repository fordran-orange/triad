-- Additive ownership migration. Historical product records remain Triad-owned.
ALTER TABLE core.work_items ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT 'triad';
ALTER TABLE core.orchestration_records ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT 'triad';
ALTER TABLE core.day3_records ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT 'triad';
DO $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM core.schema_migrations WHERE version='006_record_ownership') THEN
UPDATE core.orchestration_records SET owner='core' WHERE kind='Agent';
UPDATE core.day3_records SET owner='core' WHERE kind IN
 ('TransportStatus','ProviderPolicy','TransportVerification','TransportRun','Usage','ProviderHealth','ControlAction','FallbackGrant');
INSERT INTO core.schema_migrations(version) VALUES ('006_record_ownership');
END IF; END $$;
CREATE INDEX IF NOT EXISTS work_owner_idx ON core.work_items(owner,created_at DESC);
CREATE INDEX IF NOT EXISTS record_owner_idx ON core.orchestration_records(owner,created_at DESC);
CREATE INDEX IF NOT EXISTS ledger_owner_idx ON core.day3_records(owner,created_at DESC);
CREATE TABLE IF NOT EXISTS core.product_controls (
 product text PRIMARY KEY, paused boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS core.exchange_candidates (
 id text PRIMARY KEY, source_product text NOT NULL, destination_product text NOT NULL,
 status text NOT NULL CHECK(status='CLOSED'), payload jsonb NOT NULL
);

CREATE SCHEMA IF NOT EXISTS p2p;
CREATE TABLE IF NOT EXISTS core.product_stops (product text NOT NULL, work_id text NOT NULL, PRIMARY KEY(product,work_id));
