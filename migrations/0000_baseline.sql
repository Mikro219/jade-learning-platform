-- 0000_baseline (jade-urd, plan U4). Hand-written; created with `drizzle-kit generate --custom`.
-- It creates no table. The ledger, schema_migrations, is created by the runner before any file
-- runs (plan U3), and jade_app is created by the runner's role bootstrap (plan U2).
--
-- The app role may use the public schema and read the ledger (readiness compares it with the
-- manifest the app ships), and nothing else: it cannot create objects in the schema.
-- jade:contract jade-urd (the first migration: no previous release reads anything it revokes)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
--> statement-breakpoint
GRANT USAGE ON SCHEMA public TO jade_app;
--> statement-breakpoint
GRANT SELECT ON schema_migrations TO jade_app;
