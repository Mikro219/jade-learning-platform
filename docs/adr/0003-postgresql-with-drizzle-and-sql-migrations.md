# 0003. PostgreSQL with Drizzle and SQL migrations

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-03
- Related: [0016](0016-step-views-and-retention-post-launch-ok.md)

## Context

PostgreSQL 16 holds everything persistent, as a single instance with nightly encrypted backups (ARCHITECTURE.md section 4). A release builds the image, runs forward-only migrations, starts, health-checks and switches; rollback is the previous image, so migrations stay compatible with the previous app version (ARCHITECTURE.md section 10). Analytics are staff-only pages over SQL views in the same database (ARCHITECTURE.md section 11).

## Decision

PostgreSQL 16. Drizzle for typed queries. Migrations are SQL files, forward-only, run on deploy. Analytics is SQL views in the same database.

## Consequences

- p1-db (jade-urd) sets up PostgreSQL 16, Drizzle and SQL migrations; its acceptance requires migrations to be forward-only and run automatically on deploy.
- Migrations stay compatible with the previous app version, so rollback to the previous image works (ARCHITECTURE.md section 10; p10-cd jade-kn0 description).
- Analytics are SQL views in the same database, built by p8-views (jade-lx4), which [0016](0016-step-views-and-retention-post-launch-ok.md) labels post-launch-ok.
