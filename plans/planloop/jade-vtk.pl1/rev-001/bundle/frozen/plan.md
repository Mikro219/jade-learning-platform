# PLAN jade-vtk: Phase 1 foundation and walking skeleton (revision 1, 2026-11-15)

Code and infrastructure plan for the eight agent beads of Phase 1 (epic jade-vtk): jade-h8i, jade-8v4, jade-urd, jade-alt, jade-80h, jade-xu0, jade-lhq and jade-4zw. Track: escalated (secrets, privacy, schema-migration). Human beads are out of scope.

This plan is not authorization to implement. After it is approved and Mike has signed off, implementation waits for Mike's explicit go-ahead. It then proceeds one bead at a time, in the order of section 16, each bead delegated by the orchestrator to a subagent with a complete brief.

## 0. Summary

- Buildable now, on this machine, with no remote: the scaffold (jade-h8i), typed config (jade-8v4), database tooling and test harness (jade-urd), health endpoints and logs (jade-alt), the image and production Compose stack (jade-80h), and the UI shells (jade-lhq). Each has automated checks that run locally.
- Not finishable now: jade-xu0 (the workflow can be written and its stages run locally, but it cannot run, be timed or be made required until a remote and CI host exist) and jade-4zw (blocked by the human bead jade-0za; nothing of it is started). Phase exit criteria AC2 and AC3 are therefore blocked; AC1 is not.
- Mike decides before go-ahead: Q1 (remote, CI host, trunk name, merge flow, registry), Q2 (how beads close while no CI exists), Q3 (two changes to his machine). Section 18.
- The brief's contradictions 1 to 7 and seven more found while planning are settled or raised in section 3. No rule of CLAUDE.md and no ADR is changed or relaxed.
- Scope is Phase 1 only: no domain table, no Phase 2+ route or feature, no teaching content.

## 1. Facts this plan rests on

### 1.1 Repository and machine (read-only checks, 2026-11-14 and 2026-11-15)

- The repository holds docs, plans, skills and Beads data only. There is no `package.json`, no `src/`, no `README.md`. `.gitignore` has only the Beads and `__pycache__/` entries.
- `git remote -v` is empty. The only branch is `master`; every source says `main`.
- `/usr/bin/node` is v20.20.1, with corepack 0.34.6 beside it. No nvm, fnm, volta, mise or asdf.
- `pnpm` on `PATH` resolves to a Windows-side shim reached through WSL interop (under `/mnt/c/.../AppData/Roaming/npm/`). It refuses to run on Node 20. It is treated as absent, and as a hazard: it must never be the pnpm that runs.
- `/usr/bin/psql` is the `pg_wrapper` stub with no client package behind it, so psql is unusable. `gh` is absent. The plan uses neither.
- Docker 29.7.2, Compose v5.4.0 and buildx v0.36.1 work, and the user is in the `docker` group.
- Playwright Chromium builds are cached from other projects. The OS libraries WebKit needs (libwoff1, libmanette, libenchant-2, libhyphen and others) are not installed, so WebKit cannot start until they are, which needs sudo.
- The machine has 32 CPUs, so local timings are faster than a hosted CI runner.

### 1.2 Tool versions (public registries and release schedule, 2026-11-14)

| Tool | Version | What matters here |
|---|---|---|
| Node 24 | 24.22.3, LTS "Krypton" | LTS since 2025-10-28, maintenance since 2026-10-20, end of life 2028-04-30. Runs `.ts` files directly by stripping types |
| Node 26 | 26.13.1, LTS "Lithium" | LTS since 2026-10-28. Not used (section 6.3) |
| pnpm | 12.21.0 | A native executable that needs no Node. Pins and downloads a Node runtime per project through `devEngines.runtime`; `--no-runtime` skips that; an `engines.pnpm` mismatch always fails the install |
| @sveltejs/kit | 3.2.0 | Needs Node 22.17 or later, Vite 8, TypeScript 6. Configuration lives in `vite.config.ts` (no `svelte.config.js`); `$lib` is replaced by a `#lib` alias declared in `package.json` `imports`, with file extensions; `$app/env`, `$app/manifest`; hook types in `@sveltejs/kit/hooks`; `handleError` receives every error |
| @sveltejs/adapter-node | 6.0.2 | `node build`; reads `PORT`, `HOST`, `ORIGIN`; serves static assets before `handle` |
| vite, vitest, @playwright/test, @axe-core/playwright | 8.3.8, 5.1.0, 1.65.1, 4.14.0 | |
| drizzle-orm, drizzle-kit, pg | 0.45.4, 0.31.11, 8.23.1 | |
| zod, eslint, prettier, typescript-eslint | 4.6.7, 10.15.0, 3.10.1, 8.72.2 | typescript-eslint accepts TypeScript below 6.1 only |
| typescript | 6.0.x | `latest` is 7.0.2, which the peer ranges of kit, svelte-check and typescript-eslint exclude |
| Images | `node:24.22.3-alpine3.24`, `postgres:16.16-bookworm`, `caddy:2.11.9-alpine` | All three tags exist on Docker Hub |

Nothing was installed or run while planning. Versions and behaviour come from the registries and the tools' published documentation (RR4).

### 1.3 Evidence behind two choices

- drizzle-orm 0.45.4, `pg-core/dialect.js`, `migrate()`: it reads only the newest row of `drizzle.__drizzle_migrations` and applies journal entries whose `when` is later than that row. It never compares the hash of a file that is already applied, takes no lock, and silently skips an entry with an older `when`. It cannot show that migrations are forward-only or current, so this plan uses its own runner (PD4).
- SvelteKit 3 documentation: `handle` does not run for static assets; an `init` hook runs once when the server is created; `handleError` is called with `kind` `app`, `framework`, `validation` or `unknown`, and what it returns becomes the error body.

## 2. Obligations

Every row OB1 to OB80, its owning bead, the step that answers it and the check that proves it. Steps are defined in sections 6 to 14, checks in the owning section and in section 5. "Waits" means the check cannot run until section 12.3 or 14 says it can.

| OB | Owner | Step | Check |
|---|---|---|---|
| OB1 | jade-h8i | H5, H6 | The gate `pnpm lint && pnpm check && pnpm test && pnpm e2e` exits 0 on the jade-h8i commit (AC4) |
| OB2 | jade-h8i | H4 | `tests/unit/module-boundaries.test.ts` |
| OB3 | jade-h8i | H8 | `pnpm ci:clean-clone` |
| OB4 | jade-urd | U6 | `tests/integration/db-scripts.test.ts` |
| OB5 | jade-urd, jade-xu0 | U4, U7, X2 | `tests/integration/baseline-migration.test.ts`, locally and in `pnpm ci:local`; in CI job `check` once a host exists (waits) |
| OB6 | jade-urd, jade-80h | U3, U5, D3 | INV5 checks; `tests/infra/compose-up.test.ts` (migrate runs before the app on every `up`); on staging Z4 (waits) |
| OB7 | jade-8v4 | V3 | `tests/blackbox/boot-failfast.test.ts` |
| OB8 | jade-8v4 | V4, V5 | `tests/unit/env-example.test.ts`, `tests/unit/repo-hygiene.test.ts` |
| OB9 | jade-8v4 | V2 | `tests/unit/config.test.ts`; `tests/infra/compose-config.test.ts` |
| OB10 | jade-xu0 | X3 | `tests/unit/ci-workflow.test.ts` (job timeouts); `pnpm ci:local` timings, indicative; the run duration on the real host (waits) |
| OB11 | jade-xu0 | X5 | A pull request with a failing check cannot be merged, shown on the host (waits) |
| OB12 | jade-xu0 | X2, X5 | `tests/unit/ci-workflow.test.ts` (upload step on failure); a deliberately failing branch on the host (waits) |
| OB13 | jade-80h | D2, D3 | `tests/infra/compose-up.test.ts` |
| OB14 | jade-80h | D1 | `tests/infra/image.test.ts` |
| OB15 | jade-80h | D2 | `tests/infra/compose-config.test.ts` |
| OB16 | jade-4zw | Z3, Z4 | The deploy workflow's last step reads `/healthz` on staging and compares the version (waits) |
| OB17 | jade-4zw | Z4 | A rehearsal with a deliberately broken image, locally and then on staging (waits) |
| OB18 | jade-4zw | Z6 | `grep` for the staging URL in `README.md` (waits) |
| OB19 | jade-alt | A3 | `tests/blackbox/health.test.ts`; `tests/infra/compose-up.test.ts` (database container stopped) |
| OB20 | jade-alt | A1, A2 | `tests/blackbox/log-privacy.test.ts`, `tests/unit/log-schema.test.ts` |
| OB21 | jade-alt | A4 | `tests/blackbox/request-id.test.ts` |
| OB22 | jade-lhq, jade-h8i | H7, L4 | `tests/e2e/no-offorigin.spec.ts`, `tests/unit/no-external-refs.test.ts` |
| OB23 | jade-lhq | L2, L4 | `tests/e2e/a11y.spec.ts` |
| OB24 | jade-lhq | L1, L4 | `tests/e2e/layout.spec.ts` |
| OB25 | jade-h8i | H1 to H6 | `tests/unit/toolchain-pins.test.ts`, `tests/unit/module-boundaries.test.ts`, the gate |
| OB26 | jade-urd | U1, U2, U7 | `tests/integration/harness-isolation-a.test.ts` and `-b.test.ts`; `tests/unit/toolchain-pins.test.ts` (Postgres 16) |
| OB27 | jade-8v4 | V1, V2, V4 | `tests/unit/config.test.ts`, `tests/unit/env-example.test.ts` |
| OB28 | jade-xu0 | X2 | `tests/unit/ci-workflow.test.ts`; a real run (waits) |
| OB29 | jade-80h | D1 to D5 | `tests/infra/image.test.ts`, `compose-config.test.ts`, `compose-up.test.ts`, `caddy-logs.test.ts`, `media.test.ts` |
| OB30 | jade-4zw | Z1 to Z5 | Section 14 checks (waits) |
| OB31 | jade-alt | A1 to A3 | `tests/blackbox/health.test.ts`, `tests/unit/log-schema.test.ts`, `tests/blackbox/log-privacy.test.ts` |
| OB32 | jade-lhq | L1 to L3 | `tests/e2e/layout.spec.ts`, `a11y.spec.ts`, `no-offorigin.spec.ts` |
| OB33 | jade-h8i | H2, H9 | `tests/unit/toolchain-pins.test.ts`; `docs/adr/0024-node-24-pinned.md` exists (AC13) |
| OB34 | epic | Sections 7 to 14 | AC1, AC2, AC3 |
| OB35 | epic | H8 | AC1 |
| OB36 | epic | X5 | AC2 (blocked) |
| OB37 | epic | Z3 to Z6 | AC3 (blocked) |
| OB38 | all | No form, input or account exists in Phase 1 | AC12 |
| OB39 | jade-alt | A1: no log key can carry a kit, class, session or step identifier; no activity table exists | `tests/unit/log-schema.test.ts`; AC12 |
| OB40 | all | No Phase 1 route reads a request body | AC12 |
| OB41 | jade-alt, jade-urd, jade-80h | A1, A2, U2, D4 | INV1, INV2, INV4 checks |
| OB42 | jade-h8i, jade-lhq | H7, L4 | INV3 checks |
| OB43 | jade-xu0 | X1: `ci:check` is where `pnpm content:lint` (jade-as7) is added; Phase 1 creates no content and no step id | AC12 |
| OB44 | jade-h8i | H9: one ADR added, no Decision edited | AC13 |
| OB45 | all | Section 16: jade-0za is never started; jade-4zw is not started while it is blocked | AC14 |
| OB46 | all | Section 16 and Q2: no bead is closed before its conditions hold | AC14 |
| OB47 | jade-h8i, jade-alt | H7, A5 | `tests/unit/route-registry.test.ts`, `tests/blackbox/route-access.test.ts` |
| OB48 | all | Section 16: the gate is run for every bead and its exit status recorded in the bead's notes | AC4 to AC10 |
| OB49 | all | Section 16: every commit names its bead; merging waits for CI (Q1) | AC14; merge and staging deploy wait |
| OB50 | all | Section 16, stop points | AC14 |
| OB51 | jade-h8i | H3, H4 | `tests/unit/toolchain-pins.test.ts` (adapter-node, `strict`), `tests/unit/module-boundaries.test.ts` |
| OB52 | jade-urd | U1 to U5 | `tests/unit/toolchain-pins.test.ts` (Postgres 16 everywhere), `tests/integration/migrate.test.ts`. No view is built; the runner applies any SQL file, which Phase 8 uses |
| OB53 | jade-urd, jade-xu0 | U5, X4 | INV5 checks |
| OB54 | jade-80h, jade-4zw | D2; Z1 | `tests/infra/compose-config.test.ts`; provider and region come from jade-0za (waits) |
| OB55 | jade-80h | D5 | `tests/infra/media.test.ts` |
| OB56 | jade-alt | As OB39 | As OB39 |
| OB57 | jade-8v4 | V2 | `tests/unit/config.test.ts` |
| OB58 | jade-lhq | L4. The CSP itself is built by jade-c42, as ADR 0013's Consequences say (C12) | `tests/e2e/no-offorigin.spec.ts` |
| OB59 | jade-4zw | Z3 | Waits; RR3 |
| OB60 | jade-h8i, jade-8v4, jade-xu0 | H1 to H6, V1, X2 | `tests/unit/toolchain-pins.test.ts`, `tests/unit/ci-workflow.test.ts`. k6 belongs to Phase 9 |
| OB61 | jade-xu0 | X5, Q1 | No remote is created or assumed by an agent (AC14) |
| OB62 | jade-80h | D2, D4, D5 | `tests/infra/compose-up.test.ts` (TLS, compression), `caddy-logs.test.ts`, `media.test.ts` |
| OB63 | jade-h8i | H4 | `tests/unit/module-boundaries.test.ts` |
| OB64 | jade-h8i | H4 | `tests/unit/route-registry.test.ts` (the three groups and `api/` exist) |
| OB65 | jade-h8i | H4 | `tests/unit/module-boundaries.test.ts` |
| OB66 | jade-alt, jade-80h | A1, D4 | INV1 and INV2 checks |
| OB67 | jade-80h, jade-4zw | D2: the stack takes its image from `JADE_IMAGE`, so one image moves from local to staging to production | `tests/infra/compose-config.test.ts`; promotion is jade-kn0 |
| OB68 | jade-80h, jade-4zw | D3, Z4 | `tests/infra/compose-up.test.ts` (migrate, start, health); `tests/integration/migrate.test.ts` (readiness with the database ahead); Z4 (waits) |
| OB69 | jade-urd | U4: the only migration holds no table | AC12 |
| OB70 | jade-urd, jade-8v4 | U2, U3, V2 | `tests/integration/baseline-migration.test.ts` (the app role cannot run DDL); grants on `events` are jade-7j8 |
| OB71 | jade-alt, jade-80h | A1, D2 | INV1 checks. The 14-day retention is jade-ada; Phase 1 caps log size |
| OB72 | jade-alt | A1, A4 | `tests/unit/log-schema.test.ts` (no address, user agent or device key); `tests/blackbox/request-id.test.ts` (no `Set-Cookie` on any Phase 1 response) |
| OB73 | jade-lhq, jade-80h, jade-4zw | L4, D2 | INV3 checks; `tests/infra/compose-config.test.ts` (backend network is internal); the Canadian VM is jade-4zw (waits) |
| OB74 | jade-80h | D2 | `tests/infra/compose-config.test.ts` |
| OB75 | jade-80h | D2, D4 | `tests/infra/compose-config.test.ts`, `caddy-logs.test.ts` |
| OB76 | jade-4zw, jade-8v4, jade-xu0 | Z2, V2, X2 | `tests/unit/ci-workflow.test.ts` (no app secret is named in a workflow); `tests/unit/config.test.ts` (test-only values refused outside test); Z2 (waits) |
| OB77 | jade-8v4 | V2 | `tests/unit/config.test.ts`. Nothing in Phase 1 writes a config value to the database |
| OB78 | jade-alt, jade-80h | A1, D4 | INV1 and INV2 checks |
| OB79 | jade-alt, jade-80h | A2, D4 | `tests/blackbox/log-privacy.test.ts` (a code in `/redeem?code=`), `tests/infra/caddy-logs.test.ts` |
| OB80 | jade-xu0 | X5, Q1 | As OB61 |

## 3. Contradictions and their resolution

C1 to C7 are the brief's. C8 to C14 were found while planning.

- **C1, `/media` (OB29 against OB55).** Settled within ADR 0007. The Phase 1 Caddyfile answers every `/media/*` request with 403. The file-serving directives sit in a snippet, `deploy/caddy/media-files.caddy`, that the site block does not yet use, and the media volume is mounted read-only into Caddy. jade-u8z replaces the 403 with its signed-URL check and imports the snippet; it adds, it undoes nothing, and its acceptance "Unsigned or expired media URLs return 403" already holds. Range support is proven on the snippet in a throwaway Caddy container (D5). The remainder is RR1.
- **C2, the "route" log field (OB31 against OB39, OB56, OB79).** Settled. The field is the route pattern (`event.route.id`, for example `/(student)/s/[step_id]`), or `null` when nothing matched. The path, query string, parameters and headers are never read by the logger. A log line therefore carries no code and no kit, class, session or step identifier. The reading that such a line is not kit activity is RR5.
- **C3, three never-log lists (jade-alt, OB71, OB41).** Settled: the union applies from Phase 1. `tests/blackbox/log-privacy.test.ts` asserts that no IP address, cookie, kit code, join code, token, email or request body appears in any line, for every route in the registry. Deferred to jade-ada: the grep of staging logs after a full e2e run, Caddy's logs on the real VM, the check that the database has no IP column, and 14-day retention.
- **C4, one `DATABASE_URL` against the app role's grants (OB70).** Settled: two roles and two URLs from Phase 1 (PD3). jade-7j8's acceptance "App role cannot UPDATE events (tested)" needs a role that does not own the tables, and re-owning tables on a live staging database later is the costly path. No Phase 2 or Phase 6 schema is built.
- **C5, the authorization matrix (OB47) before Phase 3.** Settled: `tests/authz/route-registry.ts` lists every route with its access class, and a test fails when a route is missing or stale (PD7). `/healthz` and `/readyz` are entered as `public`. jade-aq5 widens each entry to its five actors.
- **C6, migrations "run automatically on deploy" (OB6) with no deploy target.** Settled: `compose.prod.yml` has a one-shot `migrate` service that the `app` service waits for, so every `docker compose up` migrates first. It is exercised now by `tests/infra/compose-up.test.ts`, which also mounts one extra migration and brings the stack up again. The staging deploy script calls the same service (Z4).
- **C7, CI under 10 minutes (OB10).** Settled as a budget in section 12.2: four parallel jobs, the slowest estimated at about 5 minutes cold, each with `timeout-minutes: 9`. The estimate is unverified until a host exists (RR2).
- **C8, OB46 against the bead graph.** Raised, Q2. A bead is done only when tests pass "in CI" and the change is merged, but CI is built by jade-xu0, which the graph places after jade-h8i and jade-urd, and no remote exists. As written, no Phase 1 bead can close and no dependent bead becomes ready. The plan does not relax the rule; section 16 states the conservative default.
- **C9, `master` against `main` (OB11, OB16, OB36, OB49).** Raised, Q1. Renaming the trunk is one local command while no remote exists; it needs Mike's word.
- **C10, OB26's "an isolated schema or transaction rollback".** Settled: each test file gets its own database, cloned from a migrated template (PD5). That gives the file its own schema in the plainest sense. A schema inside a shared database is rejected because drizzle-kit writes `"public".`-qualified names and grants and extensions are per database; rollback is rejected because jade-7if needs parallel transactions that commit.
- **C11, OB30's "22 from deploy source only" against hosted CI runners.** Raised, RR10 and Q5. It is settled with jade-0za.
- **C12, OB58's "CSP enforces it and an e2e test asserts it".** Settled by ADR 0013 itself: its Consequences give the CSP to p9-headers (jade-c42). Phase 1 delivers the e2e assertion.
- **C13, OB59's "Staging exists before feature work" against the blocked jade-4zw.** Raised, RR3 and Q4.
- **C14, OB25 and OB60 say "current Node LTS", Mike pinned Node 24 (OB33) while Node 26 is also LTS.** Taken as given, not reargued; recorded as ADR 0024 (section 6.3).

## 4. Cross-cutting decisions

- **PD1, toolchain.** pnpm 12 provisions Node 24 for the project; three pins agree by test (section 6).
- **PD2, environment.** `APP_ENV` is `development`, `test`, `staging` or `production`, required, with no default. `NODE_ENV` is `production` in the image for staging and production alike. No secret value for a development, staging or production environment is committed: `pnpm env:init` generates them. The one literal credential in the repository is the CI job's throwaway database password (X2).
- **PD3, two database roles.** `jade_owner` owns the database and runs migrations; `jade_app` is what the app connects as. The app reads `DATABASE_URL` (app role). Only the migration entry point reads `MIGRATION_DATABASE_URL` (owner role), and the app container never receives it.
- **PD4, own migration runner.** Drizzle Kit generates SQL; a runner of about a hundred lines applies it against a ledger table, with a lock and hash checks (section 9). Drizzle ORM stays the query layer, as ADR 0003 says.
- **PD5, a database per test file**, cloned from a template (C10).
- **PD6, a closed logger.** Log lines are built from an allowlist of keys, each with a value validator. There is no call that logs an arbitrary object. `console` is banned in `src/` by lint.
- **PD7, route registry.** One file lists every route, its access class and a sample URL. The registry drives the authorization seed, the off-origin test and the log-privacy test, so a new route is covered by all three or fails all three.
- **PD8, dev-only routes.** Pages needed only to exercise shells and the error path live under `/dev/` and return 404 unless `APP_ENV` is `development` or `test`. On staging and production the only page is `/`.
- **PD9, black-box checks.** Invariant tests start the built server (`node build`) or the built image and look at what it emits. They do not depend on framework internals, which matters given RR4.
- **PD10, platform folders.** `src/lib/server/config`, `db`, `log` and `http` sit beside the five domain modules and follow the same rule (imports go through `index.ts`). `config`, `db` and `log` import nothing from SvelteKit, so the migration tool can use them outside the app.

## 5. Invariants

Each invariant names the checks that keep it enforced. Unit, integration and black-box checks run in `pnpm test`; e2e checks in `pnpm e2e`; infra checks in `pnpm test:infra`. All three are stages of `pnpm ci:local` and of the CI jobs in section 12.

- **INV1, app logs.** No log line written by the app contains an IP address, cookie, kit code, join code, token, email or request body, nor a path, query string, header, user agent, or a kit, class, session or step identifier. Kept by: `tests/unit/log-schema.test.ts` (every key is on the allowlist; forbidden key names cannot be registered; each value passes its validator or is replaced by `[invalid]`; an error's message and properties are never serialized); `tests/blackbox/log-privacy.test.ts` (the built server, every registry route, canary values in the path, query, cookie, `Authorization`, `X-Forwarded-For`, `X-Request-Id` and body; every output line is either on the adapter's start-up allowlist or parses as JSON and matches the line schema; no canary appears anywhere); ESLint `no-console` as an error in `src/`. A change to the forbidden-key list or the line schema touches rule 4 and goes to Mike.
- **INV2, Caddy logs.** Caddy writes no access log, and no line it writes carries a client address, URI, query string or request header. Kept by `tests/infra/caddy-logs.test.ts`.
- **INV3, same origin.** No page causes a request, WebSocket or prefetch to another origin. Kept by `tests/e2e/no-offorigin.spec.ts` (every page in the registry plus the error page, Chromium and WebKit, requests recorded at context level) and `tests/unit/no-external-refs.test.ts` (no absolute external URL in a `src`, `href`, `@import` or `url()` under `src/` and `static/`).
- **INV4, secrets.** No secret has a default in any environment; none is committed, baked into the image, named in CI configuration or echoed in an error. Kept by: `tests/unit/config.test.ts`; `tests/blackbox/boot-failfast.test.ts`; `tests/unit/env-example.test.ts`; `tests/unit/repo-hygiene.test.ts` (`.env` ignored, no tracked `.env*` but `.env.example`, `.dockerignore` excludes `.env*`); `tests/infra/compose-config.test.ts` (every secret is `${NAME:?}`); `tests/infra/image.test.ts` (no `.env` in the image); `tests/unit/ci-workflow.test.ts`.
- **INV5, migrations.** Migrations are forward-only: a file that has been merged is never edited, renamed, reordered or removed, and there is no down path. A migration stays compatible with the previous app version. Kept by: `tests/unit/migrations-static.test.ts` (names, contiguous numbers, `manifest.json` equals the files, journal order equals file order, a destructive statement needs a `-- jade:contract <bead>` marker); `pnpm db:check --base <ref>` (the base's manifest is an unchanged prefix of HEAD's), run by CI job `check`; `tests/integration/migrate.test.ts` (an edited applied file stops the runner; two runners at once apply each file once; an app is ready on a database that is ahead of it); CI job `migration-compat` (the previous app's build and integration tests against the new schema). The limit of this is RR8.
- **INV6, least privilege.** The running app cannot run DDL and never holds the owner's credentials. Kept by `tests/integration/baseline-migration.test.ts` and `tests/infra/compose-config.test.ts` (the `app` service has no `MIGRATION_DATABASE_URL` and no owner password).
- **INV7, exposure.** Only Caddy publishes ports, and only 80 and 443; the app and the database are not reachable from the host; `/media/*` returns 403 until jade-u8z. Kept by `tests/infra/compose-config.test.ts`, `compose-up.test.ts` and `media.test.ts`.
- **INV8, routes.** Every route is in the registry with an access class, and a `/dev/` route returns 404 unless `APP_ENV` is `development` or `test`. Kept by `tests/unit/route-registry.test.ts` and `tests/blackbox/route-access.test.ts`.
- **INV9, pins.** `.nvmrc`, `package.json` (`devEngines.runtime`, `engines.node`), the Dockerfile and the running `process.version` name one Node release; `packageManager` and the Dockerfile name one pnpm; `compose.dev.yml`, `compose.prod.yml` and the workflow name one Postgres 16 image. Kept by `tests/unit/toolchain-pins.test.ts`.

## 6. Toolchain: Node 24 and pnpm

### 6.1 How the tools are obtained

- **pnpm on this machine.** pnpm 12.21.0 is installed for the user with pnpm's standalone installer: `curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION=12.21.0 sh -`. It needs no Node and no sudo, puts the binary under `~/.local/share/pnpm`, and adds `PNPM_HOME` to `~/.bashrc`. Because it changes Mike's shell profile, it runs only with his yes (Q3). Corepack is not used: it ships with Node 24 but not with Node 25 and later, and pnpm 12's installation documentation no longer describes a corepack install.
- **Node 24 on this machine.** Not installed system-wide. `package.json` declares `devEngines.runtime` (Node, 24.22.3, `onFail: "download"`), so `pnpm install` downloads that Node for this project, verifies it, records it in the lockfile, and runs every script with it. `/usr/bin/node` v20 is untouched, so other projects on the machine are unaffected.
- **Agent commands.** Every command that uses pnpm starts with `export PNPM_HOME="$HOME/.local/share/pnpm" PATH="$HOME/.local/share/pnpm:$PATH"`, so the Windows-side shim can never be picked up. The first command of each bead is `pnpm --version`, which must print 12.21.0. `tests/unit/toolchain-pins.test.ts` runs in every gate and fails when the Node running the scripts is not the pinned one. Scripts never call a bare `node` from `PATH`; they use pnpm scripts or `process.execPath`.
- **WebKit libraries.** `pnpm exec playwright install --with-deps chromium webkit` installs the browsers and, with sudo, the OS libraries. An agent does not run sudo: Mike runs this once after H2 (Q3). Until then `pnpm e2e` cannot pass on WebKit and jade-h8i cannot meet OB1.
- **In the image.** The build stage starts from `node:24.22.3-alpine3.24`, installs pnpm with `npm install -g pnpm@12.21.0`, and runs `pnpm install --frozen-lockfile --no-runtime`, so the image's own Node is used and nothing is downloaded twice. The runtime stage has Node only.
- **In CI.** `pnpm/action-setup` reads `packageManager`; `actions/setup-node` reads `.nvmrc` and caches the pnpm store; `pnpm install --frozen-lockfile --no-runtime`.
- **A contributor with nvm or fnm** runs `nvm use`, which reads `.nvmrc`, and gets the same release.

### 6.2 How they are pinned

| Pin | Where | Value |
|---|---|---|
| Node | `.nvmrc` | `24.22.3` |
| Node | `package.json` `devEngines.runtime` and `engines.node` | `24.22.3` |
| Node | `Dockerfile` | `ARG NODE_VERSION=24.22.3`, `FROM node:${NODE_VERSION}-alpine3.24` |
| pnpm | `package.json` `packageManager`; `engines.pnpm` | `pnpm@12.21.0`; `>=12.21.0 <13` |
| pnpm | `Dockerfile` | `ARG PNPM_VERSION=12.21.0` |
| Install policy | `pnpm-workspace.yaml` | `engineStrict: true`; the list of dependencies allowed to run build scripts, named one by one |
| Postgres | `compose.dev.yml`, `compose.prod.yml`, the workflow | `postgres:16.16-bookworm` |
| Caddy | `compose.prod.yml` | `caddy:2.11.9-alpine` |

The Node patch is the newest Node 24 release on the day jade-h8i is implemented (24.22.3 on 2026-11-14); all Node pins move together, and INV9 fails when they differ. Pinning images by digest is jade-8ho.

### 6.3 Recording the Node 24 choice (ADR 0024)

jade-h8i adds `docs/adr/0024-node-24-pinned.md`, following the README's convention for a new ADR (next number, same header lines and sections). The Decision is Mike's note, verbatim. Its full text:

```
# 0024. Node 24 is the pinned Node LTS line

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-h8i, notes (Mike, 2026-11-14)
- Related: [0015](0015-tooling.md)

## Context

ADR 0015 decides "current Node LTS (pinned)", and p1-scaffold (jade-h8i) pins it in `.nvmrc` and the Dockerfile (jade-h8i description). On 2026-11-14 the two newest Node LTS lines were 24 (LTS since 2025-10-28) and 26 (LTS since 2026-10-28) (Node.js release schedule).

## Decision

Decided (Mike, 2026-11-14): pin Node 24 (.nvmrc and Dockerfile).

## Consequences

- `.nvmrc`, `package.json` and the Dockerfile name the same Node 24 release, and a test fails when they differ (jade-h8i).
- ADR 0015 is unchanged. For this build, its "current Node LTS (pinned)" is Node 24.
- Moving to another Node line is a new decision, recorded as a new ADR. Node 24 reaches end of life on 2028-04-30 (Node.js release schedule); p9-deps (jade-8ho) audits the pinned images.
```

Two more edits, and no others, under `docs/adr/`:

- `docs/adr/README.md`: one index row, `| 0024 | [Node 24 is the pinned Node LTS line](0024-node-24-pinned.md) | accepted | bead jade-h8i |`.
- `docs/adr/0015-tooling.md`: one bullet appended under Consequences, `- The pinned Node LTS line is Node 24 ([0024](0024-node-24-pinned.md)).` Its Status, Date, Source, Context and Decision stay byte-identical.

Mike's sign-off on this plan covers this wording. `CLAUDE.md` is not edited.

## 7. jade-h8i: scaffold

**Files.** New: `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `.nvmrc`, `vite.config.ts`, `tsconfig.json`, `eslint.config.js`, `.prettierrc`, `.prettierignore`, `playwright.config.ts`, `src/app.html`, `src/app.d.ts`, `src/error.html`, `src/lib/index.ts`, `src/lib/server/{auth,codes,content,events,analytics}/index.ts`, `src/lib/shared/events/index.ts`, `src/routes/+layout.svelte`, `src/routes/(student)/+layout.svelte`, `src/routes/(student)/+page.svelte`, `src/routes/(adult)/+layout.svelte`, `src/routes/(staff)/+layout.svelte`, `src/routes/api/README.md`, `static/favicon.svg`, `tests/authz/route-registry.ts`, `tests/unit/{toolchain-pins,module-boundaries,route-registry,no-external-refs,repo-hygiene}.test.ts`, `tests/e2e/{smoke,no-offorigin}.spec.ts`, `tools/ci/clean-clone.sh`, `README.md`, `docs/adr/0024-node-24-pinned.md`. Changed: `.gitignore`, `docs/adr/README.md`, `docs/adr/0015-tooling.md`.

**Steps.**

- H0. Preconditions: Mike's answers to Q1 (trunk name) and Q3; pnpm 12.21.0 answers `pnpm --version`.
- H1. Generate the SvelteKit template with the Svelte CLI (`sv create`, template `minimal`, types `ts`, add-ons eslint, prettier, vitest with unit usage, playwright, and the node adapter) into a scratch directory outside the repository, read what it produced, and copy it in. The CLI is run through pnpm under Node 24: a `package.json` carrying the runtime pin of section 6.2 is placed in the scratch directory first. Nothing is generated straight into the repository, so the template cannot overwrite a tracked file unseen. If the CLI will not run, the same files are written by hand from the SvelteKit 3 project-structure documentation.
- H2. `package.json`: the pins of section 6.2, `"type": "module"`, and the `#lib` import alias. `pnpm-workspace.yaml` as in section 6.2. `.nvmrc`. Then `pnpm install`, which provisions Node 24.22.3 and writes the lockfile. If pnpm reports ignored build scripts, only the ones a tool needs are allowed, each by name.
- H3. `vite.config.ts`: the `sveltekit()` plugin with adapter-node and `version.name` taken from `APP_VERSION` (default `dev`). `tsconfig.json` extends `$app/tsconfig` and sets `strict`, `noUncheckedIndexedAccess`, `erasableSyntaxOnly` and `allowImportingTsExtensions`. Nothing is prerendered, so every page passes through `handle`.
- H4. Folders. Each of `auth`, `codes`, `content`, `events`, `analytics` gets an `index.ts` holding a one-line comment of its responsibility (ARCHITECTURE.md section 4) and `export {}`. The three route groups each get a pass-through `+layout.svelte`; `src/routes/api/` gets a README, because it has no endpoint yet. `/` is a placeholder page in `(student)` showing the product name only. `content/` is not created (rule 7).
- H5. Scripts: `dev`, `build`, `preview`, `start` (`node build`), `lint` (`prettier --check . && eslint . --max-warnings 0`), `format`, `check` (the template's type check with warnings as failures), `test` (Vitest, every project but `infra`), `e2e` (`playwright test`), `ci:clean-clone`.
- H6. Vitest projects `unit` (now), `integration` and `blackbox` (added by later beads), `infra` (jade-80h, run only by `pnpm test:infra`). Playwright projects `chromium` (desktop, 1366x768) and `webkit` (an iPad descriptor); its `webServer` builds the app and starts it with `process.execPath`, on a port and `ORIGIN` of its own.
- H7. `tests/authz/route-registry.ts` with the entry for `/`. `tests/unit/route-registry.test.ts` walks `src/routes` for `+page.svelte` and `+server.ts`, derives route ids, and requires set equality with the registry. `tests/e2e/no-offorigin.spec.ts` visits every page in the registry and a URL that does not exist.
- H8. `README.md`: what the project is, prerequisites (Docker, pnpm 12), the setup block, the gate, where the docs are. The setup block sits between `<!-- setup:begin -->` and `<!-- setup:end -->`. `tools/ci/clean-clone.sh` clones `HEAD` into a temporary directory, runs exactly the commands in that block, then `pnpm test` and `pnpm e2e`, then starts `pnpm dev`, waits for `/` to answer 200 and stops it, and finally removes the directory and any Compose project it started. The README's steps are therefore the steps that are tested. The sudo step for WebKit is listed as a machine prerequisite outside the block.
- H9. ADR 0024 and the two one-line edits of section 6.3.
- H10. `.gitignore`: `node_modules/`, `.svelte-kit/`, `build/`, `test-results/`, `playwright-report/`, `blob-report/`, `coverage/`, and Vite's timestamp files. The bugfix skill needs gate output ignored.

**Checks.**

- `tests/unit/toolchain-pins.test.ts`: INV9; `vite.config.ts` names adapter-node; `tsconfig.json` has `strict: true`; TypeScript resolves to 6.0.x.
- `tests/unit/module-boundaries.test.ts`: the five module folders exist with an `index.ts`; no file outside `src/lib/server/<m>/` imports a path inside it other than `index.ts`; `config`, `db` and `log` import nothing from `$app/` or `@sveltejs/kit` (vacuous until those folders exist).
- `tests/unit/route-registry.test.ts` (which also requires the three group folders and `api/` to exist), `tests/unit/no-external-refs.test.ts`, `tests/unit/repo-hygiene.test.ts` (gate output is ignored), `tests/e2e/smoke.spec.ts` (`/` returns 200 with an `h1`), `tests/e2e/no-offorigin.spec.ts`.
- The generated template is searched for remote fonts, CDN links and telemetry snippets before it is copied; `no-external-refs` keeps that true afterwards.
- `pnpm ci:clean-clone` exits 0.

## 8. jade-8v4: typed config and secrets

**Files.** New: `src/lib/server/config/index.ts`, `src/hooks.server.ts`, `tools/env-init.ts`, `tools/load-env.ts`, `.env.example`, `tests/support/{env,server}.ts`, `tests/unit/{config,env-example}.test.ts`, `tests/blackbox/boot-failfast.test.ts`. Changed: `.gitignore` (`.env`, `.env.*`, `!.env.example`), `vite.config.ts`, `package.json` (zod as a dependency; `env:init`), `README.md`, `tests/unit/repo-hygiene.test.ts`.

**Design.**

- V1. One module, no SvelteKit import. `loadAppConfig(env)` is pure and returns a frozen typed object or throws `ConfigError`. `getConfig()` parses `process.env` once and memoizes. `loadMigrationConfig(env)` is added by jade-urd. No other file reads `process.env` for app settings (lint: `no-restricted-properties` on `process.env` in `src/`, outside this module).
- V2. Schema (zod). `APP_ENV`: required enum. `DATABASE_URL`: required, a `postgres:` or `postgresql:` URL whose user is `jade_app`. `CODE_PEPPER`, `SESSION_SECRET`: required, at least 43 characters of `[A-Za-z0-9_+/=-]` (32 random bytes in base64, base64url or hex). `LOG_LEVEL`: `debug`, `info`, `warn` or `error`, default `info`. No secret key has a default or a fallback, in any `APP_ENV`, test included: tests pass their values explicitly. A value containing `test-only` is refused unless `APP_ENV` is `test`. `SESSION_SECRET` is required now although nothing uses it before Phase 3, because the bead names it.
- V3. Fail fast. The `init` hook calls `getConfig()` unless the app is building, so the image build needs no secret and a missing variable stops the process before it listens. `ConfigError`'s message is built from variable names and fixed phrases only, for example `Configuration error. Missing: CODE_PEPPER, SESSION_SECRET. Invalid: DATABASE_URL (must be a postgres URL for role jade_app). See .env.example.` It lists every problem at once, and never includes a value or zod's own message text.
- V4. `.env.example` documents every variable with a comment: what reads it, whether it is a secret, how to generate it. Secrets are empty. It covers the app's variables, the adapter's (`PORT`, `HOST`, `ORIGIN`), the migration tool's, and the Compose files' interpolation variables, as later beads add them.
- V5. `pnpm env:init` writes `.env` from `.env.example` with freshly generated random secrets, mode 600. It refuses to overwrite an existing file and prints variable names only. For the development database it uses port 5432 when that is free and the next free port otherwise, or the one given with `--db-port`, so a second worktree gets a database of its own. `.env` is ignored by git and by Docker.
- V6. `.env` is read only outside production: `vite.config.ts`, `playwright.config.ts`, `drizzle.config.ts` and the tools call `tools/load-env.ts`, which is `process.loadEnvFile('.env')` when the file exists and `NODE_ENV` is not `production`. `node build` never reads a file.
- V7. Contract for later beads: the config object exposes `codePepper` and `sessionSecret` as opaque strings. How jade-fd5 derives key bytes from `CODE_PEPPER` is its decision and must be fixed before any code is generated (section 15).

**Checks.**

- `tests/unit/config.test.ts`: with any one of `APP_ENV`, `DATABASE_URL`, `CODE_PEPPER`, `SESSION_SECRET` removed, `loadAppConfig` throws and names it, for each of the four `APP_ENV` values; a short pepper, a non-postgres URL and a URL for another role are refused; a `test-only` value is refused under `staging` and `production`; canary values placed in bad inputs never appear in the error text; the schema source has no default on a secret key.
- `tests/blackbox/boot-failfast.test.ts`: `node build` with each required variable missing in turn exits non-zero within 5 seconds, prints the variable's name and no value, and never prints the adapter's start-up line. With all set, it listens. `pnpm build` succeeds with an empty environment.
- `tests/unit/env-example.test.ts`: the keys of `.env.example` are a superset of the config schemas' keys, of every `process.env.NAME` read in `tools/`, and of every `${NAME}` in the Compose files; every secret key is empty.
- `tests/unit/repo-hygiene.test.ts`: `git check-ignore .env` succeeds; `git ls-files` lists no `.env*` but `.env.example`.

## 9. jade-urd: database, migrations, test harness

**Files.** New: `compose.dev.yml`, `drizzle.config.ts`, `src/lib/server/db/{index,client,migrate,roles,schema}.ts`, `migrations/0000_baseline.sql`, `migrations/manifest.json`, `migrations/meta/` (Drizzle Kit's journal and snapshot), `migrations/README.md`, `tools/db/{migrate,reset,manifest,check-migrations}.ts`, `tests/support/{db,global-setup-db}.ts`, `tests/integration/{migrate,baseline-migration,harness-isolation-a,harness-isolation-b,db-scripts}.test.ts`, `tests/unit/migrations-static.test.ts`. Changed: the config module, `.env.example`, `tools/env-init.ts`, `package.json` (`pg`, `drizzle-orm` as dependencies, `drizzle-kit` as a dev dependency; scripts), the Vitest and Playwright configs, `README.md`, `tests/unit/toolchain-pins.test.ts`, and the "The gates" paragraph of `.claude/skills/bugfix/SKILL.md`.

**Design.**

- U1. `compose.dev.yml`: one service, `db`, `postgres:16.16-bookworm`, user `jade_owner`, password `${JADE_OWNER_DB_PASSWORD:?}`, database `jade`, a named volume, a `pg_isready` health check, published on `127.0.0.1:${JADE_DEV_DB_PORT:-5432}` only. There is no hard-coded password. `pnpm db:up` is `docker compose -f compose.dev.yml up -d --wait db`; `pnpm db:down` stops it.
- U2. Roles (PD3). `loadMigrationConfig(env)` requires `MIGRATION_DATABASE_URL` (user `jade_owner`) and `DATABASE_URL` (user `jade_app`). `ensureAppRole()` in `roles.ts` runs as the owner: it creates `jade_app` with `LOGIN` if it is missing and sets its password from `DATABASE_URL`. The password is sent as a SCRAM-SHA-256 verifier computed in the tool, never as plain text in SQL, so it cannot reach a Postgres log even when a statement fails. Role names are fixed, because migration files grant to `jade_app` by name. The same code runs in development, CI and the image.
- U3. The runner, `migrate()` in `src/lib/server/db/migrate.ts`, called by `tools/db/migrate.ts` (`pnpm db:migrate`):
  1. Connect as the owner and take a session advisory lock, so two runners cannot interleave.
  2. `ensureAppRole()`.
  3. Create the ledger if absent: `schema_migrations (name text primary key, sha256 text not null, applied_at timestamptz not null default now())`. It is bookkeeping, not a DATA-MODEL table, and it holds no kit data.
  4. Read `migrations/*.sql` in name order and check them against `migrations/manifest.json`.
  5. Compare with the ledger, row by row. A different name or hash at any position stops with `MIGRATION_HISTORY_MISMATCH` and applies nothing. If the ledger is longer than the shipped list, the database is ahead: log it and exit 0.
  6. Apply each pending file in its own transaction together with its ledger row. A failure rolls that file back and exits non-zero.
  There is no down command and no way to reapply. A file that cannot run inside a transaction is out of scope until one is needed.
- U4. The sample migration, `0000_baseline.sql`, is hand-written SQL created with `drizzle-kit generate --custom`: it revokes `CREATE` on schema `public` from `PUBLIC`, and grants `jade_app` `USAGE` on the schema and `SELECT` on `schema_migrations` (readiness reads the ledger). It creates no table. `src/lib/server/db/schema.ts` is empty until Phase 2.
- U5. Forward-only and compatibility rules, written in `migrations/README.md` and enforced by INV5: files are immutable once merged; `manifest.json` (name and sha256 per file, written by `pnpm db:manifest`) is the lock, and it is also what the app bundles to know which migrations it ships; a release may add, and may remove or rename only what the previous release no longer reads, so a destructive change ships one release after the code stops using the thing. Drizzle Kit's `migrate` and `push` commands are never used.
- U6. `pnpm db:reset` drops and recreates the database named in the URLs and migrates it. It refuses unless `APP_ENV` is `development` or `test` and the host is a loopback address. `pnpm db:generate` is `drizzle-kit generate` followed by `pnpm db:manifest`.
- U7. Test harness (PD5). The integration project's global setup migrates a template database once per run. `createTestDatabase()` in `tests/support/db.ts`, called in a file's `beforeAll`, clones the template into a uniquely named database and returns an owner pool and an app-role pool; `afterAll` drops it; global teardown drops the template and anything left over. Vitest runs files in parallel. A test that needs a table creates a scratch table in its own database; no table is added to `migrations/` for tests. Playwright's global setup resets and migrates one database, `jade_e2e`, for the server under test.
- U8. The bugfix skill's gates paragraph gains the two commands a gate now needs in a fresh worktree (`pnpm env:init`, `pnpm db:up`). A subagent makes the edit and runs both skill test suites, as CLAUDE.md requires.

**Checks.**

- `tests/integration/migrate.test.ts`: a fresh database ends with the ledger equal to the manifest; a second run applies nothing; changing one byte of an applied file stops the runner with `MIGRATION_HISTORY_MISMATCH` and leaves the ledger as it was; a file that fails is rolled back with no ledger row; two runners started together apply each file exactly once; with one extra migration applied from a temporary directory, the readiness function of an app that ships only the baseline still reports ready, and with the baseline missing it reports behind.
- `tests/integration/baseline-migration.test.ts` (the sample integration test): the ledger has `0000_baseline`; over the app pool `SELECT` from `schema_migrations` works, while `CREATE TABLE` and `INSERT INTO schema_migrations` are refused; the app URL's password works and a wrong one does not.
- `tests/integration/harness-isolation-a.test.ts` and `-b.test.ts`: each creates the same scratch table name and writes different rows while the other runs; neither sees the other's rows, and each has its own database name.
- `tests/integration/db-scripts.test.ts`: against a scratch database, the entry points that `pnpm db:reset` and `pnpm db:migrate` name both succeed, reset removes a scratch table, a second migrate is a no-op, and reset under `APP_ENV=production` exits non-zero and changes nothing.
- `tests/unit/migrations-static.test.ts` and `pnpm db:check --base <ref>`: as INV5.

## 10. jade-alt: health endpoints, logs, request ids

**Files.** New: `src/lib/server/log/index.ts`, `src/lib/server/http/{index,request-context,readiness,dev-only}.ts`, `src/routes/healthz/+server.ts`, `src/routes/readyz/+server.ts`, `src/routes/dev/boom/+server.ts`, `src/routes/+error.svelte`, `tests/unit/log-schema.test.ts`, `tests/blackbox/{health,log-privacy,request-id,route-access}.test.ts`. Changed: `src/hooks.server.ts`, `src/app.d.ts`, `eslint.config.js`, `tests/authz/route-registry.ts`.

**Design.**

- A1. Logger (PD6). One JSON object per line on stdout. Three line kinds, each with a closed key set:
  - request: `ts`, `level`, `msg` (`request`), `request_id`, `method`, `route`, `status`, `duration_ms`;
  - error: `ts`, `level`, `msg` (`error`), `request_id`, `route`, `kind`, `err_type`, `err_tag`, `stack_frames`;
  - lifecycle: `ts`, `level`, `msg` (one of a fixed list such as `boot`, `shutdown`, `migrate`) and keys from the allowlist, such as `migration` and `count`.
  Every key has a validator: `route` must be a known route id or `null`; `method` an HTTP method; `err_type` an identifier; `err_tag` upper-case letters, digits and underscores (a Postgres SQLSTATE, or one of the app's own error tags); `stack_frames` frame lines only, without the first line of the stack. A value that fails is written as `[invalid]`. An error's message and its other properties are never written. In `APP_ENV=development` only, the raw error is also printed to the terminal. Key names that could carry forbidden data cannot be put on the allowlist: `ip`, `addr`, `cookie`, `code`, `token`, `email`, `body`, `authorization`, `password`, `secret`, `pepper`, `url`, `path`, `query`, `headers`, `user_agent`, `referer`, `kit`, `class`, `session`, `step`, and any key that has one of them as an underscore-separated part.
- A2. Request logging in `handle`: generate a request id with `crypto.randomUUID()`, resolve, write one request line, and set `X-Request-Id` on the response. An incoming `X-Request-Id` is ignored; honouring it would let a client write into the logs. `route` is `event.route.id` (C2). A 2xx from `/healthz` or `/readyz` logs at `debug`, so health probes do not fill the log; 5xx logs at `error`.
- A3. `/healthz` returns 200 `{"status":"ok","version":"<APP_VERSION>"}` and touches nothing else. `/readyz` runs one query over the app pool with a 2-second limit and compares the ledger with the bundled manifest: 200 `{"status":"ready"}` when the database answers and every shipped migration is applied with the same hash; otherwise 503 with `status` `not_ready`, a `checks` object (`db`: `ok` or `fail`; `migrations`: `ok`, `behind`, `mismatch` or `unknown`) and the request id. A database that is ahead is ready, which is what lets the previous image run after a newer migration (OB53). Both send `Cache-Control: no-store`, and neither reveals a host name or an error text.
- A4. Request id in errors. `App.Error` gains `requestId`; `handleError` returns it for every kind, logs an error line for kind `unknown` only, and never throws. JSON error bodies and `+error.svelte` show it; the header is on every response that passes through `handle`, including the fallback `src/error.html`. Handlers for `uncaughtException` and `unhandledRejection` write an error line and exit 1; on `sveltekit:shutdown` the pool is closed.
- A5. Routes and the registry. `/healthz` and `/readyz` are entered as `public`, with the note that they return no data about anyone. `/dev/boom` (PD8) throws an error whose message contains the request's query string; it exists so that the error path can be tested on the built server. Every `/dev/` route calls `assertDevRoute()`, which answers 404 unless `APP_ENV` is `development` or `test`.

**Checks.**

- `tests/unit/log-schema.test.ts`: as INV1, including a Postgres-style error whose message, `detail` and `parameters` hold canaries.
- `tests/blackbox/log-privacy.test.ts`: as INV1. For each registry route, every `[param]` is replaced by a kit-code-shaped canary, and the request carries canaries in the query (`?code=`, an email), a cookie, `Authorization`, `X-Forwarded-For`, `X-Request-Id` and a POST body. `/redeem?code=<canary>`, which does not exist yet, is requested as well. The IP patterns are applied to every value but `ts`.
- `tests/blackbox/health.test.ts`: `/healthz` is 200 with no database; `/readyz` is 200 on a migrated database, 503 with `db: fail` when `DATABASE_URL` points at a closed port (within 3 seconds), and 503 with `migrations: behind` on an empty database.
- `tests/blackbox/request-id.test.ts`: a 404 (JSON and HTML), a 405, a 503 from `/readyz` and a 500 from `/dev/boom` each carry `X-Request-Id`, and the body's `requestId` equals it; two requests get different ids; a client-sent id is not used; no Phase 1 response sets a cookie.
- `tests/blackbox/route-access.test.ts`: every `public` route answers without a session; every `dev-only` route is 404 under `APP_ENV=production` and reachable under `test`; every route id containing `/dev/` is `dev-only`.

## 11. jade-80h: image and production Compose stack

**Files.** New: `Dockerfile`, `.dockerignore`, `compose.prod.yml`, `deploy/caddy/Caddyfile`, `deploy/caddy/media-files.caddy`, `tests/infra/{image,compose-config,compose-up,caddy-logs,media}.test.ts`, `tests/infra/fixtures/`. Changed: `package.json` (`ci:image`, `test:infra`), `.env.example`, `tools/env-init.ts`, `tests/unit/{toolchain-pins,repo-hygiene}.test.ts`, `README.md`.

**Design.**

- D1. Dockerfile, two stages. Build: the pinned Node Alpine image, pnpm, `pnpm install --frozen-lockfile --no-runtime`, `pnpm build` with `APP_VERSION` as a build argument, then production dependencies only. Runtime: the same Node image, `NODE_ENV=production`, the `build/` output, production `node_modules`, `package.json`, `migrations/`, `tools/db/` and the three SvelteKit-free folders the migration tool imports (`config`, `db`, `log`); `USER node`; a `HEALTHCHECK` that fetches `/healthz` with Node; `CMD ["node","build"]`. The migration tool runs as `node tools/db/migrate.ts`, relying on Node 24 stripping types; if that does not hold in the image, the build stage compiles the tool to JavaScript instead, and the deviation is recorded (RR4). `.dockerignore` keeps `.git`, `.env*`, `node_modules`, `docs/`, `plans/`, `.beads/`, `.claude/` and `tests/` out of the build context. No build step needs a secret.
- D2. `compose.prod.yml`, four services and two networks:
  - `db`: Postgres 16, a named volume, user `jade_owner`, password `${JADE_OWNER_DB_PASSWORD:?}`, health check, network `backend` only, no `ports`.
  - `migrate`: the app image with the migration command; receives both URLs; starts after `db` is healthy; exits.
  - `app`: `image: ${JADE_IMAGE:-jade-app:local}` with `build: .` as the local fallback; receives `APP_ENV`, `DATABASE_URL` (app role), `CODE_PEPPER`, `SESSION_SECRET`, `LOG_LEVEL` and `ORIGIN=https://${SITE_ADDRESS:?}`, each secret as `${NAME:?}`; starts only after `migrate` completed successfully; read-only root filesystem, all capabilities dropped, `no-new-privileges`; no `ports`.
  - `caddy`: `caddy:2.11.9-alpine`; the only service with `ports`, `${JADE_HTTP_PORT:-80}:80` and `${JADE_HTTPS_PORT:-443}:443`; volumes for certificates and config; the media volume mounted read-only; starts after `app` is healthy.
  - Networks: `edge`, and `backend` with `internal: true`, so the app and the database have no route to the internet. Caddy is on both.
  - Container logs are size-capped (`max-size`, `max-file`) so that a disk cannot fill; the 14-day rule is jade-ada.
  The file declares its own project name (`name: jade-stack`), so bringing it up in a checkout never touches the development `db` service or its volume; the infra tests pass a project name of their own. The Compose project's `.env` is the env file on a VM: one file, mode 600, from which each service is given only the variables listed above. Generated passwords use `[A-Za-z0-9_-]` only, so they can sit in a URL unescaped.
- D3. Migrations on deploy (C6): the `migrate` service and the `depends_on` conditions above. Locally, `docker compose -f compose.prod.yml up` with the `.env` from `pnpm env:init` (which sets `SITE_ADDRESS=localhost`) builds the image, migrates, starts the app and serves it at `https://localhost` with Caddy's internal certificate.
- D4. Caddyfile. The site address is `{$SITE_ADDRESS}`, which gives automatic TLS (the internal CA for `localhost`, ACME for a real name). `encode zstd gzip`. No `log` directive in the site block, so there is no access log. The global `log` block filters Caddy's own runtime logs so that the `request` object is deleted from every entry, and excludes the standard-library HTTP logger, whose messages can embed a peer address. HTTP/3 is switched off, because only TCP 80 and 443 are published. `reverse_proxy app:3000` removes `X-Forwarded-For` before the request reaches the app: nothing in Phase 1 uses a client address, and the flag of ADR 0020 restores it deliberately (section 15). The exact filter syntax for Caddy 2.11 is confirmed with `caddy validate` in the pinned image; the behavioural test is what decides.
- D5. `/media` (C1). `handle /media/*` answers `respond 403`, with a comment naming ADR 0007 and jade-u8z. `deploy/caddy/media-files.caddy` holds the file-server directives for the media volume and is not imported by the site block.

**Checks** (`pnpm test:infra`, which builds `jade-app:ci` first):

- `tests/infra/image.test.ts`: `docker image inspect --format '{{.Size}}'` is below 300,000,000 bytes (both the value and what the image store reports are recorded in the bead's notes); the configured user is `node` and `id -u` inside is not 0; a `HEALTHCHECK` is present; `node --version` inside equals `.nvmrc`; no `.env` exists in the image.
- `tests/infra/compose-config.test.ts`, on the file's text and on `docker compose -f compose.prod.yml config` with a throwaway env file and default port variables: only `caddy` has `ports`, exactly 80 and 443 over TCP; `db` and `app` are on `backend` only and it is internal; every secret is a `${NAME:?}` reference, and `config` fails when any one of them is unset; `app` has neither `MIGRATION_DATABASE_URL` nor the owner password; `app` and `migrate` take their image from `JADE_IMAGE`; the images match the pins.
- `tests/infra/compose-up.test.ts`, with a temporary env file, a project name of its own and high host ports: `up -d --wait` succeeds; `https://localhost:<port>/` and `/healthz` answer 200 through Caddy; plain HTTP redirects to HTTPS; a compressed response is offered; the ledger holds the baseline, which shows `migrate` ran first; ports 3000 and 5432 refuse connections from the host; stopping `db` turns `/readyz` into 503 and starting it brings 200 back; with one fixture migration mounted over `/app/migrations`, a second `up` applies it and `/readyz` stays 200.
- `tests/infra/caddy-logs.test.ts`: after normal requests, after requests with the app container stopped (502), and after a broken TLS handshake, no Caddy log line contains the Docker gateway address the requests came from, a `remote_ip` or `client_ip` key, the canary code sent in `/redeem?code=`, or the canary cookie.
- `tests/infra/media.test.ts`: `/media/x.mp4` through the stack is 403, with and without a `Range` header; a throwaway Caddy container that imports `media-files.caddy` over a fixture file answers a `Range: bytes=0-99` request with 206 and the right `Content-Range`.

## 12. jade-xu0: CI pipeline

### 12.1 What is built

**Files.** New: `.github/workflows/ci.yml`, `tools/ci/local.sh`, `tools/ci/migration-compat.sh`, `tests/unit/ci-workflow.test.ts`. Changed: `package.json` (`ci:check`, `ci:e2e`, `ci:image`, `ci:compat`, `ci:local`), `README.md`.

- X1. The logic lives in pnpm scripts, so the workflow is thin wiring and a different host would reuse them: `ci:check` (`pnpm lint && pnpm check && pnpm db:check --base <ref> && pnpm test`), `ci:e2e`, `ci:image` plus `test:infra`, `ci:compat`. `pnpm ci:local` runs them in order and prints a timing per stage.
- X2. `.github/workflows/ci.yml`, written now because ADR 0015 decides GitHub Actions; no host, remote or registry is invented by writing it. Triggers: `pull_request`, and `push` to `main`. `permissions: contents: read`. A concurrency group cancels superseded runs of a pull request. The runner image is pinned (`ubuntu-24.04`), and every third-party action is pinned to a full commit SHA. Four parallel jobs:
  - `check`: a Postgres 16 service container with CI-only credentials; pnpm and Node setup with the pnpm store cached; `pnpm ci:check`.
  - `e2e`: the same service container; `playwright install --with-deps chromium webkit`; `pnpm ci:e2e` on both browsers; on failure, `playwright-report/` and `test-results/` are uploaded as an artifact kept 7 days.
  - `image`: buildx with the Actions cache; `pnpm ci:image`; `pnpm test:infra`.
  - `migration-compat`: always starts and ends at once unless `migrations/` changed, so it can be a required check.
  No app secret appears in the workflow. The service container's password is a literal that exists only for the life of the job, and it contains `test-only`, which the config module refuses outside `APP_ENV=test`.
- X3. Every job has `timeout-minutes: 9`. The jobs are parallel, so a run that passes took under 10 minutes of execution (section 12.2).
- X4. `migration-compat` (INV5): check out the base commit beside the head, install and build it, apply the head's migrations to a fresh database, start the base build and require `/readyz` 200, then run the base's integration tests against that database. `pnpm ci:compat --base <ref>` does the same locally with a temporary git worktree. It has nothing to compare until a second migration exists; its first real use is Phase 2.
- X5. On the host, once it exists: the first green run, branch protection requiring the four jobs, and the proof that a failing run uploads the report (section 12.3).

**Checks.** `tests/unit/ci-workflow.test.ts` parses the workflow and asserts: the two triggers; the four jobs; a Postgres service whose image equals the pin; both browser projects; the pnpm cache; lint with `--max-warnings 0`; an upload step conditioned on failure; `timeout-minutes` of 9 or less on every job; actions pinned by a 40-character SHA; and that none of `CODE_PEPPER`, `SESSION_SECRET`, `DATABASE_URL` or a `JADE_*_PASSWORD` is drawn from the secret store. The file is also linted with `actionlint` from its pinned container image. `pnpm ci:local` exits 0.

### 12.2 Time budget

Estimates for a 4-vCPU hosted runner; they are replaced by measurements from the first real runs.

| Job | Cold cache | Warm cache | Made of |
|---|---|---|---|
| `check` | 3:30 | 3:00 | setup and install 1:15 or 0:50; lint 0:25; type check 0:30; unit, integration and black-box tests including one build 1:15 |
| `e2e` | 4:30 | 3:30 | setup and install 1:15 or 0:50; browsers and OS libraries 1:15 or 0:45; build 0:25; both browsers 1:30 |
| `image` | 5:15 | 3:30 | setup 0:30; image build 3:00 or 1:15; infra tests 1:45 |
| `migration-compat` | 0:15, or 3:30 when migrations change | same | second checkout, install, build, base integration tests |
| Whole run | about 5:15 | about 3:30 | the slowest job; the 9-minute timeout leaves over 3 minutes of slack |

If a measured run exceeds 7 minutes, the first levers are the Playwright container image in place of installing browsers, and splitting the infra tests from the image build. The staging deploy of jade-4zw runs as its own workflow after CI succeeds on `main`, so it does not lengthen this one.

### 12.3 The remote-less state

| | Now | Waits on |
|---|---|---|
| Stage scripts, `pnpm ci:local`, local timings | Delivered and run | |
| The workflow file, its static test and lint | Delivered | |
| First run on the host | | Mike naming the remote and CI host, and the first push (Q1) |
| OB10, measured | Local timing only, which is indicative (32 CPUs) | The first runs on the host |
| OB11, protected trunk requiring the workflow | | The remote; a trunk called `main` (C9); someone with admin rights setting the rule, Mike in the web UI or an agent through the API with a credential Mike supplies (`gh` is not installed and not assumed) |
| OB12, report uploaded on failure | Static assertion | A deliberately failing branch pushed to the host |
| OB5, the sample migration and test "in CI" | Pass in `pnpm ci:local` | The first green `check` job |
| Pushing the image | | The registry (Q1) |

"Done" for jade-xu0 meanwhile: X1 to X4 delivered, their checks green locally, and the bead left open with a note listing exactly the rows above that wait. It is not closed, and jade-4zw stays blocked behind it. If Mike names a host other than GitHub, the workflow file is rewritten for it (assumption A6, "Swap the CI and authoring-guide details"), the scripts are kept, and ADR 0015's "GitHub Actions" becomes a question for Mike, not something an agent changes.

## 13. jade-lhq: layout, tokens, accessibility baseline

**Files.** New: `src/lib/styles/{tokens,base}.css`, `src/lib/components/shell/{StudentShell,AdultShell,StaffShell}.svelte`, `src/routes/(student)/dev/shell/student/+page.svelte` and `+page.server.ts`, the same pair for `(adult)` and `(staff)`, `tests/e2e/{a11y,layout}.spec.ts`. Changed: the root and group layouts, `src/routes/(student)/+page.svelte`, `tests/authz/route-registry.ts`.

**Design.**

- L1. Tokens as CSS custom properties: colour pairs chosen for WCAG AA contrast, spacing, radii, a type scale, `--tap-min: 48px`, and a system font stack (`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`). There is no `@font-face` and no font file. `base.css` sets the reset, focus-visible outlines, and a `prefers-reduced-motion: reduce` block that removes transitions and animations.
- L2. Three shells that differ visibly and structurally: the student shell (body text 18px or larger, large targets, one column, minimal chrome), the adult shell (compact, with a navigation region), and the staff shell (dense, a distinct colour band and a "Staff" label). Each group layout wraps its pages in its shell and sets `data-shell` on the root element. Each has a skip link, one `main` landmark and one `h1`.
- L3. Pages. `/` shows the student shell with the product name. `/dev/shell/student`, `/dev/shell/adult` and `/dev/shell/staff` (PD8) show each shell with neutral sample elements: a heading, a paragraph, a link and a button. There is no form field (rule 1) and no teaching content (rule 7).
- L4. Tests read their page list from the route registry, so a later page is covered automatically or the registry test fails.

**Checks** (both browsers).

- `tests/e2e/no-offorigin.spec.ts`: as INV3, now over all four pages and the error page.
- `tests/e2e/a11y.spec.ts`: axe finds no violation on the student shell pages (`/`, `/dev/shell/student`); it is run on the adult and staff shells too. Contrast is covered by axe's rule.
- `tests/e2e/layout.spec.ts`: at 360x640 and at 1366x768, on each shell, the document has no horizontal overflow and the `main` landmark and `h1` are visible; on student pages the computed body font size is at least 18px and every link and button is at least 48 by 48 CSS pixels; with reduced motion emulated, the sample button's transition duration is effectively zero; the three shells report three different `data-shell` values. No screenshot comparison is used, because a system font stack renders differently on each machine.

## 14. jade-4zw: staging (specified, not started)

jade-4zw is blocked by the human bead jade-0za and depends on jade-xu0, which cannot finish without a remote. No part of it is started until both are resolved. This section is its specification and the list of what must be supplied.

**What jade-0za must supply** (through Mike, never as a secret pasted into a bead):

1. The provider and the Canadian region, recorded in ADR 0004 by jade-0za.
2. The staging host name under the registered domain, and the DNS record for it. A DNS change is Mike's to make.
3. The staging VM, or the means to create it. The account and its billing are Mike's.
4. How a deploy authenticates: a key for a non-root deploy user, placed in the CI secret store by Mike, and how port 22 is restricted (C11).
5. Who creates the staging env file on the VM. A secret is needed there, which is a stop-and-ask point.

**What Q1 must supply:** the remote and CI host, and the image registry with its credentials.

**Design, for when it is unblocked.**

- Z1. The VM: the provider's firewall allowing 80 and 443 from anywhere and 22 as decided under C11; a non-root deploy user in the `docker` group; Docker and the Compose plugin; the steps scripted in `deploy/staging/` so the VM can be rebuilt.
- Z2. Secrets: `tools/env-init.ts` run on the VM writes the env file with `APP_ENV=staging` and freshly generated secrets. They never leave the VM and never enter CI or the repository, so staging has its own by construction. CI holds only the deploy key and the registry credential.
- Z3. CI: on `main`, the `image` job pushes the image it tested, tagged with the commit SHA. A deploy workflow that starts when CI succeeds on `main` connects to the VM and runs the deploy script with the image's digest. No manual step.
- Z4. `deploy/deploy.sh <image@digest>`, as the deploy user: pull; run migrations with the new image (`docker compose run --rm migrate`), and stop if that fails, with the old app untouched; start the new image as a candidate container that Caddy does not route to, and poll its `/readyz`; if it never becomes ready, remove the candidate and exit non-zero, so the previous version is still the one running; otherwise switch the `app` service to the new image, with Caddy retrying the upstream during the swap, and check `/readyz` and the version in `/healthz` through Caddy; if that fails, return to the previous image and exit non-zero. The current and previous image references are kept in files beside the env file. The script is rehearsed locally against the Compose stack with a good and a deliberately broken image before it is used on the VM.
- Z5. The STAGING banner: the root layout's server load passes `APP_ENV` to the page, and a fixed, high-contrast "STAGING" bar is rendered when it is `staging`. An e2e run against a server started with `APP_ENV=staging` and generated secrets asserts the bar is visible, and the normal run asserts it is absent.
- Z6. The staging URL is written into `README.md`. The deploy workflow's last step fetches `https://<staging host>/healthz` with certificate verification on. The region is evidenced by the provider's own record of the VM, noted on the bead and in ADR 0004.

## 15. Later-phase consumers

What Phase 1 hands on. The orchestrator appends the matching note to each bead (`bd update <id> --append-notes`) when the Phase 1 bead that creates the contract lands.

| Consumer | What it gets | What it must do |
|---|---|---|
| jade-o07 (p2-schema-core) | `pnpm db:generate`, the runner, `createTestDatabase()` | Add explicit grants to `jade_app` for every table; regenerate the manifest; the `citext` extension goes in its own migration |
| jade-fd5 (p2-code-lib) | `getConfig().codePepper` | Fix how key bytes are derived from the string before any code is generated; never pass the pepper to the logger |
| jade-99j, jade-q01 | The `tools/` pattern, `tools/load-env.ts`, `APP_ENV` | Refuse to run in production through `APP_ENV`; keep output directories ignored |
| jade-aq5 (p3-authz-tests) | `tests/authz/route-registry.ts` and its completeness test | Widen each entry to the five actors; keep `dev-only` |
| jade-vcy, jade-6cq | Caddy removes `X-Forwarded-For`; `/healthz` and `/readyz` are unauthenticated and unthrottled, and `/readyz` makes one database query per call | For the per-IP flag of ADR 0020, restore the header in Caddy, set the adapter's address header and depth, and add the flag to the config module; decide whether the health endpoints need a limit |
| jade-u8z (p4-video) | The 403 gate, the snippet, the read-only media volume in Caddy | Replace the gate with the signed-URL check; import the snippet |
| jade-as7 (p4-lock) | `ci:check` | Add `pnpm content:lint` to it |
| jade-7j8 (p6-table) | The two roles; an app-role pool in tests | Grant `jade_app` insert and select only on `events`; test the refusal over the app pool |
| jade-hhp (p6-nolog-invariant) | The closed logger and its forbidden keys; the black-box server helper | Assert on the built server's captured output; keep the test in a required job |
| jade-3ek (p6-catalog) | `src/lib/shared/events/`; the build's `APP_VERSION` | Use it as `app_version` |
| jade-d98, jade-mz1 | The axe and off-origin specs | Extend them; a service worker's requests are already recorded at context level |
| jade-c42 (p9-headers) | No CSP yet | Set it through the `sveltekit()` plugin's `csp` option; add the other headers |
| jade-ada (p9-logs) | Caddy's runtime-log filter; the adapter's plain start-up line; size-capped container logs | Grep staging logs; replace the size cap with 14-day retention |
| jade-8ho (p9-deps) | Images pinned by tag, checked by INV9 | Pin by digest |
| jade-lnn.1 | The env-file contract: variable names, lengths, the password alphabet; `tools/env-init.ts` | Build the production script on it |
| jade-kn0 (p10-cd) | The deploy script's gate, images by digest, readiness that tolerates a newer database, `ci:compat` | Promote the staging image by digest; rehearse rollback |
| jade-j93 (p10-monitoring) | `/readyz`, public; an app with no outbound route | Probe from outside; alerts cannot originate in the app container |

One bead to file when the work reaches it, `discovered-from` jade-h8i: fill the "Build & Test" placeholder of `CLAUDE.md` with the Phase 1 commands. A change to that file is Mike's to approve.

## 16. Order of work, gates and stop points

Nothing here starts on approval. Implementation begins only on Mike's go-ahead, given after approval and sign-off, and is then carried out bead by bead by subagents the orchestrator briefs.

**Order.** jade-h8i, jade-8v4, jade-urd, jade-alt, jade-80h, jade-xu0, jade-lhq, jade-4zw. This respects every dependency in the phase file: jade-h8i first; jade-8v4, jade-urd and jade-lhq after it; jade-alt after jade-8v4; jade-xu0 after jade-urd; jade-80h after jade-urd and jade-alt; jade-4zw last and blocked. Within that, P0 beads come first where dependencies allow. jade-alt (P1) precedes jade-80h because jade-80h depends on it; jade-8v4 precedes jade-urd because the migration tool reads its URLs through the config module; jade-xu0 follows jade-80h because its `image` job builds the Dockerfile.

**For each bead.**

1. The orchestrator runs `bd show <id>` and briefs one subagent with this plan's section, the files to read, the checks to write, and the paths it must not touch.
2. The subagent implements with tests on a branch named for the bead, cut from the previous bead's branch. Nothing is merged into the trunk by an agent until Q1 is answered.
3. The orchestrator runs `pnpm lint && pnpm check && pnpm test && pnpm e2e`, plus `pnpm test:infra` from jade-80h on, and records each command's exit status in the bead's notes.
4. The work is committed with the bead id in the message, under Mike's authorization for commits.
5. Closing follows Q2. Without an answer the default is the conservative one: the bead stays open with its evidence in its notes, no bead is closed on local gates alone, and the next bead is started only if Mike's go-ahead named this order.

**Stop points** (stop and ask Mike):

- Anything that needs a secret that is not generated and kept on the machine that uses it: the staging env file, CI secrets, registry credentials.
- A DNS change, a payment, creating a VM, or any production deploy.
- Creating a remote, pushing, or changing branch protection.
- sudo on the development machine, or any change to Mike's shell profile beyond what Q3 allows.
- A change that would touch CLAUDE.md rules 1 to 6, the logger's forbidden-key list or line schema, or any ADR. An ADR that looks wrong becomes a `decision` bead.
- A deviation from this plan that changes a mechanism rather than a name (RR4): back to planloop.
- A human bead blocking all remaining work, or the same test failing three times after three different fixes.

## 17. Acceptance

Phase exit criteria:

- AC1 (OB35): `pnpm ci:clean-clone` exits 0. It clones `HEAD`, runs the README's setup block, then `pnpm test`, `pnpm e2e` and a `pnpm dev` smoke check. Not blocked, given Q3.
- AC2 (OB36): the workflow is green on the trunk and is a required check. **Blocked** by Q1: no remote, no CI host, no trunk named `main`.
- AC3 (OB37): `curl -fsS https://<staging host>/healthz` returns 200 over a valid certificate, and the provider's record shows a Canadian region. **Blocked** by jade-0za, and by AC2.

Per bead, each on that bead's commit:

- AC4, jade-h8i: the gate exits 0; `toolchain-pins`, `module-boundaries`, `route-registry`, `no-external-refs`, `repo-hygiene`, `smoke` and `no-offorigin` pass; `pnpm ci:clean-clone` exits 0.
- AC5, jade-8v4: `config`, `env-example`, `repo-hygiene` and `boot-failfast` pass.
- AC6, jade-urd: `migrate`, `baseline-migration`, both `harness-isolation` files, `db-scripts` and `migrations-static` pass; `pnpm db:check` passes; both skill test suites pass after the bugfix skill edit. The "in CI" half of OB5 is **blocked** by Q1.
- AC7, jade-alt: `log-schema`, `log-privacy`, `health`, `request-id` and `route-access` pass.
- AC8, jade-80h: `pnpm test:infra` passes (`image`, `compose-config`, `compose-up`, `caddy-logs`, `media`).
- AC9, jade-xu0: `ci-workflow` passes and `pnpm ci:local` exits 0 with its timings recorded. The first run on the host, branch protection and the upload proof are **blocked** by Q1.
- AC10, jade-lhq: `a11y`, `layout` and `no-offorigin` pass on Chromium and WebKit.
- AC11, jade-4zw: section 14's checks. **Blocked** by jade-0za and Q1.

Scope and process, checked when the last workable bead lands:

- AC12: `grep -rniE "create table" migrations/*.sql` finds nothing; `grep -rnE "<(input|textarea|select|form)|contenteditable" src/routes` finds nothing; `grep -rnE "request\.(json|formData|text|arrayBuffer)\(" src` finds nothing; `content/` does not exist; the registry holds exactly `/`, `/healthz`, `/readyz`, `/dev/boom` and the three `/dev/shell/` pages.
- AC13: `git diff --stat <base>..HEAD -- docs/adr` lists exactly three paths: `0024-node-24-pinned.md` (new), `README.md` (one added row) and `0015-tooling.md` (one added line). `CLAUDE.md` is unchanged.
- AC14: every Phase 1 commit subject names its bead; no agent claimed or started jade-0za; jade-4zw was not started while blocked; no bead was closed against Q2's answer; no remote, registry or secret was created by an agent.

## 18. Open questions for Mike

- **Q1, remote and merge flow.** Where is the remote, and is it GitHub (assumption A6)? Which CI host? May the trunk be renamed from `master` to `main` now (`git branch -m master main`)? How are changes merged (a pull request per bead with required checks, or another flow), and who sets branch protection? Which image registry? Until answered, work stays on local bead branches and AC2 is blocked.
- **Q2, closing beads before CI exists (C8).** Option (a), recommended: beads stay open with local gate evidence and are closed when the first green CI run covers them and they are merged; the go-ahead names the order of section 16 so the next bead may be worked while its predecessor is open. Option (b): Mike records a Phase-1-only reading that lets beads close on local gates and a local merge, with the first CI run re-validating them. Option (c): no implementation until the remote exists. The plan chooses none of these.
- **Q3, the development machine.** May the implementing subagent install pnpm 12.21.0 for your user with pnpm's standalone installer (no sudo; it adds `PNPM_HOME` to `~/.bashrc`; system Node 20 is untouched)? And will you run once, after the scaffold's `pnpm install`, `pnpm exec playwright install --with-deps chromium webkit`, which uses sudo for WebKit's OS libraries? Without both, jade-h8i cannot meet its acceptance (RR12).
- **Q4, Phase 2 and staging (C13).** If jade-0za is still open when the workable Phase 1 beads are done, may Phase 2 planning and work start without staging? Phase 2's exit criterion "Core schema migrated on staging" would wait as well.
- **Q5, deploy access (C11).** To settle with jade-0za: how port 22 is limited to the deploy source when hosted runners have changing addresses.
- **Q6, `/media` in Phase 1 (C1).** Confirm that a closed `/media` until jade-u8z is the intended reading (RR1).

## Residual risks
- RR1: `/media/*` is closed (403) in Phase 1, so OB29's "static /media with Range support" is delivered as configuration that is tested for Range support only in a throwaway Caddy container and is not reachable in the running stack until jade-u8z adds the signed-URL check of ADR 0007; seeking on real devices is first proven in Phase 4.
- RR2: With no git remote and no CI host, the workflow of jade-xu0 has never run; OB10, OB11, OB12, OB36, OB46 and OB49 cannot be verified, the 10-minute budget rests on estimates and on local timings from a 32-CPU machine, and the first run on the real host may need fixes.
- RR3: jade-4zw and the staging exit criterion stay blocked by the human bead jade-0za, so ADR 0014's "Staging exists before feature work" is not met if Phase 2 starts first, and deploy problems would then surface later than the phase goal intends.
- RR4: The tool majors are newer than anything the planner could run (SvelteKit 3.2, Vite 8, pnpm 12, Vitest 5, ESLint 10, TypeScript 6, Caddy 2.11): the design was checked against registries and published documentation only and nothing was installed, so file names, option names or CLI flags may differ at implementation; the black-box checks hold regardless, but a difference that changes a mechanism has to come back to planloop.
- RR5: Request log lines are written for every request, including requests from kits with logging off; they carry no kit, class, session or step identifier, and this plan reads that as outside CLAUDE.md rule 2 on the strength of PRIVACY.md's server-logs row, a reading in the same family as the open threat-model item TM-5.
- RR6: Error messages are never written to the JSON logs (only the error's type, tag and stack frames), which protects rule 4 but makes failures on staging and production harder to diagnose.
- RR7: Two outputs fall outside the JSON log contract: adapter-node's start-up line, which is plain text and shows the server's own bind address, and requests for static assets, which the adapter serves before `handle` and which therefore get no log line and no request id.
- RR8: Compatibility of a migration with the previous app version cannot be proven in general; the destructive-statement guard and the old-app-on-new-schema job catch structural breaks, not semantic ones such as a column whose meaning changed or a backfill the old code misreads.
- RR9: In the Compose stacks the owner role `jade_owner` is the superuser of the official Postgres image, so migrations run with superuser rights; the app never holds those credentials, and a managed database (ARCHITECTURE.md extension point E7) would need the role bootstrap revisited.
- RR10: OB30's "22 from deploy source only" cannot be met as written with hosted CI runners, whose addresses change; the deploy path (a self-hosted runner, the provider's firewall API, a VPN, or a pull-based deploy) has to be chosen with jade-0za, and until then jade-4zw's firewall rule is undefined.
- RR11: The image base is Alpine (musl) to stay well under 300 MB; a later native dependency without musl builds, for example an argon2 binding in Phase 3, would force a move to a Debian slim base and a new size check.
- RR12: Phase 1 changes Mike's machine (a user-level pnpm install that edits `~/.bashrc`, and OS libraries for WebKit installed with sudo); without them jade-h8i cannot meet OB1, and a Windows-side pnpm shim on the WSL `PATH` can shadow the right pnpm when `PATH` is not set explicitly.

## Change log
- Revision 1: first draft; no findings to answer.

## Artifact inventory
- section: ## 0. Summary
- section: ## 1. Facts this plan rests on
- section: ### 1.1 Repository and machine (read-only checks, 2026-11-14 and 2026-11-15)
- section: ### 1.2 Tool versions (public registries and release schedule, 2026-11-14)
- section: ### 1.3 Evidence behind two choices
- section: ## 2. Obligations
- section: ## 3. Contradictions and their resolution
- section: ## 4. Cross-cutting decisions
- section: ## 5. Invariants
- section: ## 6. Toolchain: Node 24 and pnpm
- section: ### 6.1 How the tools are obtained
- section: ### 6.2 How they are pinned
- section: ### 6.3 Recording the Node 24 choice (ADR 0024)
- section: ## 7. jade-h8i: scaffold
- section: ## 8. jade-8v4: typed config and secrets
- section: ## 9. jade-urd: database, migrations, test harness
- section: ## 10. jade-alt: health endpoints, logs, request ids
- section: ## 11. jade-80h: image and production Compose stack
- section: ## 12. jade-xu0: CI pipeline
- section: ### 12.1 What is built
- section: ### 12.2 Time budget
- section: ### 12.3 The remote-less state
- section: ## 13. jade-lhq: layout, tokens, accessibility baseline
- section: ## 14. jade-4zw: staging (specified, not started)
- section: ## 15. Later-phase consumers
- section: ## 16. Order of work, gates and stop points
- section: ## 17. Acceptance
- section: ## 18. Open questions for Mike
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
- id: INV1
- id: INV2
- id: INV3
- id: INV4
- id: INV5
- id: INV6
- id: INV7
- id: INV8
- id: INV9
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
