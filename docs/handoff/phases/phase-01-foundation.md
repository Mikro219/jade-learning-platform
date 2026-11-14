# Phase 1: Foundation and walking skeleton

**Goal.** A deployable empty app: repo, CI, database, container image, and a live staging URL. Everything after this ships to staging on every merge, so deploy problems surface in week one instead of the week before the pilot.

## Exit criteria

- [ ] `pnpm dev`, `pnpm test`, `pnpm e2e` work from a clean clone
- [ ] CI is green and required on main
- [ ] Staging URL serves /healthz over HTTPS from a Canadian region

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p1-scaffold` | P0 | task | Scaffold SvelteKit app with TypeScript strict, lint, unit and e2e test runners | `p0-adr` | foundation |
| `p1-config` | P0 | task | Typed environment config and secrets handling | `p1-scaffold` | foundation, security |
| `p1-db` | P0 | task | PostgreSQL via Docker Compose, Drizzle, migration tooling, test database harness | `p1-scaffold` | foundation, db |
| `p1-observability` | P1 | task | Health endpoints, structured logs without IPs, request IDs | `p1-config` | foundation, privacy |
| `p1-ui-shell` | P1 | task | Base layout, design tokens, kid-friendly accessibility baseline | `p1-scaffold` | foundation, ui |
| `p1-ci` | P0 | task | CI pipeline: lint, typecheck, unit, integration, e2e, image build | `p1-db` | foundation, ci |
| `p1-docker` | P0 | task | Production Dockerfile and compose.prod.yml (app, postgres, caddy) | `p1-db`, `p1-observability` | foundation, infra |
| `p1-staging` | P0 | task | Provision staging VM and deploy from CI on every merge to main | `p1-docker`, `p1-ci`, `p0-host` | infra, deploy |

### `p1-scaffold` Scaffold SvelteKit app with TypeScript strict, lint, unit and e2e test runners

SvelteKit with adapter-node, TypeScript strict, pnpm, ESLint + Prettier, Vitest, Playwright. Use the current Node LTS and pin it in .nvmrc and the Dockerfile. Folder layout per ARCHITECTURE.md section 4 (src/lib/server/{auth,codes,content,events,analytics}, src/routes/{(student),(adult),(staff),api}).

Acceptance:

- `pnpm lint`, `pnpm check`, `pnpm test`, `pnpm e2e` all pass on an empty app
- Module boundaries exist as folders with an index.ts each
- README has setup steps that work from a clean clone

### `p1-config` Typed environment config and secrets handling

Single config module that parses process.env with zod at boot and fails fast. .env.example documents every variable. Secrets (CODE_PEPPER, SESSION_SECRET, DATABASE_URL) never have defaults outside test.

Acceptance:

- App refuses to start with a clear message when a required variable is missing
- .env.example is complete; .env is gitignored
- No secret has a production default

### `p1-db` PostgreSQL via Docker Compose, Drizzle, migration tooling, test database harness

compose.dev.yml with Postgres 16. Drizzle ORM with SQL migrations checked in. Test harness that gives each test file an isolated schema or transaction rollback so tests run in parallel.

Acceptance:

- `pnpm db:migrate` and `pnpm db:reset` work
- A sample migration and a sample integration test pass in CI
- Migrations are forward-only and run automatically on deploy

### `p1-observability` Health endpoints, structured logs without IPs, request IDs

/healthz (process up) and /readyz (DB reachable, migrations current). JSON logs with request id, route, status, duration. Never log IP addresses, cookies, kit codes, join codes or request bodies.

Acceptance:

- /readyz fails when the DB is down
- A test asserts log lines contain no IP, cookie or code values
- Error responses carry the request id

### `p1-ui-shell` Base layout, design tokens, kid-friendly accessibility baseline

Shared layout and CSS tokens. Body text at least 18px on student pages, tap targets at least 48px, WCAG AA contrast, system font stack (no third-party font requests), reduced-motion respected. Three route groups with distinct shells: student, adult, staff.

Acceptance:

- No network request leaves the app origin on any page (Playwright asserts this)
- Student shell passes an automated axe check
- Layout holds at 360px wide and at 1366x768 (Chromebook)

### `p1-ci` CI pipeline: lint, typecheck, unit, integration, e2e, image build

GitHub Actions workflow on pull request and main. Postgres service container for integration tests. Playwright with Chromium and WebKit (iPad Safari stand-in). Cache pnpm. Fail on lint warnings.

Acceptance:

- Workflow runs in under 10 minutes
- Main branch is protected and requires the workflow
- Playwright report is uploaded on failure

### `p1-docker` Production Dockerfile and compose.prod.yml (app, postgres, caddy)

Multi-stage Dockerfile, non-root user, healthcheck. compose.prod.yml with app, postgres (named volume), and Caddy as the only public service (automatic TLS, compression, static /media with Range support, access log disabled or IP-stripped). App and DB are not exposed on the host.

Acceptance:

- `docker compose -f compose.prod.yml up` serves the app locally over Caddy
- Image runs as non-root and is under 300 MB
- Only ports 80 and 443 are published

### `p1-staging` Provision staging VM and deploy from CI on every merge to main

Staging VM in the chosen Canadian region. Firewall (22 from deploy source only, 80, 443), non-root deploy user, Docker. CI job: build image, push to registry, SSH deploy, run migrations, health-check gate. Staging shows a visible STAGING banner and uses its own secrets.

Acceptance:

- Merge to main results in a new version live on staging without manual steps
- A failed health check leaves the previous version running
- Staging URL recorded in README
