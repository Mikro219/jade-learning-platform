# 0023. Tiered retention for kit-keyed data

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.8, close reason (Mike, 2026-11-14)
- Related: [0016](0016-step-views-and-retention-post-launch-ok.md)

## Context

DATA-MODEL.md section 6 and PRIVACY.md gave a retention rule only for raw events, replaced by per-step aggregates without kit ids 12 months after the class ends (jade-8n2.8 description). `kit_progress`, `facilitator_notes`, `quiz_responses`, `exit_cards` and `device_sessions` also carry `kit_id`, but no retention rule covered them, so they would be kept indefinitely unless a kit is deleted (jade-8n2.8 description). `step_aggregates` was also not defined in the DATA-MODEL schema, and the rule was to be checked against the research approval (p0-consent) (jade-8n2.8 description).

## Decision

Decided (Mike, 2026-11-14): tiered retention (see p9-retention acceptance).

Acceptance criteria this decision added:

- jade-8vo: Tiered at classes.ended_at + RETENTION_MONTHS (jade-8n2.8): events reduced to step_aggregates (no kit id); kit_progress and device_sessions deleted; facilitator_notes kept with kit_id set to null; quiz_responses and exit_cards reduced to per-question / per-module counts with no kit id, then deleted
- jade-8vo: step_aggregates and the quiz/exit-card aggregate tables are defined in a migration and documented in the data model

## Consequences

- Corrected in place: the DATA-MODEL.md section 6 "Retention" bullet and PRIVACY.md "Retention" now state the tiers ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- `step_aggregates` and the quiz and exit-card aggregate tables are not yet defined; p9-retention (jade-8vo) defines them in a migration and documents them in the data model (jade-8vo acceptance).
- `RETENTION_MONTHS` (default 12 months after the class ends) stays open until p0-open-decisions (jade-6is) records the retention period (jade-6is acceptance; open question 7 in the [README](README.md#open-questions)).
- The tiers were to be checked against the research approval (jade-8n2.8 description); p0-consent (jade-bi5) is open, so that check has not happened.
- After retention, `facilitator_notes` keep the adult's note text with its class, no longer linked to a kit (jade-8vo acceptance: kept with `kit_id` set to null).
- The ARCHITECTURE.md section 9 sentence on a "retention job that reduces raw events to aggregates" and the generated `phase-09` p9-retention text describe raw events only; they are not edited ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- When the job ships is [0016](0016-step-views-and-retention-post-launch-ok.md).
