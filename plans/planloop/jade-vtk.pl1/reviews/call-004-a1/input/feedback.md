PLANLOOP-BUNDLE run=jade-vtk.pl1 revision=3 call=4 attempt=1 sha256=fa000c2550afb5e518041b1693add57a4b44823a0869859e85079b2e81e4459e
Policy planloop/3 (quartz-rs-lur, 2026-10-22).

/home/mikep/.local/state/planloop-isolated/r-f8a4c30c3e964f6b/repo is a frozen, read-only snapshot of the repository for this revision. Read only files
under it; a relative path below is relative to it. Never read the original checkout or any other path
outside it: such reads are detected in your transcript and void the review.
/home/mikep/.local/state/planloop-isolated/r-f8a4c30c3e964f6b/repo/.planloop-bundle/ holds the frozen plan, brief, obligations, binding bead text, evidence and
the discovery record; bead text cannot be fetched any other way (never run bd).

Coverage must contain, for every finding listed below in state fix_proposed, exactly one entry
`finding R<k>: resolved` or `finding R<k>: unresolved`. To withdraw an open finding you judge invalid,
write `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, at least 40 chars>`.
When re-raising a known finding, use its R id as your finding id.
Check every REMOVED and SHRINK disposition below: each must say what was removed, why, and which
obligations or capabilities it affects; an unexplained removal is a finding.

This is the final gate: an independent, full-rubric review of the whole plan. Earlier rounds
are not evidence that anything is correct; check interactions between revised and unchanged
sections.

--- REVIEW BRIEF (host) ---
# Review brief: jade-vtk.pl1 (Phase 1: Foundation and walking skeleton), revision 2

## Scope
Code and infrastructure. The plan covers the eight agent beads of Phase 1 (epic jade-vtk) against their acceptance criteria and the phase exit criteria:
- jade-h8i (p1-scaffold): SvelteKit scaffold, TS strict, pnpm, ESLint + Prettier, Vitest, Playwright, module folders.
- jade-urd (p1-db): Postgres 16 via compose.dev.yml, Drizzle, forward-only SQL migrations, parallel-safe test DB harness.
- jade-8v4 (p1-config): zod-parsed typed config, fail-fast, .env.example, no production secret defaults.
- jade-alt (p1-observability): /healthz, /readyz, JSON logs without IPs/cookies/codes/bodies, request ids.
- jade-lhq (p1-ui-shell): three shells, tokens, accessibility baseline, no off-origin requests.
- jade-xu0 (p1-ci): CI workflow (lint, typecheck, unit, integration, e2e on Chromium + WebKit, image build).
- jade-80h (p1-docker): multi-stage non-root image, compose.prod.yml with Caddy as the only public service.
- jade-4zw (p1-staging): staging VM and deploy from CI. Blocked by the human bead jade-0za (host, region, domain); the plan specifies the work and states exactly what jade-0za must supply, it does not choose a host.

Track: escalated (risk domains secrets, privacy, schema-migration). Human beads are out of scope (CLAUDE.md: never start a bead labelled `human`).

## Facts and decisions the plan must take as given
- Mike, 2026-11-14: pin **Node 24** in `.nvmrc` and the Dockerfile (recorded in jade-h8i notes, OB33). ADR 0015 says "current Node LTS (pinned)" (OB60); Node 24 is a supported LTS line. Mike chose 24 over 26 when both were offered. The plan records this choice durably (for example a dated note or ADR consequence line, through the normal ADR conventions in docs/adr/README.md) rather than reargue it.
- The dev machine has Node v20.20.1; pnpm, gh and psql are not installed; Docker 29.7 is. The plan must say how Node 24 and pnpm are obtained (for example corepack is not bundled with Node 25+, so state the mechanism for 24) without assuming tools that are absent.
- The repository has no git remote (`git remote -v` is empty); GitHub hosting is assumption A6 (OB61, OB80), unconfirmed. OB11, OB36, OB46 and OB49 (protected main, CI required, merge once CI is green) cannot be met until a remote exists. The plan must say precisely which steps are possible now, which wait on Mike naming the remote/CI host, and what "done" means for jade-xu0 meanwhile. It must not invent a remote.
- No secret, payment, DNS change or production deploy is performed by an agent (OB50). Staging secrets and the VM come through jade-0za.

## Contradictions found in discovery (the plan must resolve each explicitly, or raise it as an open question / residual risk; never silently)
1. Caddy "static /media with Range support" (jade-80h, OB29) vs ADR 0007 short-lived signed URLs (OB55): Phase 1 Caddy config must not expose /media publicly in a way Phase 4's entitlement check would have to undo.
2. jade-alt logs "route" (OB31) vs rule 2 (OB39), ADR 0009 (OB56) and AB16 (OB79, `/redeem?code=`): log the route pattern, never the raw path or query string.
3. The never-log lists differ: jade-alt (IP, cookie, kit code, join code, body), PRIVACY server-logs row (OB71: IP, email, code, token, body), rule 4 (OB41). The union applies; say which the Phase 1 test (OB20) asserts and what is deferred to p9-logs (jade-ada).
4. One DATABASE_URL (jade-8v4) vs the app role's restricted grants on `events` (OB70): say whether migrations run under a separate role/URL and how config expresses it, without building Phase 2/6 schema.
5. CLAUDE.md "Every new route goes into the authorization matrix test" (OB47) while that test is built in Phase 3: say how /healthz and /readyz are recorded so the Phase 3 matrix picks them up.
6. "Migrations ... run automatically on deploy" (OB6) with no deploy target until jade-4zw: define the mechanism now (entrypoint or release step) and how it is exercised before staging exists.
7. CI under 10 minutes (OB10) with two browsers plus an image build: give the budget.

## Rubric (every round)
Contradictions; missing requirements (every obligation row OB1 to OB80 is answered, each by a concrete step and an acceptance check); incorrect assumptions (tool availability, versions, what exists in the repo today); affected consumers (Phase 2 schema and codes on jade-urd and jade-8v4, Phase 3 authorization matrix, Phase 4 media signing, Phase 6 no-log invariant, Phase 9 log audit jade-ada, Phase 10 production deploy jade-kn0); test coverage (each acceptance criterion has an automated check where one is possible, with the command that runs it); verifiable acceptance criteria; bead order and dependencies match the phase file (h8i first; 8v4, urd, lhq after it; alt after 8v4; xu0 after urd; 80h after urd and alt; 4zw last and blocked); unnecessary scope expansion (no Phase 2+ schema, routes or features; no teaching content, rule 7: use the `demo` kit only if content is needed at all).

JADE invariants: the plan must not change or relax CLAUDE.md rules 1 to 6 or any decision in docs/adr/ (rule 8); a contradiction between sources is raised, not resolved by choosing one silently; no third-party request from the browser in any page or in the scaffold's defaults (rule 5, ADR 0013: no Google Fonts, CDNs, telemetry in tooling templates); no IP, cookie, code, token or body in any log line (rule 4); secrets never have production defaults and are never committed (.env gitignored); every migration forward-only and compatible with the previous app version (ADR 0003). Implementation waits for Mike's go-ahead after approval; the plan says so and contains no authorization to self-start.

Findings need a severity (high/medium/low) and concrete evidence (file and line, or bead and field, or OB id).

## Change map (navigation only)
New: package.json, pnpm-lock.yaml, .nvmrc, svelte.config.js, vite.config.ts, tsconfig.json, eslint/prettier config, playwright.config.ts, src/lib/server/{auth,codes,content,events,analytics}/index.ts, src/lib/server/config, src/lib/server/log (or wherever the plan puts them), src/routes/{(student),(adult),(staff),api}/, src/routes/healthz, src/routes/readyz, compose.dev.yml, compose.prod.yml, Dockerfile, Caddyfile, drizzle config, migrations/, tests/, .env.example, .github/workflows/ (once a remote is named), README.md. Changed: .gitignore; docs/adr (Node 24 record).

## Checking the plan's obligations
OB1 to OB80 are frozen in the bundle (`obligations.json`) with their sources: bead fields (acceptance criteria, descriptions, jade-h8i notes) and exact lines of CLAUDE.md, the ADRs, ARCHITECTURE, DATA-MODEL, PRIVACY and the threat model. Check that the plan answers each with a step and a check, and that nothing it states contradicts one.

## Reviewing the snapshot
The snapshot is a `git archive` export with no `.git` directory, so git commands (log, branch, status) do not work in it and are not needed: the facts they would show (only branch `master`, empty `git remote -v`) are stated in this brief and in the plan's section 1.1.

## Host-verified issues from revision 1 (H1 to H8)

Two independent reviews of revision 1 (call 1 attempts 1 and 2) were voided on a tool-use technicality (a read-only `git branch -a` that planloop's write checker counts as a write), so their findings are not planloop finding ids. The orchestrator verified each against `rev-001/plan.md` and they are requirements of revision 2. Check that each is fixed; a fix that only renames the instance and leaves the class open is not a fix.

### H1 (medium) section 11 Checks, `tests/infra/compose-up.test.ts`; 9 U1; 16 step 3; 12.1 X1
Evidence: compose-up.test.ts asserts "ports 3000 and 5432 refuse connections from the host". U1 publishes the development database on `127.0.0.1:${JADE_DEV_DB_PORT:-5432}` and V5 picks 5432 when it is free; `pnpm test` needs that database, and the section 16 gate and `pnpm ci:local` run it before `pnpm test:infra`. So the dev Postgres answers on 5432 and the check fails though the stack's db publishes nothing; AC8 cannot pass locally and an implementer is pushed to weaken it.
Suggested fix: assert exposure from the stack itself (`docker compose -p <project> ps --format json` / `docker inspect`: app and db have no Publishers or PortBindings); any connection probe targets the stack containers or a port the test has just shown is free.

### H2 (medium) section 9 U2 `ensureAppRole`, U3 steps 1-2, U7; `migrate.test.ts`, `db-scripts.test.ts`
Evidence: U3's session advisory lock is keyed per database (the lock tag includes the database OID), but `ensureAppRole()` rewrites the cluster-wide `jade_app` row in `pg_authid` on every run (a fresh-salt SCRAM verifier). U7 runs Vitest files in parallel and migrate.test.ts and db-scripts.test.ts each run `migrate()` on different databases of one cluster, so two `ALTER ROLE jade_app ... PASSWORD` can run at once and fail with `tuple concurrently updated` (XX000), and two `CREATE ROLE` on a fresh cluster can hit a duplicate (23505). Intermittent failures in the required check job, which the three-strikes stop then treats as real. "Two runners at once apply each file once" covers only the same-database case.
Suggested fix: serialize role bootstrap across the cluster (advisory lock in the `postgres` maintenance database around it, or alter only when the role is missing or a login with DATABASE_URL fails; role bootstrap once in the integration global setup), and add a test that starts `migrate()` on two different databases of one cluster at the same time and requires both to succeed.

### H3 (medium) section 10 A1 ("In `APP_ENV=development` only, the raw error is also printed to the terminal"); A5 `/dev/boom`; 5 INV1; 11 D3
Evidence: INV1 and CLAUDE.md rule 4 (OB41) have no environment exception; A1 adds one. `/dev/boom` deliberately puts the query string in the error message, and later routes see the same path (a code in `/redeem?code=`, a route parameter). D3 runs the local `compose.prod.yml` stack with the `.env` from `pnpm env:init`, which is the development `.env` (`APP_ENV=development`), so raw error text lands in Docker's on-disk json-file logs. `log-privacy.test.ts` runs only under `APP_ENV=test`, so nothing catches it. Section 16 sends any change to the logger's contract to Mike.
Suggested fix: remove the raw-error print (or limit it to the JSON error line's fields). If a fuller development view is wanted, raise it to Mike as a rule-4 question instead of planning it. Run log-privacy.test.ts under `APP_ENV=development` as well as `test`. The local production stack never runs with `APP_ENV=development` (see H4).

### H4 (medium) section 11 D2, D3; 8 V5; OB13; Z2
Evidence: D3 runs `docker compose -f compose.prod.yml up` "with the .env from pnpm env:init"; V5 points that file's URLs at `127.0.0.1:<dev port>` and PD2/V2 give it `APP_ENV=development`. D2 says only that app "receives APP_ENV, DATABASE_URL (app role)" and migrate "receives both URLs"; nowhere does the plan say compose.prod.yml builds the URLs with host `db` from password variables, and no app-role password variable exists (only `JADE_OWNER_DB_PASSWORD`). Passed through, the URLs make migrate connect to 127.0.0.1 inside its own container; the app never starts and OB13 fails. compose-up.test.ts uses "a temporary env file", so it passes while the README path is broken. Z2's env:init on the VM has the same unstated contract.
Suggested fix: specify compose.prod.yml's env contract: `DATABASE_URL` built as `postgres://jade_app:${JADE_APP_DB_PASSWORD:?}@db:5432/jade`, `MIGRATION_DATABASE_URL` from `${JADE_OWNER_DB_PASSWORD:?}`; the stack's `APP_ENV` from a stack-specific required variable or fixed (production locally; staging set by env:init on the VM), never the development value. env:init and `.env.example` carry `JADE_APP_DB_PASSWORD`, and the development `DATABASE_URL` agrees with it. compose-up.test.ts generates its env file with `pnpm env:init` (temporary directory, port overrides) so OB13 is proven on the README path; compose-config.test.ts asserts the URL host is `db` and that the app is not `APP_ENV=development`.

### H5 (low) section 11 D1 against 8 V6
Evidence: V6 says the tools call `tools/load-env.ts`; D1's runtime copy lists `migrations/`, `tools/db/` and the `config`, `db`, `log` folders only. If `tools/db/migrate.ts` imports `../load-env.ts`, the migrate service fails with ERR_MODULE_NOT_FOUND in the image.
Suggested fix: add `tools/load-env.ts` (or everything the migration entry point imports) to D1, or state that the entry point does not import it in the image; have image.test.ts run the migration entry point inside the image.

### H6 (low) section 11 D2 ("`name: jade-stack` ... never touches the development `db` service"); `.claude/skills/bugfix/SKILL.md` "The gates" (COMPOSE_PROJECT_NAME); U8
Evidence: `COMPOSE_PROJECT_NAME` and `-p` take precedence over a top-level `name:`. The bugfix skill exports `COMPOSE_PROJECT_NAME=bugfix-<bead>-<purpose>` for every gate, so in that shell compose.dev.yml and compose.prod.yml share one project, each with a service `db`, and a manual compose.prod.yml up recreates the dev db container with the production configuration. Two checkouts also share `jade-stack`. The "never touches" claim is false.
Suggested fix: qualify the claim; give the production stack distinct service and volume names or always use an explicit `-p`; cover the interaction in the U8 edit to the bugfix skill.

### H7 (low) section 12.2, `image` row ("setup 0:30")
Evidence: the image job runs `pnpm ci:image` and `pnpm test:infra` (Vitest), so it needs `pnpm install`; the other jobs budget 1:15 cold for setup and install. With the same allowance the image job is about 6:00 cold, not 5:15.
Suggested fix: budget its setup and install like the other jobs and restate the whole-run estimate.

### H8 (low) section 12.1 X4; INV5
Evidence: X4 applies the head's migrations to a fresh database and then runs "the base's integration tests against that database". The base's integration project includes migrate.test.ts ("a fresh database ends with the ledger equal to the manifest") and its global setup migrates its own template; the plan does not say whose template the base tests clone or which base tests are in scope. Under the obvious reading the first Phase 2 pull request that adds a migration turns migration-compat red for a reason unrelated to compatibility.
Suggested fix: state that compat migrates the template with the head's runner (the base runner then sees a database ahead and exits 0), and either exclude the runner's own tests (migrate.test.ts, migrations-static) from the compat run or require that they use empty databases they create themselves rather than template clones.

Orchestrator check: H1 rev-001 lines 297 (U1) and 368 (compose-up checks); H2 lines 298 (U2) and 300-301 (U3 steps 1-2); H3 line 331 (A1) and 335 (A5), 360 (D3); H4 lines 280 (V5), 359-360 (D2, D3), grep finds no `JADE_APP_DB_PASSWORD`; H5 lines 281 (V6) and 351 (D1); H6 line 359; H7 line 399; H8 line 386 (X4) and 315 (migrate.test.ts).

## Host-verified issues found after revision 1 was reviewed (H9 to H16)

These came from benchmark reviews (outside planloop) and from a review of revision 1 that planloop voided because a bundled input changed during it, so they are not planloop finding ids either. The orchestrator verified each against `rev-001/plan.md`; they are requirements of revision 2. A fix must close the class, not only the instance.

- H9 medium (section 12.1 X1-X2): CI jobs supply no APP_ENV, DATABASE_URL, MIGRATION_DATABASE_URL, CODE_PEPPER or SESSION_SECRET; say how each job gets test-only values (generated in the job, never from the secret store) and assert it in ci-workflow.test.ts.
- H10 low (section 9 U5): reword "remove or rename" so it plainly means schema objects, not migration files (two reviewers misread it as letting merged files be removed).
- H11 medium (section 10 A1): `stack_frames` = "frame lines only, without the first line of the stack". Node's err.stack embeds the whole message, so lines 2+ of a multi-line message (a value, URL or code) can pass as frames. Build frames from structured data or drop non-frame-shaped lines strictly and drop everything until the first real frame; add a multi-line canary case to log-privacy/log-schema tests.
- H12 low (section 14 Z4): after the candidate passes, the switch stops the old app; if the post-switch check through Caddy fails, the previous version is no longer running (OB17). Either keep the old container until the post-switch check passes, or state precisely why the candidate gate is the health check OB17 means and what the post-switch rollback guarantees.
- H13 medium (sections 5 INV5, 12.1 X1, X4): `pnpm db:check --base <ref>` and migration-compat never define the base ref per trigger (pull_request: the PR base SHA; push to main: the previous main SHA / event.before) nor fetch it (actions/checkout defaults to fetch-depth 1). Define both, handle a first push with no predecessor, and test both trigger cases in ci-workflow.test.ts.
- H14 medium (sections 8 V3, 10 A1/A4): the config fail-fast message (OB7, boot-failfast.test.ts prints the variable name) can be swallowed: A4's uncaughtException/unhandledRejection handlers write a closed error line (no message) and exit 1, and a ConfigError thrown in init during adapter-node's top-level await reaches them. Specify the config-failure path: catch ConfigError at init, write the value-free message (variable names only) to stderr or a fixed lifecycle line whose keys are validated against the config schema's key set, exit 1 before the generic handlers; keep boot-failfast in every gate from jade-alt on.
- H15 low (section 6.3 and AC13): ADR 0024's Consequences says "ADR 0015 is unchanged" while the plan appends a Consequences bullet to 0015. Reword (for example "ADR 0015's Decision is unchanged; one Consequences line points here").
- H16 low (sections 7 H8, 16 steps 3-4, AC1/AC4): `ci:clean-clone` clones HEAD, but the gate runs before the commit, so it tests the previous commit. State that it runs after the bead's commit and its result is recorded against that SHA (or clone the working tree).

--- OBLIGATIONS (exact source text) ---
OB1 [bead:jade-h8i acceptance_criteria]: `pnpm lint`, `pnpm check`, `pnpm test`, `pnpm e2e` all pass on an empty app
OB2 [bead:jade-h8i acceptance_criteria]: Module boundaries exist as folders with an index.ts each
OB3 [bead:jade-h8i acceptance_criteria]: README has setup steps that work from a clean clone
OB4 [bead:jade-urd acceptance_criteria]: `pnpm db:migrate` and `pnpm db:reset` work
OB5 [bead:jade-urd acceptance_criteria]: A sample migration and a sample integration test pass in CI
OB6 [bead:jade-urd acceptance_criteria]: Migrations are forward-only and run automatically on deploy
OB7 [bead:jade-8v4 acceptance_criteria]: App refuses to start with a clear message when a required variable is missing
OB8 [bead:jade-8v4 acceptance_criteria]: .env.example is complete; .env is gitignored
OB9 [bead:jade-8v4 acceptance_criteria]: No secret has a production default
OB10 [bead:jade-xu0 acceptance_criteria]: Workflow runs in under 10 minutes
OB11 [bead:jade-xu0 acceptance_criteria]: Main branch is protected and requires the workflow
OB12 [bead:jade-xu0 acceptance_criteria]: Playwright report is uploaded on failure
OB13 [bead:jade-80h acceptance_criteria]: `docker compose -f compose.prod.yml up` serves the app locally over Caddy
OB14 [bead:jade-80h acceptance_criteria]: Image runs as non-root and is under 300 MB
OB15 [bead:jade-80h acceptance_criteria]: Only ports 80 and 443 are published
OB16 [bead:jade-4zw acceptance_criteria]: Merge to main results in a new version live on staging without manual steps
OB17 [bead:jade-4zw acceptance_criteria]: A failed health check leaves the previous version running
OB18 [bead:jade-4zw acceptance_criteria]: Staging URL recorded in README
OB19 [bead:jade-alt acceptance_criteria]: /readyz fails when the DB is down
OB20 [bead:jade-alt acceptance_criteria]: A test asserts log lines contain no IP, cookie or code values
OB21 [bead:jade-alt acceptance_criteria]: Error responses carry the request id
OB22 [bead:jade-lhq acceptance_criteria]: No network request leaves the app origin on any page (Playwright asserts this)
OB23 [bead:jade-lhq acceptance_criteria]: Student shell passes an automated axe check
OB24 [bead:jade-lhq acceptance_criteria]: Layout holds at 360px wide and at 1366x768 (Chromebook)
OB25 [bead:jade-h8i description]: SvelteKit with adapter-node, TypeScript strict, pnpm, ESLint + Prettier, Vitest, Playwright. Use the current Node LTS and pin it in .nvmrc and the Dockerfile. Folder layout per ARCHITECTURE.md section 4 (src/lib/server/{auth,codes,content,events,analytics}, src/routes/{(student),(adult),(staff),api}).
OB26 [bead:jade-urd description]: compose.dev.yml with Postgres 16. Drizzle ORM with SQL migrations checked in. Test harness that gives each test file an isolated schema or transaction rollback so tests run in parallel.
OB27 [bead:jade-8v4 description]: Single config module that parses process.env with zod at boot and fails fast. .env.example documents every variable. Secrets (CODE_PEPPER, SESSION_SECRET, DATABASE_URL) never have defaults outside test.
OB28 [bead:jade-xu0 description]: GitHub Actions workflow on pull request and main. Postgres service container for integration tests. Playwright with Chromium and WebKit (iPad Safari stand-in). Cache pnpm. Fail on lint warnings.
OB29 [bead:jade-80h description]: Multi-stage Dockerfile, non-root user, healthcheck. compose.prod.yml with app, postgres (named volume), and Caddy as the only public service (automatic TLS, compression, static /media with Range support, access log disabled or IP-stripped). App and DB are not exposed on the host.
OB30 [bead:jade-4zw description]: Staging VM in the chosen Canadian region. Firewall (22 from deploy source only, 80, 443), non-root deploy user, Docker. CI job: build image, push to registry, SSH deploy, run migrations, health-check gate. Staging shows a visible STAGING banner and uses its own secrets.
OB31 [bead:jade-alt description]: /healthz (process up) and /readyz (DB reachable, migrations current). JSON logs with request id, route, status, duration. Never log IP addresses, cookies, kit codes, join codes or request bodies.
OB32 [bead:jade-lhq description]: Shared layout and CSS tokens. Body text at least 18px on student pages, tap targets at least 48px, WCAG AA contrast, system font stack (no third-party font requests), reduced-motion respected. Three route groups with distinct shells: student, adult, staff.
OB33 [bead:jade-h8i notes]: 2026-11-14 Mike: pin Node 24 (.nvmrc and Dockerfile).
OB34 [bead:jade-vtk description]: A deployable empty app: repo, CI, database, container image, and a live staging URL. Everything after this ships to staging on every merge, so deploy problems surface in week one instead of the week before the pilot.
OB35 [docs/handoff/phases/phase-01-foundation.md Exit criteria]: - [ ] `pnpm dev`, `pnpm test`, `pnpm e2e` work from a clean clone
OB36 [docs/handoff/phases/phase-01-foundation.md Exit criteria]: - [ ] CI is green and required on main
OB37 [docs/handoff/phases/phase-01-foundation.md Exit criteria]: - [ ] Staging URL serves /healthz over HTTPS from a Canadian region
OB38 [CLAUDE.md Rules that are not up for negotiation]: 1. No accounts, names or free-text input for children. Ever.
OB39 [CLAUDE.md Rules that are not up for negotiation]: 2. When a kit's `logging_enabled` is false, the server stores nothing about that kit's activity. The `p6-nolog-invariant` test must never be skipped, weakened or deleted.
OB40 [CLAUDE.md Rules that are not up for negotiation]: 3. Class and kit identity come from the session, never from a request body.
OB41 [CLAUDE.md Rules that are not up for negotiation]: 4. Plain kit codes, join codes and tokens are never stored or logged. IP addresses are never stored or logged.
OB42 [CLAUDE.md Rules that are not up for negotiation]: 5. No request from the browser to any origin but our own. No third-party scripts, fonts, analytics or embeds.
OB43 [CLAUDE.md Rules that are not up for negotiation]: 6. Step IDs are permanent. A changed step gets a version bump; CI enforces it.
OB44 [CLAUDE.md Rules that are not up for negotiation]: 8. The decisions in `docs/adr/` stand. If one looks wrong, file a `decision` bead and stop.
OB45 [CLAUDE.md Work tracking: beads]: - **Never start a bead labelled `human`.** If one blocks you, say so and stop, or pick other ready work.
OB46 [CLAUDE.md Work tracking: beads]: - A bead is done when every acceptance criterion is met, tests pass locally and in CI, and the change is merged. Not before.
OB47 [CLAUDE.md How each bead is worked]: 3. Implement with tests. Every new route goes into the authorization matrix test.
OB48 [CLAUDE.md How each bead is worked]: 4. Run `pnpm lint && pnpm check && pnpm test && pnpm e2e`.
OB49 [CLAUDE.md How each bead is worked]: 5. Commit with the bead ID in the message. Merge once CI is green; staging deploys itself.
OB50 [CLAUDE.md Stop and ask the human when]: - A secret, payment, DNS change or production deploy is needed.
OB51 [docs/adr/0002-modular-monolith-in-sveltekit.md Decision]: One SvelteKit app (adapter-node, TypeScript strict) serves pages and API routes. Server code is split into `auth`, `codes`, `content`, `events`, `analytics` modules that talk through their `index.ts`.
OB52 [docs/adr/0003-postgresql-with-drizzle-and-sql-migrations.md Decision]: PostgreSQL 16. Drizzle for typed queries. Migrations are SQL files, forward-only, run on deploy. Analytics is SQL views in the same database.
OB53 [docs/adr/0003-postgresql-with-drizzle-and-sql-migrations.md Consequences]: - Migrations stay compatible with the previous app version, so rollback to the previous image works
OB54 [docs/adr/0004-one-canadian-vm-docker-compose.md Decision]: Production is a single Linux VM in a Canadian region running Compose: Caddy, app, Postgres. Staging is a second, smaller VM. Provider is a human decision (`p0-host`).
OB55 [docs/adr/0007-self-hosted-same-origin-video.md Decision]: H.264/AAC MP4 at 720p with faststart, on a volume served by Caddy with Range support, behind short-lived signed URLs. No third-party video host.
OB56 [docs/adr/0009-consent-gated-logging.md Decision]: Off means zero activity stored server-side.
OB57 [docs/adr/0011-kit-code-format-and-storage.md Consequences]: - Pepper handling: p1-config (jade-8v4) reads `CODE_PEPPER` from config with no production default (jade-8v4 description)
OB58 [docs/adr/0013-no-third-party-requests-from-the-browser.md Decision]: No analytics, fonts, CDNs, embeds or error trackers that load in the user's browser. CSP enforces it and an e2e test asserts it.
OB59 [docs/adr/0014-staging-from-phase-1.md Decision]: Staging exists before feature work and is deployed on every merge to main. Production receives the image that passed staging.
OB60 [docs/adr/0015-tooling.md Decision]: pnpm, current Node LTS (pinned), ESLint + Prettier, Vitest, Playwright (Chromium and WebKit), GitHub Actions, zod, k6 for load.
OB61 [docs/adr/README.md Assumptions (unconfirmed)]: A6: the repository has no git remote configured today (`git remote -v` is empty), so A6 is unconfirmed.
OB62 [docs/handoff/ARCHITECTURE.md 4. Components]: | Caddy | TLS, HTTP/2, compression, serves `/media` with Range requests | Only public service. Access log off or IP-stripped |
OB63 [docs/handoff/ARCHITECTURE.md 4. Components]: src/lib/server/{auth,codes,content,events,analytics}/   one folder per module, index.ts is its public API
OB64 [docs/handoff/ARCHITECTURE.md 4. Components]: src/routes/(student)/  (adult)/  (staff)/  api/
OB65 [docs/handoff/ARCHITECTURE.md 4. Components]: Modules call each other only through their `index.ts`. That is the whole "architecture enforcement" for a monolith this size.
OB66 [docs/handoff/ARCHITECTURE.md 9. Security and privacy]: | IP addresses as hidden identifiers | Not logged by Caddy or the app; used in memory for rate limiting only |
OB67 [docs/handoff/ARCHITECTURE.md 10. Deployment]: - **Environments:** local (Compose), staging (live from Phase 1, deployed on every merge to main), production (promoted by tag; same image that passed staging).
OB68 [docs/handoff/ARCHITECTURE.md 10. Deployment]: - **Releases:** build image, run forward-only migrations, start, health-check, switch. Rollback is the previous image. Migrations stay compatible with the previous app version.
OB69 [docs/handoff/DATA-MODEL.md Data model]: Phase 2 and Phase 6 implement it as Drizzle schema plus SQL migrations.
OB70 [docs/handoff/DATA-MODEL.md 4. Content registry, events, progress]: The application's database role has `insert` and `select` on `events`, no `update`, and `delete` only through the `delete_kit_data(kit_id)` function added in Phase 9.
OB71 [docs/handoff/PRIVACY.md Data inventory]: | Server logs | VM disk, 14 days | Every request | Staff with server access. No IPs, emails, codes, tokens or bodies |
OB72 [docs/handoff/PRIVACY.md Data inventory]: Not collected at all: child names, photos, audio, free text from students, IP addresses, location, device identifiers, advertising identifiers, third-party cookies.
OB73 [docs/handoff/PRIVACY.md Where it runs]: One VM and one object-storage bucket, both in Canada. No student traffic goes to any other company: no analytics service, no video platform, no font or script CDN, no error tracker in the browser.
OB74 [docs/threat-model.md 3. Trust boundaries]: - **TB1 Browser to Caddy.** Over the internet or school Wi-Fi, with TLS; only 80 and 443 are published (ARCHITECTURE.md section 10; p1-docker jade-80h).
OB75 [docs/threat-model.md 3. Trust boundaries]: - **TB2 Caddy to app.** The internal Compose network (ARCHITECTURE.md section 10); the Caddy access log is off or IP-stripped (ARCHITECTURE.md section 4; jade-80h).
OB76 [docs/threat-model.md 3. Trust boundaries]: - **TB9 Object storage to the staging VM.** Staging "uses its own secrets" (p1-staging jade-4zw; ADR 0014)
OB77 [docs/threat-model.md 2. Assets]: read through typed config with no production default (p1-config jade-8v4). Never in the database (ARCHITECTURE.md section 6)
OB78 [docs/threat-model.md 5. Abuse cases]: | AB9 | IP addresses as hidden identifiers | Not logged by Caddy or the app (jade-80h, jade-alt, jade-ada); used in memory only, for rate limiting (jade-6cq; ADR 0020) |
OB79 [docs/threat-model.md 5. Abuse cases]: | AB16 | A plain kit code leaking from the QR redeem URL (`/redeem?code=...`) into server logs or a Referer header (beyond ARCHITECTURE.md section 9) | App log lines contain no code values (jade-alt);
OB80 [docs/threat-model.md 1. Actors]: - The repository and CI path: GitHub is assumed (assumption A6 of `docs/adr/README.md`); code and content arrive through it, and content changes go through the same CI (ARCHITECTURE.md section 4; ADR 0006; p1-ci jade-xu0).

--- DISPOSITIONS IN THIS REVISION ---
SHRINK ## 9. jade-urd: database, migrations, test harness: U6 and the db-scripts.test.ts check line edited in place (R10). U6 keeps its refusal rule (APP_ENV development or test and a loopback host) and adds that the guard runs before the config is loaded or any connection is made, writes DB_RESET_REFUSED with the failed half and refuses an unparsable URL. The db-scripts check keeps its success, removal and no-op assertions and replaces the bare non-zero-exit production case with two tagged cases whose inputs pass the config schema. No rule or check is weakened.
SHRINK ## 14. jade-4zw: staging (specified, not started): Z2 and Z3 edited in place. Z2 now runs env-init with --user of the deploy user, so the env file is owned by that user with mode 600 (R11); Z3 now names the pushed image as jade-app:ci, the image the infra tests checked and ran, never rebuilt (R9). The rest of both bullets is unchanged, and Z4b is a new line; what jade-0za and Q1 must supply is unchanged.
FIX R10
FIX R11
FIX R9

--- FINDINGS (Beads, at dispatch) ---
| ID | severity | state | raised in call | fixes proposed | resolution |
|---|---|---|---|---|---|
| R1 | medium | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R2 | medium | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R3 | medium | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R4 | medium | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R5 | low | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R6 | low | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R7 | low | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R8 | low | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R9 | low | fix_proposed | 3 | 1 | - |
| R10 | low | fix_proposed | 3 | 1 | - |
| R11 | low | fix_proposed | 3 | 1 | - |

