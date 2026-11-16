# JADE learning platform

The web platform that hosts the learning modules for JADE STEM kits. A kit code unlocks a kit's
content, and kit-level usage data is collected, with consent, to redesign the modules. It is a
SvelteKit app (adapter-node, TypeScript) backed by PostgreSQL.

## Prerequisites

- **pnpm 12** (12.21.0), installed with pnpm's standalone installer, which needs no Node:
  `curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION=12.21.0 sh -`.
  Make sure `pnpm --version` prints `12.21.0`; on WSL, a Windows-side `pnpm` must not come first
  on `PATH`.
- **Node 24** is not a prerequisite: `pnpm install` downloads the Node release pinned in
  `package.json` (`devEngines.runtime`, the same release as `.nvmrc`) and runs every script with
  it. With nvm or fnm, `nvm use` selects the same release.
- **Docker** with Compose v2, for the development database (PostgreSQL 16).
- **Browser system libraries**, once per machine, with sudo, for Playwright's WebKit and Chromium:
  `pnpm exec playwright install --with-deps chromium webkit`.

## Setup

From a fresh clone:

<!-- setup:begin -->

```sh
pnpm install --frozen-lockfile
pnpm exec playwright install chromium webkit
pnpm env:init
pnpm db:up
pnpm db:migrate
```

<!-- setup:end -->

Then `pnpm dev` serves the app on <http://localhost:5173>.

`pnpm env:init` writes `.env` (mode 600, ignored by git) with freshly generated secrets and prints
the variable names only. It never overwrites an existing `.env`. Every variable is documented in
`.env.example`; nothing in the repository holds a secret value. The app refuses to start, naming
the missing or invalid variables, when its configuration is incomplete. `.env` is read only
outside production; the built server (`node build`) reads its settings from the environment.

### The development database

`pnpm db:up` starts PostgreSQL 16 from `compose.dev.yml` (service `devdb`) on `127.0.0.1` at the
port `pnpm env:init` chose (`JADE_DEV_DB_PORT`: 5432 when free, else another, so a second checkout
gets its own), and waits until it is healthy. Its Compose project is the exported
`COMPOSE_PROJECT_NAME` when there is one, else `jade-dev-<hash of this checkout's path>`.

- `pnpm db:migrate`: applies pending migrations as the owner role (`jade_owner`,
  `MIGRATION_DATABASE_URL`), after creating the app role (`jade_app`, `DATABASE_URL`) or setting
  its password. A second run applies nothing.
- `pnpm db:reset`: drops, recreates and migrates the database; only for `APP_ENV` development or
  test on a loopback host.
- `pnpm db:down`: stops the database and keeps its data; `docker compose -p <project> down -v`
  removes the data too.
- `pnpm db:generate`, `pnpm db:check`: write and check migrations; see `migrations/README.md`.

`pnpm test` and `pnpm e2e` need the database up: each test file gets a database of its own on it,
cloned from a template the run migrates once, and every database a run creates is dropped when
it ends.

## The gate

Every change passes:

```sh
pnpm lint && pnpm check && pnpm test && pnpm e2e
```

- `pnpm lint`: Prettier and ESLint, warnings as failures.
- `pnpm check`: svelte-check (TypeScript strict), warnings as failures.
- `pnpm test`: Vitest, every project but `infra` (unit, integration, black-box).
- `pnpm e2e`: Playwright on Chromium (desktop) and WebKit (iPad).
- `pnpm ci:clean-clone`: clones the committed `HEAD` into a temporary directory, runs the setup
  block above, `pnpm test`, `pnpm e2e` and a `pnpm dev` smoke check. It refuses to run while the
  working tree has uncommitted changes.

## Documentation

- `CLAUDE.md`: the rules every change keeps.
- `docs/handoff/ARCHITECTURE.md`: the architecture; `docs/adr/`: the accepted decisions.
- `docs/handoff/DATA-MODEL.md`, `docs/handoff/EVENTS.md`, `docs/handoff/PRIVACY.md`: data shapes
  and privacy promises.
- `docs/threat-model.md`: the threat model.
- Work is tracked with beads (`bd ready`, `bd show <id>`).
