# 0008. Event integrity

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-08
- Related: [0018](0018-stale-timestamps-flagged-not-clamped.md)

## Context

v1 events carried a server-set `ts` only, so events from an offline session would all be stamped with the moment Wi-Fi came back, and time-on-step would be garbage (REVIEW.md finding 2). v1 described no deduplication for the offline queue, so a retried batch would double-count (REVIEW.md finding 3). v1 sent kit ID and seat with events, so any tablet could write events for any kit (REVIEW.md finding 6). Architecture v2 sets out client-assigned UUIDv7 and `client_ts`, server `received_at`, idempotent insert, identity from the device session, a versioned catalog and an append-only events table (ARCHITECTURE.md section 8, "Event integrity").

## Decision

Client-assigned UUIDv7 event IDs and client timestamps, server receive time, idempotent batched ingest, a zod event catalog shared by client and server, append-only storage.

## Consequences

- p6-catalog (jade-3ek) builds the shared zod catalog; p6-client (jade-4a7) the client queue; p6-ingest (jade-zg3) the idempotent, session-authenticated ingest; p6-table (jade-7j8) the append-only `events` table (bead titles and descriptions).
- CLAUDE.md rule 3: class and kit identity come from the session, never from a request body.
- How the server treats stale client timestamps is made explicit by [0018](0018-stale-timestamps-flagged-not-clamped.md).
