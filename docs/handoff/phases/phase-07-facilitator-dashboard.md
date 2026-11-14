# Phase 7: Facilitator dashboard

**Goal.** What the adult in the room needs during a session: who is where, who is stuck, and a fast way to record observations on the same step IDs as the event data.

## Exit criteria

- [ ] Facilitator can run a full session from a phone or laptop
- [ ] Observation notes and quiz results land in the database tied to kits and steps

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p7-class-view` | P0 | task | Class dashboard: kits, current step, progress, last active | `p5-progress`, `p3-session-controls` | adult-ui |
| `p7-live-stuck` | P0 | task | Live stuck alerts | `p7-class-view`, `p5-stuck` | adult-ui |
| `p7-notes` | P0 | task | Facilitator observation form | `p7-class-view` | adult-ui, data |
| `p7-quiz` | P1 | task | Pre/post quiz and exit card entry | `p7-class-view`, `p4-schema` | adult-ui, data |
| `p7-guide` | P2 | task | Facilitator view of steps with answer keys and common fixes | `p5-step` | adult-ui, content |
| `p7-e2e` | P1 | task | End-to-end test: run a session as facilitator | `p7-live-stuck`, `p7-notes` | tests |

### `p7-class-view` Class dashboard: kits, current step, progress, last active

Grid of kits showing current step, progress bar, last activity and logging state. Kits with logging off show 'not recorded' rather than stale data.

Acceptance:

- Usable on a phone held in one hand
- Reflects a kit's progress within 10 seconds

### `p7-live-stuck` Live stuck alerts

Kits that pressed 'I'm stuck' rise to the top with step and reason; facilitator can mark 'helping' and the kit sees that help is coming. Use polling or server-sent events; no websockets dependency. For kits with logging off, stuck alerts still work in the moment but are held in memory only and not persisted.

Acceptance:

- Alert appears within 5 seconds
- With logging off, an alert is shown live and no row is stored (covered by the invariant test)

### `p7-notes` Facilitator observation form

Three taps to record: kit (optional), step (defaults to the kit's current step), issue type (wording, video, diagram, hardware, sequencing, other), severity 1 to 3, optional short note. Guidance text reminds facilitators not to write children's names.

Acceptance:

- A note can be saved in under 15 seconds on a phone
- Notes are stored with step_id and content_version

### `p7-quiz` Pre/post quiz and exit card entry

Quiz questions are defined in kit content. Staff or facilitators enter paper results in a grid: kit, participant letter (A/B/C), phase (pre/post), answer per question; plus exit-card fun rating per module. Participant letters are assigned on paper in class and are the only per-child identifier in the system. Only stored when logging is enabled for the kit.

Acceptance:

- Entry for a class of 30 takes under 15 minutes
- Same question ids across pre and post so gain can be computed

### `p7-guide` Facilitator view of steps with answer keys and common fixes

Adults can open any step with facilitator_notes and checkpoint answers shown.

Acceptance:

- Student sessions can never see facilitator notes (authz matrix updated)

### `p7-e2e` End-to-end test: run a session as facilitator

Playwright with two browser contexts: a student device and a facilitator. Open session, join, get stuck, facilitator sees it, records a note, closes session.

Acceptance:

- Scenario passes in CI
