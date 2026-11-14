# Phase 8: Analytics and the redesign loop

**Goal.** Turn pilot data into a ranked list of steps to fix. Only verification and export are needed before Pilot 1; the dashboards can land while the pilot runs.

## Exit criteria

- [ ] Before launch: data-quality report and export work on staging data
- [ ] Before February analysis: heatmap and step detail pages work on Pilot 1 data

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p8-views` | P1 | task | Step metrics as SQL views | `p6-table`, `p4-registry` | analytics, db |
| `p8-quality` | P0 | task | Data-quality report for pilot days | `p6-ingest` | analytics |
| `p8-export` | P0 | task | Staff export to CSV and JSON | `p8-quality` | analytics |
| `p8-heatmap` | P2 | task | Step heatmap ranked by friction | `p8-views` | analytics, staff-ui, post-launch-ok |
| `p8-step-detail` | P2 | task | Step detail page | `p8-views`, `p6-video-events` | analytics, staff-ui, post-launch-ok |
| `p8-outcomes` | P2 | task | Learning outcomes: pre/post gain | `p7-quiz` | analytics, staff-ui, post-launch-ok |
| `p8-compare` | P3 | task | Version comparison for the same step | `p8-step-detail` | analytics, staff-ui, post-launch-ok |

### `p8-views` Step metrics as SQL views

Views per step x version x track x class: kits viewed, kits completed, median and p90 active seconds, overrun ratio against expected time, kits stuck, stuck reasons, kits rewatching, first-attempt miss rate per checkpoint, note count and severity sum. Report counts alongside every rate (4 of 13 kits), because a pilot has 12 to 15 kits and percentages alone mislead.

Acceptance:

- Views are covered by tests with fixture events and hand-computed expected values
- Every rate column has matching numerator and denominator columns

### `p8-quality` Data-quality report for pilot days

Staff page per class session: events per kit, time of first and last event, gaps over 10 minutes, flagged timestamps, kits with logging off, app versions seen. Run after every session to catch a broken tablet or a missed consent toggle the same day.

Acceptance:

- A kit that sent nothing during a session is highlighted
- Report loads in under 3 seconds for a 30-kit class

### `p8-export` Staff export to CSV and JSON

Staff-only export of events, notes, quiz results and step metrics per class or per pilot, for analysis outside the app and for the evidence package. Exports contain kit ids, never adult emails.

Acceptance:

- Export is staff-only and audited
- Row counts in the export match the database

### `p8-heatmap` Step heatmap ranked by friction

Modules by steps grid coloured by friction rank, filterable by pilot, version and track. Friction is a rank for sorting, not a score to report. Cells show n of N.

Acceptance:

- Top 10 friction steps list matches a hand-check on fixture data

### `p8-step-detail` Step detail page

Funnel, active-time distribution, stuck reasons and time-to-unstuck, video replay histogram by second, checkpoint answer spread, facilitator notes.

Acceptance:

- Each chart states its n
- Replay histogram highlights the most replayed 10 seconds

### `p8-outcomes` Learning outcomes: pre/post gain

Per question and per module: pre correct, post correct, gain, with counts.

Acceptance:

- Handles participants missing a pre or post entry without crashing or miscounting

### `p8-compare` Version comparison for the same step

Side-by-side metrics for two versions of a step (Pilot 1 v1 against Pilot 2 v2). Needed in March.

Acceptance:

- Shows both versions' counts and the difference, with a small-n warning
