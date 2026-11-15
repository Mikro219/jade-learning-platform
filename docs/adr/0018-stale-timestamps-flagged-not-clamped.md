# 0018. Stale client timestamps are flagged, not clamped

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.3, close reason (Mike, 2026-11-14)
- Related: [0008](0008-event-integrity.md)

## Context

EVENTS.md server rule 4 clamps a `client_ts` more than 5 minutes in the future and flags it `future`, and flags one older than 14 days `stale` without clamping it; p6-ingest said to clamp timestamps that are in the future or older than 14 days and flag them (jade-8n2.3 description). Clamping stale timestamps would overwrite the real time of events queued offline for a long time, which REVIEW.md finding 2 exists to protect (jade-8n2.3 description). REVIEW.md finding 2 introduced `client_ts` plus server `received_at` because server-stamped offline events make time-on-step meaningless (REVIEW.md finding 2).

## Decision

Decided (Mike, 2026-11-14): flag only, per EVENTS.md. Future clamped and flagged; stale flagged, not clamped.

Acceptance criteria this decision added:

- jade-zg3: client_ts more than 5 min in the future is clamped to received_at and flagged 'future'; older than 14 days keeps its client_ts and is flagged 'stale', not clamped (EVENTS.md server rule 4; jade-8n2.3)

## Consequences

- p6-ingest (jade-zg3) implements the rule (jade-zg3 acceptance). `events.ts_flag` already allows `future` and `stale` (DATA-MODEL.md section 4), so no schema change follows.
- Corrected in place: EVENTS.md server rule 4 now says a `client_ts` older than 14 days keeps its value and is flagged `stale`, not clamped ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The generated `phase-06` p6-ingest text still says "Clamp client timestamps that are in the future or older than 14 days and flag them" ([README amendment map](README.md#amendments-to-the-handoff-documents)).
