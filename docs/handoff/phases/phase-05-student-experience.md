# Phase 5: Student experience

**Goal.** The step player an 8 to 10 year old group uses on a shared tablet: read, watch, build, check, ask for help, move on. It must survive flaky Wi-Fi.

## Exit criteria

- [ ] A group can join, complete a demo module end to end, close the tablet and resume
- [ ] Steps already opened remain usable offline
- [ ] Usability pass done on a Chromebook and an iPad

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p5-home` | P0 | task | Student home: module list, progress, resume | `p3-join`, `p4-loader`, `p4-sample` | student-ui |
| `p5-step` | P0 | task | Step player: text, images, video, navigation, track switch | `p5-home` | student-ui |
| `p5-checkpoint` | P0 | task | Checkpoint questions | `p5-step` | student-ui |
| `p5-stuck` | P0 | task | 'I'm stuck' button with preset reasons and resolution | `p5-step` | student-ui |
| `p5-progress` | P0 | task | Progress persistence: device always, server only when logging is enabled | `p5-step`, `p3-consent-flag` | student-ui, privacy |
| `p5-entitlement` | P2 | task | Entitlement gating for core and add-on content | `p5-home` | student-ui, codes |
| `p5-pwa` | P1 | task | Offline support: service worker, app shell and content precache | `p5-step` | student-ui, offline |
| `p5-a11y` | P1 | task | Accessibility and kid-usability pass on real devices | `p5-checkpoint`, `p5-stuck` | student-ui, a11y |
| `p5-e2e` | P0 | task | End-to-end test: join, complete a module, resume | `p5-checkpoint`, `p5-stuck`, `p5-progress` | tests |

### `p5-home` Student home: module list, progress, resume

After join, show modules as large cards with progress and a single obvious Continue button. Locked content (not entitled) is shown as locked, not hidden.

Acceptance:

- Continue goes to the first incomplete step
- Usable with touch only and with keyboard only

### `p5-step` Step player: text, images, video, navigation, track switch

One step per screen. Video at top when present, then instructions, then a large Done button. Back and Next. Track switch (beginner/advanced) where the step has both. No autoplay with sound.

Acceptance:

- Works at 360px width and on 1366x768
- Next is disabled until Done or checkpoint is satisfied; facilitator override exists
- Track switch keeps position in the module

### `p5-checkpoint` Checkpoint questions

Multiple choice with text or picture options, immediate feedback, retry allowed. First attempt and attempt count are what analytics needs; do not show scores or leaderboards.

Acceptance:

- Options are shuffled per render but recorded by stable option id
- Wrong answer shows the hint from content, not just 'try again'

### `p5-stuck` 'I'm stuck' button with preset reasons and resolution

Always-visible button on every step. Opens preset reasons from content (defaults: can't find the part, it won't fit, don't understand, it doesn't work). After choosing, the step shows a 'We fixed it!' button. No free text from students anywhere.

Acceptance:

- Stuck state is visible to the facilitator view (Phase 7 consumes it)
- Resolution records how it ended: fixed, skipped, facilitator helped

### `p5-progress` Progress persistence: device always, server only when logging is enabled

Progress is always kept in localStorage so a group can resume. It is written to the server (kit_progress) only when the kit's logging_enabled is on. In no-log mode the server stores nothing about activity.

Acceptance:

- With logging off, completing steps creates zero rows server-side (test)
- With logging on, a second device joining the same kit resumes at the same step

### `p5-entitlement` Entitlement gating for core and add-on content

Content sections map to entitlements on the kit's code. Locked modules show a friendly locked card.

Acceptance:

- A kit without the add-on entitlement cannot open add-on steps by URL

### `p5-pwa` Offline support: service worker, app shell and content precache

Installable PWA. Precache app shell and the current module's text and images on join. Videos stream when online; optional 'download this session's videos' button for facilitators to run before class. Show a small offline indicator, never a blocking error.

Acceptance:

- With the network disabled after join, the current module's steps open and Done works
- A new deploy updates the service worker without trapping users on an old version

### `p5-a11y` Accessibility and kid-usability pass on real devices

Automated axe checks in e2e plus a manual pass on a Chromebook and an iPad: focus order, contrast, reduced motion, text resize to 200%, reading level of UI strings (short words, no jargon).

Acceptance:

- axe reports no serious or critical issues on student pages
- Manual checklist committed with findings filed as beads

### `p5-e2e` End-to-end test: join, complete a module, resume

Playwright scenario on Chromium and WebKit covering join, steps, checkpoint (wrong then right), stuck and fixed, close and resume.

Acceptance:

- Scenario passes on both browsers in CI
