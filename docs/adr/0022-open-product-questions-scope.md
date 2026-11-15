# 0022. The open-product-questions bead covers retention, quiz entry and the freeze date

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.7, close reason (Mike, 2026-11-14)
- Related: [0023](0023-tiered-retention-for-kit-keyed-data.md)

## Context

DECISIONS.md lists eight open questions and says they are seeded as p0-open-decisions, but the bead's acceptance covered only the kit slug and prefix, the module outline and networked electronics (jade-8n2.7 description). It omitted the retention period (question 7), who enters quiz results and whether the quiz is still paper and picture-based (question 8), and whether mid-December is still the freeze, which the whole calendar rests on (jade-8n2.7 description; REVIEW.md "Things this review could not settle" item 6; assumption A3). The suggested calendar also has Phase 9 (Dec 13-16) overlapping Phase 10 (Dec 14-18), though p10-prod-infra depends on p9-load (jade-8n2.7 description; START-HERE.md "Suggested calendar").

## Decision

Decided (Mike, 2026-11-14): extend jade-6is acceptance with retention period, quiz entry and freeze date; calendar re-sequenced once the freeze is confirmed.

Acceptance criteria this decision added:

- jade-6is: Retention period recorded (it sets RETENTION_MONTHS; default 12 months after class end)
- jade-6is: Who enters quiz results, and whether the quiz is still paper and picture-based, recorded
- jade-6is: Freeze date confirmed or moved; the calendar is re-sequenced so Phase 10 infra starts after the Phase 9 load test (jade-8n2.7)

## Consequences

- The acceptance of p0-open-decisions (jade-6is) now includes the retention period, who enters quiz results, and the freeze date (lines above).
- The generated `phase-00` p0-open-decisions text still lists only three acceptance lines ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The calendar in START-HERE.md (Phase 9 Dec 13-16 overlapping Phase 10 Dec 14-18) is re-sequenced by jade-6is once the freeze is confirmed; it is not edited here ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The freeze date is added as open question 9 in the [README](README.md#open-questions), owned by jade-6is. The retention period sets `RETENTION_MONTHS` for [0023](0023-tiered-retention-for-kit-keyed-data.md).
