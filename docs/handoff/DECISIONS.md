# Decisions

Accepted decisions for the v1 build. Phase 0 turns each into a file under `docs/adr/`. An agent that believes one is wrong files a `decision` bead and stops; it does not quietly build something else.

## ADR-01 Kit-agnostic platform

The platform serves any kit. A kit is a `products` row (slug, name, code prefix) and a `content/<slug>/` folder. First product: the mechanical arm, slug `arm`, prefix `ARM`. Both are placeholders until the team names the kit; changing them before codes are printed is a one-line change.

## ADR-02 Modular monolith in SvelteKit

One SvelteKit app (adapter-node, TypeScript strict) serves pages and API routes. Server code is split into `auth`, `codes`, `content`, `events`, `analytics` modules that talk through their `index.ts`. Chosen for server-rendered pages that work on weak school devices, form actions that work without JavaScript, and one thing to deploy.

The framework may be swapped for an equivalent (for example Next.js) **only during Phase 0** and only by a human decision. Nothing else in this document depends on SvelteKit specifically.

## ADR-03 PostgreSQL with Drizzle and SQL migrations

PostgreSQL 16. Drizzle for typed queries. Migrations are SQL files, forward-only, run on deploy. Analytics is SQL views in the same database.

## ADR-04 One Canadian VM, Docker Compose

Production is a single Linux VM in a Canadian region running Compose: Caddy, app, Postgres. Staging is a second, smaller VM. Provider is a human decision (`p0-host`). Providers with Canadian regions to compare: DigitalOcean (Toronto), AWS (Montréal, Calgary), Google Cloud (Montréal, Toronto), Azure (Toronto, Québec City), OVHcloud (Beauharnois). Backups go to object storage in Canada.

A home server is not used for pilot data: residential uplink and uptime are the wrong risk to carry into a classroom.

## ADR-05 Authentication without email

Adults: email + password, argon2id, server-side sessions. Signup requires a valid unused kit code or a staff invite. Password reset is a staff action. Students: class join code plus kit selection, yielding a device-session cookie bound to class and kit. No accounts for children.

## ADR-06 Content as Markdown in the repo, version-locked

Markdown with YAML frontmatter under `content/`. Permanent step IDs. `content.lock.json` and a CI lint enforce version bumps. No CMS in v1.

## ADR-07 Self-hosted, same-origin video

H.264/AAC MP4 at 720p with faststart, on a volume served by Caddy with Range support, behind short-lived signed URLs. No third-party video host.

## ADR-08 Event integrity

Client-assigned UUIDv7 event IDs and client timestamps, server receive time, idempotent batched ingest, a zod event catalog shared by client and server, append-only storage.

## ADR-09 Consent-gated logging

`logging_enabled` per kit per class, default off, switched on by an adult who confirms consent. Off means zero activity stored server-side. A required test enforces this.

## ADR-10 The kit is the unit of analysis

Events have no seat or participant. A participant letter exists only on adult-entered quiz and exit-card rows.

## ADR-11 Kit code format and storage

`PREFIX-XXXX-XXXX-C`, Crockford Base32, CSPRNG, check character. Stored as HMAC-SHA256 under a server-side pepper. Plain codes exist only on print and in an offline CSV.

## ADR-12 Device telemetry and AI assistant are out of scope

Neither is built in v1. See extension points E1 and E2 in `ARCHITECTURE.md`.

## ADR-13 No third-party requests from the browser

No analytics, fonts, CDNs, embeds or error trackers that load in the user's browser. CSP enforces it and an e2e test asserts it.

## ADR-14 Staging from Phase 1

Staging exists before feature work and is deployed on every merge to main. Production receives the image that passed staging.

## ADR-15 Tooling

pnpm, current Node LTS (pinned), ESLint + Prettier, Vitest, Playwright (Chromium and WebKit), GitHub Actions, zod, k6 for load. Work is tracked in beads (`bd`); planning and bug work use the repo's `planloop` and `bugfix` skills.

---

# Assumptions made without confirmation

| # | Assumption | If wrong |
|---|---|---|
| A1 | The arm kit has no Wi-Fi board and no AI assistant | Build E1 and/or E2; add a phase after Phase 6 |
| A2 | Groups of 2 or 3 share one device | If one device per child, revisit ADR-10 and the consent wording |
| A3 | Freeze is still mid-December for a January classroom pilot | Re-plan dates in `START-HERE.md`; phase order stays |
| A4 | The pilot site has tablets or Chromebooks with a current browser | If not, the team supplies devices or runs print-first with QR lookups on a few shared devices |
| A5 | Adults in the pilots are the team's facilitators plus one teacher | If many outside adults need accounts, bring E4 (email) forward |
| A6 | The repo is hosted on GitHub | Swap the CI and authoring-guide details |
| A7 | English only | Content format would need a locale dimension |

# Open questions for the team

Seeded as bead `p0-open-decisions` (and `p0-host`, `p0-school-it`, `p0-consent`).

1. **Kit name and code prefix.** Needed before production codes are printed.
2. **Module and step outline for the arm kit**, with a rough expected time per step. Needed before real content is loaded; the build proceeds on demo content until then.
3. **Networked electronics or AI assistant on the arm?** Confirms or overturns A1.
4. **Host and domain.** Blocks staging.
5. **Pilot-site devices and network.** Device type, browser, allowlisting lead time, cookie persistence.
6. **Consent and research approval.** Do the current documents describe a web platform that logs kit-level activity? If the application was approved for the incubator, does the pivot need an amendment?
7. **Retention period.** Default in the build is 12 months after a class ends.
8. **Who enters quiz results**, and is the quiz still picture-based on paper?
