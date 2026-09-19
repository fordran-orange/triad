CREATE TABLE IF NOT EXISTS core.artifact_owners (
 path text PRIMARY KEY, owner text NOT NULL, record_id text NOT NULL
);
-- Historical raw/canonical market data contains no product conclusions.
DO $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM core.schema_migrations WHERE version='008_artifact_ownership') THEN
UPDATE core.day3_records SET owner='shared'
 WHERE kind IN ('RawDataset','DatasetManifest','QualityReport') AND owner='triad';
END IF; END $$;
INSERT INTO core.artifact_owners(path,owner,record_id)
 SELECT artifact->>'path', r.owner, r.id
 FROM core.day3_records r, jsonb_each(COALESCE(r.payload->'result_artifacts','{}'::jsonb)) e(k,artifact)
 WHERE artifact->>'path' IS NOT NULL ON CONFLICT DO NOTHING;
INSERT INTO core.schema_migrations(version) VALUES ('008_artifact_ownership') ON CONFLICT DO NOTHING;
