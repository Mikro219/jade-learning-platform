# 0016. Step-metrics views and the retention job are post-launch-ok

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.1, close reason (Mike, 2026-11-14)
- Related: [0003](0003-postgresql-with-drizzle-and-sql-migrations.md), [0023](0023-tiered-retention-for-kit-keyed-data.md)

## Context

START-HERE.md says Phase 8's dashboards can ship in January and "Only `p8-quality` and `p8-export` block launch" (START-HERE.md, "Phases"). But p8-views, not labelled post-launch-ok, blocked p9-retention, which blocked p9-privacy-doc, which blocked p10-go-live, so the step-metrics views were on the critical path before the mid-December freeze (jade-8n2.1 description). One of the options the bead listed was to make retention post-launch-ok, since the first raw events are not due for aggregation until 12 months after a class ends (jade-8n2.1 description).

## Decision

Decided (Mike, 2026-11-14): retention post-launch. p9-retention and p8-views labelled post-launch-ok; p9-retention due 2027-06-30; p9-privacy-doc no longer depends on p9-retention and documents the policy instead.

Acceptance criteria this decision added:

- jade-8vo: Running in production before the first class reaches classes.ended_at + RETENTION_MONTHS (jade-8n2.1)
- jade-771: Describes the agreed retention policy (tiered, jade-8n2.8) and states that the retention job ships after launch (jade-8n2.1)

## Consequences

- p8-views (jade-lx4) and p9-retention (jade-8vo) are labelled post-launch-ok; jade-8vo is due 2027-06-30; p9-privacy-doc (jade-771) no longer depends on jade-8vo, and documents the policy instead (bead labels, due date and dependencies).
- The START-HERE.md sentence "Only `p8-quality` and `p8-export` block launch" now holds (jade-lx4 and jade-8vo labels).
- The retention job ships after launch (jade-771 acceptance) and must be running in production before the first class reaches `classes.ended_at + RETENTION_MONTHS` (jade-8vo acceptance).
- Corrected in place: the DATA-MODEL.md section 6 "Retention" bullet and PRIVACY.md "Retention" now say when the job ships and when it must run ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The generated phase files still show the old edges: `phase-08` lists p8-views without the post-launch-ok label, and `phase-09` lists p9-retention without it and p9-privacy-doc depending on p9-retention ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The retention rule itself is [0023](0023-tiered-retention-for-kit-keyed-data.md).
