# Phase 6: Event pipeline

**Goal.** Trustworthy data for redesigning the modules: every event validated, idempotent, correctly timed even when it was queued offline, and never stored without consent.

## Exit criteria

- [ ] All catalog events flow from the demo kit to the database on staging
- [ ] Replaying a batch creates no duplicates
- [ ] The no-log invariant test passes

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p6-catalog` | P0 | task | Event catalog as code, with generated documentation | `p1-scaffold` | events |
| `p6-table` | P0 | task | Events table, indexes and progress table | `p2-schema-core` | events, db |
| `p6-ingest` | P0 | task | Ingest endpoint: authenticated, validated, consent-gated, idempotent | `p6-catalog`, `p6-table`, `p3-join`, `p3-consent-flag` | events, privacy, security |
| `p6-client` | P0 | task | Client event queue: persistent, batched, retried | `p6-catalog`, `p5-step` | events, offline |
| `p6-time` | P0 | task | Active-time measurement | `p6-client` | events |
| `p6-video-events` | P1 | task | Video instrumentation | `p6-client`, `p4-video` | events |
| `p6-instrument` | P0 | task | Instrument the student app with all catalog events | `p6-client`, `p5-checkpoint`, `p5-stuck`, `p4-shortlinks` | events |
| `p6-nolog-invariant` | P0 | task | Privacy invariant test: no-log mode stores nothing | `p6-ingest`, `p6-instrument`, `p5-progress` | privacy, tests |
| `p6-replay-tests` | P1 | task | Offline and replay robustness tests | `p6-ingest`, `p6-client` | tests, offline |

### `p6-catalog` Event catalog as code, with generated documentation

Implement docs/handoff/EVENTS.md as a zod discriminated union shared by client and server, with a catalog version. Generate docs/events.md from the code so the consent appendix is always accurate.

Acceptance:

- Unknown event types and extra fields are rejected
- Generated doc matches the code (CI checks it is up to date)

### `p6-table` Events table, indexes and progress table

Tables from DATA-MODEL.md section 4: events (append-only, primary key event_id), kit_progress. Indexes for (class_id, kit_id, client_ts) and (step_id, content_version, type). No update or delete grants for the app role on events except through the deletion function added in Phase 9.

Acceptance:

- Insert with a duplicate event_id is a no-op
- App role cannot UPDATE events (tested)

### `p6-ingest` Ingest endpoint: authenticated, validated, consent-gated, idempotent

POST /api/events accepts a batch (max 100 events, max 64 KB). Auth by device session; class and kit come from the session, never from the payload. If logging is off for the kit, return 204 and store nothing. Validate against the catalog, set received_at, insert with ON CONFLICT DO NOTHING. Clamp client timestamps that are in the future or older than 14 days and flag them.

Acceptance:

- Payload cannot write events for another kit (tested)
- Same batch posted three times yields one set of rows
- With logging off, zero rows are written and the response is indistinguishable in timing class

### `p6-client` Client event queue: persistent, batched, retried

Queue in IndexedDB. Each event gets a UUIDv7, client_ts, a per-session sequence number and the app version. Flush every 10 seconds or 20 events, on visibilitychange and pagehide (sendBeacon/keepalive), with exponential backoff. Cap the queue (drop oldest heartbeats first, never stuck or checkpoint events). If the server says logging is off, stop queueing.

Acceptance:

- Events created offline are delivered after reconnect with original client_ts
- Queue survives a tab close and a browser restart
- No events are queued in no-log mode

### `p6-time` Active-time measurement

Count time on a step only while the tab is visible and there was interaction (touch, key, scroll, video playing) in the last 60 seconds. Emit step_time deltas at flush and on leave. This replaces the vague 'time on screen', which over-counts every time a group walks away to build.

Acceptance:

- Leaving a step open and idle for 10 minutes records about 60 seconds, not 600
- Sum of deltas equals measured active time within 5%

### `p6-video-events` Video instrumentation

Emit video_play, video_pause, video_seek (from, to), video_ended and watched ranges (merged intervals in seconds) so analytics can show which seconds get replayed.

Acceptance:

- Replaying 0:20 to 0:35 twice produces overlapping ranges that reconstruct the replay
- No event spam: at most one range update per 5 seconds

### `p6-instrument` Instrument the student app with all catalog events

Wire step_view (with entry: nav, resume, qr), step_complete, stuck, stuck_resolved, checkpoint_answer, track_switch, session_start. Every event carries step_id, content_version and track from the content actually rendered.

Acceptance:

- e2e test asserts the exact event sequence for the scripted scenario
- content_version on events matches the rendered step

### `p6-nolog-invariant` Privacy invariant test: no-log mode stores nothing

A dedicated e2e test runs the full student scenario with logging off, then asserts row counts in events, kit_progress, notes and quiz tables are unchanged, and that app logs contain no kit activity. This test is the evidence behind the consent form's opt-out promise; it must never be skipped or weakened.

Acceptance:

- Test fails if any activity row is written with logging off
- Test is marked required in CI

### `p6-replay-tests` Offline and replay robustness tests

Tests for duplicate batches, out-of-order delivery, partial batch failure, clock skew of plus or minus one day, and an airplane-mode e2e run.

Acceptance:

- All cases leave the events table consistent and deduplicated
