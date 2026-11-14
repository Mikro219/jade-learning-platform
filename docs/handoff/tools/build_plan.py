#!/usr/bin/env python3
"""Single source of truth for the JADE platform build plan.

Generates:
  phases/phase-NN-<slug>.md   human-readable phase files
  beads/plan.json             graph plan for `bd create --graph`

Run:  python3 tools/build_plan.py
Edit the PHASES list below, re-run, and both outputs stay in sync.
The script fails if a dependency key is unknown or the graph has a cycle.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Task tuple: key, title, type, priority, labels, deps, description, acceptance[]
# labels: "human" = a person must do it (agent must not), "post-launch-ok" =
# may ship after Pilot 1 starts, "post-pilot" = not needed until after go/no-go.

PHASES = [
    {
        "n": 0, "slug": "architecture-lock", "title": "Architecture lock",
        "goal": "Freeze the decisions the build depends on, and start the slow human-side items (host, school IT, consent wording) on day one because they have lead times the code does not.",
        "exit": [
            "ADRs committed under docs/adr/ and referenced from CLAUDE.md",
            "Threat model and data-flow doc committed",
            "Host chosen, domain bought, pilot-site IT contacted, consent wording under review (human beads closed or explicitly deferred with a date)",
        ],
        "tasks": [
            ("p0-adr", "Commit ADRs from the handoff decisions", "task", 0, ["docs"], [],
             "Turn each ADR in docs/handoff/DECISIONS.md into its own file under docs/adr/NNNN-title.md (status: accepted). Do not change the decisions. If one looks wrong, file a `decision` bead and stop instead of silently deviating.",
             ["One file per ADR, numbered, each with Context / Decision / Consequences",
              "docs/adr/README.md indexes them",
              "CLAUDE.md links to docs/adr/ and docs/handoff/ARCHITECTURE.md"]),
            ("p0-threat", "Write threat model and data-flow document", "task", 1, ["docs", "security"], ["p0-adr"],
             "Write docs/threat-model.md: actors (student device, facilitator, staff, outsider on school Wi-Fi, outsider on internet), assets (kit codes, code pepper, adult credentials, event data), trust boundaries, and the abuse cases listed in ARCHITECTURE.md section 9. Include a data-flow diagram (Mermaid).",
             ["Every abuse case has a named mitigation and the phase that implements it",
              "Data-flow diagram shows every place adult PII and kit-level data is stored"]),
            ("p0-open-decisions", "HUMAN: answer the open product questions", "decision", 0, ["human"], [],
             "Mike/Given/Kai to answer the questions in docs/handoff/DECISIONS.md section 'Open questions': kit name and code prefix, module and step outline for the arm kit, whether the arm has any networked electronics, device availability at the pilot site, retention period. Record answers in docs/adr/ and close this bead.",
             ["Kit slug and 3-letter code prefix recorded",
              "Module list with step counts recorded (or a date when Given will deliver it)",
              "Explicit yes/no on networked electronics and AI assistant for the arm kit"]),
            ("p0-host", "HUMAN: choose Canadian host, create account, buy domain", "task", 0, ["human", "infra"], [],
             "Pick a VM provider with a Canadian region (see DECISIONS.md ADR-04 for candidates), create the account with billing, and register the domain. Give the agent: provider name, region, domain, and how it will receive SSH/API access (never paste secrets into a bead).",
             ["Provider and region recorded in docs/adr/0004",
              "Domain registered and DNS manageable",
              "Access method for deploys agreed"]),
            ("p0-school-it", "HUMAN: contact pilot-site IT about devices and network", "task", 0, ["human", "pilot"], [],
             "Ask the pilot site: which devices and how many (Chromebook / iPad / other), browser versions, whether new domains must be allowlisted and how long that takes, whether video streaming is throttled, and whether devices keep cookies between sessions (managed Chromebooks often wipe on sign-out).",
             ["Device type, count and browser recorded",
              "Allowlist process and lead time recorded",
              "Cookie/session persistence behaviour on the school devices recorded"]),
            ("p0-consent", "HUMAN: update consent form and research application for the platform", "task", 0, ["human", "privacy", "pilot"], [],
             "The consent form and school board application were written before the pivot and before the web platform existed. They must describe what the platform logs (see docs/handoff/EVENTS.md and PRIVACY.md) and the opt-out behaviour (no-log mode). Phase 9 produces a plain-language appendix to attach.",
             ["Consent form text covers the web platform, kit-level logging and deletion on request",
              "School board / research reviewer has the event list appendix"]),
        ],
    },
    {
        "n": 1, "slug": "foundation", "title": "Foundation and walking skeleton",
        "goal": "A deployable empty app: repo, CI, database, container image, and a live staging URL. Everything after this ships to staging on every merge, so deploy problems surface in week one instead of the week before the pilot.",
        "exit": [
            "`pnpm dev`, `pnpm test`, `pnpm e2e` work from a clean clone",
            "CI is green and required on main",
            "Staging URL serves /healthz over HTTPS from a Canadian region",
        ],
        "tasks": [
            ("p1-scaffold", "Scaffold SvelteKit app with TypeScript strict, lint, unit and e2e test runners", "task", 0, ["foundation"], ["p0-adr"],
             "SvelteKit with adapter-node, TypeScript strict, pnpm, ESLint + Prettier, Vitest, Playwright. Use the current Node LTS and pin it in .nvmrc and the Dockerfile. Folder layout per ARCHITECTURE.md section 4 (src/lib/server/{auth,codes,content,events,analytics}, src/routes/{(student),(adult),(staff),api}).",
             ["`pnpm lint`, `pnpm check`, `pnpm test`, `pnpm e2e` all pass on an empty app",
              "Module boundaries exist as folders with an index.ts each",
              "README has setup steps that work from a clean clone"]),
            ("p1-config", "Typed environment config and secrets handling", "task", 0, ["foundation", "security"], ["p1-scaffold"],
             "Single config module that parses process.env with zod at boot and fails fast. .env.example documents every variable. Secrets (CODE_PEPPER, SESSION_SECRET, DATABASE_URL) never have defaults outside test.",
             ["App refuses to start with a clear message when a required variable is missing",
              ".env.example is complete; .env is gitignored",
              "No secret has a production default"]),
            ("p1-db", "PostgreSQL via Docker Compose, Drizzle, migration tooling, test database harness", "task", 0, ["foundation", "db"], ["p1-scaffold"],
             "compose.dev.yml with Postgres 16. Drizzle ORM with SQL migrations checked in. Test harness that gives each test file an isolated schema or transaction rollback so tests run in parallel.",
             ["`pnpm db:migrate` and `pnpm db:reset` work",
              "A sample migration and a sample integration test pass in CI",
              "Migrations are forward-only and run automatically on deploy"]),
            ("p1-observability", "Health endpoints, structured logs without IPs, request IDs", "task", 1, ["foundation", "privacy"], ["p1-config"],
             "/healthz (process up) and /readyz (DB reachable, migrations current). JSON logs with request id, route, status, duration. Never log IP addresses, cookies, kit codes, join codes or request bodies.",
             ["/readyz fails when the DB is down",
              "A test asserts log lines contain no IP, cookie or code values",
              "Error responses carry the request id"]),
            ("p1-ui-shell", "Base layout, design tokens, kid-friendly accessibility baseline", "task", 1, ["foundation", "ui"], ["p1-scaffold"],
             "Shared layout and CSS tokens. Body text at least 18px on student pages, tap targets at least 48px, WCAG AA contrast, system font stack (no third-party font requests), reduced-motion respected. Three route groups with distinct shells: student, adult, staff.",
             ["No network request leaves the app origin on any page (Playwright asserts this)",
              "Student shell passes an automated axe check",
              "Layout holds at 360px wide and at 1366x768 (Chromebook)"]),
            ("p1-ci", "CI pipeline: lint, typecheck, unit, integration, e2e, image build", "task", 0, ["foundation", "ci"], ["p1-db"],
             "GitHub Actions workflow on pull request and main. Postgres service container for integration tests. Playwright with Chromium and WebKit (iPad Safari stand-in). Cache pnpm. Fail on lint warnings.",
             ["Workflow runs in under 10 minutes",
              "Main branch is protected and requires the workflow",
              "Playwright report is uploaded on failure"]),
            ("p1-docker", "Production Dockerfile and compose.prod.yml (app, postgres, caddy)", "task", 0, ["foundation", "infra"], ["p1-db", "p1-observability"],
             "Multi-stage Dockerfile, non-root user, healthcheck. compose.prod.yml with app, postgres (named volume), and Caddy as the only public service (automatic TLS, compression, static /media with Range support, access log disabled or IP-stripped). App and DB are not exposed on the host.",
             ["`docker compose -f compose.prod.yml up` serves the app locally over Caddy",
              "Image runs as non-root and is under 300 MB",
              "Only ports 80 and 443 are published"]),
            ("p1-staging", "Provision staging VM and deploy from CI on every merge to main", "task", 0, ["infra", "deploy"], ["p1-docker", "p1-ci", "p0-host"],
             "Staging VM in the chosen Canadian region. Firewall (22 from deploy source only, 80, 443), non-root deploy user, Docker. CI job: build image, push to registry, SSH deploy, run migrations, health-check gate. Staging shows a visible STAGING banner and uses its own secrets.",
             ["Merge to main results in a new version live on staging without manual steps",
              "A failed health check leaves the previous version running",
              "Staging URL recorded in README"]),
        ],
    },
    {
        "n": 2, "slug": "data-model-and-kit-codes", "title": "Data model and kit codes",
        "goal": "The tables everything hangs off, and the kit code lifecycle: generate, print, redeem once, revoke.",
        "exit": [
            "Core schema migrated on staging",
            "A batch of codes can be generated, printed as cards, and redeemed exactly once",
            "Plain codes exist only on the printed sheet and the packing CSV, never in the database",
        ],
        "tasks": [
            ("p2-schema-core", "Core schema: products, kits, code batches, kit codes, users, sessions, classes, class kits, device sessions, audit log", "task", 0, ["db"], ["p1-db"],
             "Implement the tables in docs/handoff/DATA-MODEL.md sections 1 to 3 as Drizzle schema plus SQL migrations, with the constraints and indexes listed there. Kits are product-agnostic: nothing in the schema names a specific kit.",
             ["Migrations apply cleanly on an empty database and on staging",
              "Constraints from DATA-MODEL.md are enforced (tests insert violating rows and expect failure)",
              "No column stores a plain kit code or plain join-session token"]),
            ("p2-code-lib", "Kit code library: generate, normalise, validate, HMAC", "task", 0, ["codes", "security"], ["p1-config"],
             "Format PREFIX-XXXX-XXXX-C: 3-letter product prefix, 8 random Crockford Base32 characters from a CSPRNG, 1 check character. Normalise input (case, spaces, dashes, O to 0, I and L to 1). Lookup key is HMAC-SHA256(CODE_PEPPER, normalised code). Plain SHA-256 is not acceptable: 40 bits of entropy is brute-forceable from a leaked table.",
             ["Property tests: generate then validate round-trips; single-character typos are rejected by the check character",
              "Normalisation accepts lower case, missing dashes and O/I/L confusions",
              "HMAC uses the pepper from config and constant-time comparison"]),
            ("p2-redeem", "Redemption service: single use, transactional, rate limited, audited", "task", 0, ["codes", "security"], ["p2-schema-core", "p2-code-lib"],
             "redeemCode(user, code, classId?) in one transaction with row lock: unused becomes redeemed, kit attached to class. Reject revoked and already-redeemed codes with distinct, non-leaky messages. Rate limit per account and per IP (IP held in memory only). Write an audit row.",
             ["Concurrent redemption of the same code succeeds exactly once (test with parallel transactions)",
              "Ten failed attempts in an hour locks further attempts for that account",
              "Audit log records who redeemed which kit and when, never the code"]),
            ("p2-code-cli", "Batch generator CLI with printable code cards and packing CSV", "task", 1, ["codes", "tooling"], ["p2-schema-core", "p2-code-lib"],
             "`pnpm codes:generate --product <slug> --batch <label> --count <n>` creates kits and code rows, and writes two files outside the repo: packing CSV (kit number, code) and a printable A4/Letter sheet of code cards with the code in large type plus a QR that opens /redeem?code=... The plain codes are shown once and never stored.",
             ["Running the CLI twice with the same batch label fails instead of duplicating",
              "Printed sheet is legible in greyscale and each QR scans on a phone",
              "Output directory is gitignored and the CLI warns that the files are the only copy"]),
            ("p2-staff-codes", "Staff screen: batches, code status, revoke and reissue, move kit between classes", "task", 2, ["codes", "staff-ui"], ["p2-redeem", "p3-adult-auth"],
             "Staff-only pages listing batches and per-kit status. Actions: revoke a code, reissue a new code for the same kit (prints once), detach a kit from a class and attach to another keeping its kit id so history carries across pilots.",
             ["Non-staff users get 404 on every staff route",
              "Reissue keeps kit_id and invalidates the old code",
              "Every action writes an audit row"]),
            ("p2-seed", "Development seed data", "task", 2, ["tooling"], ["p2-schema-core"],
             "`pnpm db:seed` creates a demo product, a batch of 15 kits with known dev codes, a staff user, a facilitator, and a class. Dev-only; refuses to run when NODE_ENV=production.",
             ["Fresh clone to a usable local app in under 5 minutes following the README",
              "Seed refuses to run in production"]),
        ],
    },
    {
        "n": 3, "slug": "accounts-classes-sessions", "title": "Accounts, classes and student sessions",
        "goal": "Adults hold accounts and own classes. Students never have accounts: a tablet joins a class with a short code and is bound to one kit.",
        "exit": [
            "A facilitator can sign up with a kit code, create a class, redeem kits, open a session and see a join code",
            "A student device can join, pick a kit, and stay joined across page reloads",
            "Authorization matrix tests pass",
        ],
        "tasks": [
            ("p3-adult-auth", "Adult accounts: code-gated signup, login, sessions, staff role", "task", 0, ["auth", "security"], ["p2-redeem"],
             "Email + password (argon2id). Signup requires a valid unused kit code or a staff invite, so there is no open registration and no email service in v1. Server-side sessions in Postgres, httpOnly + Secure + SameSite=Lax cookie, rotation on login, idle and absolute expiry. Roles: adult, staff. Password reset is a staff action in v1 (generates a one-time reset link shown to staff).",
             ["Signup without a valid code or invite is impossible",
              "Login is rate limited and returns the same message for unknown email and wrong password",
              "Session cookie flags verified by test; logout invalidates server-side"]),
            ("p3-invites", "Staff invites for facilitators", "task", 1, ["auth", "staff-ui"], ["p3-adult-auth"],
             "Staff create a single-use, expiring invite link to hand to a facilitator or teacher in person or over Discord. Accepting it creates an adult account without consuming a kit code.",
             ["Invite works once and expires after 7 days",
              "Invite token is stored hashed"]),
            ("p3-classes", "Classes: create, redeem kits into a class, list kits", "task", 0, ["classes", "adult-ui"], ["p3-adult-auth"],
             "Adult creates a class (name, kind: classroom / camp / home). Redeem by typing a code or opening the QR link while signed in. Class page lists kits with their display number.",
             ["A user only ever sees their own classes",
              "Redeeming 15 codes in a row takes under 2 minutes with the QR flow",
              "Kit display numbers are stable within a class"]),
            ("p3-join", "Student join flow: join code, kit picker, device session", "task", 0, ["auth", "student-ui", "security"], ["p3-classes", "p1-ui-shell"],
             "Facilitator opens a session, which shows a 6-character join code (same alphabet as kit codes) valid only while the session is open. Student device enters the code, taps its kit number, and receives a device-session cookie (random token, stored hashed, bound to class + kit). Rate limit join attempts. If p0-school-it reports that devices wipe cookies, re-joining must take under 15 seconds.",
             ["Join code stops working when the facilitator closes the session",
              "A device session can only read and write for its own kit (tested)",
              "Join attempts are rate limited; join codes are not guessable within the limit"]),
            ("p3-session-controls", "Facilitator session controls: open, close, rotate code, reset a kit's devices", "task", 1, ["classes", "adult-ui"], ["p3-join"],
             "Controls on the class page. Reset revokes all device sessions for one kit (for when a group joined as the wrong kit).",
             ["Rotating the code does not disconnect devices already joined",
              "Reset forces the kit's devices back to the join screen on next request"]),
            ("p3-consent-flag", "Per-kit logging switch with consent confirmation", "task", 0, ["privacy", "adult-ui"], ["p3-classes"],
             "Each kit in a class has logging_enabled, default off. Facilitator turns it on only after confirming consent is in hand for every child in that group; the confirmation (who, when) is stored. Turning it off stops collection immediately. This flag is the single switch Phase 6 ingestion checks.",
             ["Default is off for every newly redeemed kit",
              "Toggle writes an audit row with user and time",
              "UI states plainly what is and is not recorded in each mode"]),
            ("p3-authz-tests", "Authorization matrix tests", "task", 0, ["security", "tests"], ["p3-join", "p3-consent-flag"],
             "Table-driven tests over every route and API endpoint for five actors: anonymous, student device (own kit), student device (other kit), adult (other owner's class), staff. Add new routes to the matrix as later phases create them; CI fails if a route is missing from it.",
             ["Matrix covers 100% of routes (enforced by a test that enumerates the route manifest)",
              "No IDOR: other-kit and other-class access returns 404"]),
            ("p3-home-mode", "Home mode: parent redeems one code, device joins without a class code", "task", 3, ["post-pilot", "auth"], ["p3-join"],
             "Retail path. Parent account with a single kit; the parent's own browser session can open the student view directly. Not needed for either pilot.",
             ["Parent can reach the student view for their kit in two taps after login"]),
        ],
    },
    {
        "n": 4, "slug": "content-pipeline", "title": "Content pipeline",
        "goal": "Modules live as Markdown in the repo, with permanent step IDs and enforced versioning, so every data point can be tied to the exact wording a group saw.",
        "exit": [
            "Sample kit content renders from Markdown",
            "CI rejects a changed step whose version was not bumped",
            "Given has a written authoring guide and a preview URL",
        ],
        "tasks": [
            ("p4-schema", "Content format and validation schema", "task", 0, ["content"], ["p1-scaffold"],
             "content/<kit>/kit.yaml, content/<kit>/<module>/module.yaml, content/<kit>/<module>/<step>.md with frontmatter (id, version, title, track, expected_seconds, video, checkpoints[], facilitator_notes, stuck_reasons override). Step id format <kit>.<module>.<step>, permanent. zod schema validates everything at build time. Document in docs/content-format.md.",
             ["Invalid frontmatter fails the build with file and field named",
              "Checkpoint definitions support text and image options",
              "Format doc includes one complete example step"]),
            ("p4-loader", "Build-time content loader and sanitised Markdown rendering", "task", 0, ["content"], ["p4-schema"],
             "Load all content into a typed index at build time. Render Markdown to HTML with a strict allowlist (no raw HTML, no external images or links in student view). Images are processed to responsive sizes and served from the app origin.",
             ["Typed API: getKit, getModule, getStep(stepId, version?)",
              "Rendering strips script, iframe and external URLs (tested)",
              "Images get width/height to avoid layout shift"]),
            ("p4-lock", "Content lint and lockfile: unique permanent IDs and enforced version bumps", "task", 0, ["content", "ci"], ["p4-loader"],
             "content.lock.json maps step_id@version to a content hash. `pnpm content:lint` fails if an existing id@version's hash changed (must bump version), if an id disappeared (must be marked retired, never reused), or if ids collide. `pnpm content:lock` updates the lockfile. Runs in CI. Old versions stay retrievable from git history via the hash for analytics labels.",
             ["Editing a step without bumping version fails CI with a clear message",
              "Reusing a retired id fails CI",
              "Typo-only fixes can be marked `minor: true` to keep the same version, and that is recorded in the lockfile"]),
            ("p4-registry", "Sync content registry to the database on deploy", "task", 1, ["content", "db"], ["p4-lock", "p2-schema-core"],
             "On deploy, upsert content_steps (step_id, version, module, track, title, expected_seconds, hash, first_published_at) so analytics can join events to step metadata without reading the repo. Never delete rows.",
             ["Deploying a version bump adds a row and keeps the old one",
              "Registry sync is idempotent"]),
            ("p4-sample", "Placeholder kit content for development and tests", "task", 0, ["content"], ["p4-schema"],
             "A clearly fake kit ('demo') with 2 modules of 3 steps each, both tracks on one module, one checkpoint, one short placeholder video and one image. Used by tests and staging until real arm-kit content arrives. Do not invent real arm-kit teaching content.",
             ["Demo kit exercises every content feature",
              "All e2e tests run against the demo kit"]),
            ("p4-video", "Video pipeline: transcode script, storage layout, same-origin serving with entitlement check", "task", 1, ["content", "infra"], ["p4-loader", "p1-docker"],
             "`pnpm video:prepare <file>` runs ffmpeg to H.264/AAC MP4 at 720p with faststart plus a poster image. Files live on a volume and are served by Caddy from /media with Range support. The app issues short-lived signed URLs only to sessions entitled to the kit. Same origin means one domain to allowlist at schools.",
             ["Seeking works on Chromebook Chrome and iPad Safari",
              "Unsigned or expired media URLs return 403",
              "Video files are not in git; README documents where they live and how they are backed up"]),
            ("p4-shortlinks", "Stable step short links and QR generation for print", "task", 1, ["content", "tooling"], ["p4-loader"],
             "/s/<step_id> redirects to the current version of the step and marks entry=qr. `pnpm content:qr` writes one SVG QR per step for Kai's print layout. The QR never changes when a step's version changes.",
             ["Short link survives a version bump",
              "QR SVGs regenerate deterministically"]),
            ("p4-print", "Print stylesheet and PDF export of a module from the same source", "task", 2, ["content", "tooling"], ["p4-shortlinks"],
             "A print view per module (both tracks) with step QR codes, exported to PDF with Playwright. Keeps printed guide and web steps from drifting apart.",
             ["PDF for the demo module is paginated without cut-off images",
              "Each printed step shows its QR and step id"]),
            ("p4-authoring-guide", "Authoring guide for Given and per-branch preview", "task", 1, ["docs", "content"], ["p4-lock"],
             "docs/content-authoring.md written for a non-developer: how to edit a step in the GitHub web editor, what version bumps mean, how to add an image, how to see a preview. CI posts a preview link or the staging URL on content pull requests.",
             ["Guide has screenshots or exact click paths",
              "A content-only pull request can be merged without touching code"]),
            ("p4-real-content", "Load the real arm-kit modules", "task", 1, ["content", "human"], ["p4-lock", "p0-open-decisions"],
             "HUMAN-GATED: needs Given's module text, images and videos. The agent may convert supplied drafts to the content format and run lint, but must not write teaching content itself.",
             ["All modules for Pilot 1 pass content lint",
              "Expected time is set on every step",
              "Given has reviewed the preview"]),
        ],
    },
    {
        "n": 5, "slug": "student-experience", "title": "Student experience",
        "goal": "The step player an 8 to 10 year old group uses on a shared tablet: read, watch, build, check, ask for help, move on. It must survive flaky Wi-Fi.",
        "exit": [
            "A group can join, complete a demo module end to end, close the tablet and resume",
            "Steps already opened remain usable offline",
            "Usability pass done on a Chromebook and an iPad",
        ],
        "tasks": [
            ("p5-home", "Student home: module list, progress, resume", "task", 0, ["student-ui"], ["p3-join", "p4-loader", "p4-sample"],
             "After join, show modules as large cards with progress and a single obvious Continue button. Locked content (not entitled) is shown as locked, not hidden.",
             ["Continue goes to the first incomplete step",
              "Usable with touch only and with keyboard only"]),
            ("p5-step", "Step player: text, images, video, navigation, track switch", "task", 0, ["student-ui"], ["p5-home"],
             "One step per screen. Video at top when present, then instructions, then a large Done button. Back and Next. Track switch (beginner/advanced) where the step has both. No autoplay with sound.",
             ["Works at 360px width and on 1366x768",
              "Next is disabled until Done or checkpoint is satisfied; facilitator override exists",
              "Track switch keeps position in the module"]),
            ("p5-checkpoint", "Checkpoint questions", "task", 0, ["student-ui"], ["p5-step"],
             "Multiple choice with text or picture options, immediate feedback, retry allowed. First attempt and attempt count are what analytics needs; do not show scores or leaderboards.",
             ["Options are shuffled per render but recorded by stable option id",
              "Wrong answer shows the hint from content, not just 'try again'"]),
            ("p5-stuck", "'I'm stuck' button with preset reasons and resolution", "task", 0, ["student-ui"], ["p5-step"],
             "Always-visible button on every step. Opens preset reasons from content (defaults: can't find the part, it won't fit, don't understand, it doesn't work). After choosing, the step shows a 'We fixed it!' button. No free text from students anywhere.",
             ["Stuck state is visible to the facilitator view (Phase 7 consumes it)",
              "Resolution records how it ended: fixed, skipped, facilitator helped"]),
            ("p5-progress", "Progress persistence: device always, server only when logging is enabled", "task", 0, ["student-ui", "privacy"], ["p5-step", "p3-consent-flag"],
             "Progress is always kept in localStorage so a group can resume. It is written to the server (kit_progress) only when the kit's logging_enabled is on. In no-log mode the server stores nothing about activity.",
             ["With logging off, completing steps creates zero rows server-side (test)",
              "With logging on, a second device joining the same kit resumes at the same step"]),
            ("p5-entitlement", "Entitlement gating for core and add-on content", "task", 2, ["student-ui", "codes"], ["p5-home"],
             "Content sections map to entitlements on the kit's code. Locked modules show a friendly locked card.",
             ["A kit without the add-on entitlement cannot open add-on steps by URL"]),
            ("p5-pwa", "Offline support: service worker, app shell and content precache", "task", 1, ["student-ui", "offline"], ["p5-step"],
             "Installable PWA. Precache app shell and the current module's text and images on join. Videos stream when online; optional 'download this session's videos' button for facilitators to run before class. Show a small offline indicator, never a blocking error.",
             ["With the network disabled after join, the current module's steps open and Done works",
              "A new deploy updates the service worker without trapping users on an old version"]),
            ("p5-a11y", "Accessibility and kid-usability pass on real devices", "task", 1, ["student-ui", "a11y"], ["p5-checkpoint", "p5-stuck"],
             "Automated axe checks in e2e plus a manual pass on a Chromebook and an iPad: focus order, contrast, reduced motion, text resize to 200%, reading level of UI strings (short words, no jargon).",
             ["axe reports no serious or critical issues on student pages",
              "Manual checklist committed with findings filed as beads"]),
            ("p5-e2e", "End-to-end test: join, complete a module, resume", "task", 0, ["tests"], ["p5-checkpoint", "p5-stuck", "p5-progress"],
             "Playwright scenario on Chromium and WebKit covering join, steps, checkpoint (wrong then right), stuck and fixed, close and resume.",
             ["Scenario passes on both browsers in CI"]),
        ],
    },
    {
        "n": 6, "slug": "event-pipeline", "title": "Event pipeline",
        "goal": "Trustworthy data for redesigning the modules: every event validated, idempotent, correctly timed even when it was queued offline, and never stored without consent.",
        "exit": [
            "All catalog events flow from the demo kit to the database on staging",
            "Replaying a batch creates no duplicates",
            "The no-log invariant test passes",
        ],
        "tasks": [
            ("p6-catalog", "Event catalog as code, with generated documentation", "task", 0, ["events"], ["p1-scaffold"],
             "Implement docs/handoff/EVENTS.md as a zod discriminated union shared by client and server, with a catalog version. Generate docs/events.md from the code so the consent appendix is always accurate.",
             ["Unknown event types and extra fields are rejected",
              "Generated doc matches the code (CI checks it is up to date)"]),
            ("p6-table", "Events table, indexes and progress table", "task", 0, ["events", "db"], ["p2-schema-core"],
             "Tables from DATA-MODEL.md section 4: events (append-only, primary key event_id), kit_progress. Indexes for (class_id, kit_id, client_ts) and (step_id, content_version, type). No update or delete grants for the app role on events except through the deletion function added in Phase 9.",
             ["Insert with a duplicate event_id is a no-op",
              "App role cannot UPDATE events (tested)"]),
            ("p6-ingest", "Ingest endpoint: authenticated, validated, consent-gated, idempotent", "task", 0, ["events", "privacy", "security"], ["p6-catalog", "p6-table", "p3-join", "p3-consent-flag"],
             "POST /api/events accepts a batch (max 100 events, max 64 KB). Auth by device session; class and kit come from the session, never from the payload. If logging is off for the kit, return 204 and store nothing. Validate against the catalog, set received_at, insert with ON CONFLICT DO NOTHING. Clamp client timestamps that are in the future or older than 14 days and flag them.",
             ["Payload cannot write events for another kit (tested)",
              "Same batch posted three times yields one set of rows",
              "With logging off, zero rows are written and the response is indistinguishable in timing class"]),
            ("p6-client", "Client event queue: persistent, batched, retried", "task", 0, ["events", "offline"], ["p6-catalog", "p5-step"],
             "Queue in IndexedDB. Each event gets a UUIDv7, client_ts, a per-session sequence number and the app version. Flush every 10 seconds or 20 events, on visibilitychange and pagehide (sendBeacon/keepalive), with exponential backoff. Cap the queue (drop oldest heartbeats first, never stuck or checkpoint events). If the server says logging is off, stop queueing.",
             ["Events created offline are delivered after reconnect with original client_ts",
              "Queue survives a tab close and a browser restart",
              "No events are queued in no-log mode"]),
            ("p6-time", "Active-time measurement", "task", 0, ["events"], ["p6-client"],
             "Count time on a step only while the tab is visible and there was interaction (touch, key, scroll, video playing) in the last 60 seconds. Emit step_time deltas at flush and on leave. This replaces the vague 'time on screen', which over-counts every time a group walks away to build.",
             ["Leaving a step open and idle for 10 minutes records about 60 seconds, not 600",
              "Sum of deltas equals measured active time within 5%"]),
            ("p6-video-events", "Video instrumentation", "task", 1, ["events"], ["p6-client", "p4-video"],
             "Emit video_play, video_pause, video_seek (from, to), video_ended and watched ranges (merged intervals in seconds) so analytics can show which seconds get replayed.",
             ["Replaying 0:20 to 0:35 twice produces overlapping ranges that reconstruct the replay",
              "No event spam: at most one range update per 5 seconds"]),
            ("p6-instrument", "Instrument the student app with all catalog events", "task", 0, ["events"], ["p6-client", "p5-checkpoint", "p5-stuck", "p4-shortlinks"],
             "Wire step_view (with entry: nav, resume, qr), step_complete, stuck, stuck_resolved, checkpoint_answer, track_switch, session_start. Every event carries step_id, content_version and track from the content actually rendered.",
             ["e2e test asserts the exact event sequence for the scripted scenario",
              "content_version on events matches the rendered step"]),
            ("p6-nolog-invariant", "Privacy invariant test: no-log mode stores nothing", "task", 0, ["privacy", "tests"], ["p6-ingest", "p6-instrument", "p5-progress"],
             "A dedicated e2e test runs the full student scenario with logging off, then asserts row counts in events, kit_progress, notes and quiz tables are unchanged, and that app logs contain no kit activity. This test is the evidence behind the consent form's opt-out promise; it must never be skipped or weakened.",
             ["Test fails if any activity row is written with logging off",
              "Test is marked required in CI"]),
            ("p6-replay-tests", "Offline and replay robustness tests", "task", 1, ["tests", "offline"], ["p6-ingest", "p6-client"],
             "Tests for duplicate batches, out-of-order delivery, partial batch failure, clock skew of plus or minus one day, and an airplane-mode e2e run.",
             ["All cases leave the events table consistent and deduplicated"]),
        ],
    },
    {
        "n": 7, "slug": "facilitator-dashboard", "title": "Facilitator dashboard",
        "goal": "What the adult in the room needs during a session: who is where, who is stuck, and a fast way to record observations on the same step IDs as the event data.",
        "exit": [
            "Facilitator can run a full session from a phone or laptop",
            "Observation notes and quiz results land in the database tied to kits and steps",
        ],
        "tasks": [
            ("p7-class-view", "Class dashboard: kits, current step, progress, last active", "task", 0, ["adult-ui"], ["p5-progress", "p3-session-controls"],
             "Grid of kits showing current step, progress bar, last activity and logging state. Kits with logging off show 'not recorded' rather than stale data.",
             ["Usable on a phone held in one hand",
              "Reflects a kit's progress within 10 seconds"]),
            ("p7-live-stuck", "Live stuck alerts", "task", 0, ["adult-ui"], ["p7-class-view", "p5-stuck"],
             "Kits that pressed 'I'm stuck' rise to the top with step and reason; facilitator can mark 'helping' and the kit sees that help is coming. Use polling or server-sent events; no websockets dependency. For kits with logging off, stuck alerts still work in the moment but are held in memory only and not persisted.",
             ["Alert appears within 5 seconds",
              "With logging off, an alert is shown live and no row is stored (covered by the invariant test)"]),
            ("p7-notes", "Facilitator observation form", "task", 0, ["adult-ui", "data"], ["p7-class-view"],
             "Three taps to record: kit (optional), step (defaults to the kit's current step), issue type (wording, video, diagram, hardware, sequencing, other), severity 1 to 3, optional short note. Guidance text reminds facilitators not to write children's names.",
             ["A note can be saved in under 15 seconds on a phone",
              "Notes are stored with step_id and content_version"]),
            ("p7-quiz", "Pre/post quiz and exit card entry", "task", 1, ["adult-ui", "data"], ["p7-class-view", "p4-schema"],
             "Quiz questions are defined in kit content. Staff or facilitators enter paper results in a grid: kit, participant letter (A/B/C), phase (pre/post), answer per question; plus exit-card fun rating per module. Participant letters are assigned on paper in class and are the only per-child identifier in the system. Only stored when logging is enabled for the kit.",
             ["Entry for a class of 30 takes under 15 minutes",
              "Same question ids across pre and post so gain can be computed"]),
            ("p7-guide", "Facilitator view of steps with answer keys and common fixes", "task", 2, ["adult-ui", "content"], ["p5-step"],
             "Adults can open any step with facilitator_notes and checkpoint answers shown.",
             ["Student sessions can never see facilitator notes (authz matrix updated)"]),
            ("p7-e2e", "End-to-end test: run a session as facilitator", "task", 1, ["tests"], ["p7-live-stuck", "p7-notes"],
             "Playwright with two browser contexts: a student device and a facilitator. Open session, join, get stuck, facilitator sees it, records a note, closes session.",
             ["Scenario passes in CI"]),
        ],
    },
    {
        "n": 8, "slug": "analytics", "title": "Analytics and the redesign loop",
        "goal": "Turn pilot data into a ranked list of steps to fix. Only verification and export are needed before Pilot 1; the dashboards can land while the pilot runs.",
        "exit": [
            "Before launch: data-quality report and export work on staging data",
            "Before February analysis: heatmap and step detail pages work on Pilot 1 data",
        ],
        "tasks": [
            ("p8-views", "Step metrics as SQL views", "task", 1, ["analytics", "db"], ["p6-table", "p4-registry"],
             "Views per step x version x track x class: kits viewed, kits completed, median and p90 active seconds, overrun ratio against expected time, kits stuck, stuck reasons, kits rewatching, first-attempt miss rate per checkpoint, note count and severity sum. Report counts alongside every rate (4 of 13 kits), because a pilot has 12 to 15 kits and percentages alone mislead.",
             ["Views are covered by tests with fixture events and hand-computed expected values",
              "Every rate column has matching numerator and denominator columns"]),
            ("p8-quality", "Data-quality report for pilot days", "task", 0, ["analytics"], ["p6-ingest"],
             "Staff page per class session: events per kit, time of first and last event, gaps over 10 minutes, flagged timestamps, kits with logging off, app versions seen. Run after every session to catch a broken tablet or a missed consent toggle the same day.",
             ["A kit that sent nothing during a session is highlighted",
              "Report loads in under 3 seconds for a 30-kit class"]),
            ("p8-export", "Staff export to CSV and JSON", "task", 0, ["analytics"], ["p8-quality"],
             "Staff-only export of events, notes, quiz results and step metrics per class or per pilot, for analysis outside the app and for the evidence package. Exports contain kit ids, never adult emails.",
             ["Export is staff-only and audited",
              "Row counts in the export match the database"]),
            ("p8-heatmap", "Step heatmap ranked by friction", "task", 2, ["analytics", "staff-ui", "post-launch-ok"], ["p8-views"],
             "Modules by steps grid coloured by friction rank, filterable by pilot, version and track. Friction is a rank for sorting, not a score to report. Cells show n of N.",
             ["Top 10 friction steps list matches a hand-check on fixture data"]),
            ("p8-step-detail", "Step detail page", "task", 2, ["analytics", "staff-ui", "post-launch-ok"], ["p8-views", "p6-video-events"],
             "Funnel, active-time distribution, stuck reasons and time-to-unstuck, video replay histogram by second, checkpoint answer spread, facilitator notes.",
             ["Each chart states its n",
              "Replay histogram highlights the most replayed 10 seconds"]),
            ("p8-outcomes", "Learning outcomes: pre/post gain", "task", 2, ["analytics", "staff-ui", "post-launch-ok"], ["p7-quiz"],
             "Per question and per module: pre correct, post correct, gain, with counts.",
             ["Handles participants missing a pre or post entry without crashing or miscounting"]),
            ("p8-compare", "Version comparison for the same step", "task", 3, ["analytics", "staff-ui", "post-launch-ok"], ["p8-step-detail"],
             "Side-by-side metrics for two versions of a step (Pilot 1 v1 against Pilot 2 v2). Needed in March.",
             ["Shows both versions' counts and the difference, with a small-n warning"]),
        ],
    },
    {
        "n": 9, "slug": "privacy-security-hardening", "title": "Privacy, security and hardening",
        "goal": "Make the promises in the consent form true and testable, and make sure fifteen tablets streaming video in one room do not take the site down.",
        "exit": [
            "Deletion, retention and no-log behaviour are covered by tests",
            "Security headers and rate limits verified on staging",
            "Load test passed at twice the pilot size",
        ],
        "tasks": [
            ("p9-delete", "Kit data deletion", "task", 0, ["privacy"], ["p6-table", "p7-notes", "p7-quiz"],
             "Staff action: delete all activity data for a kit (events, progress, notes, quiz, exit cards) in one transaction. Record an audit row with counts only. This is how a parent withdrawal is honoured.",
             ["After deletion no table contains the kit's activity rows (test enumerates all tables with a kit_id column)",
              "Deletion is idempotent and audited"]),
            ("p9-retention", "Retention job", "task", 1, ["privacy"], ["p8-views", "p9-delete"],
             "Scheduled job that, after the configured period, replaces raw events with per-step aggregates. Period comes from config (default 12 months after class end, to be confirmed against the research approval). Supports dry run.",
             ["Dry run reports what would be removed",
              "Aggregates are preserved after raw rows are removed"]),
            ("p9-headers", "Security headers, cookies and CSRF", "task", 0, ["security"], ["p3-join"],
             "CSP default-src 'self' with no inline script, HSTS, Referrer-Policy no-referrer, Permissions-Policy denying camera/mic/geolocation (except camera on the adult QR-scan page if used), X-Content-Type-Options. CSRF protection on all state-changing requests.",
             ["Playwright asserts headers on every route group",
              "No CSP violations in the console during e2e runs"]),
            ("p9-ratelimit", "Rate limiting and lockout review", "task", 0, ["security"], ["p3-join", "p2-redeem", "p6-ingest"],
             "Review and test limits for login, signup, redeem, join and ingest. A whole classroom shares one public IP, so join and ingest limits are per device session or per class, not per IP. IPs are used in memory only and never written to disk.",
             ["30 devices joining within one minute from one IP all succeed",
              "Brute-forcing join codes from one device is cut off well before the expected number of guesses"]),
            ("p9-logs", "Log and PII audit", "task", 0, ["privacy", "security"], ["p1-observability", "p1-docker"],
             "Verify end to end on staging: Caddy stores no client IPs, app logs contain no emails, codes, tokens or bodies, database has no IP columns. Document log retention (14 days).",
             ["Grep of staging logs after a full e2e run finds no IPs, emails or codes",
              "Log retention configured and documented"]),
            ("p9-authz-sweep", "Abuse-case sweep against the threat model", "task", 1, ["security", "tests"], ["p3-authz-tests", "p6-ingest", "p7-quiz", "p8-export", "p0-threat"],
             "Walk every abuse case in docs/threat-model.md and add a test or a documented manual check: join-code guessing, kit-code brute force, event spoofing for another kit, media URL sharing, student reaching adult or staff pages, facilitator reaching another class.",
             ["Each abuse case links to a passing test or a signed-off manual check"]),
            ("p9-deps", "Dependency audit and pinned images", "task", 2, ["security"], ["p1-docker"],
             "pnpm audit clean or exceptions documented, Docker base images pinned by digest, Dependabot or Renovate enabled, lockfile committed.",
             ["No high or critical advisories without a written exception"]),
            ("p9-load", "Load test at twice pilot size", "task", 0, ["infra", "tests"], ["p6-instrument", "p4-video", "p1-staging"],
             "k6 (or similar) scenario on staging: 30 devices joining within a minute, stepping through a module, sending events and each streaming a 720p video. Record CPU, memory, bandwidth and p95 latency; size the production VM from the result.",
             ["p95 page response under 500 ms and no errors at 30 devices",
              "Capacity note committed with the chosen production VM size and expected monthly bandwidth"]),
            ("p9-privacy-doc", "Final privacy documentation and consent appendix", "task", 0, ["privacy", "docs"], ["p6-catalog", "p9-delete", "p9-retention", "p9-logs"],
             "Finalize docs/PRIVACY.md from the handoff version against what was actually built: data inventory, where it is stored, who can see it, retention, deletion. Produce a one-page plain-language appendix with the generated event list for the consent form and research application.",
             ["Every table and log is in the data inventory",
              "Appendix is readable by a parent (no jargon) and matches the generated event catalog"]),
        ],
    },
    {
        "n": 10, "slug": "production-deploy", "title": "Production deploy and pilot readiness",
        "goal": "A production environment that can be restored from backup, real content and real codes loaded, and a rehearsed plan for the pilot day including what happens when the Wi-Fi fails.",
        "exit": [
            "Production is live in a Canadian region with backups restored at least once in a drill",
            "Printed code cards match the kits; smoke test passes on the pilot's device types",
            "Go/no-go checklist signed by the team",
        ],
        "tasks": [
            ("p10-prod-infra", "Provision production VM", "task", 0, ["infra", "deploy"], ["p9-load", "p0-host"],
             "Production VM sized from the load test, same region as staging, separate from staging. Firewall, automatic security updates, non-root deploy user, Docker, separate volumes for database and media, time sync.",
             ["Only 80/443 public; SSH restricted",
              "Infra steps are scripted or documented so the VM can be rebuilt from scratch"]),
            ("p10-secrets", "Production secrets and the code pepper backup procedure", "task", 0, ["infra", "security", "human"], ["p10-prod-infra"],
             "Generate production secrets on the server. HUMAN: store CODE_PEPPER and the backup encryption key in two offline places the team controls. Losing the pepper invalidates every printed code; leaking it weakens them. Document rotation.",
             ["Secrets exist only on the server and in the team's offline store",
              "docs/runbook/secrets.md explains recovery and rotation"]),
            ("p10-backups", "Encrypted nightly backups and a restore drill", "task", 0, ["infra"], ["p10-prod-infra", "p10-secrets"],
             "Nightly pg_dump, encrypted client-side, to object storage in Canada, 30-day retention; media volume synced separately. Perform a full restore onto staging and record the time taken.",
             ["Restore drill completed and documented with elapsed time",
              "Backup failure raises an alert"]),
            ("p10-cd", "Release pipeline with health gate and rollback", "task", 0, ["deploy", "ci"], ["p10-prod-infra", "p1-staging"],
             "Tagged release promotes the exact image tested on staging: migrate, start, health-check, switch. Rollback is one documented command to the previous image. Migrations must be backward compatible with the previous app version.",
             ["A deliberately broken release is rejected by the health gate and the old version stays up",
              "Rollback rehearsed once on staging"]),
            ("p10-dns-tls", "Domain, DNS and TLS for production", "task", 0, ["infra", "deploy"], ["p10-prod-infra"],
             "Point the production hostname at the VM, Caddy obtains certificates, HTTP redirects to HTTPS, HSTS on. Give the final hostname to the pilot site for allowlisting.",
             ["TLS test grade A or better",
              "Hostname sent to pilot-site IT (note on the p0-school-it bead)"]),
            ("p10-monitoring", "Uptime, resource and error alerts to Discord", "task", 1, ["infra"], ["p10-dns-tls"],
             "External uptime check on /readyz, disk/CPU/memory alerts, alert on 5xx spikes and on backup failure, all to a Discord webhook channel. No third-party script runs in users' browsers.",
             ["Stopping the app triggers an alert within 3 minutes",
              "Alert channel documented in the runbook"]),
            ("p10-content-release", "Content v1 freeze and release", "task", 0, ["content", "deploy"], ["p4-real-content", "p4-registry", "p10-cd"],
             "Freeze v1 content for Pilot 1, deploy, sync the registry, upload videos, verify every step and video in production.",
             ["Every step opens and every video plays in production",
              "content.lock.json tagged as pilot-1"]),
            ("p10-codes", "Generate the production code batch and print code cards", "task", 0, ["codes", "human"], ["p2-code-cli", "p10-secrets", "p0-open-decisions"],
             "Run the generator against production for the Pilot 1 batch (kits plus spares). HUMAN: print cards, match each card to its kit during packing using the CSV, store the CSV offline.",
             ["One card per kit and spare, QR scans to the production redeem page",
              "Packing check recorded: card number equals kit label for every kit"]),
            ("p10-accounts", "Create staff and facilitator accounts and the pilot class", "task", 1, ["deploy", "human"], ["p10-dns-tls", "p3-invites"],
             "Create staff accounts for the team, invite facilitators and the teacher, create the Pilot 1 class. Kits are redeemed into it during the dry run.",
             ["Each facilitator has logged in once before pilot day"]),
            ("p10-smoke", "Production smoke test", "task", 0, ["deploy", "tests"], ["p10-content-release", "p10-codes", "p10-backups", "p10-monitoring"],
             "Scripted end-to-end check against production using a spare kit's real code: redeem, open session, join from a second device, complete a step, get stuck, see it on the dashboard, verify events arrive, then delete that kit's data.",
             ["Smoke script passes and leaves no test data behind",
              "Script is re-runnable before every pilot session"]),
            ("p10-school-test", "HUMAN: test on the pilot site's network and devices", "task", 0, ["human", "pilot"], ["p0-school-it", "p10-dns-tls", "p5-e2e"],
             "On site or with a borrowed school device on the school network: load the site, join, play a video, go offline and back. Earlier is better: run it against staging as soon as Phase 5 is done, then again against production.",
             ["Site and video load on the school network on the actual device type",
              "Join and resume behaviour confirmed with the school's cookie policy"]),
            ("p10-runbook", "Pilot-day runbook and offline fallback", "task", 0, ["docs", "pilot"], ["p10-smoke"],
             "docs/runbook/pilot-day.md: setup checklist, how to open a session, what to do when a tablet will not join, when the Wi-Fi drops, when the site is down (printed guides plus videos on USB or a facilitator laptop), who to message, and the after-session data-quality check.",
             ["Runbook fits on two printed pages",
              "Offline fallback kit list is specific (how many printed guides, which files on the USB)"]),
            ("p10-dry-run", "HUMAN: facilitator dry run with all kits", "task", 0, ["human", "pilot"], ["p10-runbook", "p10-accounts", "p10-school-test"],
             "Full rehearsal with every kit and tablet, facilitators following the runbook. File every problem as a bead.",
             ["All kits redeemed into the pilot class",
              "Problems filed and triaged; P0/P1 fixed"]),
            ("p10-go-live", "Go/no-go checklist and launch", "task", 0, ["pilot", "human"], ["p10-dry-run", "p0-consent", "p9-privacy-doc", "p9-authz-sweep", "p9-headers", "p9-ratelimit", "p6-nolog-invariant", "p8-export"],
             "Team signs off: consent and approval in hand and matching what the platform does, dry run clean, backups restorable, no open P0/P1 beads, runbook printed.",
             ["Checklist committed with names and date",
              "`bd list` shows no open P0 or P1 beads outside post-launch-ok and post-pilot"]),
        ],
    },
]

PRI = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}


def main() -> int:
    keys = {}
    for ph in PHASES:
        for t in ph["tasks"]:
            if t[0] in keys:
                print(f"duplicate key {t[0]}", file=sys.stderr)
                return 1
            keys[t[0]] = ph["n"]
    # validate deps
    graph = {}
    for ph in PHASES:
        for key, _title, _type, _pri, _labels, deps, _d, _a in ph["tasks"]:
            for d in deps:
                if d not in keys:
                    print(f"{key}: unknown dep {d}", file=sys.stderr)
                    return 1
            graph[key] = list(deps)
    state = {}

    def visit(k, stack):
        if state.get(k) == 2:
            return
        if state.get(k) == 1:
            raise SystemExit("cycle: " + " -> ".join(stack + [k]))
        state[k] = 1
        for d in graph[k]:
            visit(d, stack + [k])
        state[k] = 2

    for k in graph:
        visit(k, [])

    # phase markdown
    pdir = ROOT / "phases"
    for old in pdir.glob("phase-*.md"):
        old.unlink()
    index = ["# Phases", "",
             "Generated from `tools/build_plan.py`. Edit that file and re-run it; do not hand-edit these.", "",
             "| Phase | Title | Tasks | Human-gated |", "|---|---|---|---|"]
    for ph in PHASES:
        name = f"phase-{ph['n']:02d}-{ph['slug']}.md"
        humans = sum(1 for t in ph["tasks"] if "human" in t[4])
        index.append(f"| {ph['n']} | [{ph['title']}]({name}) | {len(ph['tasks'])} | {humans} |")
        out = [f"# Phase {ph['n']}: {ph['title']}", "", f"**Goal.** {ph['goal']}", "",
               "## Exit criteria", ""]
        out += [f"- [ ] {e}" for e in ph["exit"]]
        out += ["", "## Tasks", "",
                "| Key | Pri | Type | Title | Depends on | Labels |", "|---|---|---|---|---|---|"]
        for key, title, typ, pri, labels, deps, _d, _a in ph["tasks"]:
            out.append(f"| `{key}` | {PRI[pri]} | {typ} | {title} | {', '.join('`'+d+'`' for d in deps) or 'none'} | {', '.join(labels)} |")
        out.append("")
        for key, title, typ, pri, labels, deps, desc, acc in ph["tasks"]:
            out += [f"### `{key}` {title}", "", desc, "", "Acceptance:", ""]
            out += [f"- {a}" for a in acc]
            out.append("")
        (pdir / name).write_text("\n".join(out))
    index += ["", "Labels: `human` means a person must do it and the agent must not start it. "
              "`post-launch-ok` may ship after Pilot 1 starts. `post-pilot` is not needed until after the go/no-go.", ""]
    (pdir / "README.md").write_text("\n".join(index))

    # beads graph plan
    nodes, edges = [], []
    for ph in PHASES:
        ek = f"phase-{ph['n']:02d}"
        nodes.append({
            "key": ek, "type": "epic", "priority": 0 if ph["n"] <= 7 or ph["n"] >= 9 else 1,
            "title": f"Phase {ph['n']}: {ph['title']}",
            "description": ph["goal"] + f"\n\nDetails: docs/handoff/phases/phase-{ph['n']:02d}-{ph['slug']}.md",
            "acceptance_criteria": "\n".join(f"- {e}" for e in ph["exit"]),
            "labels": [f"phase-{ph['n']}"],
        })
        for key, title, typ, pri, labels, deps, desc, acc in ph["tasks"]:
            nodes.append({
                "key": key, "type": typ, "priority": pri, "title": title,
                "parent_key": ek,
                "description": desc + f"\n\nPlan key: {key}. Phase file: docs/handoff/phases/phase-{ph['n']:02d}-{ph['slug']}.md",
                "acceptance_criteria": "\n".join(f"- {a}" for a in acc),
                "labels": [f"phase-{ph['n']}"] + labels,
            })
            for d in deps:
                # from depends on (is blocked by) to
                edges.append({"from_key": key, "to_key": d, "type": "blocks"})
    plan = {"commit_message": "Seed JADE platform build plan", "nodes": nodes, "edges": edges}
    (ROOT / "beads" / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")

    n_tasks = sum(len(p["tasks"]) for p in PHASES)
    roots = sorted(k for k, d in graph.items() if not d)
    summary = {"phases": len(PHASES), "tasks": n_tasks, "edges": len(edges),
               "human_tasks": sum(1 for p in PHASES for t in p["tasks"] if "human" in t[4]),
               "initially_ready_tasks": roots}
    (ROOT / "beads" / "expected.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
