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
- **Docker** with Compose v2 and buildx, for the development database (PostgreSQL 16), the image
  and the production stack.
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

### The local production stack

`compose.prod.yml` is the stack staging and production run: `db` (PostgreSQL 16, volume
`db-data`), `migrate` (applies migrations as `jade_owner`, then exits), `app` (the image built
from `Dockerfile`, as `jade_app`, with `APP_ENV=production`) and `caddy`, the only service with
published ports. The app and the database sit on an internal network with no host port.

```sh
pnpm env:init   # once; also writes the stack's variables to .env
pnpm stack:up   # builds the image, migrates, serves https://localhost
pnpm stack:down # stops it and keeps its volumes (needs no valid .env)
```

`pnpm stack:up` builds the image as `jade-app:local-<hash of this checkout's path>` and runs the
stack as the Compose project `jade-stack-<same hash>`, ignoring an exported
`COMPOSE_PROJECT_NAME`. Caddy serves `https://localhost` (or `https://localhost:<JADE_HTTPS_PORT>`)
with its internal CA's certificate, which a browser does not trust until you trust that CA. Plain
HTTP on `JADE_HTTP_PORT` is redirected to `https://localhost/<same path>`, that is to port 443:
Caddy only knows its container port, so when `JADE_HTTPS_PORT` is not 443 the redirect points at
the wrong host port, and you open `https://localhost:<JADE_HTTPS_PORT>` directly. On a VM, where
the ports are 80 and 443, the redirect is right. The stack reads only its own variables from `.env`
(`JADE_STACK_APP_ENV`, `SITE_ADDRESS`, `JADE_HTTP_PORT`, `JADE_HTTPS_PORT`, `JADE_ORIGIN` and the
two database passwords and the app's secrets); it builds its own database URLs, with host `db`.
If ports 80 or 443 are taken, write `.env` with `pnpm env:init --http-port <p> --https-port <p>`.
`docker compose -p jade-stack-<hash> down -v` also removes its volumes, and with them the stack's
database. That is needed after the passwords in `.env` change (a new `pnpm env:init`): the kept
database volume still holds the old `jade_owner` password, so the stack would not start on it.

For one checkout, in a shell without `COMPOSE_PROJECT_NAME`, the plain Compose command does the
same with the shared image tag `jade-app:local` and the project `jade-stack`, reading `.env`:

```sh
docker compose -f compose.prod.yml up --build
```

Without `--build`, `up` builds `jade-app:local` only when that tag is missing, and otherwise runs
whatever image the tag last pointed at.

On a VM, the env file is written by the image itself with
`node tools/env-init.ts --profile stack --app-env staging --site <host> --out <path>`, run as the
deploy user (`docker run --rm --user "$(id -u):$(id -g)"` with the env directory mounted), so it
holds that VM's own secrets and no development variable.

## The gate

Every change passes:

```sh
pnpm lint && pnpm check && pnpm test && pnpm e2e
pnpm test:infra
```

- `pnpm lint`: Prettier and ESLint, warnings as failures.
- `pnpm check`: svelte-check (TypeScript strict), warnings as failures.
- `pnpm test`: Vitest, every project but `infra` (unit, integration, black-box).
- `pnpm e2e`: Playwright on Chromium (desktop) and WebKit (iPad).
- `pnpm test:infra`: the image and the production stack (needs Docker, not the development
  database). Its global setup pulls the pinned `postgres` and `caddy` images and builds the run's
  image once with `pnpm ci:image` (`docker buildx bake` on the `app` service of
  `compose.prod.yml`); each test file brings up a stack of its own, as the Compose project
  `jade-infra-<run id>-<test>` on free ports, and removes it with its volumes afterwards. The
  run's image tag is removed at the end, and so is any stack of the run a crashed test file left.
  In CI, `JADE_CI_IMAGE_CACHE=gha` makes the global setup add the GitHub Actions cache flags
  (`--set app.cache-from=type=gha --set app.cache-to=type=gha,mode=max`) to `pnpm ci:image`; it
  accepts no other value. `pnpm ci:image` itself needs `JADE_IMAGE` (the tag to build) and refuses
  to run without it.
- After an infra run that was interrupted (a single Ctrl-C already ends `vitest run` without its
  teardown) or crashed, its stacks and image tag may remain. A later run does not remove them: it
  sweeps only its own run id.
  With no other infra run going on this machine, in any checkout, remove them with:

  ```sh
  docker compose ls -a -q | grep '^jade-infra-' | xargs -r -I{} docker compose -p {} down -v
  docker ps -a -q --filter label=jade-test=media --filter name=jade-infra- | xargs -r docker rm -f -v
  docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^jade-app:(ci|build)-' | xargs -r docker image rm
  ```

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
