# Migrations

SQL migrations for PostgreSQL 16 (ADR 0003). Drizzle Kit writes them; the project's own runner,
`pnpm db:migrate` (`src/lib/server/db/migrate.ts`), applies them. Drizzle Kit's `migrate` and
`push` commands are never used.

## Writing one

- A schema change: edit `src/lib/server/db/schema.ts`, then `pnpm db:generate`, which runs
  `drizzle-kit generate` and then `pnpm db:manifest`.
- Hand-written SQL (grants, data fixes): `pnpm exec drizzle-kit generate --custom --name <name>`,
  write the SQL into the new file, then `pnpm db:manifest`.
- Commit the `.sql` file, `manifest.json` and `meta/` (Drizzle Kit's journal and snapshot)
  together. `pnpm db:check` must pass.

## Rules (forward-only, plan U5 and INV5)

- **Files are immutable once merged.** A merged file is never edited, renamed, reordered or
  removed. There is no down migration and no way to reapply a file: a mistake is corrected by a
  new migration.
- **`manifest.json` is the lock.** It lists every file's name and SHA-256 in order. The runner
  refuses files that do not match it, and stops with `MIGRATION_HISTORY_MISMATCH`, applying
  nothing, when an applied file's name or hash differs from the ledger (`schema_migrations`).
  The manifest is also what the app ships to know which migrations it needs (readiness).
- **Compatible with the previous release.** A deploy migrates before the new app starts, and a
  rollback runs the previous image on the new schema. So a migration may add schema objects
  (tables, columns, indexes, grants), and may drop or rename only an object that the previous
  release's code no longer reads: a destructive change ships one release after the code stops
  using the object.
- **Destructive statements are marked.** A file with `DROP`, `TRUNCATE`, `RENAME`, `REVOKE`,
  `DELETE`, a column type change or `SET NOT NULL` carries a line
  `-- jade:contract <bead>` naming the bead that removed the last reader. `pnpm db:check`
  refuses the file without it.
- **One transaction per file.** The runner applies each file in its own transaction together
  with its ledger row; a failure rolls the file back. A statement that cannot run inside a
  transaction is out of scope until one is needed. A file holds no transaction-control
  statement (`BEGIN`, `COMMIT`, `ROLLBACK`, `END`, `ABORT`, `START TRANSACTION`, `SAVEPOINT`,
  `RELEASE`): one would commit the file apart from its ledger row. `pnpm db:check` refuses it.
- **Grants to `jade_app` by name.** The app connects as `jade_app` and owns nothing; the owner,
  `jade_owner`, runs migrations. Every new table needs its grants to `jade_app` in the same file.

## Commands

- `pnpm db:migrate`: apply pending files to the database `MIGRATION_DATABASE_URL` names.
- `pnpm db:reset`: drop, recreate and migrate it; development and test on a loopback host only.
- `pnpm db:check [--base <ref>]`: the static rules above, and with `--base`, that the base
  commit's manifest is an unchanged prefix of this one.

## Notes

- `0000_baseline` revokes `CREATE` on schema `public` from `PUBLIC`. On PostgreSQL 15 and later
  (the project runs 16) `PUBLIC` has no such privilege by default, so the statement is defensive:
  it keeps the app role unable to create objects on a cluster made by an older `initdb` or changed
  by hand. `tests/integration/baseline-migration.test.ts` checks the privilege itself
  (`has_schema_privilege`), not only that a `CREATE TABLE` by the app role fails.
