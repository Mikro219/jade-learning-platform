# 0017. Live stuck alerts for kits with logging off

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.2, close reason (Mike, 2026-11-14)
- Related: [0009](0009-consent-gated-logging.md)

## Context

ARCHITECTURE.md section 8 and p7-live-stuck say that for kits with logging off, stuck alerts still reach the facilitator, held in memory and never stored (jade-8n2.2 description). But EVENTS.md client rule 5 says that when logging is off the client clears its queue and stops queueing, and server rule 2 (and p6-ingest) say ingest returns 204 and writes nothing, so as written a no-log kit's "I'm stuck" press is never sent and the alert cannot be shown (jade-8n2.2 description). The question touches CLAUDE.md rule 2, so it needed a human decision (jade-8n2.2 description).

## Decision

Decided (Mike, 2026-11-14): separate live endpoint, memory-only, device-session auth; client sends only stuck/stuck_resolved there in no-log mode; no-log invariant extended (now depends on p7-live-stuck).

Acceptance criteria this decision added:

- jade-4a7: With logging off the client sends only stuck/stuck_resolved, live to the alert endpoint, never queued offline; nothing else is sent (jade-8n2.2)
- jade-zg3: Ingest stays store-nothing with logging off; live alerts use the separate endpoint from p7-live-stuck (jade-8n2.2)
- jade-p99: Live alert endpoint for stuck/stuck_resolved, authenticated by device session (class and kit from the session), holds alerts in memory per class until resolved or the session closes; never written to the database or logs (jade-8n2.2)
- jade-hhp: Covers the live stuck endpoint: with logging off, a stuck/resolved cycle persists nothing and leaves no kit activity in logs (jade-8n2.2)

## Consequences

- p7-live-stuck (jade-p99) builds the live alert endpoint; p6-client (jade-4a7) sends only `stuck` and `stuck_resolved` there when logging is off; p6-ingest (jade-zg3) stays store-nothing; p6-nolog-invariant (jade-hhp) covers the live endpoint and now depends on jade-p99 (bead acceptance and dependencies).
- Corrected in place: EVENTS.md client rule 5 and server rule 2; DATA-MODEL.md section 4 (a paragraph on live stuck alerts for kits with logging off); PRIVACY.md "Data inventory" (a live stuck alerts row) and "Consent and opt-out" (a bullet) ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- ARCHITECTURE.md section 8, "The consent gate", is not edited; for these alerts this ADR is the current statement ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- For kits with logging off the alert store is process memory, so a restart of the app drops their open alerts (follows from jade-p99 acceptance: held in memory per class, never written to the database or logs).
- Whether kits with logging on use the same endpoint and store, or the facilitator's live alert for them comes from ingested `stuck` events, is not decided by any source. The close reason speaks of no-log mode only; p7-live-stuck (jade-p99) must not guess.
