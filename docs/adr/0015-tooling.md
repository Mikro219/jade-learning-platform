# 0015. Tooling

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-15

## Context

DECISIONS.md ADR-15 lists the toolchain and the work-tracking tools for the build. The handoff documents give no further rationale for these choices; this record adds none (DECISIONS.md ADR-15).

## Decision

pnpm, current Node LTS (pinned), ESLint + Prettier, Vitest, Playwright (Chromium and WebKit), GitHub Actions, zod, k6 for load. Work is tracked in beads (`bd`); planning and bug work use the repo's `planloop` and `bugfix` skills.

## Consequences

- p1-scaffold (jade-h8i) sets up pnpm, TypeScript strict, ESLint and Prettier, Vitest and Playwright, with the Node LTS pinned in `.nvmrc` and the Dockerfile (jade-h8i description).
- p1-ci (jade-xu0) runs the GitHub Actions workflow, with Playwright on Chromium and WebKit (jade-xu0 description). GitHub hosting is assumption A6, which is unconfirmed ([README](README.md#assumptions-unconfirmed)).
- p9-load (jade-0d8) runs the load test with k6 (jade-0d8 description).
- Work is tracked in beads (`bd`), and planning and bug work use the `planloop` and `bugfix` skills, as CLAUDE.md describes ("Work tracking: beads", "How each bead is worked").
