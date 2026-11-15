# 0004. One Canadian VM, Docker Compose

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-04
- Related: [0014](0014-staging-from-phase-1.md)

## Context

Design principle 7 is "Boring and portable": Docker Compose on a Canadian VM, so moving hosts is a restore, not a rewrite (ARCHITECTURE.md section 2). v1 deployed at the end, so first contact with the host, TLS, the school network and backups would all have happened in the last week (REVIEW.md finding 18). v1 described no backups, monitoring or rollback, and losing pilot data loses the pilot (REVIEW.md finding 19). The v2 deployment is Caddy, app and PostgreSQL on one VM, with local, staging and production environments and nightly encrypted dumps to Canadian object storage (ARCHITECTURE.md section 10).

## Decision

Production is a single Linux VM in a Canadian region running Compose: Caddy, app, Postgres. Staging is a second, smaller VM. Provider is a human decision (`p0-host`). Providers with Canadian regions to compare: DigitalOcean (Toronto), AWS (Montréal, Calgary), Google Cloud (Montréal, Toronto), Azure (Toronto, Québec City), OVHcloud (Beauharnois). Backups go to object storage in Canada.

A home server is not used for pilot data: residential uplink and uptime are the wrong risk to carry into a classroom.

## Consequences

- Provider and region: not yet chosen; recorded here by jade-0za (p0-host).
- p1-docker (jade-80h) builds the Compose stack with Caddy as the only public service; p1-staging (jade-4zw) provisions the staging VM in the chosen Canadian region; p10-prod-infra (jade-dvm) provisions the production VM; p10-backups (jade-6o3) sends encrypted nightly dumps to object storage in Canada and performs a restore drill (bead descriptions).
- No source names the object-storage provider for the backups; the Decision requires only that it is in Canada.
- Staging from Phase 1 is [0014](0014-staging-from-phase-1.md).
