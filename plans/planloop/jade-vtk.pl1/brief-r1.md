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
