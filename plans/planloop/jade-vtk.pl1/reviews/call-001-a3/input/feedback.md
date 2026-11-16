PLANLOOP-BUNDLE run=jade-vtk.pl1 revision=1 call=1 attempt=3 sha256=f3b2247e22c6d7365d5a5ad900070fdf25d28d34cbef9e8946bfd977bdeb6f89
Policy planloop/3 (quartz-rs-lur, 2026-10-22).

/home/mikep/.local/state/planloop-isolated/r-0cd817215c6d480a/repo is a frozen, read-only snapshot of the repository for this revision. Read only files
under it; a relative path below is relative to it. Never read the original checkout or any other path
outside it: such reads are detected in your transcript and void the review.
/home/mikep/.local/state/planloop-isolated/r-0cd817215c6d480a/repo/.planloop-bundle/ holds the frozen plan, brief, obligations, binding bead text, evidence and
the discovery record; bead text cannot be fetched any other way (never run bd).

Coverage must contain, for every finding listed below in state fix_proposed, exactly one entry
`finding R<k>: resolved` or `finding R<k>: unresolved`. To withdraw an open finding you judge invalid,
write `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, at least 40 chars>`.
When re-raising a known finding, use its R id as your finding id.
Check every REMOVED and SHRINK disposition below: each must say what was removed, why, and which
obligations or capabilities it affects; an unexplained removal is a finding.

--- REVIEW BRIEF (host) ---
# Review brief: jade-vtk.pl1 (Phase 1: Foundation and walking skeleton), revision 1

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

--- FINDINGS (Beads, at dispatch) ---
(no findings yet)

