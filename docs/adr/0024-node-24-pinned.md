# 0024. Node 24 is the pinned Node LTS line

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-h8i, notes (Mike, 2026-11-14)
- Related: [0015](0015-tooling.md)

## Context

ADR 0015 decides "current Node LTS (pinned)", and p1-scaffold (jade-h8i) pins it in `.nvmrc` and the Dockerfile (jade-h8i description). On 2026-11-14 the two newest Node LTS lines were 24 (LTS since 2025-10-28) and 26 (LTS since 2026-10-28) (Node.js release schedule).

## Decision

Decided (Mike, 2026-11-14): pin Node 24 (.nvmrc and Dockerfile).

## Consequences

- `.nvmrc`, `package.json` and the Dockerfile name the same Node 24 release, and a test fails when they differ (jade-h8i).
- ADR 0015's Decision is unchanged; one line under its Consequences points here. For this build, its "current Node LTS (pinned)" is Node 24.
- Moving to another Node line is a new decision, recorded as a new ADR. Node 24 reaches end of life on 2028-04-30 (Node.js release schedule); p9-deps (jade-8ho) audits the pinned images.
