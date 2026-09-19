-- The documentation relay is Triad acceptance policy, including its initial
-- pre-WorkItem audit envelope. Retain IDs and payloads while correcting metadata.
UPDATE core.day3_records SET owner='triad' WHERE kind='ProviderRelay' AND owner='core';
INSERT INTO core.schema_migrations(version) VALUES ('009_product_audit_ownership') ON CONFLICT DO NOTHING;
