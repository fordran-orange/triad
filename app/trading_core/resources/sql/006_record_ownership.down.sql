-- Run only during a controlled rollback after preserving new product data.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM core.work_items WHERE owner='p2p') OR EXISTS
 (SELECT 1 FROM core.day3_records WHERE owner='p2p') THEN
   RAISE EXCEPTION 'Rollback would lose P2P ownership; export product data first';
 END IF;
END $$;
DROP TABLE IF EXISTS core.artifact_owners;
DROP TABLE IF EXISTS core.exchange_candidates;
DROP TABLE IF EXISTS core.product_stops;
DROP TABLE IF EXISTS core.product_controls;
DELETE FROM core.schema_migrations WHERE version IN ('006_record_ownership','008_artifact_ownership');
-- Retain additive ownership columns: legacy Day-5A ignores them. Dropping them
-- would break compatibility views and destroy ownership evidence unnecessarily.
