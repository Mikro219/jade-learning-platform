# 0014. Staging from Phase 1

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-14
- Related: [0004](0004-one-canadian-vm-docker-compose.md)

## Context

v1 deployed at the end, with a December load test, so first contact with the host, TLS, the school network and backups would all have happened in the last week (REVIEW.md finding 18). In v2, staging is live from Phase 1 and deployed on every merge to main, and production is promoted by tag with the same image that passed staging (ARCHITECTURE.md section 10).

## Decision

Staging exists before feature work and is deployed on every merge to main. Production receives the image that passed staging.

## Consequences

- p1-staging (jade-4zw) provisions staging and deploys from CI on every merge to main; it is blocked by p0-host (jade-0za), which chooses the host (bead dependencies).
- p10-cd (jade-kn0) promotes the exact image tested on staging, with a health gate and rollback (jade-kn0 description).
- The VM and Compose setup is [0004](0004-one-canadian-vm-docker-compose.md).
