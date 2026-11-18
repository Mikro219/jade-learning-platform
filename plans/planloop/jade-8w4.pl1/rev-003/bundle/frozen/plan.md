# PLAN jade-8w4: Phase 2 data model and kit codes (revision 3, 2026-11-18)

Code, schema and tooling plan for Phase 2 (epic jade-8w4): the agent beads jade-o07, jade-fd5, jade-7if, jade-99j and jade-q01, the decision of jade-hap, and the specification of jade-pe9, which cannot be implemented before jade-vcy (Phase 3). Track: escalated (schema-migration, secrets, privacy, authorization, concurrency, state-machine, idempotency). Human beads are out of scope. Development data is the `demo` product only; no teaching content is written.

This plan is not authorization to implement. After approval and Mike's sign-off, implementation waits for Mike's explicit go-ahead and for his answers to section 17. It then proceeds one bead at a time in the order of section 15, each bead delegated by the orchestrator to a subagent with a complete brief.

## 0. Summary

- Implementable in this phase, with no staging: the core schema (jade-o07), the code library (jade-fd5), the app pool beside the readiness pool (jade-hap), the redemption service with its limits and audit rows (jade-7if), the batch generator (jade-99j) and the development seed (jade-q01). Each has automated checks that run locally and in CI.
- Not finishable in this phase: the staging half of jade-o07 and of exit criterion AC1 (deferred by Mike's Q4 until jade-4zw lands; section 16 says how it is verified and where it is recorded), and jade-pe9 (needs accounts, sessions, the staff role and the authorization matrix of Phase 3; section 12 specifies it). The epic cannot close before both.
- Mike decides before go-ahead (section 17): the QR URL form (Q1), the permanent code-format and pepper choices recorded as ADR 0026 (Q2), whether jade-7if or jade-pe9 get planloop runs of their own (Q3), where the failed-code counters live (Q4), whether jade-o07 closes before the staging check (Q5), and three smaller items (Q6 to Q8). The plan is written for the recommended option of each; a different answer returns the affected section to planloop before that bead starts.
- The brief's nineteen contradictions and gaps, and three more found while planning, are settled or raised in section 3. No rule of CLAUDE.md and no ADR is changed, relaxed or planned around.
- Scope is Phase 2 only: no route is added (the registry stays as Phase 1 left it until jade-pe9), no sign-in, no classes UI, no Phase 6 table, no deletion function, no event shape (so nothing to bump in a catalog version and nothing new for the consent appendix beyond Q4's counter rows).

## 1. Facts this plan rests on

Read in the repository on 2026-11-18 (main 72254ef) unless stated.

- `src/lib/server/db/schema.ts` exports nothing; `codes/index.ts` and `auth/index.ts` export nothing; `migrations/` holds `0000_baseline` only. `tests/unit/migrations-static.test.ts` has a Phase 1 case, "creates no table in Phase 1, and schema.ts declares none", which the first Phase 2 migration must replace, not delete silently (SC6).
- `src/lib/server/http/readiness.ts` owns a private pool (max 4; 2 s `connectionTimeoutMillis`, `query_timeout`, `statement_timeout`, `lock_timeout`) and `closeDatabase()` ends only that pool. No app-wide pool exists.
- `config/index.ts` accepts `CODE_PEPPER` as at least 43 characters of `A-Za-z0-9_+/=-` and treats it as opaque. `pnpm env:init` generates it as 32 random bytes in base64url (43 characters). A value containing `test-only` is refused unless `APP_ENV` is `test`. When `NODE_ENV` is `production` only `APP_ENV` `staging` or `production` is accepted.
- The image (Dockerfile) copies `build/`, `migrations/`, `tools/` and `src/lib/server/{config,db,log}` with production dependencies only; the `migrate` service runs `node tools/db/migrate.ts` as `jade_owner`; the `app` service never receives the owner URL; the database has no host port in the production stack.
- `tools/ci/migration-compat.sh` runs only when a pull request adds a migration: (1) the head's runner migrates a fresh database and a template; (2) the base commit's build must answer `/readyz` 200 on the fresh database; (3) the base's whole `integration` project runs with `JADE_TEST_TEMPLATE` naming the template, so the base's tests that clone the template run on the head's schema, while the base's tests that migrate an empty database themselves run on the base's schema. Phase 2's first migration pull request is its first real run.
- `tests/support/db.ts` gives a test file `createTestDatabase()` (a clone of the migrated template) and `createEmptyDatabase()`; `jade_owner` is a superuser in development, CI and the Compose stack.
- Phase 1 tests that assume `0000_baseline` is the only shipped migration: `tests/integration/role-bootstrap.test.ts` (lines 47 and 135), `tests/integration/migrate.test.ts` (the `0001_fails`, `0001_unlisted` and `0001_extra` cases, whose files sort between `0001_citext` and `0002_core_schema` once those exist), `tests/unit/migrations-static.test.ts` (the gap case expects `number is not 0001`; the `0001_drop` and `0001_tx` copies), `tests/infra/stack-up.test.ts:72`, and `tests/infra/compose-up.test.ts:67` and its fixture case (lines 186 to 210), which copies `tests/infra/fixtures/migrations/0001_infra_fixture.sql` in under that name. `tools/ci/migration-compat.sh` reads the same fixture for its self-test and already numbers it from the manifest. `tests/integration/db-scripts.test.ts` and `baseline-migration.test.ts` hold with more migrations: they match single output lines or read the manifest.
- `tools/ci/clean-clone.sh` runs the README setup block, then `pnpm test`, then `pnpm e2e`, and only then starts `pnpm dev` and curls `/`; it does not request `/readyz`.
- Each `pnpm ci:clean-clone` run uses a new, randomly named Compose project, so a new and empty database, and a new `pnpm env:init`, so a new `CODE_PEPPER`, but runs under the operator's own `HOME`: a file that a step writes outside the temporary clone directory, for example under `<home>/jade-code-batches/`, outlives the run and is met by the next one. `pnpm db:reset` (`tools/db/reset.ts`) drops, recreates and migrates the database and touches no other file.
- `/readyz` (`src/routes/readyz/+server.ts`) answers 200 only when `checkReadiness()` reports `db: ok` and `migrations: ok`; `classifyReadyz` in `tools/ci/compat.ts` reads only those two checks; `tests/unit/readiness.test.ts` compares whole `{ db, migrations }` literals.
- Readers of a readiness body, from a search of `tests/` and `tools/` for `/readyz`, `checkReadiness` and `readinessOfFailure`: `tests/unit/readiness.test.ts` (whole `readinessOfFailure` literals); `tests/blackbox/health.test.ts`, whose `expectNotReady` compares the whole `checks` object of each 503 (`{ db: 'fail', migrations: 'unknown' }` twice, `{ db: 'ok', migrations: 'behind' }` once) and whose 200 case compares the whole body `{ status: 'ready' }`; `tests/unit/compat.test.ts`, which builds bodies with `checks: { db, migrations }` as inputs to `classifyReadyz`; `tools/ci/compat.ts` (reads `db` and `migrations` only); `tests/blackbox/request-id.test.ts` (the `requestId` of a 503 only); `tests/infra/compose-up.test.ts` (the status only); `tests/integration/migrate.test.ts` (`migrationStatus`, no `checks` object). No other file reads one.
- `tests/authz/route-registry.ts` knows the access classes `public` and `dev-only`; jade-aq5 widens it in Phase 3.
- `.gitignore` and `.dockerignore` list no output directory for code cards.
- npm registry, 2026-11-18: `fast-check` 4.10.2 (MIT; one dependency, `pure-rand`), `qrcode-generator` 2.0.4 (MIT; no dependencies), `jsqr` 1.4.0 (Apache-2.0; no dependencies), `@node-rs/argon2` 2.2.2 (MIT; not added in this phase).
- PostgreSQL 16 behaviour the design relies on, each exercised by a test of sections 6, 9 or 13 rather than assumed: `citext` is a trusted extension that the database owner can create; an identity column needs no sequence grant for an INSERT by a role with INSERT on the table; `SELECT ... FOR UPDATE` needs UPDATE on at least one column; `FOR NO KEY UPDATE` on a parent row does not block a child's foreign-key insert but blocks another `FOR NO KEY UPDATE`; under READ COMMITTED a statement that waited for a row lock re-reads the committed row; an INSERT that meets an uncommitted duplicate of a unique key waits for that transaction to end.
- Contracts inherited from the approved Phase 1 plan (jade-vtk.pl1 revision 5), restated because that plan is not a review input: migrations are forward-only and compatible with the previous release (`tests/unit/migrations-static.test.ts`, `pnpm db:check --base <ref>`, `tests/integration/migrate.test.ts`, CI job `migration-compat`); a database ahead of the app is ready (`migrationStatus`); the running app cannot run DDL and never holds the owner's credentials (jade-hwu, CREATE TEMP TABLE, is deferred by Mike); no log line carries an IP, cookie, kit code, join code, token, email, body, path, query string or a kit, class, session or step identifier, in any `APP_ENV` (the closed logger of `src/lib/server/log`); every route is in the registry with an access class; a refusal test feeds inputs that every earlier check accepts and asserts the refusing check's own tag; cluster-wide state in tests is written once or serialized; no check assumes a host port is free.

## 2. Obligations

Every row OB1 to OB136, its owner, the step that answers it (sections 6 to 12; SC schema, CL code library, PL pools, RD redeem, GN generator, SD seed, ST staff pages) and the check that proves it. Files under `tests/unit`, `tests/integration` and `tests/blackbox` run with `pnpm test`; files under `tests/e2e` with `pnpm e2e`. "Waits" names what the check waits for.

| OB | Owner | Step | Check |
|---|---|---|---|
| OB1 | epic | SC, CL, RD, GN; revoke is ST | AC1 to AC3; revoke waits for jade-pe9 (AC10) |
| OB2 | epic | section 16, Q5 | AC1 recorded as deferred; the staging-acceptance bead of section 15 |
| OB3 | jade-o07 | SC8 | AC1 (waits for jade-4zw) |
| OB4 | jade-99j, jade-7if | GN3, RD3 | AC2: `tests/integration/code-lifecycle.test.ts`; browser flow waits for jade-bu6 |
| OB5 | jade-o07, jade-99j, jade-7if | SC7, GN3, RD3 | AC3: `tests/integration/no-plain-codes.test.ts`, `schema-catalog.test.ts` |
| OB6 | jade-pe9 | ST1 to ST6 | AC10 (waits for jade-vcy and jade-aq5) |
| OB7 | jade-o07 | SC2, SC3 | `schema-catalog.test.ts`; `tests/unit/product-agnostic.test.ts` (INV7) |
| OB8 | jade-o07 | SC1 to SC4, SC8 | `migrate.test.ts` (fresh database ends with the ledger equal to the manifest), `pnpm db:check`, `pnpm ci:compat`; the staging half is AC1 (waits) |
| OB9 | jade-o07 | SC2, SC7 | `tests/integration/schema-constraints.test.ts`: one violating row per constraint, asserting SQLSTATE and constraint name |
| OB10 | jade-o07 | SC7 | `schema-catalog.test.ts` (column allowlist), `no-plain-codes.test.ts` (canary) (INV1) |
| OB11 | jade-fd5 | CL1 to CL3 | `tests/unit/codes-format.test.ts`, `codes-generate.test.ts`, `codes-hmac.test.ts` |
| OB12 | jade-fd5 | CL1, CL5 | `codes-format.test.ts`: fast-check round trip; every position and substitution, by exhaustion |
| OB13 | jade-fd5 | CL1 | `codes-format.test.ts`: lower case, no dashes, spaces, O, I and L in the body |
| OB14 | jade-fd5 | CL3 | `codes-hmac.test.ts`: known answers under a fixed pepper; a different pepper gives a different value; `timingSafeEqual` is the only comparison |
| OB15 | jade-7if | RD3, RD4, C1, C3 | `tests/integration/redeem.test.ts` (each outcome and its message); no per-IP limit (OB19) |
| OB16 | jade-7if | RD3 | `tests/integration/redeem-concurrency.test.ts` (section 13, T1) |
| OB17 | jade-7if | RD2 | `tests/integration/redeem-limits.test.ts` |
| OB18 | jade-7if | RD4 | `tests/integration/audit.test.ts`, `tests/unit/audit-subject.test.ts`, `no-plain-codes.test.ts` |
| OB19 | jade-7if | RD2, C1 | `redeem-limits.test.ts` (account lock, global throttle); `tests/unit/no-ip.test.ts` |
| OB20 | jade-99j | GN1 to GN5, Q1 | `tests/integration/codes-cli.test.ts`, `tests/unit/code-sheet.test.ts`, `tests/e2e/code-sheet.spec.ts` |
| OB21 | jade-99j | GN3 | `codes-cli.test.ts`: second run and two simultaneous runs (section 13, T4) |
| OB22 | jade-99j | GN4, GN7 | `code-sheet.spec.ts` (decoded in Chromium and WebKit; black and white only); Mike's print and phone check (Q7) |
| OB23 | jade-99j | GN5 | `tests/unit/repo-hygiene.test.ts` (`var/` ignored), `codes-cli.test.ts` (in-tree path refused; the warning text) |
| OB24 | jade-q01 | SD1 to SD3, C2 | `tests/integration/seed.test.ts` |
| OB25 | jade-q01 | SD4 | `pnpm ci:clean-clone` with the seed step, elapsed time recorded (C16) |
| OB26 | jade-q01 | SD1 | `seed.test.ts`: each refusal with its own tag |
| OB27 | jade-pe9 | ST1 to ST5 | AC10 (waits) |
| OB28 | jade-pe9 | ST2 | the matrix test of jade-aq5 over every staff route and action (waits) |
| OB29 | jade-pe9 | ST4 | `tests/integration/staff-codes.test.ts` (waits) |
| OB30 | jade-pe9 | ST3 to ST5 | `staff-codes.test.ts`, `audit-subject.test.ts` (waits) |
| OB31 | jade-hap | PL1 to PL3 | `tests/unit/pools.test.ts`, `tests/integration/pools.test.ts` |
| OB32 | jade-4el | section 14 | filed when jade-7if merges; jade-7if's own tests stay (T1) |
| OB33 | jade-4el | section 14 | recorded in that bead; no Phase 2 step |
| OB34 | jade-4el | section 14 | recorded in that bead; no Phase 2 step |
| OB35 | jade-7if, jade-4el | RD5, C1 | `tests/unit/config.test.ts`: the override is refused outside `APP_ENV=test`; there is no per-IP limit to raise |
| OB36 | jade-4el, jade-q01 | SD2 | the seed's demo data is the only fixture; no real code exists in development |
| OB37 | all | INV11 | `schema-catalog.test.ts` (no column about a child); no route or form is added (AC11) |
| OB38 | all | INV11 | no Phase 2 code writes `device_sessions` or any activity table; the no-log test does not exist yet and is not touched |
| OB39 | jade-7if, jade-pe9 | RD3, C3, ST2 | `redeem.test.ts` (another owner's class is `class_not_found`); no route in Phase 2 |
| OB40 | all | INV1 | `no-plain-codes.test.ts`, `no-ip.test.ts`, `tests/blackbox/log-privacy.test.ts` (unchanged) |
| OB41 | jade-99j, jade-pe9 | GN4, ST1 | `code-sheet.spec.ts` (zero requests); `tests/e2e/no-offorigin.spec.ts` covers staff pages through the registry (waits) |
| OB42 | jade-q01 | SD2 | `product-agnostic.test.ts`; `content/` is not created |
| OB43 | all | sections 3 and 17 | AC13: the ADR diff is the new files only |
| OB44 | orchestrator | section 15 | AC12 |
| OB45 | orchestrator | section 15 | AC12: no human bead claimed |
| OB46 | orchestrator | section 15, Q5 | AC12 |
| OB47 | orchestrator | section 15 | AC12: out-of-scope finds become beads |
| OB48 | Mike | Q3 | answered before go-ahead |
| OB49 | orchestrator | preamble, section 15 | AC12 |
| OB50 | jade-pe9 | ST2 | Phase 2 adds no route (AC11); staff routes enter the matrix (waits) |
| OB51 | orchestrator | section 15 | gate exit statuses in each bead's notes |
| OB52 | orchestrator | section 15 | one pull request per bead, merged on green CI |
| OB53 | orchestrator | section 15 | stop points; jade-6is and jade-0za do not block (section 3, last paragraph) |
| OB54 | all | section 15 | stop point; Q1 and Q4 touch rule 4 questions and go to Mike |
| OB55 | all | section 15 | stop point; no agent runs anything against production (GN2) |
| OB56 | orchestrator | section 15 | stop point |
| OB57 | jade-7if | C1 | the bead's fourth acceptance line is followed |
| OB58 | jade-6is | C4, Q8 | the schema takes any `^[A-Z]{3}$` prefix; no prefix is chosen here |
| OB59 | jade-o07 | SC2 | `product-agnostic.test.ts`; `schema-catalog.test.ts` |
| OB60 | jade-fd5, jade-7if | CL6, RD3 | `tests/unit/module-boundaries.test.ts` |
| OB61 | jade-o07 | SC2, SC3 | `schema-catalog.test.ts` on PostgreSQL 16; Drizzle is the query layer |
| OB62 | jade-o07, jade-7if | SC8, RD1 | `pnpm ci:compat`, CI job `migration-compat` (section 13, T7) |
| OB63 | jade-o07, jade-q01 | SC2, SD2, C15 | `users` as written; no password library is added; `seed.test.ts` (the seeded hash is not a hash) |
| OB64 | jade-o07, jade-7if | SC2, RD3 | `schema-constraints.test.ts` (default false), `redeem.test.ts` (an attached kit has logging off) |
| OB65 | jade-fd5, jade-99j | CL1 to CL3, GN3 | `codes-format.test.ts`, `codes-hmac.test.ts`, `no-plain-codes.test.ts` |
| OB66 | Mike | Q1 | answered before jade-99j starts |
| OB67 | jade-fd5 | CL3, CL4, Q2 | ADR 0026; `codes-hmac.test.ts` pins the derivation; RR6 |
| OB68 | jade-99j, jade-pe9 | GN4, ST1 | as OB41 |
| OB69 | Mike | Q5 | Mike's Q4 answer stands; RR1 |
| OB70 | jade-7if | RD2, C1 | as OB19 |
| OB71 | jade-7if | RD2 | RR3; thresholds tuned by jade-6cq |
| OB72 | jade-7if | RD2, Q4 | `redeem-limits.test.ts` (the interaction cases); ADR 0027 |
| OB73 | jade-99j | GN2 | `codes-cli.test.ts`: production needs a terminal and a typed confirmation; no agent runs it |
| OB74 | jade-99j, jade-pe9 | GN4, ST1 | as OB41 |
| OB75 | jade-o07 | SC2 | `schema-catalog.test.ts`: names and types exactly as DATA-MODEL; no type is adjusted |
| OB76 | jade-o07 | SC2 | `schema-catalog.test.ts` (ids, `created_at`, `timestamptz`, text enums with checks) |
| OB77 | jade-o07 | SC2 | `schema-catalog.test.ts`, `schema-constraints.test.ts` |
| OB78 | jade-o07 | SC2, SC3 | same two tests; C14 (creation order) |
| OB79 | jade-o07 | SC2 | same two tests |
| OB80 | jade-o07 | SC2 | same two tests |
| OB81 | jade-o07 | SC1, SC2 | same two tests (case-insensitive unique email) |
| OB82 | jade-o07 | SC2 | same two tests (cascade from `users`) |
| OB83 | jade-o07 | SC2 | same two tests; `invites.role` has no check, as written (C14, Q8) |
| OB84 | jade-o07 | SC2 | same two tests |
| OB85 | jade-o07 | SC2 | same two tests |
| OB86 | jade-o07 | SC2 | same two tests (composite foreign key, cascade) |
| OB87 | jade-o07, jade-7if | SC2, SC5, RD4 | same two tests; `audit-subject.test.ts` |
| OB88 | jade-o07 | SC2 | `schema-constraints.test.ts`: a second live code for a kit fails; a revoked one does not count |
| OB89 | jade-o07, jade-7if | SC2, RD3 | `schema-constraints.test.ts`; `redeem.test.ts` (`kit_active_elsewhere`) |
| OB90 | jade-o07 | SC7 | `schema-catalog.test.ts`: `users.email` and `users.display_name` are the only personal columns |
| OB91 | jade-o07, jade-l13 | SC5, C10 | `tests/integration/kit-tables.test.ts`; the function and its deletion assertion wait for jade-l13 |
| OB92 | jade-o07, jade-8vo | SC5 | `device_sessions` is classified `activity`; deletion waits for jade-l13 and jade-8vo |
| OB93 | all | INV11 | as OB37 |
| OB94 | jade-o07 | SC2 | `schema-catalog.test.ts` (`users` columns) |
| OB95 | jade-o07 | SC2, SC4 | `schema-grants.test.ts` (who can read `users`) |
| OB96 | jade-o07, jade-7if | SC4, SC5, RD4 | `schema-grants.test.ts` (append-only for the app), `audit.test.ts` |
| OB97 | all | INV1 | `log-privacy.test.ts` (unchanged); no logger key is added |
| OB98 | all | INV1, INV11 | `no-ip.test.ts`; `schema-catalog.test.ts` (no address-typed or address-named column) |
| OB99 | jade-7if | C1 | no per-IP limit is built; the signup flag is jade-vcy's |
| OB100 | jade-o07, jade-7if | SC2, RD3 | as OB64; the confirmation columns exist and Phase 2 never writes them |
| OB101 | jade-vcy | section 14 | the `auth` module is not touched; `users.role` exists |
| OB102 | jade-fd5, jade-7if, jade-pe9 | CL6, RD3, ST3 | `module-boundaries.test.ts`; revoke waits for jade-pe9 |
| OB103 | jade-99j | GN3 | `tools/codes/`; `codes-cli.test.ts` |
| OB104 | all | CL6 | `module-boundaries.test.ts` |
| OB105 | jade-pe9 | ST2 | waits for jade-vcy |
| OB106 | jade-7if, jade-bu6 | RD3 | `redeem.test.ts` (into a class); the scan flow waits for jade-bu6 |
| OB107 | jade-fd5 | CL1 | `codes-format.test.ts`; the check character is always one of the 32 symbols |
| OB108 | jade-fd5 | CL3 | `codes-hmac.test.ts`; no code path computes a plain hash of a code (grep case in the same file) |
| OB109 | jade-99j | GN3 | `no-plain-codes.test.ts`; `codes-cli.test.ts` (nothing on stdout) |
| OB110 | jade-o07, jade-7if | SC4, RD3 | `schema-grants.test.ts` (the app cannot update or delete `kits`); `redeem.test.ts` (the kit id is the code's) |
| OB111 | jade-7if, jade-pe9 | RD3, RD4, ST3, ST4 | T1, `audit.test.ts`; revoke and reissue wait for jade-pe9 |
| OB112 | jade-fd5, jade-lnn.1 | CL4, RD6 | ADR 0026; section 14 note to jade-lnn.1; RR6 |
| OB113 | jade-fd5, jade-7if | CL1, RD2 | as OB12 and OB17 |
| OB114 | jade-fd5 | CL3 | as OB14 |
| OB115 | jade-pe9 | ST2 | waits for jade-aq5 |
| OB116 | all | INV1 | `no-ip.test.ts` |
| OB117 | jade-o07, jade-7if | SC8, RD1 | as OB62 |
| OB118 | jade-fd5, jade-7if | CL1, RD2 | as OB12, OB17 and OB19 |
| OB119 | jade-fd5, jade-o07 | CL3, SC7 | as OB14 and OB10 |
| OB120 | jade-pe9 | ST2 | waits for jade-aq5 |
| OB121 | jade-7if, jade-6cq | RD2 | RR3 |
| OB122 | jade-99j, Mike | Q1 | `log-privacy.test.ts` already sends a code in `/redeem?code=`; Phase 2 adds no route |
| OB123 | Mike | Q1 | answered before jade-99j starts; RR2 |
| OB124 | jade-o07 | SC2 | the table is created and never written in Phase 2; RR5 |
| OB125 | jade-7if, Mike | RD1, RD2, Q4 | ADR 0027 and the threat-model edit of RD6 |
| OB126 | jade-o07 | SC4 | `schema-grants.test.ts`: the app cannot delete `kits` or `kit_codes`; no deletion rule is added |
| OB127 | jade-7if | RD4, C9 | `audit-subject.test.ts`; RR4 |
| OB128 | jade-99j | GN3 | `codes-cli.test.ts` (the only-copy warning); destruction is not decided here (RR8, note to jade-lnn.2) |
| OB129 | jade-o07, jade-7if | SC3, RD1 | `pnpm db:check --base`, `migrations-static.test.ts` |
| OB130 | jade-o07, jade-7if | SC3, RD1 | `migrations-static.test.ts`, `migrate.test.ts` |
| OB131 | jade-o07, jade-7if | SC8, RD1 | as OB62 |
| OB132 | jade-o07, jade-7if | SC6 | `pnpm db:check`: no Phase 2 file has a destructive statement |
| OB133 | jade-o07, jade-7if | SC3 | `pnpm db:check` |
| OB134 | jade-o07, jade-7if | SC4, SC6, RD1 | `pnpm db:check` (a table without a grant in its file is refused), `schema-grants.test.ts` |
| OB135 | jade-o07, jade-7if | SC3, RD1 | `pnpm db:check`; the pull request holds the `.sql`, `manifest.json` and `meta/` together |
| OB136 | jade-o07 | SC3 | `drizzle-kit generate` only; no script calls `migrate` or `push` (`migrations-static.test.ts` case over `package.json`) |

## 3. Contradictions and gaps

C1 to C19 are the brief's items, in its order. C20 to C22 were found while planning.

- **C1, per-IP limit.** Settled by OB57 and ADR 0020: jade-7if limits failed redemptions per account and by a global failed-code throttle, with no per-IP limit. No Phase 2 code reads a client address (INV1, `no-ip.test.ts`). jade-4el's note about per-IP limits is corrected when its configuration bead is filed (section 14).
- **C2, seed refusal.** Settled, stricter than the bead: `pnpm db:seed` runs only when `APP_ENV` is `development` or `test`, `NODE_ENV` is not `production`, and both database URLs name a loopback host without a query string. So it is refused on staging and production, by `APP_ENV` and again by `NODE_ENV`, since the image sets `NODE_ENV=production` for both (SD1).
- **C3, rule 3 and `classId`.** Settled as a reading, listed for Mike in Q8: the user comes from the session only (Phase 2 has no route; `redeemCode` takes the user id from its caller, which in Phase 3 is the session); the kit comes only from the code lookup; `classId` is the adult's chosen target and is accepted only for a class that this user owns and that has not ended, otherwise the outcome is `class_not_found`, which a route answers with 404, never 403.
- **C4, normalisation and the prefix; the check character.** Settled without touching the DATA-MODEL constraint. Parsing is by position: the first three characters are the prefix and are only upper-cased; O, I and L are mapped to digits only in the nine characters after it, so a prefix containing those letters is never corrupted. A digit in a prefix position is malformed. The check character is one symbol of the 32-symbol alphabet, computed over the prefix and the body in GF(32) (CL1), which rejects every single-character substitution at every position; the proof is by exhaustion (CL5). The tools warn about a prefix containing I, L, O or U; restricting prefixes in the schema is not done (Q8).
- **C5, plain codes in the repository.** Settled: the repository holds no code. The seed derives its fifteen codes at run time from a reserved range that the generator never produces and that `redeemCode` refuses outside development and test (CL2, RD3, SD2). Three independent layers keep a known code from ever redeeming on staging or production; each has a test.
- **C6, the QR URL.** Raised, Q1. Nothing is settled here; jade-99j does not start before the answer.
- **C7, "redeemed exactly once" without a redeem page.** Settled: Phase 2 shows it at service level, on codes the generator itself produced and wrote to its CSV (`code-lifecycle.test.ts`, AC2). The browser flow (sign-in, the redeem page, the scan) is the acceptance of jade-vcy and jade-bu6.
- **C8, counters.** Raised for storage (Q4), settled for semantics (RD2): only an unknown, well-formed code counts as a failed attempt; ten of them within any sixty minutes lock the account for one hour from the tenth; nobody lifts a lock early in Phase 2; the global throttle counts the same failures across all accounts in a ten-minute window; a per-account row lock makes the account limit exact under concurrency.
- **C9, the audit log.** Settled: a closed list of actions, each with an exact subject shape whose values can only be row ids, integers and booleans (SC5, RD4). Failed redemptions are not audited one by one; a lockout and a throttle trip are, once each. No audit row holds anything about a child: actors are adults, subjects are anonymous kit, class, batch, product and code-row ids. Kit ids inside `subject` are records of adult actions and are not kit activity; they outlive a kit deletion on purpose (RR4).
- **C10, `delete_kit_data` coverage.** Settled without building Phase 9 work: a committed classification of every table with a `kit_id` column, and a test that fails when such a table is unclassified (SC5). jade-l13 consumes it (section 14).
- **C11, jade-pe9 before Phase 3.** Settled: specified in section 12, not implementable, the epic stays open. The reissued code is shown once in a POST response with `Cache-Control: no-store` and exists nowhere else (ST4).
- **C12, output location.** Settled: by default the files go outside the work tree; inside it only `var/codes/` is accepted, which `.gitignore` and `.dockerignore` list; any other in-tree path is refused (GN5).
- **C13, the QR origin.** Settled: `--origin` is a required flag with no default. A batch generated before the production domain is fixed carries dead QR codes (the typed code still works), so the production batch waits for the domain (jade-0za, jade-151); that is stated in the note to jade-lnn.2 and jade-t17 (section 14).
- **C14, DATA-MODEL details.** Settled: Drizzle Kit emits every `CREATE TABLE` first and the foreign keys afterwards, so `code_batches.created_by` can reference `users` (SC3 checks the generated file); `device_sessions` gets exactly its composite foreign key; `invites.role` gets no check and `users.role` keeps its own, as written (Q8); `citext` is created by the owner in a migration of its own (SC1); every table's grants are in its file, least privilege per table (SC4).
- **C15, seed users without a password library.** Settled: no library is added. The seeded staff user and facilitator get the fixed `password_hash` `!`, which is not an argon2id encoding and can match no password. jade-vcy decides how development sign-in works and must treat a value that is not a valid encoding as "cannot sign in" (section 14). No development password exists, so none can reach staging or production.
- **C16, "usable in under 5 minutes".** Settled as a definition: after the README's setup block, which gains `pnpm db:seed`, `pnpm dev` answers `/` with 200 and `/readyz` with 200 (`migrations: ok`), and the seeded rows exist (the setup block runs under `bash -e`, so a failed seed stops it). `pnpm ci:clean-clone` prints the seconds from the start of the setup block to those two answers; its dev smoke runs before its `pnpm test` and `pnpm e2e`, which are not part of the figure (SD4). The criterion is met when that figure is at most 300 on the development machine with a warm pnpm store, cached Playwright browsers and pulled images; a first-ever download is not counted (RR13).
- **C17, separate planloops.** Raised, Q3.
- **C18, the pepper.** Raised for the permanent choices (Q2); the recommended derivation, its record (ADR 0026) and the mismatch check are in CL3, CL4 and RD1.
- **C19, who may mint.** Settled: the generator and the seed connect as `jade_owner` (the migration URL). `jade_app` has no INSERT on `products`, `code_batches` or `kits`, so the running app cannot mint a kit. A product row is created by `pnpm codes:product` (GN2) or by the seed; no migration inserts one.
- **C20, Phase 1's hand-off against jade-t17.** The Phase 1 plan handed jade-99j the note "refuse to run in production through `APP_ENV`", but jade-t17 (human) runs the generator against production. Settled: the generator and the product tool are not refused outright under production; they are refused unless an operator at a terminal confirms (GN2), and no agent runs them there. The seed keeps the outright refusal.
- **C21, Phase 1's one-migration tests.** `migrations-static.test.ts` asserts that no migration creates a table, and several other Phase 1 tests assume that `0000_baseline` is the only shipped migration (section 1). Settled: SC6 replaces the "creates no table" case with one that ties the created tables to `schema.ts`, and SC9 lists every other assertion that changes, each a stated replacement with the same meaning, not a weakened check.
- **C22, the compat job against catalog tests.** A test that enumerates the catalog or the grants on a template clone would fail in the `migration-compat` job as soon as a later head adds a table or a grant, although nothing is incompatible. Settled by PD1.

Not a contradiction but stated: jade-8n2.4 (letters A to D) adds nothing to Phase 2's schema; jade-6is does not block this phase, and `RETENTION_MONTHS` is not read.

## 4. Cross-cutting decisions

- **PD1, two kinds of database test.** A test that asserts on the whole catalog or on privileges (every table, every `kit_id` column, every grant, every text column) runs on a database it creates empty and migrates with this checkout's own `migrations/` (new helper `createOwnSchemaDatabase()` in `tests/support/db.ts`). A behaviour test runs on a clone of the template. Reason: in the `migration-compat` job the template is migrated by a newer head, so a base test that enumerates the catalog on a clone would fail on a table or grant the head added, which is not an incompatibility; and behaviour tests on clones are exactly what proves the previous release still works on the new schema.
- **PD2, outcomes are values.** `redeemCode` and the tools report every expected refusal as a returned outcome or a fixed tag, never by throwing; a transaction is rolled back only by an unexpected error. So a counted failure commits with its counter, and a rollback always means "nothing happened". Tool tags are fixed strings registered with the logger, as `db:reset`'s are, and carry no value.
- **PD3, one clock.** Every window and lock time is computed by the database (`now()`); tests move time by editing rows as the owner, never by faking a clock.
- **PD4, the plain code stops at the module edge.** Inside `codes`, a plain code is parsed, turned into its HMAC and dropped. Only the 32-byte HMAC is passed to a query, so no SQL text or parameter, and therefore no Postgres log, can hold a code. The code tools (`tools/codes/`) write codes to the two output files only, never to stdout or stderr; the seed writes no file and prints only its fifteen derived development codes (SD2, GN8).
- **PD5, one lock order.** Every transaction that touches these rows takes its locks in this order: the account's counter row, then `classes` rows (ascending id when two), then `kit_codes` rows, then `class_kits`, and last the global throttle row. Section 12's staff actions follow the same order.
- **PD6, minting is the owner's.** Tools that create products, batches, kits and codes use the owner URL; the app role cannot (C19).
- **PD7, closed audit writer.** Audit rows are written only through `writeAudit()` (SC5), whose action list and subject shapes are closed.
- **PD8, tools stay image-ready.** `tools/codes/` and `tools/db/seed.ts` import only the `index.ts` of `config`, `db`, `log` and `codes` and production dependencies, and the pure files of `codes` import nothing from SvelteKit, so a later bead can run the generator in the image with one more `COPY` line (section 14). `module-boundaries.test.ts` gains both rules.
- **PD9, new dependencies.** `qrcode-generator` 2.0.4 (MIT, dependency: it encodes a string to a module matrix and does nothing else); `fast-check` 4.10.2 (MIT, devDependency, tests only); `jsqr` 1.4.0 (Apache-2.0, devDependency, decodes a bitmap in tests only). None opens a socket or reads a URL at run time; each is pinned exactly and the lockfile committed. No PDF library: the sheet is HTML. No argon2 library in this phase.

## 5. Invariants

Each names the checks that keep it. Unit, integration and black-box checks run in `pnpm test`; e2e in `pnpm e2e`.

- **INV1, plain codes and addresses.** A plain kit code exists only in process memory, in the generator's two output files and, in development, in the seed's terminal output. It is never in a table, a query parameter, a log line, an audit row or an error. The seed writes no file (GN8, SD6), and tests write the generator's files only under temporary directories that they remove. No Phase 2 code reads, stores or logs a client address. Kept by `no-plain-codes.test.ts` (after a generated batch, the seed and every redemption outcome, every row of every table rendered as text holds no code in dashed, undashed or lower-case form, and every query parameter recorded during the run is free of them), `seed.test.ts` and `codes-cli.test.ts` (no batch file and no `jade-code-batches` directory appears under the spawned tool's `HOME` or in the repository's `var/` after a seed run or a `none`-mode batch), `schema-catalog.test.ts` (column allowlist), `audit-subject.test.ts`, `no-ip.test.ts` (no source under `src/lib/server/codes`, `tools/codes` or `tools/db/seed.ts` mentions a client-address API or header; no column is typed `inet` or `cidr` or named like an address), and the unchanged `log-privacy.test.ts`.
- **INV2, single use.** A code row moves from `unused` to `redeemed` at most once, and the number of `code.redeem` audit rows equals the number of such moves. Kept by `redeem-concurrency.test.ts` and `audit.test.ts`.
- **INV3, status machine.** `kit_codes.status` moves only `unused` to `redeemed`, `unused` to `revoked` and `redeemed` to `revoked`; nothing leaves `revoked`; `redeemed_by` and `redeemed_at` are set exactly when a row becomes `redeemed` and never cleared. Kept by `redeem.test.ts` (every outcome leaves the row as the table in RD3 says) and, for the revoke edges, `staff-codes.test.ts` (waits).
- **INV4, the account limit is exact.** No interleaving lets an account record more than ten counted failures within sixty minutes, and a locked account redeems nothing, a valid code included. Kept by `redeem-limits.test.ts` (section 13, T3).
- **INV5, migrations.** Phase 2 migrations only add objects; merged files are never edited; each file carries its tables' grants; the previous release works on the new schema. Kept by `pnpm db:check --base`, `migrations-static.test.ts`, `migrate.test.ts`, `pnpm ci:compat` and CI job `migration-compat`, with PD1 keeping that job's verdict about compatibility only.
- **INV6, least privilege.** `jade_app` cannot run DDL, cannot insert a product, batch or kit, cannot insert, delete or re-key a code row, cannot update or delete an audit row or the key-check row, and cannot delete a kit, a user or a class. Kept by `schema-grants.test.ts` (each allowed verb succeeds and each refused verb fails with 42501, over the app pool) and `baseline-migration.test.ts`.
- **INV7, product-agnostic.** No schema object, migration, module or tool names a specific kit. Kept by `product-agnostic.test.ts`: no migration inserts into `products`; `slug`, `name` and `code_prefix` have no default; every product literal in `tools/` and `tests/` comes from `tools/codes/demo.ts` (slug `demo`, name `Demo kit`, prefix `DEM`) or is one of the synthetic test prefixes `AAA`, `QRS` and `ZZZ`.
- **INV8, identity.** The redeeming user is a parameter that only a session supplies; the kit comes only from the code; a class is accepted only when the user owns it. Kept by `redeem.test.ts` and by AC11 (no route exists that could take a user from a body).
- **INV9, no other origin.** The printed sheet references nothing outside itself, and no new dependency makes a request. Kept by `code-sheet.test.ts` (no URL in any `src`, `href`, `@import` or `url()`; no `<script>`, `<link>`, `<img>` or `<iframe>`), `code-sheet.spec.ts` (zero requests when opened, Chromium and WebKit) and the unchanged `no-external-refs.test.ts`.
- **INV10, the pepper.** Key bytes and the HMAC message follow ADR 0026 and cannot change unnoticed; the pepper and the key never reach the logger, an error or a table; a process whose pepper differs from the one the stored codes were made with redeems nothing and mints nothing; under staging and production the stored key-check value is the app's own (RD8), so no batch is minted there before an app of that environment has stored it. Kept by `codes-hmac.test.ts` (known answers), `tests/integration/key-check.test.ts` and `codes-cli.test.ts`.
- **INV11, children and consent.** No Phase 2 table, row, audit subject, file or log line holds anything about a child; an attached kit always starts with `logging_enabled` false and no consent fields; Phase 2 writes no activity. Kept by `schema-catalog.test.ts`, `redeem.test.ts` and AC11.
- **INV12, pools.** The readiness limit applies to readiness queries only; every pool the process opened is ended on `sveltekit:shutdown`; a query in flight at shutdown finishes or fails whole. Kept by `pools.test.ts` (unit and integration).
- **INV13, one batch, one set of files.** For each product and label at most one batch commits; a batch made in `files` mode has its files published once, together, by one directory rename, or kept complete in a partial directory that a rerun publishes, and a batch made in `none` mode (the seed's, GN8) has no file at all; no run removes a partial directory whose transaction committed or may still commit; at most one `createBatch()` call reports that it created or published the batch (the seed's exit 0 on a verified existing batch reports neither). Kept by `codes-cli.test.ts` (section 13, T4, T5 and T10, and GN8's cases), `seed.test.ts` (SD6) and `tests/unit/codes-recovery.test.ts`.

## 6. jade-o07: core schema

- **SC1, `0001_citext.sql`.** Hand-written (`pnpm exec drizzle-kit generate --custom --name citext`, then `pnpm db:manifest`): `CREATE EXTENSION IF NOT EXISTS citext;` and nothing else.
- **SC2, `schema.ts`.** The eleven tables of DATA-MODEL sections 1 to 3, names and types exactly as written: `uuid` ids with `gen_random_uuid()`, `timestamptz`, `bytea` for `code_hmac`, `token_hash` and `join_code_hash`, `citext` for `users.email`, `text[]` with default `'{core}'`, `jsonb` for `audit_log.subject`, `bigint generated always as identity` for `audit_log.id`, every listed `unique`, `check`, `references` and `on delete cascade`, the composite primary key and composite foreign key, and the two partial unique indexes under their given names `one_live_code_per_kit` and `kit_in_one_active_class`. Types Drizzle lacks are declared with `customType`. Nothing is added that DATA-MODEL does not list (Q8) and no type is adjusted (OB75 allows it only when a test shows a reason; none has).
- **SC3, `0002_core_schema.sql`.** `pnpm exec drizzle-kit generate --name core_schema`, then `pnpm db:manifest` (the `db:generate` script cannot pass a name through its `&&`). The subagent reads the generated file against DATA-MODEL line by line; foreign keys must come after every `CREATE TABLE`; the file has no transaction-control or destructive statement. Both files, `manifest.json` and `meta/` are committed together.
- **SC4, grants, appended to `0002_core_schema.sql` by hand before it is merged.** To `jade_app`: `products`, `code_batches`, `kits`: SELECT. `kit_codes`: SELECT and UPDATE of the columns `status`, `redeemed_by`, `redeemed_at` only. `users`, `invites`, `classes`, `class_kits`, `device_sessions`: SELECT, INSERT, UPDATE. `auth_sessions`: SELECT, INSERT, UPDATE, DELETE. `audit_log`: SELECT, INSERT. Each verb is one that a documented feature of the table needs (DATA-MODEL, the Phase 3 phase file); a verb no documented feature needs is not granted, and a later bead that needs one adds it in its own migration (jade-pe9 adds INSERT on `kit_codes` for reissue). Granting the Phase 3 verbs now follows the README's rule that a table's grants sit in its file (Q6, RR14).
- **SC5, two small files in the `db` platform module, exported through its `index.ts`.** `kit-tables.ts`: `KIT_KEYED_TABLES`, mapping every table that has a `kit_id` column to `identity` (`kits`, `kit_codes`: never deleted by kit deletion), `membership` (`class_kits`: the consent record and display number) or `activity` (`device_sessions`: what `delete_kit_data` removes). `audit.ts`: `writeAudit(tx, entry)`, the only writer of `audit_log`, whose `entry` is a union of the actions listed in RD4 and ST, each validated by a strict zod object with fixed keys whose values are uuids, non-negative integers or booleans, and null only in the keys that the action's shape marks nullable: in Phase 2 only `code.redeem`'s `class_id` (uuid or null) and `display_number` (integer or null), which are null together or set together.
- **SC6, static checks.** `tools/db/check-migrations.ts` gains: every `CREATE TABLE` in a file has a `GRANT ... TO jade_app` for that table in the same file, or a line `-- jade:no-app-grant <table>` giving the reason. `migrations-static.test.ts`: the Phase 1 case "creates no table" is replaced by a case that the set of tables created by `migrations/` equals the tables `schema.ts` declares (C21), and gains a case that no `package.json` script runs `drizzle-kit migrate` or `push`.
- **SC7, tests** (`pnpm test`). `schema-catalog.test.ts` (PD1, own database): tables, columns, types, nullability, defaults, constraints and indexes read from the catalog equal a literal transcribed from DATA-MODEL; every column whose type can hold free text (`text`, `citext`, `text[]`, `jsonb`) is on an allowlist with its purpose, and every column whose name contains `code`, `token`, `secret`, `password` or `pepper` is one of `code_hmac`, `token_hash` (three tables), `join_code_hash` (all `bytea`), `password_hash` and `code_prefix`; so a column that could hold a plain code or token cannot be added without editing the allowlist in review. `schema-constraints.test.ts` (clone): for every `not null`, `unique`, `check`, foreign key, cascade, default and partial index of sections 1 to 3, one row that violates it, expecting the SQLSTATE and the constraint's name, and one neighbouring row that is accepted, so a test cannot pass because another constraint refused first. `schema-grants.test.ts` and `kit-tables.test.ts` (PD1): INV6, and every catalog table with a `kit_id` column is a key of `KIT_KEYED_TABLES` and the reverse.
- **SC8, compatibility.** Before the pull request: `pnpm ci:compat` locally. Expected of the first real `migration-compat` run: step 1 leaves both ledgers equal to the three-entry manifest; step 2, the Phase 1 build answers `/readyz` 200 because its one shipped migration is a prefix of the ledger; step 3, the base's five integration files pass, since none asserts the absence of tables. If the job fails for a reason in the harness (a timeout, the worktree, the install), the orchestrator files a bug bead and uses the bugfix skill; the job is never skipped, made optional or weakened, and jade-o07 does not merge until it is green. Three different failed fixes are a stop point.
- **SC9, Phase 1 tests that assume one shipped migration** (C21). Stated replacements, each keeping its assertion's meaning, with `next` the four-digit number after the last shipped migration (`String(manifest.migrations.length).padStart(4, '0')`, as the compat self-test numbers its fixture). `tests/integration/role-bootstrap.test.ts` lines 47 and 135: `applied` equals the names of `readManifest(MIGRATIONS_DIR)`, not `['0000_baseline']`. `tests/integration/migrate.test.ts`: the extra files `0001_fails`, `0001_unlisted` and `0001_extra` become `<next>_fails`, `<next>_unlisted` and `<next>_extra`, so they sort after every shipped file as they did in Phase 1; the readiness case expects `applied` to be the shipped names plus `<next>_extra`, and the second run `{ applied: [], ahead: true, recorded: <shipped count + 1>, shipped: <shipped count> }` from the manifest's length. `tests/unit/migrations-static.test.ts`: the gap case adds a file numbered one after `next` and expects `number is not <next>`; the `0001_drop` and `0001_tx` copies become `<next>_drop` and `<next>_tx`, so the only problem in each is the one under test. `tests/infra/stack-up.test.ts:72` and `tests/infra/compose-up.test.ts:67`: the ledger equals the manifest's names (the stack-up case's title says "every shipped migration"). `tests/infra/compose-up.test.ts` lines 186 to 210: the fixture is renamed `tests/infra/fixtures/migrations/infra_fixture.sql`, copied in as `<next>_infra_fixture.sql`, and the expected ledger is the shipped names plus that one; `tools/ci/migration-compat.sh` line 253 reads the renamed file. `tests/integration/db-scripts.test.ts` and `baseline-migration.test.ts` stay as they are. Later migration beads keep these assertions derived from the manifest.

## 7. jade-fd5: kit code library

All in `src/lib/server/codes/`, pure TypeScript with no SvelteKit import, public API through `index.ts`.

- **CL1, format (`format.ts`).** Alphabet: `0123456789ABCDEFGHJKMNPQRSTVWXYZ`, a symbol's value being its index. A code is three prefix letters, eight body symbols and one check symbol; display form `PREFIX-XXXX-XXXX-C`, canonical form the same twelve characters without dashes. `parseCode(input)`: refuse input longer than 64 characters or with a character outside printable ASCII; remove spaces, tabs and hyphens; upper-case; require exactly twelve characters; positions 1 to 3 must be `A` to `Z` and are kept as they are; in positions 4 to 12 map `O` to `0` and `I` and `L` to `1`, then require alphabet symbols (`U` is refused); verify the check symbol. It returns the canonical and display forms, or `invalid`. Check symbol: arithmetic in GF(32) with reduction polynomial x^5 + x^2 + 1 and generator 2, whose powers for exponents 0 to 11 are 1, 2, 4, 8, 16, 5, 10, 20, 13, 26, 17, 7. With s1 to s3 the prefix letters' values (A is 0, Z is 25) and s4 to s11 the body values, the check value is the XOR over i from 1 to 11 of (2^i times s_i), written as its alphabet symbol. Why every single-character typo is caught: changing position i from value a to value b changes the sum by 2^i times (a XOR b), a product of two non-zero field elements, which is never zero; the check position has weight 1. The weights are distinct, so a swap of two body or check characters, or of two prefix letters, is caught too. ARCHITECTURE.md's sample code is a format illustration and does not validate under this, or any, stated algorithm.
- **CL2, generation (`generate.ts`).** `generateCode(prefix)`: five bytes from `crypto.randomBytes` give forty bits, read as eight 5-bit symbols, so the draw is uniform with no modulo bias. A body whose first four symbols are `0000` is redrawn: that range (one in 2^20) is reserved for development codes and is never produced.
- **CL3, HMAC (`hmac.ts`).** `codeKey(pepper)`: the key is the UTF-8 bytes of the `CODE_PEPPER` string exactly as configured (Q2). `codeHmac(key, canonical)`: HMAC-SHA256 over the twelve ASCII bytes of the canonical form, 32 bytes. `hmacEquals(a, b)`: `crypto.timingSafeEqual` after a length check; it is used wherever two HMACs meet in code (the row returned by the lookup, the key check, the generator's verification of a partial file). The lookup itself is an index probe in Postgres, which is not constant-time; that is accepted because the probe value is a keyed HMAC an attacker cannot choose (RR6). `keyCheckValue(key)`: HMAC-SHA256 of the ASCII label `jade:code-key-check:v1`, which no canonical code can equal. The key and the pepper are never passed to the logger and never appear in an error.
- **CL4, ADR 0026 "Kit code check character, HMAC key bytes and message form"** (Status, Date, Source, Related; Context, Decision, Consequences), written from Q2's answer, with a row in the ADR README index and a row in its "Amendments to the handoff documents" table: `ARCHITECTURE.md` section 6, the sample code `ARM-7KQ4-XM2H-9`, which does not validate under this ADR; not edited, the ADR is current. It records the alphabet, the check-symbol algorithm, the key derivation, the message form, the reserved range, the key-check label and the known answers below, and states that changing any of them after a card is printed is a pepper-rotation-sized event.
- **CL5, tests** (`pnpm test`). Known answers, computed for this plan with Python's `hmac` and a separate GF(32) routine, not with production code, and frozen as literals: `DEM-0000-0001-Y`, `DEM-0000-0002-Q`, `DEM-0000-000F-H`, `DEM-7KQ4-XM2H-T`, `ZZZ-ZZZZ-ZZZZ-J`, `AAA-0000-0000-0`, `QRS-0123-456Z-N`; under the pepper string `test-only-kat-pepper-00000000000000000000000`, `DEM00000001Y` gives `06b4daa8d04ae93cecae33cc873959faf2268992a742a268acd6d2ac86d0abcb`, `DEM7KQ4XM2HT` gives `805dcff78208629b338dcd74b05583b5fe5a3205b18ddf1071e6814536d26477`, and the key-check label gives `9abb695193446616aa01669330788e6087082a8732c201aa49f2e67cf373af62`. The tests judge production output against these literals and against properties, never against a second implementation of the check symbol or the HMAC. Properties (fast-check, seed printed on failure): `parseCode(generateCode(p))` returns the same code for any prefix; display and canonical forms round-trip; lower case, missing dashes, extra spaces and O, I, L in the body parse to the same canonical form. Typos, two ways: (a) for every position 1 to 12 and every ordered pair of distinct values legal there, the production field multiply of the position's weight and the XOR of the pair is non-zero, which with linearity covers every code that can exist; (b) through `parseCode` itself, for at least 2,000 generated codes, all 354 single-character substitutions (25 other letters at each prefix position, 31 other symbols at each of nine positions) are `invalid`. Generation: 100,000 draws contain no reserved body and every symbol at every position. `codes-hmac.test.ts` also asserts that the sources of `codes` call `createHash` nowhere on a code.
- **CL6, boundaries.** `module-boundaries.test.ts` adds `codes` to the folders that import nothing from SvelteKit (PD8).

## 8. jade-hap: database pools

Decision: two pools, on purpose. Readiness keeps a small pool of its own; the app's queries get a second one. Reason: readiness answers "can this process reach its database and is the schema the one it ships", for the deploy health gate and the uptime probe; on a shared pool a burst of slow app queries would hold every connection and turn `/readyz` red although the database is healthy, and the 2-second limits would have to be re-imposed per query by discipline rather than by construction. The cost is at most two extra connections.

- **PL1, `src/lib/server/db/pools.ts`.** A registry of every pool the process opens; `getAppPool()` and `getDatabase()` create the app pool lazily (max 10, `connectionTimeoutMillis` 5 s, `statement_timeout` 15 s, `lock_timeout` 5 s, `idle_in_transaction_session_timeout` 30 s) and Drizzle over it; `closeAllPools()` ends every registered pool once and makes later `getDatabase()` calls throw the fixed tag `DB_CLOSED`.
- **PL2, readiness.** Its pool drops to max 2, keeps its 2-second limits and is created through the registry. `closeDatabase()` in `http` calls `closeAllPools()`; `hooks.server.ts` is unchanged.
- **PL3, tests.** `tests/unit/pools.test.ts`: the registry ends each pool exactly once, also when one `end()` rejects; the readiness options are not the app pool's. `tests/integration/pools.test.ts`: a query on the app pool that sleeps 3 seconds succeeds (the readiness limit does not apply to it) while `checkReadiness()` still answers within its limit; with ten app connections held, `checkReadiness()` is still `db: ok`; after `closeAllPools()` both pools report ended and `getDatabase()` throws `DB_CLOSED`; T9 of section 13.

## 9. jade-7if: redemption service

- **RD1, `0003_code_support.sql`** (generated from `schema.ts`, grants appended; additive only). Three tables that DATA-MODEL does not list (Q4 for the first two, Q2 for the third):

```sql
create table code_attempt_limits (
  user_id         uuid primary key references users(id) on delete cascade,
  recent_failures timestamptz[] not null default '{}' check (cardinality(recent_failures) <= 10),
  locked_until    timestamptz
);
create table code_attempt_throttle (
  id                boolean primary key default true check (id),   -- one row
  window_started_at timestamptz not null default now(),
  failures          int not null default 0 check (failures >= 0)
);
create table code_key_check (
  id          boolean primary key default true check (id),         -- one row
  check_value bytea not null,
  created_at  timestamptz not null default now()
);
```

  The file inserts the single throttle row. Grants to `jade_app`: `code_attempt_limits` SELECT, INSERT, UPDATE; `code_attempt_throttle` SELECT, UPDATE; `code_key_check` SELECT, INSERT (its one-row key bounds the insert; no UPDATE or DELETE). None has a `kit_id`, a code, a token or an address. Who stores the `code_key_check` value and who only compares is RD8: in staging and production the app stores it and the generator compares.
- **RD2, limits (`limits.ts`).** Constants: ten failures, sixty minutes, a one-hour lock; globally 100 failures in a ten-minute window (initial values; jade-6cq tunes and tests the global one). A failed attempt is counted only for the outcome `not_found`. A malformed code never reaches the database; `revoked`, `already_redeemed`, `already_yours`, `kit_active_elsewhere` and `class_not_found` are refusals of a real code or a wrong target, not guesses, and counting them would lock a facilitator who rescans cards a colleague already redeemed. On a counted failure, inside the redemption transaction and under the account row's lock: drop entries older than sixty minutes from `recent_failures`, append `now()`; at ten entries set `locked_until` to `now()` plus one hour, empty the array and write the audit row `code.lockout`; then add one to the throttle row (restarting its window when it is older than ten minutes) and, when the count reaches the limit exactly, write `code.throttle`. Interaction (OB72): a locked account is refused before any lookup and adds nothing to the global count; while the throttle is tripped every attempt is refused before the lookup and adds nothing to any account. The throttle is read without a lock, so it can overshoot by at most the number of concurrent attempts, bounded by the pool size (RR3); the account limit cannot (INV4).
- **RD3, `redeemCode(db, { userId, code, classId? })` (`redeem.ts`), one transaction at READ COMMITTED.** Steps: (1) `parseCode`; `invalid`, or a reserved-range body when `APP_ENV` is not `development` or `test`, returns `invalid_code` with no query. (2) The key check of RD8 in create mode, `ok` cached; on `mismatch`, return `unavailable` and log the registered tag `CODE_PEPPER_MISMATCH`, at most once a minute. (3) Compute the HMAC; the plain code is not used again. (4) Begin; insert the account's limit row if absent and select it `FOR UPDATE`; if `locked_until` is in the future return `locked`. (5) With `classId`: select the class where `owner_id` is the user and `ended_at` is null, `FOR NO KEY UPDATE`; none returns `class_not_found`. (6) Read the throttle row; tripped returns `throttled`. (7) Select the code row by `code_hmac` `FOR UPDATE`, and confirm it with `hmacEquals`. (8) Decide:

| Row found | Outcome | Writes |
|---|---|---|
| none | `not_found` | the counters of RD2 |
| `revoked` | `revoked` | none |
| `redeemed` by another user | `already_redeemed` | none |
| `redeemed` by this user | `already_yours` | with `classId` and the kit active in no class: attach, audit `kit.attach`; otherwise none |
| `unused`, and with `classId` the kit is active in another class | `kit_active_elsewhere` | none; the code stays `unused` |
| `unused` otherwise | `redeemed` | status, `redeemed_by`, `redeemed_at`; with `classId` attach; audit `code.redeem` |

  Attach: if a `class_kits` row for this class and kit exists, set it active again and keep its number; otherwise insert with `logging_enabled` false, no consent fields and a `display_number` equal to the kit's `serial` when no row of the class has it, else one more than the class's highest number. A number therefore never changes once given, a detached kit keeps its number reserved, and the class lock of step 5 makes the choice race-free. Idempotency: a second call for the same code by the same adult (a double submit, a rescan, or the scan that follows a code-gated signup) is `already_yours`, changes nothing but a missing attachment, and is not a failed attempt. Messages: one fixed sentence per outcome in `messages.ts`; `invalid_code` and `not_found` share one, and none names a person, a time, a class or a kit; that is the sense of "non-leaky" here, since "already used" and "no longer valid" are distinct by requirement (OB15) and reveal only that a spent code was real. A seam for jade-vcy: the body from step 4 on is exported as `redeemWithin(tx, ...)` with the account limit optional, so signup can create the user and redeem in one transaction under the global throttle; its use is jade-vcy's plan.
- **RD4, audit actions of this bead** (through `writeAudit`): `code.redeem`, actor the user, subject `{ kit_id, code_id, class_id, display_number }` (the last two null without a class); `kit.attach`, `{ kit_id, class_id, display_number }`; `code.lockout`, `{ failures }`; `code.throttle`, actor null, `{ failures }`. "Who redeemed which kit and when" is `actor_id`, `subject.kit_id` and `at`.
- **RD5, limits override for tests and the FaultForge sandbox.** One optional config key, `CODE_LIMITS_OVERRIDE`, whose only accepted form is `test-only:account=<n>,global=<n>`. The config module's existing rule refuses any value containing `test-only` unless `APP_ENV` is `test`, so the app does not start with it set under development, staging or production; `.env.example` documents it. jade-7if adds no route.
- **RD6, documents, after Q4 and Q2.** ADR 0027 "Failed-code counters: storage and semantics" (what counts, the windows, the lock, the interaction left open by ADR 0020, the initial global threshold) with its README row; DATA-MODEL.md gains the three tables as a short section; PRIVACY.md's data inventory gains a row for the counters (an adult's account id, failure times, a lock time; no child, no address); `docs/threat-model.md` section 4 (`RL_MEM`) and section 6 ("Rate-limit counters") say where the redeem counters live. `docs/adr/README.md` also gains two rows in its "Amendments to the handoff documents" table: `DATA-MODEL.md`, the new section on the code-support tables, amended by 0027 and 0026 (the key-check table is Q2's), corrected in place; and `PRIVACY.md` "Data inventory", the counters row, amended by 0027, corrected in place. `docs/threat-model.md` is not a handoff document, so ADR 0027's Consequences name its edit instead. Each edit is shown to Mike in the pull request; none changes a rule or an ADR's decision.
- **RD7, tests** (`pnpm test`). `redeem.test.ts`: every row of the table above, with the exact rows written and not written, the message, a class of another owner and an ended class as `class_not_found`, the reserved range refused under a non-development `APP_ENV`, and the display-number rules. `redeem-concurrency.test.ts`, `redeem-limits.test.ts`: section 13, T1 to T3. `audit.test.ts`: the rows of RD4, and that the subject and every other column of the rows written during a redemption contain no code. `audit-subject.test.ts`: a subject with an extra key, a string that is not a uuid, a code-shaped string or free text is refused by `writeAudit`; for every action, null in each key that its shape does not mark nullable is refused; `code.redeem` with exactly one of `class_id` and `display_number` null is refused, and with both null is accepted. `key-check.test.ts`: a process with another pepper gets `unavailable` and writes nothing; T11 of section 13; `checkReadiness()` on a database without the row stores the app's value and answers `codes: ok`, and with another stored value answers `codes: mismatch` while `/readyz` answers 503; after the owner's guarded removal of a wrong row while `kit_codes` is empty (T6), the next check stores the app's value, and the same removal deletes nothing once a code row exists; the app role's UPDATE and DELETE on the row fail with 42501. `readiness.test.ts`: the literals of RD8. `config.test.ts`: the override's refusals, each by its own reason code. The literals of `schema-catalog.test.ts` and `schema-grants.test.ts` gain the three tables and their grants.
- **RD8, the key check, one mechanism for every process** (`key-check.ts` in `codes`, exported through `index.ts`). `ensureCodeKey(db, key, mode)`: in create mode it runs `INSERT INTO code_key_check (check_value) VALUES ($1) ON CONFLICT (id) DO NOTHING` and then, as a separate statement, reads the row; in require mode it only reads; it compares with `hmacEquals` and returns `ok`, `mismatch` or, in require mode, `absent`. Who uses which mode: the app, in every `APP_ENV`, in create mode, from `checkReadiness()` (after `migrations` is `ok`, inside its 2-second limit, over the readiness pool) and from `redeemCode` step 2, so an environment's value is the app's own from its first `/readyz` answer, which every deploy's health gate requests; the generator and the seed in create mode under development and test; the generator in require mode under staging and production (the seed is refused there, SD1); `codes:product` computes no HMAC and does no check (GN1). A process caches `ok` and does not cache `mismatch`, so the owner's removal of a wrong first row (T6) takes effect without a restart. `checkReadiness()` gains the check `codes: 'ok' | 'mismatch' | 'unknown'` (`unknown` whenever the database or the migrations are not ok), and `/readyz` answers 200 only when all three are ok (Q2(5)); `src/routes/readyz/+server.ts` calls an exported `isReady(checks)` instead of comparing two fields and adds no route. `readinessOfFailure()` returns `codes: 'unknown'`, so the literals of `tests/unit/readiness.test.ts` gain that field, a stated replacement with the same meaning; `tools/ci/compat.ts` is unchanged, since a 503 with `migrations: ok` is not a schema verdict there. The app role holds SELECT and INSERT only (RD1), so an app can add the row when it is absent and can never change or remove it.
- **RD9, every test that reads a readiness body, swept for the new `codes` field** (section 1). Stated replacements, each keeping its assertion's meaning and still comparing the whole object: `tests/unit/readiness.test.ts`, every `readinessOfFailure` literal gains `codes: 'unknown'` (as RD8 says); `tests/blackbox/health.test.ts`, the `checks` parameter of `expectNotReady` becomes `{ db: string; migrations: string; codes: string }`, the two `db: fail` cases expect `{ db: 'fail', migrations: 'unknown', codes: 'unknown' }` and the empty-database case `{ db: 'ok', migrations: 'behind', codes: 'unknown' }`, and the 200 case keeps `{ status: 'ready' }`, since a migrated clone has no key-check row and the app stores its own value; it gains one case: on a clone where the test, as the owner, inserted a key-check row computed under another generated pepper, `/readyz` answers 503 through `expectNotReady` with exactly `{ db: 'ok', migrations: 'ok', codes: 'mismatch' }`. `tests/unit/compat.test.ts` builds bodies as inputs, which `classifyReadyz` reads only for `db` and `migrations`; its cases stay, and it gains one: a 503 with `{ db: 'ok', migrations: 'ok', codes: 'mismatch' }` is `COMPAT_EXIT.step2Other`, not a schema verdict, the reading RD8 gives `tools/ci/compat.ts`. `tests/blackbox/request-id.test.ts`, `tests/infra/compose-up.test.ts` and `tests/integration/migrate.test.ts` read no `checks` object and do not change.

## 10. jade-99j: batch generator

- **GN1, configuration.** `loadCodeToolConfig(env, { pepper })` in the config module: `APP_ENV`, `MIGRATION_DATABASE_URL` and, for the generator and the seed, `CODE_PEPPER`, with the app's rules; `codes:product` computes no HMAC, does no key check and does not read the pepper. A missing or malformed pepper is a `ConfigError` naming the variable, before any connection.
- **GN2, `pnpm codes:product --slug <slug> --name <name> --prefix <AAA>`** (`tools/codes/product.ts`, owner role): inserts the product, or does nothing when an identical row exists, or refuses with `CODES_PRODUCT_DIFFERS`; it never updates. It warns when the prefix contains I, L, O or U. Audit `product.create`, `{ product_id }`. Under `APP_ENV=production` this tool and the generator refuse unless stdin is a terminal and the operator types the slug and label back (`CODES_PRODUCTION_NEEDS_OPERATOR`); under staging and production they also require `--confirm <slug>/<label>` (C20). No agent runs either against production (OB73).
- **GN3, `pnpm codes:generate --product <slug> --batch <label> --count <n> --origin <origin> [--out <dir>] [--paper a4|letter]`** (`tools/codes/generate.ts`; the work is `createBatch()` in `tools/codes/batch.ts`, which the seed and the tests call too; the recovery decision is a pure function in `tools/codes/recovery.ts`). Order of work: (1) validate the arguments (count 1 to 1,000; label `[a-z0-9][a-z0-9-]{0,62}`; an `https` origin, or `http://localhost` under development and test), the product (`CODES_UNKNOWN_PRODUCT`) and the output root (GN5). (2) The key check of RD8: in require mode under staging and production, where an absent row is `CODES_KEY_CHECK_ABSENT` ("the app of this environment has not answered `/readyz` on this database yet"), and in create mode under development and test; a different value is `CODES_PEPPER_MISMATCH`; on either refusal nothing is inserted or written. (3) The label lock: on a connection of its own, `pg_try_advisory_lock(<namespace>, hashtext(product_id::text || ':' || label))`, the two-key form, whose key space does not overlap the migration runner's one-key lock; taken without waiting, held for the whole run until after step 8's directory fsync, released by closing that connection, and released by the server when the process dies. Not acquired is `CODES_BATCH_IN_PROGRESS` with nothing changed; two labels whose keys collide get the same answer, and a later rerun succeeds. (4) Holding the lock, settle every partial directory an earlier run left for this label (below); then, if the batch row exists, exit `CODES_BATCH_EXISTS` with nothing changed, and if the final directory exists without a batch row, `CODES_OUT_EXISTS` with nothing changed. (5) Begin; insert the batch row (a unique violation, which only a run that lost its lock can meet, is `CODES_BATCH_EXISTS` after a rollback); insert kits with serials 1 to n; insert each code row with `INSERT ... ON CONFLICT (code_hmac) DO NOTHING RETURNING id`, where no returned row means the HMAC already exists, committed before the statement or while it waited on it, and that serial draws again (with an explicit code list, the seed's, it is `CODES_CODE_EXISTS` and a rollback instead); audit `batch.create`, `{ batch_id, product_id, kits }`; read `pg_current_xact_id()`. (6) Write the CSV, the sheet and, last, a `SHA256SUMS` file of their hashes into the partial directory `<root>/<slug>/.<label>.<xid>.partial/`, whose name carries the transaction's id, created exclusively with mode 700, each file created exclusively with mode 600; fsync the files, the partial directory and its parent. (7) Commit. If the connection is lost during the commit, the outcome is decided by the transaction's id, never by looking for the batch row (T10): reconnect and read `pg_xact_status(xid)`, once a second for up to 30 seconds while it is `in progress`; `committed` goes on to step 8; `aborted` removes this run's partial directory and exits `CODES_NOT_COMMITTED` (nothing exists; rerun); still `in progress`, null, or no connection exits `CODES_COMMIT_UNKNOWN` with the partial directory kept for the rerun. (8) Publish: rename the partial directory to `<root>/<slug>/<label>/` with one `rename(2)`, which moves both files at once and fails when the target exists; fsync the parent; print the counts, the path and the warning that these two files are the only copy and the database cannot reproduce them; exit 0. A rename whose source has gone means that another run published it after this run lost its lock: `CODES_FINISHED_BY_OTHER_RUN`, naming the path. A target that exists: `CODES_PUBLISH_BLOCKED`, the partial directory kept. Nothing is printed that contains a code.
  Settling (step 4), for each partial directory `.<label>.<x>.partial` under the slug directory, reading `pg_xact_status(x)` first. `in progress`: `CODES_BATCH_IN_PROGRESS` with nothing changed (a live run that lost its lock, or a backend that has not yet noticed that its client died). `aborted`: remove the directory. `committed`: that transaction inserted this label's batch row; read the row in a new statement, and if `SHA256SUMS` matches both files, every code of the CSV is in that batch at its serial by HMAC (`hmacEquals`) and the counts agree, publish it as in step 8 ("finishing an interrupted run": exit 0, no new batch; a vanished source there is `CODES_BATCH_EXISTS`), otherwise `CODES_PARTIAL_MISMATCH` with nothing changed. Null (an id too old to know, or one from another cluster, which raises and is read as null): the transaction has ended; publish when the files verify against the batch row as above, remove the directory when there is no batch row, and otherwise `CODES_PARTIAL_MISMATCH` for the operator.
  Why this holds for every interleaving: a partial directory is read only after its transaction has ended, when its files are complete, since they were synced before its COMMIT was sent; a run removes only a directory whose transaction aborted, or ended with no batch row, and publishes only one whose files verify; and of several runs that try to publish one directory, the single rename lets exactly one succeed. The lock keeps a second run away from a live first run, so in the normal case it answers at once; the transaction ids and the single rename keep the rows and files right even when a lock is lost while its holder lives.
- **GN4, the two files.** CSV: header `kit_number,code`, one row per kit with the display form. Sheet: one HTML file, self-contained: inline CSS, a system font stack, one inline SVG QR per card (from `qrcode-generator`, error-correction level Q, four-module quiet zone), the code in large monospace type, the kit number, the product name (HTML-escaped) and the batch label; black on white only; eight cards a page, cards never split across pages; `@page` size from `--paper`. The QR text is the origin plus the path form Q1 fixes. No script, link, image or font reference.
- **GN5, where the files go.** The output root is `<home>/jade-code-batches/` by default, outside any work tree, or `--out <dir>`; a batch's files are `codes.csv`, `sheet.html` and `SHA256SUMS` in `<root>/<slug>/<label>/`, written first under `<root>/<slug>/.<label>.<xid>.partial/` (GN3). With `--out`: a path outside the repository is accepted; inside it, only a path under `var/codes/`, which this bead adds to `.gitignore` and `.dockerignore` as `var/`; any other in-tree path is `CODES_OUT_IN_REPO`, and the tool confirms with `git check-ignore` before writing inside a work tree.
- **GN6, tests.** `codes-cli.test.ts` (clone, temporary output directory, the tool run as the script runs it): rows and files for a batch; `CODES_BATCH_EXISTS` on a second run with nothing added; T4, T5, T6, T10 and T11 of section 13; under `APP_ENV=staging` with no key-check row, `CODES_KEY_CHECK_ABSENT` with no batch row and no directory, and with a row stored under another pepper, `CODES_PEPPER_MISMATCH` likewise (both with generated peppers, since a `test-only` value is refused outside `APP_ENV=test`); `createBatch()` called in-process with a test-only draw function whose first draw is an existing code draws again and commits n distinct codes, and an explicit code list holding an existing code is `CODES_CODE_EXISTS` with nothing committed; each refusal reached with inputs every earlier check accepts, asserting its tag; stdout and stderr hold no code; file modes (directories 700, files 600); the production and staging confirmations (with generated values, not the CI ones). `code-sheet.test.ts`: INV9's static half, one card per kit, colours limited to black and white, escaped product name. `code-sheet.spec.ts` (`pnpm e2e`, Chromium and WebKit): opening the sheet from a file URL makes no request; each QR, drawn to a canvas and decoded with `jsqr`, equals the URL for the code printed on the same card, which proves the encoding and the pairing, not a phone's camera. `code-lifecycle.test.ts`: `createBatch()` for the demo product, then every code read from the CSV redeems once through `redeemCode`, a second adult gets `already_redeemed`, and `no-plain-codes.test.ts` runs on the same database. `tests/unit/codes-recovery.test.ts`: the decision of GN3 (step 7 and the settling) for every transaction status, `committed`, `aborted`, `in progress` and null, against every batch-row and verification result, including `in progress` past the polling limit.
- **GN7, the human check (Q7).** Mike prints the demo sheet in greyscale and scans three cards with a phone; the result goes into the bead's notes. Without it the second acceptance line of jade-99j is not met.
- **GN8, the output modes of `createBatch()`, and every caller's files and reruns.** `createBatch(db, input, output)` takes `output` as a closed union: `{ mode: 'files', root, origin, paper }`, which runs GN3's steps 1 to 8 as written, or `{ mode: 'none' }`. `mode: 'none'` is accepted only with an explicit code list whose every body is in the reserved range of CL2, and only when `APP_ENV` is `development` or `test`; anything else is `CODES_NO_FILES_REFUSED` before any query, so a batch without files can hold only derivable development codes, which `redeemCode` refuses outside development and test, never a real code that would then exist nowhere. In `none` mode GN3 runs with these differences: step 1 checks the count, the label and the product, and takes no origin and no root; step 2 (the key check, create mode) and step 3 (the label lock) are unchanged; step 4 looks at no directory, and a batch row that exists is returned as the outcome `CODES_BATCH_EXISTS` with nothing changed; step 5 is unchanged (`CODES_CODE_EXISTS` for a code that exists); steps 6 and 8 are skipped, so no directory and no file is created anywhere; step 7 decides a lost COMMIT by the same `pg_xact_status` rule, `committed` being success, `aborted` `CODES_NOT_COMMITTED` and anything else `CODES_COMMIT_UNKNOWN`, with nothing on disk to keep or remove, and the rerun finds the batch row or does not. `tools/codes/generate.ts` always builds `mode: 'files'` from its flags and has no flag that selects `none` or passes a code list; an unknown flag fails step 1 like any invalid argument. Outside `tools/codes/batch.ts` and the tests, only `tools/db/seed.ts` constructs `mode: 'none'`. `CODES_NO_FILES_REFUSED` is registered with the logger like the other tags (PD2). Every caller, with what it leaves on disk and what a rerun does:
  - `pnpm codes:generate`: `files` mode under the default root or `--out`. A rerun on the same database is `CODES_BATCH_EXISTS`; a rerun with the same product and label on another database, or after `pnpm db:reset`, meets the earlier run's final directory and is `CODES_OUT_EXISTS` with nothing changed, on purpose: those files are the only copy of another database's codes and are never overwritten, so the operator picks another label or moves the directory. No setup step and no CI flow runs this command against the default root.
  - `pnpm db:seed` (SD2, SD6): `none` mode; it writes no file anywhere; a rerun on the same database, a rerun after `pnpm db:reset`, and the next `pnpm ci:clean-clone` on its own fresh database each exit 0 (T12).
  - Tests. `code-lifecycle.test.ts` and the in-process `createBatch()` cases of `codes-cli.test.ts` use `files` mode with a root from `mkdtemp`, removed in `afterAll`. Every test that spawns a tool (`codes:generate`, `codes:product`, `db:seed`) runs `node <tool>` as its script does, through one helper in `tests/support/` that sets `HOME` to a fresh temporary directory and, for the generator, passes a temporary `--out`, so a missing `--out` cannot write under the developer's home; one `codes-cli.test.ts` case runs without `--out` and finds the batch under that temporary `HOME`'s `jade-code-batches/`, which pins the default root to `os.homedir()`. `code-sheet.test.ts` renders in memory. `code-sheet.spec.ts` gets its sheet from `renderSheet()`, the pure function of `tools/codes/sheet.ts` that step 6 calls, over codes from `generateCode`, written to a temporary directory that it removes, with no database.
  - `pnpm ci:clean-clone` runs only the README block's `pnpm db:seed` and the suites above, so no run leaves a code file outside its temporary clone directory, which it removes; `pnpm db:reset` touches no file. jade-4el's reset reuses the seed's data (OB36) and so writes no file either.
  - Tests of this step, in `codes-cli.test.ts`: the flags `--codes`, `--no-files` and `--output none` are refused by step 1 with nothing changed; `createBatch()` in `none` mode under `APP_ENV=staging`, without a code list, or with one code outside the reserved range is `CODES_NO_FILES_REFUSED` with no query run and nothing committed; a successful `none`-mode call leaves no new file under the temporary `HOME` or in the repository's `var/`; a source scan finds `mode: 'none'` only in `tools/codes/batch.ts`, `tools/db/seed.ts` and `tests/`.

## 11. jade-q01: development seed

- **SD1, guard (`tools/db/seed.ts`), before any configuration is loaded or connection made:** refuse with `DB_SEED_REFUSED` and the half that failed (`app_env`, `node_env`, `host`, `query`) unless `APP_ENV` is `development` or `test`, `NODE_ENV` is not `production`, and both database URLs are loopback without a query string (C2).
- **SD2, data, as the owner, idempotent by natural keys.** The product of `tools/codes/demo.ts`; batch `dev`; fifteen kits whose codes have the bodies `0000-0001` to `0000-000F` in alphabet order, with check symbols computed by the library at run time (the first is `DEM-0000-0001-Y`), inserted through `createBatch()` with an explicit code list, a parameter the generator command does not expose; a staff user `staff@demo.invalid` and a facilitator `facilitator@demo.invalid`, both with `password_hash` `!` (C15); one class owned by the facilitator, kind `classroom`. Codes stay `unused`. The key check runs first; a pepper that differs from the stored value stops the seed with the advice to run `pnpm db:reset`. The seed prints the fifteen codes; they are derived, not stored in the repository.
- **SD3, script and README.** `db:seed` in `package.json`; the README's setup block gains `pnpm db:seed` after `pnpm db:migrate`, with a paragraph on what it creates and that sign-in arrives with Phase 3.
- **SD4, timing.** `tools/ci/clean-clone.sh` is reordered: the README setup block; then the dev smoke (`pnpm dev` on a free loopback port, as now, until `/` answers 200 and then `/readyz` answers 200, each request with `curl --max-time 10`); then the line `clean-clone: usable after <n> s`, the seconds from the start of the setup block to the `/readyz` 200; then `pnpm dev` is stopped and `pnpm test` and `pnpm e2e` run, and the script exits 0 only after both (C16). The vite-ready rules that `repo-hygiene.test.ts` checks stay as they are; that file gains a case that `pnpm test` and `pnpm e2e` come after the dev-smoke loop and the `usable after` line in the script.
- **SD5, tests.** `seed.test.ts`: each refusal with inputs every other check accepts; a second run adds no row; the fifteen codes redeem under `APP_ENV=test` and are `invalid_code` under a non-development `APP_ENV`; `generateCode` never returns one of them (CL5); the seeded `password_hash` values are exactly `!`; `no-plain-codes.test.ts` covers the seeded database.
- **SD6, the seed's files and reruns.** The seed calls `createBatch()` in output mode `none` (GN8): it writes no CSV, sheet, checksum file or directory anywhere, takes the label lock and runs the key check exactly as the generator does, and its fifteen codes exist only in its process memory and its terminal output (INV1). When the batch `dev` of the demo product already exists (`CODES_BATCH_EXISTS`), the seed verifies, in a new statement, that the batch has exactly fifteen kits with serials 1 to 15, each with one code row whose `code_hmac` equals by `hmacEquals` the HMAC of the seed's code for that serial, whatever its status; then it inserts only the users and the class of SD2 that are missing and exits 0; otherwise it stops with `DB_SEED_DIFFERS` (registered with the logger) and the advice to run `pnpm db:reset`, having changed nothing. `CODES_BATCH_IN_PROGRESS` (another seed or a generator holds the label) stops it with that tag and nothing changed; a rerun succeeds. Tests in `seed.test.ts`, the spawned seed's `HOME` a fresh temporary directory each time: seed one database, then a second, fresh database (a new `createTestDatabase()`, as `pnpm db:reset` or the next `pnpm ci:clean-clone` leaves it), and the second seed exits 0 and its fifteen codes redeem there; after every seed run the temporary `HOME` holds no `codes.csv`, `sheet.html`, `SHA256SUMS` or `jade-code-batches` entry and the repository has no new entry under `var/`; a `dev` batch made first by `createBatch()` in `files` mode with generated codes, under a temporary root, makes the seed exit `DB_SEED_DIFFERS` with no row added.

## 12. jade-pe9: staff code pages (specified, not implementable in this phase)

Blocked by jade-vcy (accounts, sessions, the staff role) and needing jade-aq5's matrix; nothing of it is started in Phase 2. It slots after jade-aq5, and Q3 recommends a planloop run of its own then, starting from this specification.

- **ST1, routes** under `src/routes/(staff)/staff/codes/`: a batch list (product, label, date, counts by status), a batch page (per kit: serial, code status, redeeming adult, class and display number), and three form actions on the batch page: revoke, reissue, move. Server-rendered, no third-party resource.
- **ST2, authorization.** Every route and action answers 404 to anyone without a staff session: anonymous, a student device, an adult. Each is entered in `tests/authz/route-registry.ts` under the staff access class jade-aq5 defines, so the matrix, off-origin and log-privacy tests cover it. Staff name the target kit and class in the form; they are authorized by role, checked to exist and audited. That this is consistent with rule 3 is a reading for Mike to confirm in that bead's plan (Q8).
- **ST3, revoke.** One transaction: lock the kit's code rows, set the live one to `revoked`; audit `code.revoke`, `{ kit_id, code_id }`. The class attachment is not touched.
- **ST4, reissue.** One transaction: lock the kit's code rows; require the live row's id to equal the form's `expected_code_id` (a repeated submit is then a no-op that shows no code); revoke it; generate a code; insert its row with the same `kit_id`; audit `code.reissue`, `{ kit_id, old_code_id, new_code_id }`. The plain code is rendered once in the action's response, sent with `Cache-Control: no-store`, never placed in a URL, a cookie, a table or a log. It needs `GRANT INSERT ON kit_codes TO jade_app` in a migration of its own.
- **ST5, move.** One transaction in PD5's order: lock both classes, the kit's code rows, then set the old `class_kits` row inactive (audit `kit.detach`) and attach to the target with RD3's attach rule (audit `kit.attach`). The kit id never changes.
- **ST6, tests.** `staff-codes.test.ts` (each action, T8 of section 13, the no-store header, no code in any table or log after a reissue) and the matrix.

## 13. Interleavings

- **T1, two adults, one code.** Both take their own counter rows, then both select the code row `FOR UPDATE`; one waits. The winner commits `redeemed`; the waiter re-reads the committed row and returns `already_redeemed` with no write. `redeem-concurrency.test.ts`: (a) 50 rounds of 16 adults redeeming one fresh code at once over a pool of 20, with and without a class: exactly one `redeemed`, fifteen `already_redeemed`, one `code.redeem` audit row, at most one `class_kits` row. The variant without a class matters because there no unique index would stop a double success. (b) The lock is real: the test holds the code row `FOR UPDATE` from an owner connection; `redeemCode` does not settle within 300 ms and `pg_locks` shows its backend waiting; the test marks the row redeemed by another adult and commits; the call returns `already_redeemed` and has written nothing. (c) Proof that (a) fails without the lock: on a scratch branch the subagent replaces the locking read by a plain read, runs (a), and records the failing output in the bead's notes; Reviewer A checks it. jade-4el later adds load on the built app; it replaces none of this.
- **T2, two attachments into one class at once.** Each takes the class row `FOR NO KEY UPDATE` before choosing a number, so they queue; `unique (class_id, display_number)` is the backstop. Test in `redeem-concurrency.test.ts`: eight codes with clashing serials attached into one class in parallel through `redeemWithin` on eight connections give eight distinct numbers and no error.
- **T3, more than ten failed attempts in parallel.** The account row lock serializes them: each transaction sees the count the previous one committed, so the tenth sets the lock and the rest return `locked`. A counted failure commits (PD2), so it is not lost to a rollback; an attempt that dies from an unexpected error is not counted and told the caller nothing about the code. `redeem-limits.test.ts`: 25 parallel unknown codes from one account give exactly ten `not_found` and fifteen `locked`, the array and `locked_until` as specified, one `code.lockout` row; a valid code is then `locked` and stays `unused`; after the test moves `locked_until` into the past the same code redeems; nine failures aged past sixty minutes plus one new one do not lock; other accounts are unaffected; the throttle trips at its limit, refuses every account, writes one `code.throttle` row and reopens when its window is aged.
- **T4, the generator twice with one label.** One after the other: the second takes the label lock, finds the batch row and exits `CODES_BATCH_EXISTS`, adding nothing. Together, or while the first is only slow (stalled in an fsync, or between its commit and its publish), whatever output root each names: the second cannot take the lock and exits `CODES_BATCH_IN_PROGRESS` at once with nothing changed, so it never acts on a live run's partial directory. If the first lost its lock while alive (its lock connection dropped), the second can take it, and then: while the first's transaction is open, the second reads `in progress` from the id in the directory's name and refuses; once it has committed, both may publish, and the single directory rename lets exactly one succeed, the other exiting `CODES_FINISHED_BY_OTHER_RUN` or `CODES_BATCH_EXISTS`; a second batch insert for the label meets the unique key and fails. `codes-cli.test.ts`: (a) the first run stopped at each pause point (`after_insert`, `after_partial`, `after_commit`) while a second starts: the second exits `CODES_BATCH_IN_PROGRESS`, and the rows and the output root are unchanged; the first, continued, exits 0. (b) 20 rounds of two processes started together: exactly one exit 0 and one exit 1 whose tag is `CODES_BATCH_IN_PROGRESS` or `CODES_BATCH_EXISTS`, n kits, n codes, one batch, one final directory, no partial directory. (c) A lock lost while alive: the first stopped at `after_commit`, the test ends its lock connection with `pg_terminate_backend`, a second run publishes the batch and exits 0, and the first, continued, exits `CODES_FINISHED_BY_OTHER_RUN`, leaving one final directory; with the first stopped at `after_partial` instead, the second exits `CODES_BATCH_IN_PROGRESS`.
- **T5, a crash in the generator, and the rerun.** The process dies at any point; the kernel closes its sockets, so the server rolls back its open transaction and releases its label lock once it notices (a dead host is noticed only by TCP keepalive, and until then a rerun answers `CODES_BATCH_IN_PROGRESS`, RR15). Before the commit: the transaction is gone and a partial directory may remain, never under a final name; the rerun reads its transaction as `aborted`, removes it and generates afresh. Between the commit and the publish: rows and a complete, synced partial directory exist; the rerun reads `committed`, verifies the files against the batch by HMAC and `SHA256SUMS`, and publishes them. After the publish: the rerun is `CODES_BATCH_EXISTS`. Files are never written after the commit and never final before it, so neither "rows nobody can print" nor "cards that never redeem" can result from a crash; only losing the files later can leave an unprintable batch (RR8), and then the operator picks a new label. The pause point `JADE_TEST_CODES_PAUSE_AT=<point>` (honoured only when `APP_ENV` is `test`, documented in `.env.example`) writes the fixed line `codes:generate: paused at <point>` to stderr and stops the process with SIGSTOP; the test continues it with SIGCONT or kills it with SIGKILL; each connection's `application_name` (`jade-codes-lock-<pid>`, `jade-codes-tx-<pid>`) lets a test find its backends. `codes-cli.test.ts` kills the tool at each pause point, waits until `pg_stat_activity` no longer shows its backends, reruns, and asserts the recovery; a tampered partial CSV and a tampered sheet are `CODES_PARTIAL_MISMATCH` with nothing changed; a partial directory named for a transaction that the test holds open is `CODES_BATCH_IN_PROGRESS` with nothing changed.
- **T6, the pepper.** Absent or malformed in the tool's environment: `ConfigError`, nothing done. The first value of an environment: under staging and production only the app stores it (RD8), from its first `/readyz` answer or redemption, so the first batch is compared with the app's pepper like every later one, and with no row the generator refuses with `CODES_KEY_CHECK_ABSENT` before inserting or writing anything; under development and test the first of the app, the seed and the generator to run stores it and the others compare (T11). Tool and app with different peppers, or a release that changed the derivation: the values differ, so the tool refuses with `CODES_PEPPER_MISMATCH` before generating, and the app answers `/readyz` 503 with `codes: mismatch` (Q2(5)) and `unavailable` to every redemption, counts nothing and logs the tag; the known answers of CL5 fail in CI first if the derivation changed in code. An app whose wrong pepper stored the first value: the generator with the right pepper refuses, the deploy fails its health gate, and, with that app stopped and while `kit_codes` is empty, the owner removes the row by the guarded step of jade-lnn.1's runbook (section 14), after which the right app's next check stores its value (RR16). A deliberate rotation is jade-lnn.1's runbook (section 14).
- **T7, migrations and the previous release.** `0001` and `0002` on a database the Phase 1 build is using: that build reads only the ledger and is ready on a database that is ahead (step 2 of the compat job). `0003` against the release holding only `0002`: purely additive, nothing that release reads changes, and its behaviour tests run on the new schema in step 3; PD1 keeps its catalog and grant tests on their own schema. A rollback after any Phase 2 migration is the previous image on the newer schema, which is the same situation. jade-pe9's grant-only migration is additive in the same way. A later migration that is not additive needs the `-- jade:contract` marker and its own plan.
- **T8, revoke or reissue against a redemption of the same kit (jade-pe9).** Both lock the code row. Staff first: the redeemer re-reads `revoked` and returns `revoked`. Redeemer first: the staff action then revokes a `redeemed` row, which INV3 allows, and a reissue inserts the new row only after the old one is `revoked`, so `one_live_code_per_kit` holds at every commit. Test in `staff-codes.test.ts` (waits).
- **T9, shutdown with queries in flight.** The adapter stops accepting requests and waits for those in flight before it emits `sveltekit:shutdown`; `closeAllPools()` then waits for checked-out clients. If the process is killed first, Postgres rolls the open transaction back, and every Phase 2 write is one transaction. `pools.test.ts`: a `redeemCode` blocked on a row lock while `closeAllPools()` is called either completes with all its rows once the lock is released, or rejects with none; never a partial write.
- **T10, a commit whose outcome is unknown.** The tool sent COMMIT and lost the connection before the answer. The old backend may have committed, may abort when it notices the closed socket, or may still be finishing; looking for the batch row cannot tell "aborted" from "not yet committed", so the tool decides only on `pg_xact_status` of the id it read before COMMIT, as GN3 step 7 says. `committed`: it publishes. `aborted`: it removes its own partial directory, which is named with that id and so can be no other run's, and exits `CODES_NOT_COMMITTED`. Still `in progress` after 30 seconds, null, or no connection: `CODES_COMMIT_UNKNOWN` with the files kept; the rerun settles them by the same status once the transaction has ended, and refuses while it has not. While the tool waits, a rerun is refused by the lock or, if the lock was lost too, by the `in progress` status. `codes-cli.test.ts`, through the test-only fault `JADE_TEST_CODES_FAULT` (honoured only when `APP_ENV` is `test`, documented in `.env.example`): `commit_lost_after` sends COMMIT and destroys the socket without reading the answer, and the tool publishes once the status is `committed`; `commit_lost_before` destroys the socket instead of sending COMMIT, and the tool removes its partial directory once the status is `aborted`, exits `CODES_NOT_COMMITTED` and leaves no batch row; `no_reconnect` makes every reconnect fail, and the tool exits `CODES_COMMIT_UNKNOWN` with the directory kept, which a rerun then publishes. `codes-recovery.test.ts` covers the `in progress` branch, which a test cannot hold open on a backend whose client is gone.
- **T11, the first key-check row.** Two app processes, or the app and a development tool, find no row at the same moment: each runs the INSERT with `ON CONFLICT (id) DO NOTHING`; the later one waits for the earlier one's row to commit and then inserts nothing; each then reads the row in a new statement, which under READ COMMITTED sees the committed winner, and compares. One statement that inserted and read back in a single snapshot could miss a row committed after that snapshot began, so the two statements stay separate. A generator under staging or production never inserts, so it cannot race the app into storing its own value. `key-check.test.ts`: 16 concurrent `ensureCodeKey` calls in create mode, half under one pepper and half under another, on a table without the row: exactly one row; the callers whose pepper made the stored value get `ok`, the others `mismatch`; and a require-mode call on an empty table is `absent` and inserts nothing.
- **T12, the seed again, on the same database and on a fresh one.** Same database: the second seed takes the label lock, gets `CODES_BATCH_EXISTS`, verifies the fifteen codes by HMAC and exits 0 with no row added (SD6). Fresh database (after `pnpm db:reset`, or in the next `pnpm ci:clean-clone`, whose Compose project and pepper are new): the first run left nothing on disk, since the seed wrote no file, so no step meets an earlier final directory, and the seed creates the batch afresh and exits 0; under a new pepper the codes have new HMACs and the key-check row is the new environment's. A seed and a generator with the label `dev` at once: the lock admits one; whichever commits first owns the label, and the other answers `CODES_BATCH_IN_PROGRESS` or, after the commit, `CODES_BATCH_EXISTS` (the generator) or `DB_SEED_DIFFERS` (the seed). Tested by `seed.test.ts` (SD6) and AC9's second `pnpm ci:clean-clone` run.

## 14. Later-phase consumers

The orchestrator appends the matching note to each bead when the Phase 2 bead that creates the contract merges.

| Consumer | What it gets | What it must do |
|---|---|---|
| jade-vcy | `users`, `auth_sessions`; `redeemWithin`; the global throttle; seeded users with `password_hash` `!` | Treat a value that is not a valid argon2id encoding as unable to sign in; redeem inside the signup transaction; decide development sign-in; add its per-IP flag itself |
| jade-bu6 | `redeemCode` and its outcomes and messages; the attach rule | Take the user from the session only; answer `class_not_found` with 404; implement Q1's URL form on the redeem page |
| jade-5nj, jade-axr | `device_sessions`, `join_code_hash` | Extend `no-plain-codes.test.ts` to join codes and tokens |
| jade-9tk | `invites` as written, `role` without a check | Validate the role in code, or bring a constraint to Mike |
| jade-8lt | `class_kits` consent columns, default off | Write `kit.logging_on` and `kit.logging_off` through `writeAudit`, adding their shapes |
| jade-aq5 | The registry unchanged by Phase 2 | Define the staff access class jade-pe9 uses |
| jade-dfj, jade-7j8 | Migrations `0001` to `0003`, PD1, `KIT_KEYED_TABLES`, SC6's grant check | Classify every new table with a `kit_id`; keep catalog tests on their own database |
| jade-l13, jade-8vo | `KIT_KEYED_TABLES` | Delete exactly the tables classified `activity`; assert it by enumeration; decide what kit deletion does to `class_kits`; audit rows stay |
| jade-6cq | RD2's constants, RD5's override, ADR 0027 | Tune and test the global threshold; review the lock length and whether staff may lift a lock |
| jade-ada, jade-c42 | No code in logs or tables (INV1) | The staging log grep; `Referrer-Policy` |
| jade-4el | `redeemCode`, RD5's override, the seed's demo data | Its configuration bead is filed when jade-7if merges, modelled on fault-forge `demo/redeem-code`, Vultr runtime, `propose_fix` with `mode='client'`; it says "per-account and global", not per-IP; if it needs an HTTP surface before jade-bu6 exists, that is a new dev-only route with its own registry entry and rule-3 review, decided in that bead |
| jade-lnn.1, jade-fgs | ADR 0026; `code_key_check` and RD8 | The runbook says that losing or rotating the pepper invalidates every printed code and that a rotation must replace the key-check row and reissue every live code; and that a first row stored by an app with the wrong pepper is removed only while no code exists, with that app stopped, as the owner in one transaction: `LOCK TABLE kit_codes IN SHARE MODE; DELETE FROM code_key_check WHERE NOT EXISTS (SELECT 1 FROM kit_codes);` |
| jade-lnn.2, jade-t17 | The generator, PD8, GN2's production confirmation, RD8 | Run it in the image through a one-shot Compose service (one `COPY` of `src/lib/server/codes`, an output bind mount owned by the operator); not before the production origin is fixed, and not before the production app has answered `/readyz` 200 on that database, which stores its key-check value (otherwise the generator refuses with `CODES_KEY_CHECK_ABSENT`); say when cards and the CSV are destroyed |

## 15. Order of work, gates and stop points

Nothing here starts on approval. Implementation begins only on Mike's go-ahead, after sign-off and the answers of section 17.

**Order.** jade-o07, jade-fd5, jade-hap, jade-7if, jade-99j, jade-q01; jade-pe9 after Phase 3's jade-vcy and jade-aq5. Lowest phase and highest priority first: the three P0 beads in dependency order, jade-hap pulled before jade-7if because jade-7if needs the app pool, then P1, then P2.

**Dependencies the plan adds** (the orchestrator runs these on go-ahead, before the first bead is claimed, and notes the reason in each dependent bead): `bd dep add jade-7if jade-hap` (the app pool); `bd dep add jade-99j jade-7if` (the key-check table and the lifecycle test); `bd dep add jade-q01 jade-99j` (the seed calls `createBatch()`). It also creates one bead, "Phase 2 staging acceptance: core schema migrated on staging" (task, P1, label `phase-2`, child of jade-8w4, depending on jade-4zw and jade-o07), whose description is AC1's procedure; and appends a note to jade-o07 and to jade-8w4 naming it. No existing dependency is removed.

**For each bead.**

1. The orchestrator runs `bd show <id>` and briefs one subagent with this plan's section, the files to read, the checks to write and the paths it must not touch.
2. The subagent implements with tests on a branch named for the bead, cut from `main`.
3. The orchestrator runs `pnpm lint && pnpm check && pnpm test && pnpm e2e`, and `pnpm ci:compat` for a bead with a migration, and records each exit status in the bead's notes.
4. Two independent read-only Opus reviewers review the diff before the commit request: Reviewer A for correctness (conformance to this plan, the acceptance lines and the invariants, missed call sites, edge cases, whether each test proves its claim) and Reviewer B for systems (crash, restart, partial writes, retries, races, ordering, idempotency, fail-open against fail-closed, interrupted migrations, test-harness races). Only low findings: the orchestrator fixes them and re-runs the gate. Any medium or high finding: a subagent fix round, then Mike.
5. The work is committed with the bead id in the message under Mike's authorization; with a clean tree the orchestrator runs `pnpm ci:clean-clone` and records its status against the commit.
6. One pull request per bead; it is merged once CI is green, including `migration-compat` where it runs. The bead closes when every acceptance line is met, tests pass locally and in CI, and the change is merged; for jade-o07 that follows Q5.

For jade-o07 the gate of step 3 also runs `pnpm test:infra`, since SC9 changes the infra tests that CI's image job runs.

**Stop points** (stop and ask Mike): a change that would touch CLAUDE.md rules 1 to 6, the logger's keys, or any ADR (an ADR that looks wrong becomes a `decision` bead); any secret, payment, DNS change or production deploy, and any run against production; a new dependency beyond PD9, or a different version or licence than stated; a schema object, constraint or grant beyond sections 6 and 9; a deviation that changes a mechanism rather than a name (back to planloop); a human bead blocking the remaining work; the same test failing three times after three different fixes; the `migration-compat` job failing for a reason that looks like a real incompatibility.

## 16. Acceptance

Phase exit criteria:

- AC1 (OB3), deferred by Mike's Q4. Verified on the first staging deploy after jade-4zw lands, on the host jade-0za chooses (this plan names none): the deploy's `migrate` output names every Phase 2 migration as applied, or says it is up to date with a count equal to the length of `migrations/manifest.json` at the deployed commit; and `/readyz` on staging answers 200 with `migrations: ok`, which the app computes by comparing the staging ledger with the manifest in the deployed image, name and hash, so only fixed words leave the VM. The orchestrator of that deploy reads the CI deploy log and the public endpoint, records both with the commit in the staging-acceptance bead, and Mike closes it. The epic cannot close before it.
- AC2 (OB4): `code-lifecycle.test.ts` passes (generated by the tool, written to the CSV and the sheet, each code redeemed exactly once), `code-sheet.spec.ts` passes, and GN7 is recorded. The browser flow waits for jade-bu6.
- AC3 (OB5): `no-plain-codes.test.ts` and `schema-catalog.test.ts` pass on the databases the lifecycle and seed tests leave.

Per bead, each on that bead's commit, with the gate green:

- AC4, jade-o07: `schema-catalog`, `schema-constraints`, `schema-grants`, `kit-tables`, `migrations-static`, `product-agnostic`, `migrate`, `role-bootstrap` and `baseline-migration` pass, with SC9's replacements; `pnpm test:infra` passes (`stack-up` and `compose-up` with SC9's replacements); `pnpm db:check` and `pnpm ci:compat` exit 0; the first real `migration-compat` run is green. The staging half is AC1.
- AC5, jade-fd5: `codes-format`, `codes-generate`, `codes-hmac` and `module-boundaries` pass; ADR 0026 is merged with Q2's answer.
- AC6, jade-hap: both `pools` files, `readiness` and `health` pass; jade-hap is closed with this decision as its reason.
- AC7, jade-7if: `redeem`, `redeem-concurrency` (with T1(c) recorded), `redeem-limits`, `audit`, `audit-subject`, `key-check`, `readiness`, `health`, `compat`, `no-ip` and `config` pass, with RD9's replacements; `pnpm ci:compat` exits 0 for `0003`; ADR 0027, its amendments rows and the document edits of RD6 are merged.
- AC8, jade-99j: `codes-cli`, `codes-recovery`, `code-sheet` (unit and e2e), `code-lifecycle`, `no-plain-codes` and `repo-hygiene` pass; GN7 recorded.
- AC9, jade-q01: `seed` and `repo-hygiene` pass; `pnpm ci:clean-clone` exits 0, and its `usable after` line, which excludes the test runs, shows at most 300 seconds (C16, SD4); a second `pnpm ci:clean-clone`, started after the first on the same machine and under the same `HOME`, exits 0 too (T12).
- AC10, jade-pe9: section 12's checks. **Blocked** by jade-vcy and jade-aq5.

Scope and process, checked when jade-q01 lands:

- AC11: the registry holds exactly the Phase 1 routes; `src/routes` has no new file; no `<form>`, `<input>` or request-body read was added; `content/` does not exist; `migrations/` holds `0000` to `0003` only; no table of DATA-MODEL sections 4 or 5 exists.
- AC12: every Phase 2 commit names its bead; no human bead was claimed; no bead was closed against Q5's answer; nothing was run against production; each bead's notes hold its gate statuses and both reviewers' results.
- AC13: the diff of `docs/adr` is the new files 0026 and 0027, their two index rows in the README and the README's amendments rows of CL4 and RD6; `CLAUDE.md` is unchanged; the edits to DATA-MODEL.md, PRIVACY.md and `docs/threat-model.md` are exactly those of RD6.
- AC14: `package.json` gained exactly the three dependencies of PD9 and the scripts `codes:generate`, `codes:product` and `db:seed`.

## 17. Open questions for Mike

- **Q1, the QR URL (C6; TM-4, ADR 0011).** What a printed card encodes is permanent for its batch. (a) `/redeem?code=...` as the bead says: the code is in the request line and the browser history; mitigations are those of AB16. (b) Recommended: `/redeem#code=...`: a fragment is not sent to the server, so the code never reaches Caddy, the app or a Referer; the redeem page (jade-bu6) reads it with a few lines of script, fills the form and removes it from the address bar and history entry; without script the adult types the code. (c) The bare code, which needs a scanner inside the site. Option (b) or (c) changes the wording of jade-99j's description and of ADR 0011's consequence, so it is yours to decide; jade-99j waits for the answer.
- **Q2, permanent code choices (C18), to be recorded as ADR 0026.** (1) Key bytes: recommended, the UTF-8 bytes of the `CODE_PEPPER` string exactly as configured, which is unambiguous for every accepted format; the alternative, decoding it to 32 bytes, must guess between base64, base64url and hex. (2) Message: the twelve-character canonical code. (3) The check symbol of CL1. (4) The reserved development range. (5) The stored key-check value (RD8): recommended. The app stores it under its own pepper on its first `/readyz` answer or redemption, and under staging and production the generator only compares against it and refuses while it is absent, so the first batch of every environment, like every later one, is checked against the app's pepper before a card is printed, and the app says "pepper mismatch" instead of "unknown code". With it, also yours: whether `/readyz` answers 503 on a mismatch (recommended: a deploy whose app has the wrong pepper fails its health gate before anyone redeems) or stays 200 while redemption answers `unavailable`. The value is an HMAC of a fixed label under a 256-bit key, which gives nothing toward any code, but with a weak hand-typed pepper it would make guessing the pepper cheaper, so the alternative is no stored value and a runbook step that redeems a spare card before packing.
- **Q3, separate planloops (C17, OB48).** Recommended: jade-pe9 gets its own run after jade-vcy and jade-aq5 exist (authorization matrix, a new migration, section 12 as its starting point). jade-o07, jade-fd5, jade-hap, jade-99j and jade-q01 are covered here. jade-7if is the judgement call: it is a new mechanism in three risk domains, and this plan specifies and traces it at implementation depth (section 9, T1 to T3); a run of its own would repeat that review. Your call for each.
- **Q4, the failed-code counters (C8, OB125).** (a) Recommended: the two database tables of RD1: a lock survives a deploy or restart, the limit is exact under concurrency, and the rows hold an adult's account id and times only. It adds tables that DATA-MODEL does not list and a row to PRIVACY.md's inventory (RD6). (b) In memory: no table, but every restart clears every lock, and the count is per process. Also yours: the initial global threshold of 100 failures in ten minutes until jade-6cq tunes it, and ADR 0027.
- **Q5, closing jade-o07 (OB8, OB46).** (a) Recommended, as with jade-urd in Phase 1: jade-o07 closes when merged on green CI, its staging half carried by the staging-acceptance bead that blocks the epic. (b) It stays open until staging exists; its five dependents are then worked only because your go-ahead names this order.
- **Q6, grants ahead of features (SC4).** The core migration grants `jade_app` the verbs Phase 3's documented features need on `users`, `auth_sessions`, `invites`, `classes`, `class_kits` and `device_sessions`. The alternative is SELECT only now and a grant-only migration in each Phase 3 bead.
- **Q7, the print check (GN7).** Will you print the demo sheet in greyscale and scan three cards with a phone when jade-99j is ready?
- **Q8, readings and candidates the plan did not take.** Confirm two readings: rule 3 allows an adult-chosen, ownership-checked `classId` (C3), and staff naming a target kit and class in a staff-only form (ST2). And three constraints that DATA-MODEL does not have and this plan does not add: a check on `invites.role`; a check tying `redeemed_by` and `redeemed_at` to `status`; a restriction of `code_prefix` to letters other than I, L, O and U (the tools warn instead; the advice goes to jade-6is). Say if you want any of them.

Decided by the plan and listed so that you can overrule them at sign-off: only an unknown code counts as a failed attempt; a repeated redemption by the same adult is `already_yours`; a fresh code for a kit still active in another class is refused until staff move the kit; display numbers follow the kit's serial when free; two pools (jade-hap); the seed is refused on staging; the generator runs under production only with an operator's confirmation at a terminal (C20).

## Residual risks
- RR1: Phase 2 is built while staging does not exist (Mike's Q4), so ADR 0014's "staging exists before feature work" is not met, the core schema's first contact with a deployed stack comes later than the phase intends, and the criterion "core schema migrated on staging" stays open in a separate bead until jade-4zw lands.
- RR2: Whatever Q1 decides is printed on every card of a batch and cannot be changed for that batch; with the query-string form the plain code reaches the request line and the adult device's browser history, and with the fragment form it still sits in the history until the redeem page of jade-bu6 removes it.
- RR3: The global failed-code throttle is shared by everyone (TM-6, accepted by ADR 0020), its initial threshold of 100 failures in ten minutes is untuned until jade-6cq, and because it is read without a lock it can be exceeded by up to the number of concurrent attempts.
- RR4: audit_log has no retention or deletion rule in any source; its rows hold adult account ids and kit, class and code-row ids inside jsonb, are not reached by the kit-deletion enumeration, and are kept after a kit's data is deleted.
- RR5: device_sessions is created in Phase 2 with its last_seen_at column while the threat-model item TM-5 (whether a row for a kit with logging off is stored activity under rule 2) is still open; Phase 2 writes no row to it.
- RR6: The key derivation, message form and check-character algorithm of ADR 0026 are permanent once a card is printed, losing or rotating the pepper invalidates every printed code, the code lookup is an index probe that is not constant-time, and with option Q2(5) the database holds one HMAC of a fixed label under the pepper.
- RR7: Nothing in this plan was installed or run: the SQL that drizzle-kit 0.31 emits for citext, bytea, identity, check and partial-index definitions, the API of qrcode-generator 2.0.4 and the canvas decoding with jsqr may differ in detail at implementation, and a difference that changes a mechanism returns to planloop.
- RR8: If the generator's two files are lost after a successful run, the batch's kits and codes remain in the database as rows nobody can print or redeem until a staff revoke exists (jade-pe9), the label stays taken, and no source says when printed cards and the packing CSV are destroyed.
- RR9: The generator and the seed connect as jade_owner, a superuser in the Compose stacks, and a generator run holds the owner URL and the pepper in one process on the operator's machine or container.
- RR10: "Each QR scans on a phone" and "legible in greyscale" are proven by automated decoding in two browser engines and a black-and-white-only check, plus one manual print and scan by Mike; printers, paper and phone cameras at the pilot site are not covered.
- RR11: The first real migration-compat run happens on jade-o07's pull request and may expose faults in the harness or exceed its nine-minute timeout; such a fault delays the merge, since the job is never weakened.
- RR12: jade-pe9 cannot be implemented before Phase 3, so the Phase 2 epic stays open after its other beads close, revoke and reissue do not exist until then, and its specification here may need revision once jade-vcy and jade-aq5 fix the session and matrix interfaces.
- RR13: The five-minute fresh-clone criterion is measured on the development machine with warm caches; a first download of dependencies, browsers and images on a slow connection can take longer.
- RR14: The core migration grants jade_app the verbs that Phase 3 features need on users, sessions, invites, classes, class_kits and device_sessions before those features exist, so for a while the app role can write tables that no code writes.
- RR15: When the operator's machine or container dies without closing its connections, the server keeps the generator's label lock and its open transaction until TCP keepalive notices, so until then a rerun answers CODES_BATCH_IN_PROGRESS; a hash collision of two labels' lock keys makes an unrelated label wait in the same way.
- RR16: If the first app process of an environment runs with the wrong pepper, it stores the wrong key-check value; the generator then refuses and, with Q2(5)'s recommendation, the deploy fails its health gate, but the row stays wrong until the owner removes it by jade-lnn.1's guarded runbook step, which is possible only while no code exists.

## Change log
- FIX R9: createBatch() takes a closed output option; mode none, reachable only from the seed (no CLI flag, an explicit reserved-range code list and APP_ENV development or test, else CODES_NO_FILES_REFUSED), skips GN3's origin, root, partial-directory and publish steps and keeps the key check and the label lock (new GN8); every caller of createBatch() and the code tools (CLI, seed, tests, clean-clone, db:reset, jade-4el's reset) is listed with its files and its reruns, and tests spawn tools under a temporary HOME; the seed writes no file, verifies an existing dev batch by HMAC and exits 0, or stops with DB_SEED_DIFFERS (new SD6); reseeding a fresh database is tested (SD6, new T12) and a second clean-clone run is part of AC9; INV1, INV13 and PD4 state the seed's file and terminal behaviour; section 1 gains the clean-clone and db:reset facts.
- FIX R10: New RD9 gives the stated replacement for every test that reads a readiness body, found by a sweep of tests/ and tools/ that section 1 lists: the readiness.test.ts and health.test.ts literals gain codes: 'unknown', health.test.ts gains a 503 case with codes: 'mismatch', compat.test.ts gains a case that codes: 'mismatch' with migrations ok is step2Other, and request-id, compose-up and migrate need no change; AC7 lists health and compat.
- SHRINK ## 4. Cross-cutting decisions: PD4 now names the code tools and states that the seed writes no file and prints only its fifteen derived development codes, which SD2 and INV1 already said (R9); no obligation affected.
- SHRINK ## 5. Invariants: INV1 states that the seed writes no file and that tests write generator files only under temporary directories, and adds seed.test.ts and codes-cli.test.ts to its checks; INV13 separates batches made with files from the seed's batch without files and words its success clause per createBatch() call (R9); both only strengthened.
- SHRINK ## 16. Acceptance: AC7 adds health and compat with RD9's replacements (R10), and AC9 adds a second clean-clone run under the same HOME (R9); no check removed.

## Artifact inventory
- section: ## 0. Summary
- section: ## 1. Facts this plan rests on
- section: ## 2. Obligations
- section: ## 3. Contradictions and gaps
- section: ## 4. Cross-cutting decisions
- section: ## 5. Invariants
- section: ## 6. jade-o07: core schema
- section: ## 7. jade-fd5: kit code library
- section: ## 8. jade-hap: database pools
- section: ## 9. jade-7if: redemption service
- section: ## 10. jade-99j: batch generator
- section: ## 11. jade-q01: development seed
- section: ## 12. jade-pe9: staff code pages (specified, not implementable in this phase)
- section: ## 13. Interleavings
- section: ## 14. Later-phase consumers
- section: ## 15. Order of work, gates and stop points
- section: ## 16. Acceptance
- section: ## 17. Open questions for Mike
- section: ## Residual risks
- section: ## Change log
- section: ## Artifact inventory
- id: OB1
- id: OB2
- id: OB3
- id: OB4
- id: OB5
- id: OB6
- id: OB7
- id: OB8
- id: OB9
- id: OB10
- id: OB11
- id: OB12
- id: OB13
- id: OB14
- id: OB15
- id: OB16
- id: OB17
- id: OB18
- id: OB19
- id: OB20
- id: OB21
- id: OB22
- id: OB23
- id: OB24
- id: OB25
- id: OB26
- id: OB27
- id: OB28
- id: OB29
- id: OB30
- id: OB31
- id: OB32
- id: OB33
- id: OB34
- id: OB35
- id: OB36
- id: OB37
- id: OB38
- id: OB39
- id: OB40
- id: OB41
- id: OB42
- id: OB43
- id: OB44
- id: OB45
- id: OB46
- id: OB47
- id: OB48
- id: OB49
- id: OB50
- id: OB51
- id: OB52
- id: OB53
- id: OB54
- id: OB55
- id: OB56
- id: OB57
- id: OB58
- id: OB59
- id: OB60
- id: OB61
- id: OB62
- id: OB63
- id: OB64
- id: OB65
- id: OB66
- id: OB67
- id: OB68
- id: OB69
- id: OB70
- id: OB71
- id: OB72
- id: OB73
- id: OB74
- id: OB75
- id: OB76
- id: OB77
- id: OB78
- id: OB79
- id: OB80
- id: OB81
- id: OB82
- id: OB83
- id: OB84
- id: OB85
- id: OB86
- id: OB87
- id: OB88
- id: OB89
- id: OB90
- id: OB91
- id: OB92
- id: OB93
- id: OB94
- id: OB95
- id: OB96
- id: OB97
- id: OB98
- id: OB99
- id: OB100
- id: OB101
- id: OB102
- id: OB103
- id: OB104
- id: OB105
- id: OB106
- id: OB107
- id: OB108
- id: OB109
- id: OB110
- id: OB111
- id: OB112
- id: OB113
- id: OB114
- id: OB115
- id: OB116
- id: OB117
- id: OB118
- id: OB119
- id: OB120
- id: OB121
- id: OB122
- id: OB123
- id: OB124
- id: OB125
- id: OB126
- id: OB127
- id: OB128
- id: OB129
- id: OB130
- id: OB131
- id: OB132
- id: OB133
- id: OB134
- id: OB135
- id: OB136
- id: INV1
- id: INV2
- id: INV3
- id: INV4
- id: INV5
- id: INV6
- id: INV7
- id: INV8
- id: INV9
- id: INV10
- id: INV11
- id: INV12
- id: INV13
- id: AC1
- id: AC2
- id: AC3
- id: AC4
- id: AC5
- id: AC6
- id: AC7
- id: AC8
- id: AC9
- id: AC10
- id: AC11
- id: AC12
- id: AC13
- id: AC14
- id: RR1
- id: RR2
- id: RR3
- id: RR4
- id: RR5
- id: RR6
- id: RR7
- id: RR8
- id: RR9
- id: RR10
- id: RR11
- id: RR12
- id: RR13
- id: RR14
- id: RR15
- id: RR16
