# Event catalog (version 1)

Phase 6 implements this as a zod discriminated union in `src/lib/shared/events/` and generates `docs/events.md` from the code. If this file and the generated one ever disagree, the code wins and this file gets fixed.

> Amended 2026-11-14 by [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md) and [ADR 0018](../adr/0018-stale-timestamps-flagged-not-clamped.md). The handoff text is in git commit 079e846 and jade-handoff.zip.

## Envelope

Sent by the client on every event:

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUIDv7 | Client-assigned. Primary key; makes ingest idempotent |
| `client_ts` | ISO 8601 UTC | When it happened on the device |
| `seq` | integer | Increments per device session |
| `type` | string | One of the types below |
| `step_id` | string or null | Null only for `session_start` |
| `content_version` | integer or null | Version of the step actually rendered |
| `track` | `beginner` \| `advanced` \| null | |
| `app_version` | string | Build identifier |
| `catalog_version` | integer | `1` |
| `data` | object | Per-type payload below. No extra keys allowed |

Added by the server: `received_at`, `device_session`, `class_id`, `kit_id`, `ts_flag`. The client never sends class or kit.

Never present anywhere: names, free text from students, IP address, user agent string, device identifiers, location.

## Types

| Type | `data` | Emitted when |
|---|---|---|
| `session_start` | `{ resumed: boolean }` | Device joins or reopens the app |
| `step_view` | `{ entry: "nav" \| "resume" \| "qr" }` | A step is shown |
| `step_time` | `{ active_ms: integer }` | At each flush and on leaving a step. Delta since the last `step_time` for this view. Counts only while the tab is visible and there was interaction or video playback in the last 60 s |
| `step_complete` | `{ via: "done" \| "checkpoint" \| "facilitator_override" }` | Group marks the step done |
| `stuck` | `{ stuck_id: UUID, reason: string }` | "I'm stuck" pressed. `reason` is a preset id from content, never text |
| `stuck_resolved` | `{ stuck_id: UUID, outcome: "fixed" \| "helped" \| "skipped", elapsed_ms: integer }` | Group or facilitator clears it |
| `checkpoint_answer` | `{ checkpoint_id: string, option_id: string, correct: boolean, attempt: integer }` | Each answer |
| `track_switch` | `{ from: string, to: string }` | Group changes track |
| `video_play` | `{ video_id: string, at_s: number }` | Playback starts or resumes |
| `video_pause` | `{ video_id: string, at_s: number }` | |
| `video_seek` | `{ video_id: string, from_s: number, to_s: number }` | User scrubs |
| `video_ended` | `{ video_id: string }` | Reached the end |
| `video_ranges` | `{ video_id: string, ranges: [[start_s, end_s], ...] }` | At most every 5 s while playing, and on leave. Segments played since the last report; overlaps across reports are what reveal replays |

Default stuck reason ids: `cant_find_part`, `wont_fit`, `dont_understand`, `doesnt_work`. A step may override the list in its frontmatter.

## Client rules

1. Queue in IndexedDB; flush every 10 s or 20 events, on `visibilitychange` and `pagehide`.
2. Batch limit 100 events and 64 KB.
3. Retry with exponential backoff. Because ingest is idempotent, resending is always safe.
4. If the queue exceeds its cap, drop the oldest `step_time` and `video_ranges` first. Never drop `stuck`, `stuck_resolved`, `checkpoint_answer` or `step_complete`.
5. If the join response or any ingest response says logging is off, clear the queue and stop queueing. From then on the client sends only `stuck` and `stuck_resolved`, live, to the live alert endpoint (p7-live-stuck); they are never queued offline, and nothing else is sent ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)).

## Server rules

1. Authenticate by device session. Reject revoked sessions.
2. If `class_kits.logging_enabled` is false: respond 204, write nothing. That kit's `stuck` and `stuck_resolved` go to the separate live alert endpoint, which authenticates by device session, takes class and kit from the session, holds alerts in memory per class until resolved or the session closes, and never writes them to the database or logs ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)).
3. Validate the whole batch against the catalog. Reject the batch on any invalid event (a client bug should be loud).
4. `client_ts` more than 5 minutes in the future is clamped to `received_at` and flagged `future`; older than 14 days keeps its `client_ts` and is flagged `stale`, not clamped ([ADR 0018](../adr/0018-stale-timestamps-flagged-not-clamped.md)).
5. Insert with `on conflict (event_id) do nothing`.
6. Update `kit_progress` from `step_view` and `step_complete` in the same transaction.

## Not events

Facilitator notes, quiz responses and exit cards are adult-entered rows in their own tables (`DATA-MODEL.md` section 5), not events.

## Changing the catalog

Adding a type or an optional field: bump `catalog_version`, regenerate the doc, update the consent appendix if the new data is a new kind of information. Removing or renaming: never; mark deprecated and stop emitting.
