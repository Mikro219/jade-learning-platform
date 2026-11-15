# 0002. Modular monolith in SvelteKit

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-02

## Context

v1 had a separate API service, a CMS, a third-party video host and a staff analytics app: four deployables and two vendors for one developer with five weeks (REVIEW.md finding 10). Design principle 5 is "One deployable, one database, one origin": one developer has to build and run this (ARCHITECTURE.md section 2). The components are one SvelteKit app with `auth`, `codes`, `content`, `events` and `analytics` modules, each a folder whose `index.ts` is its public API (ARCHITECTURE.md section 4).

## Decision

One SvelteKit app (adapter-node, TypeScript strict) serves pages and API routes. Server code is split into `auth`, `codes`, `content`, `events`, `analytics` modules that talk through their `index.ts`. Chosen for server-rendered pages that work on weak school devices, form actions that work without JavaScript, and one thing to deploy.

The framework may be swapped for an equivalent (for example Next.js) **only during Phase 0** and only by a human decision. Nothing else in this document depends on SvelteKit specifically.

## Consequences

- p1-scaffold (jade-h8i) follows the module layout of ARCHITECTURE.md section 4, with the module boundaries as folders with an `index.ts` each (jade-h8i acceptance).
- Modules call each other only through their `index.ts` (ARCHITECTURE.md section 4).
- The framework-swap window is Phase 0 only and needs a human decision (Decision above); Phase 0 is epic jade-8n2, so the window closes when that epic closes.
