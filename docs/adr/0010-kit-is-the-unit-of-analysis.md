# 0010. The kit is the unit of analysis

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-10
- Related: [0019](0019-participant-letters-a-to-d.md)

## Context

v1 had every event carry a seat A/B/C, but two or three children share one tablet, so seat-level attribution of taps is fiction and adds per-child data for no analytical gain (REVIEW.md finding 7). Design principle 2 is "The kit is the unit": a group of two or three shares one tablet, so data is recorded per kit, not per child (ARCHITECTURE.md section 2).

## Decision

Events have no seat or participant. A participant letter exists only on adult-entered quiz and exit-card rows.

## Consequences

- The event envelope has no seat or participant field (EVENTS.md, "Envelope").
- Participant letters exist only on `quiz_responses` and `exit_cards` (DATA-MODEL.md section 5); their range, A to D, is [0019](0019-participant-letters-a-to-d.md).
- This decision depends on assumption A2 (groups of 2 or 3 share one device); if there is one device per child, A2 says to revisit this decision and the consent wording ([README](README.md#assumptions-unconfirmed)). p0-school-it (jade-tw4) records the device type and count.
