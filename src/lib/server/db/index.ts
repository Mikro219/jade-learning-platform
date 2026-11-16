// The database platform module (plan PD10): the app's client, the migration runner, the ledger's
// readiness check and the app role's bootstrap. It imports nothing from SvelteKit, so the tools in
// tools/db/ use it outside the app. Everything outside this folder imports this file only.
export { createDatabase, createPool, type Database } from './client.ts';
export {
	LEDGER_TABLE,
	buildManifest,
	checkAgainstManifest,
	formatManifest,
	migrate,
	migrationStatus,
	parseManifest,
	readManifest,
	readMigrations,
	sha256,
	type Manifest,
	type ManifestEntry,
	type MigrateOptions,
	type MigrateResult,
	type MigrationFile,
	type MigrationStatus,
	type Queryable
} from './migrate.ts';
export {
	APP_ROLE,
	DB_ERROR_TAGS,
	DbError,
	LOCK_TIMEOUT_MS,
	ensureAppRole,
	newClient,
	scramVerifier,
	sqlstateOf,
	withDatabase,
	type AppRoleOutcome,
	type DbErrorTag
} from './roles.ts';
