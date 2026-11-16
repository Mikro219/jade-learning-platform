# The app image (plan D1). Its one build definition is the `build:` stanza of `app` in
# compose.prod.yml, which `pnpm ci:image` (docker buildx bake) and `pnpm stack:up` both build from
# (PD14, D7). No build step needs a secret.
#
# Entry points (the runtime stage holds every file each one imports; tests/infra/image.test.ts
# runs each in the image):
#   node build                     the app (CMD)
#   node tools/db/migrate.ts       migrations (the `migrate` service; Node 24 strips the types)
#   node tools/env-init.ts         a VM's env file (`--profile stack`, plan Z2)

# Node pin (INV9): .nvmrc, package.json and this line name one release.
ARG NODE_VERSION=24.22.3

FROM node:${NODE_VERSION}-alpine3.24 AS build
# pnpm pin (INV9): package.json's packageManager names the same release.
ARG PNPM_VERSION=12.21.0
WORKDIR /app
RUN npm install -g pnpm@${PNPM_VERSION}
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# The image's own Node runs everything: pnpm downloads no runtime of its own here.
RUN pnpm install --frozen-lockfile --no-runtime
COPY . .
# Declared here, after the install and right before the build, so that a build with another
# APP_VERSION reuses every layer up to and including the install (D7). vite.config.ts reads it.
ARG APP_VERSION
RUN pnpm build
# Production dependencies only, for the runtime stage: a fresh install from the store, so no
# development package is left in node_modules/.pnpm.
RUN rm -rf node_modules && pnpm install --prod --frozen-lockfile --no-runtime --offline

FROM node:${NODE_VERSION}-alpine3.24
ENV NODE_ENV=production
WORKDIR /app
# Owned by root and read-only to the `node` user that runs them.
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/build ./build
COPY --from=build /app/migrations ./migrations
COPY --from=build /app/tools ./tools
# The SvelteKit-free folders the tools import (PD10).
COPY --from=build /app/src/lib/server/config ./src/lib/server/config
COPY --from=build /app/src/lib/server/db ./src/lib/server/db
COPY --from=build /app/src/lib/server/log ./src/lib/server/log
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --start-interval=1s --retries=3 \
	CMD ["node", "-e", "fetch('http://127.0.0.1:3000/healthz').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "build"]
