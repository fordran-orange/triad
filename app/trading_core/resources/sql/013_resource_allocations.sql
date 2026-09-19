-- Resource defaults are new policy; historical agent grants and work stay intact.
CREATE TABLE IF NOT EXISTS core.resource_policies (
 version text PRIMARY KEY,
 payload jsonb NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO core.resource_policies(version,payload) VALUES ('day7-v1',
 '{"reasoning_budget":8192,"max_input_chars":24000,"max_output_tokens":6144,"timeout_seconds":480,"max_tool_calls":60}'::jsonb)
 ON CONFLICT DO NOTHING;
DROP TRIGGER IF EXISTS immutable_resource_policy ON core.resource_policies;
CREATE TRIGGER immutable_resource_policy BEFORE UPDATE OR DELETE ON core.resource_policies
 FOR EACH ROW EXECUTE FUNCTION core.immutable_intelligence_record();
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM core.resource_policies WHERE version='day7-v1' AND payload=
  '{"reasoning_budget":8192,"max_input_chars":24000,"max_output_tokens":6144,"timeout_seconds":480,"max_tool_calls":60}'::jsonb) THEN
  RAISE EXCEPTION 'Conflicting resource policy version';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM core.schema_migrations WHERE version='013_resource_allocations') THEN
  -- Preserve deliberately lower operator allocations and every cost/authority rule.
  UPDATE core.autonomy_control SET payload=jsonb_set(jsonb_set(jsonb_set(payload,
   '{limits,timeout_seconds}', CASE WHEN (payload->'limits'->>'timeout_seconds')::int=120
       THEN '480'::jsonb ELSE payload->'limits'->'timeout_seconds' END),
   '{limits,max_output_tokens}', CASE WHEN (payload->'limits'->>'max_output_tokens')::int=2048
       THEN '6144'::jsonb ELSE payload->'limits'->'max_output_tokens' END),
   '{epoch}',to_jsonb((payload->>'epoch')::int+1)) WHERE id=1;
  INSERT INTO core.schema_migrations(version) VALUES ('013_resource_allocations');
 END IF;
END $$;
