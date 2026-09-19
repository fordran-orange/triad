CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS p2p;
CREATE SCHEMA IF NOT EXISTS triad;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='candles_1m' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.candles_1m SET SCHEMA core;
 END IF;
 IF to_regclass('core.candles_1m') IS NOT NULL AND to_regclass('triad.candles_1m') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.candles_1m AS SELECT * FROM core.candles_1m';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='datasets' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.datasets SET SCHEMA core;
 END IF;
 IF to_regclass('core.datasets') IS NOT NULL AND to_regclass('triad.datasets') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.datasets AS SELECT * FROM core.datasets';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='experiments' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.experiments SET SCHEMA core;
 END IF;
 IF to_regclass('core.experiments') IS NOT NULL AND to_regclass('triad.experiments') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.experiments AS SELECT * FROM core.experiments';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='events' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.events SET SCHEMA core;
 END IF;
 IF to_regclass('core.events') IS NOT NULL AND to_regclass('triad.events') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.events AS SELECT * FROM core.events';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='metrics' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.metrics SET SCHEMA core;
 END IF;
 IF to_regclass('core.metrics') IS NOT NULL AND to_regclass('triad.metrics') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.metrics AS SELECT * FROM core.metrics';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='operational_state' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.operational_state SET SCHEMA core;
 END IF;
 IF to_regclass('core.operational_state') IS NOT NULL AND to_regclass('triad.operational_state') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.operational_state AS SELECT * FROM core.operational_state';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='orders' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.orders SET SCHEMA core;
 END IF;
 IF to_regclass('core.orders') IS NOT NULL AND to_regclass('triad.orders') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.orders AS SELECT * FROM core.orders';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='positions' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.positions SET SCHEMA core;
 END IF;
 IF to_regclass('core.positions') IS NOT NULL AND to_regclass('triad.positions') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.positions AS SELECT * FROM core.positions';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='schema_migrations' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.schema_migrations SET SCHEMA core;
 END IF;
 IF to_regclass('core.schema_migrations') IS NOT NULL AND to_regclass('triad.schema_migrations') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.schema_migrations AS SELECT * FROM core.schema_migrations';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='work_items' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.work_items SET SCHEMA core;
 END IF;
 IF to_regclass('core.work_items') IS NOT NULL AND to_regclass('triad.work_items') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.work_items AS SELECT * FROM core.work_items';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='orchestration_records' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.orchestration_records SET SCHEMA core;
 END IF;
 IF to_regclass('core.orchestration_records') IS NOT NULL AND to_regclass('triad.orchestration_records') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.orchestration_records AS SELECT * FROM core.orchestration_records';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='work_events' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.work_events SET SCHEMA core;
 END IF;
 IF to_regclass('core.work_events') IS NOT NULL AND to_regclass('triad.work_events') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.work_events AS SELECT * FROM core.work_events';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='projection_outbox' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.projection_outbox SET SCHEMA core;
 END IF;
 IF to_regclass('core.projection_outbox') IS NOT NULL AND to_regclass('triad.projection_outbox') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.projection_outbox AS SELECT * FROM core.projection_outbox';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='autonomy_control' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.autonomy_control SET SCHEMA core;
 END IF;
 IF to_regclass('core.autonomy_control') IS NOT NULL AND to_regclass('triad.autonomy_control') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.autonomy_control AS SELECT * FROM core.autonomy_control';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='day3_records' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.day3_records SET SCHEMA core;
 END IF;
 IF to_regclass('core.day3_records') IS NOT NULL AND to_regclass('triad.day3_records') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.day3_records AS SELECT * FROM core.day3_records';
 END IF;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='triad' AND c.relname='autonomy_daily' AND c.relkind IN ('r','p')) THEN
   ALTER TABLE triad.autonomy_daily SET SCHEMA core;
 END IF;
 IF to_regclass('core.autonomy_daily') IS NOT NULL AND to_regclass('triad.autonomy_daily') IS NULL THEN
   EXECUTE 'CREATE VIEW triad.autonomy_daily AS SELECT * FROM core.autonomy_daily';
 END IF;
END $$;
