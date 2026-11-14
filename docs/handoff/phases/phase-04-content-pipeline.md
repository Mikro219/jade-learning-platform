# Phase 4: Content pipeline

**Goal.** Modules live as Markdown in the repo, with permanent step IDs and enforced versioning, so every data point can be tied to the exact wording a group saw.

## Exit criteria

- [ ] Sample kit content renders from Markdown
- [ ] CI rejects a changed step whose version was not bumped
- [ ] Given has a written authoring guide and a preview URL

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p4-schema` | P0 | task | Content format and validation schema | `p1-scaffold` | content |
| `p4-loader` | P0 | task | Build-time content loader and sanitised Markdown rendering | `p4-schema` | content |
| `p4-lock` | P0 | task | Content lint and lockfile: unique permanent IDs and enforced version bumps | `p4-loader` | content, ci |
| `p4-registry` | P1 | task | Sync content registry to the database on deploy | `p4-lock`, `p2-schema-core` | content, db |
| `p4-sample` | P0 | task | Placeholder kit content for development and tests | `p4-schema` | content |
| `p4-video` | P1 | task | Video pipeline: transcode script, storage layout, same-origin serving with entitlement check | `p4-loader`, `p1-docker` | content, infra |
| `p4-shortlinks` | P1 | task | Stable step short links and QR generation for print | `p4-loader` | content, tooling |
| `p4-print` | P2 | task | Print stylesheet and PDF export of a module from the same source | `p4-shortlinks` | content, tooling |
| `p4-authoring-guide` | P1 | task | Authoring guide for Given and per-branch preview | `p4-lock` | docs, content |
| `p4-real-content` | P1 | task | Load the real arm-kit modules | `p4-lock`, `p0-open-decisions` | content, human |

### `p4-schema` Content format and validation schema

content/<kit>/kit.yaml, content/<kit>/<module>/module.yaml, content/<kit>/<module>/<step>.md with frontmatter (id, version, title, track, expected_seconds, video, checkpoints[], facilitator_notes, stuck_reasons override). Step id format <kit>.<module>.<step>, permanent. zod schema validates everything at build time. Document in docs/content-format.md.

Acceptance:

- Invalid frontmatter fails the build with file and field named
- Checkpoint definitions support text and image options
- Format doc includes one complete example step

### `p4-loader` Build-time content loader and sanitised Markdown rendering

Load all content into a typed index at build time. Render Markdown to HTML with a strict allowlist (no raw HTML, no external images or links in student view). Images are processed to responsive sizes and served from the app origin.

Acceptance:

- Typed API: getKit, getModule, getStep(stepId, version?)
- Rendering strips script, iframe and external URLs (tested)
- Images get width/height to avoid layout shift

### `p4-lock` Content lint and lockfile: unique permanent IDs and enforced version bumps

content.lock.json maps step_id@version to a content hash. `pnpm content:lint` fails if an existing id@version's hash changed (must bump version), if an id disappeared (must be marked retired, never reused), or if ids collide. `pnpm content:lock` updates the lockfile. Runs in CI. Old versions stay retrievable from git history via the hash for analytics labels.

Acceptance:

- Editing a step without bumping version fails CI with a clear message
- Reusing a retired id fails CI
- Typo-only fixes can be marked `minor: true` to keep the same version, and that is recorded in the lockfile

### `p4-registry` Sync content registry to the database on deploy

On deploy, upsert content_steps (step_id, version, module, track, title, expected_seconds, hash, first_published_at) so analytics can join events to step metadata without reading the repo. Never delete rows.

Acceptance:

- Deploying a version bump adds a row and keeps the old one
- Registry sync is idempotent

### `p4-sample` Placeholder kit content for development and tests

A clearly fake kit ('demo') with 2 modules of 3 steps each, both tracks on one module, one checkpoint, one short placeholder video and one image. Used by tests and staging until real arm-kit content arrives. Do not invent real arm-kit teaching content.

Acceptance:

- Demo kit exercises every content feature
- All e2e tests run against the demo kit

### `p4-video` Video pipeline: transcode script, storage layout, same-origin serving with entitlement check

`pnpm video:prepare <file>` runs ffmpeg to H.264/AAC MP4 at 720p with faststart plus a poster image. Files live on a volume and are served by Caddy from /media with Range support. The app issues short-lived signed URLs only to sessions entitled to the kit. Same origin means one domain to allowlist at schools.

Acceptance:

- Seeking works on Chromebook Chrome and iPad Safari
- Unsigned or expired media URLs return 403
- Video files are not in git; README documents where they live and how they are backed up

### `p4-shortlinks` Stable step short links and QR generation for print

/s/<step_id> redirects to the current version of the step and marks entry=qr. `pnpm content:qr` writes one SVG QR per step for Kai's print layout. The QR never changes when a step's version changes.

Acceptance:

- Short link survives a version bump
- QR SVGs regenerate deterministically

### `p4-print` Print stylesheet and PDF export of a module from the same source

A print view per module (both tracks) with step QR codes, exported to PDF with Playwright. Keeps printed guide and web steps from drifting apart.

Acceptance:

- PDF for the demo module is paginated without cut-off images
- Each printed step shows its QR and step id

### `p4-authoring-guide` Authoring guide for Given and per-branch preview

docs/content-authoring.md written for a non-developer: how to edit a step in the GitHub web editor, what version bumps mean, how to add an image, how to see a preview. CI posts a preview link or the staging URL on content pull requests.

Acceptance:

- Guide has screenshots or exact click paths
- A content-only pull request can be merged without touching code

### `p4-real-content` Load the real arm-kit modules

HUMAN-GATED: needs Given's module text, images and videos. The agent may convert supplied drafts to the content format and run lint, but must not write teaching content itself.

Acceptance:

- All modules for Pilot 1 pass content lint
- Expected time is set on every step
- Given has reviewed the preview
