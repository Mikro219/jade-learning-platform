PLANLOOP-BUNDLE run=jade-8w4.pl1 revision=6 call=6 attempt=1 sha256=aed653c9878371b8c163bdd9a6de9342a03ddf1e24368ca9a75b475015e272ab
Policy planloop/3 (quartz-rs-lur, 2026-10-22).

/home/mikep/.local/state/planloop-isolated/r-360e05aa096e430f/repo is a frozen, read-only snapshot of the repository for this revision. Read only files
under it; a relative path below is relative to it. Never read the original checkout or any other path
outside it: such reads are detected in your transcript and void the review.
/home/mikep/.local/state/planloop-isolated/r-360e05aa096e430f/repo/.planloop-bundle/ holds the frozen plan, brief, obligations, binding bead text, evidence and
the discovery record; bead text cannot be fetched any other way (never run bd).

Coverage must contain, for every finding listed below in state fix_proposed, exactly one entry
`finding R<k>: resolved` or `finding R<k>: unresolved`. To withdraw an open finding you judge invalid,
write `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, at least 40 chars>`.
When re-raising a known finding, use its R id as your finding id.
Check every REMOVED and SHRINK disposition below: each must say what was removed, why, and which
obligations or capabilities it affects; an unexplained removal is a finding.

This is the final gate: an independent, full-rubric review of the whole plan. Earlier rounds
are not evidence that anything is correct; check interactions between revised and unchanged
sections.

--- REVIEW BRIEF (host) ---
# Review brief: jade-8w4.pl1 (Phase 2: Data model and kit codes), revision 1

## Scope
Code, schema and tooling. The plan covers the agent beads of Phase 2 (epic jade-8w4) against their acceptance criteria and the phase exit criteria (OB3 to OB5):
- jade-o07 (p2-schema-core, P0): DATA-MODEL.md sections 1 to 3 as Drizzle schema plus forward-only SQL migrations: `products`, `code_batches`, `kits`, `kit_codes`, `users`, `auth_sessions`, `invites`, `classes`, `class_kits`, `device_sessions`, `audit_log`, with their constraints and indexes, and grants to `jade_app`.
- jade-fd5 (p2-code-lib, P0): generate, normalise, validate and HMAC kit codes (`PREFIX-XXXX-XXXX-C`, Crockford Base32, CSPRNG, check character, HMAC-SHA256 under `CODE_PEPPER`).
- jade-7if (p2-redeem, P0): `redeemCode(user, code, classId?)`: one transaction with a row lock, single use, distinct non-leaky rejections, per-account lockout plus a global failed-code throttle (no per-IP limit, ADR 0020), an audit row.
- jade-99j (p2-code-cli, P1): `pnpm codes:generate`: kits and code rows, a packing CSV and a printable sheet of code cards with QR codes, written outside the repository; the plain codes are shown once and never stored.
- jade-q01 (p2-seed, P2): `pnpm db:seed`: the demo product, 15 kits with known development codes, a staff user, a facilitator and a class; development only.
- jade-pe9 (p2-staff-codes, P2): staff pages for batches and code status; revoke, reissue, move a kit between classes. **It depends on jade-vcy (p3-adult-auth, Phase 3)**, which supplies accounts, sessions and the staff role (OB6). The plan specifies jade-pe9 fully (routes, authorization, audit, tests) but it is **not implementable in this phase**: the plan says where it slots once jade-vcy has landed, what else it needs then (the authorization matrix of jade-aq5, OB50), and that the phase epic cannot close before it.
- jade-hap (readiness pool vs the app's Drizzle pool, OB31) is **decided in this plan**: Phase 2 adds the first real app queries.

Track: escalated (risk domains schema-migration, secrets, privacy, authorization, concurrency, state-machine, idempotency). Human beads are out of scope (CLAUDE.md: never start a bead labelled `human`, OB45). No teaching content (rule 7, OB42): development data is the `demo` product only.

## Facts and decisions the plan must take as given
- **Mike, 2026-11-17 (Q4 = yes), recorded in jade-8w4 notes (OB2):** Phase 2 proceeds while staging (jade-0za human, jade-4zw blocked) is open. "Migrations apply cleanly ... on staging" (jade-o07, OB8) and "Core schema migrated on staging" (exit criterion, OB3) are **deferred acceptance items**, verified when jade-4zw lands. The plan must say exactly how: which check proves it on staging (for example `/readyz` with `migrations: ok` and the staging ledger equal to the shipped `manifest.json`, read without any staging data leaving the VM), who runs it and when (the first staging deploy after jade-4zw), where the pending item is recorded so it cannot be forgotten (bead notes, an open bead, or a dependency), and whether jade-o07 closes before that check (the Phase 1 precedent: jade-urd closed under Phase 1's Q2(a) once merged and covered by green CI, with its deploy half delivered later). It must not invent a staging host.
- **Repository and CI today.** Remote `github.com/Mikro219/jade-learning-platform`; one pull request per bead; merge once CI is green (OB52). CI (`.github/workflows/ci.yml`) runs `check`, `e2e`, `image` and `migration-compat`. The **first real migration-compat run happens on Phase 2's first migration pull request** (`tools/ci/migration-compat.sh`: the previous release's build must answer `/readyz` 200 on the new schema and the base's integration tests must pass on a template migrated by the head's runner). The plan says what is expected of that run and what happens if it fails for a harness reason (a bug bead through the bugfix skill; never weakening the check). Baseline gate on main 72254ef was green on 2026-11-18 (jade-8w4 notes).
- **What exists in the code** (all in the snapshot): `src/lib/server/db/schema.ts` is empty; `codes/index.ts` and `auth/index.ts` export nothing; `createPool`/`createDatabase` exist in `db/client.ts` but no app-wide pool does; `http/readiness.ts` owns a private pool (max 4, 2 s `query_timeout`, `statement_timeout`, `lock_timeout`) and `closeDatabase()` (called on `sveltekit:shutdown` in `hooks.server.ts`) closes only that pool (jade-hap); `config/index.ts` reads `CODE_PEPPER` as an opaque string of at least 43 characters ("how key bytes are derived from it is jade-fd5's decision"); `migrations/` holds only `0000_baseline` (revokes CREATE on `public`, grants `jade_app` USAGE and SELECT on `schema_migrations`); `tests/authz/route-registry.ts` knows only the access classes `public` and `dev-only` (jade-aq5 widens it in Phase 3); `tests/support/db.ts` gives each test file a database cloned from a migrated template. `package.json` has no argon2, QR, PDF or property-testing library; Node 24.22.3 and pnpm 12.21.0 are pinned.
- **Contracts Phase 2 inherits from the approved Phase 1 plan** (plans/planloop/jade-vtk.pl1 rev-005; not bundled, because `plans/planloop/` is never a review input, so restated here): migrations forward-only and compatible with the previous release, checked by `tests/unit/migrations-static.test.ts`, `pnpm db:check --base <ref>` and `tests/integration/migrate.test.ts` (INV5; the rules are binding through migrations/README.md, OB129 to OB136); a database that is ahead of the app is ready (`migrationStatus`, OB53 of Phase 1); the running app cannot run DDL and never holds the owner's credentials (INV6; jade-hwu, `jade_app` can still CREATE TEMP TABLE, is deferred by Mike); no log line carries an IP, cookie, kit code, join code, token, email, body, path, query string or a kit, class, session or step identifier, in any APP_ENV (INV1; the closed logger of `src/lib/server/log`); every route is in the registry with an access class (INV8); a refusal test feeds inputs every earlier check accepts and asserts the refusing check's own tag (PD15); cluster-wide state in tests is written once or serialized (PD12). Phase 1 plan section 15 handed Phase 2: jade-o07 "add explicit grants to `jade_app` for every table; regenerate the manifest; the `citext` extension goes in its own migration"; jade-fd5 "fix how key bytes are derived from the string before any code is generated; never pass the pepper to the logger"; jade-99j and jade-q01 "refuse to run in production through `APP_ENV`; keep output directories ignored".
- **jade-8n2.4 (closed, ADR 0019):** participant letters are A to D. It affects only `quiz_responses` and `exit_cards` (DATA-MODEL section 5, Phase 7), not any Phase 2 table; jade-o07's dependency on it is satisfied and no Phase 2 schema follows from it.
- **jade-6is (human, open: kit name and code prefix, retention period) does not block Phase 2.** The schema is product-agnostic (OB7, OB59): a kit is a `products` row, nothing names a specific kit, and development uses the `demo` product (rule 7). `RETENTION_MONTHS` is not read in Phase 2 (only `classes.ended_at` exists). jade-6is blocks the production batch (jade-t17, human), not this phase. A plan that hard-codes `ARM`, `arm` or any real product in schema, migration data, code or tests is a finding.
- **Stop points (CLAUDE.md, OB53 to OB56):** stop and ask Mike when a change would touch rules 1 to 6, a secret, payment, DNS change or production deploy is needed, a human or human-labelled decision bead blocks the work, or the same test fails three times after three different fixes. No agent runs anything against production (ADR 0021 "Production actions stay human", OB73). An approved plan is not authorization to implement (OB49).
- **Mike's standing rules (memory, 2026-11-15 and 2026-11-16):** after every implementation round, two independent read-only Opus reviewers review the diff before the commit request: Reviewer A (correctness: plan, acceptance and invariant conformance, missed call sites, edge cases, whether tests prove the claim) and Reviewer B (systems: crash, restart, partial writes, retries, races, ordering, idempotency, fail-open versus fail-closed, interrupted migrations, test-harness races). If they return only low findings, the orchestrator fixes them itself, re-runs the gate, commits with the bead id, runs `pnpm ci:clean-clone` and records the results; any medium or high goes to a subagent fix round and then to Mike. The plan's per-bead workflow includes both.
- **FaultForge (jade-4el, OB32 to OB36):** once jade-7if exists, a separate bead adds FaultForge's `stack.yaml` and `faultforge.yaml` (modelled on fault-forge `demo/redeem-code`). Runs use the remote Vultr VM (Mike, 2026-11-17), `propose_fix` with `mode='client'`; demo kit only, throwaway sandbox database, no real codes; the scenario adds a load check next to jade-7if's own tests and replaces none of them. jade-7if's acceptance does not wait on FaultForge. The plan says when that bead is filed and what jade-7if must expose for it (for example a sandbox-only way to raise the per-account and global limits, which must be impossible to enable outside `APP_ENV=test`).

## Contradictions and gaps found in discovery (the plan must resolve each explicitly, or raise it as an open question or residual risk; never silently)
1. **Per-IP limit.** The jade-7if description and the phase file (OB15) say "Rate limit per account and per IP"; jade-7if's fourth acceptance line and ADR 0020 (OB19, OB70) replace that with per account plus a global failed-code throttle, no per-IP limit; the bead is current (OB57). jade-4el's notes (OB35) still speak of "per-IP rate limits" for p2-redeem: there are none.
2. **Seed refusal.** jade-q01 says "refuses to run when NODE_ENV=production" (OB24, OB26); the repository's environment model is `APP_ENV` (the image sets `NODE_ENV=production` for staging and production alike) and the Phase 1 hand-off says "through `APP_ENV`". Known development codes seeded on staging would be redeemable codes on a public server, so say whether staging is refused too.
3. **Rule 3 and `classId`.** "Class and kit identity come from the session, never from a request body" (OB39) against `redeemCode(user, code, classId?)` (OB15), where the adult chooses the class. State that the user comes from the session only, the kit only from the code lookup, and the class is an adult-chosen target that is ownership-checked (404, not 403, for a class the user does not own).
4. **Normalisation against the prefix.** Normalisation maps O to 0 and I and L to 1 (OB11, OB13), but `products.code_prefix` allows any `^[A-Z]{3}$` (OB77), including I, L, O and U. Say whether normalisation applies to the prefix, or whether prefixes are restricted; a stricter constraint is a change to a binding DATA-MODEL constraint and is raised, not slipped in. The check-character algorithm is unspecified: Crockford's mod-37 check symbols include `*`, `~`, `$`, `=` and `U`, outside the 32-symbol alphabet, while ARCHITECTURE's example ends in a digit (OB107). Choose an algorithm, state what it covers (the prefix too?) and prove "single-character typos are rejected" (OB12) for every position and substitution, not only by sampling.
5. **Plain codes in the database and in the repository.** Plain codes exist only on the printed sheet and the packing CSV (OB5, OB65, OB109); jade-q01 seeds "known dev codes" (OB24), which are plain codes in the repository. Say how they stay development-only (the demo product's prefix, the development pepper, the seed refused outside development/test) and why no known development code can ever redeem on staging or production.
6. **The QR URL (TM-4, ADR 0011, OB66, OB122, OB123).** jade-99j prints `/redeem?code=...`, which puts the plain code into the adult device's browser history and the request line; the conflict is open and no source settles it. The card's contents are printed and handed out (jade-t17), so whatever is chosen is permanent for that batch. The plan may propose an option (for example the code in a URL fragment, which the browser does not send) but brings the choice to Mike; it does not settle it.
7. **The exit criterion "redeemed exactly once" (OB4)** in a phase with no `/redeem` page and no adult sign-in (jade-bu6 and jade-vcy are Phase 3). Say how Phase 2 demonstrates it (a service-level test on codes the CLI generated?) and what waits for Phase 3.
8. **Where the lockout and throttle counters live.** "Ten failed attempts in an hour locks further attempts for that account" (OB17, OB19); the threat model says the storage of these counters is not decided (OB125), and ADR 0020 says the sources do not say how the per-account limit and the global throttle interact (OB72). In memory, a restart clears a lockout; in the database, it is a table DATA-MODEL does not list (and it must hold no IP). Also undecided: what counts as a failed attempt (malformed, unknown, revoked, already redeemed by another, already redeemed by the same user), how long a lock lasts and who lifts it, the global threshold (jade-6cq tunes it later, AB11/TM-6, OB71, OB121), and how concurrent failed attempts cannot all pass the check before any is counted.
9. **What the audit log holds.** `audit_log.subject` is free `jsonb` "ids and counts only; never codes, tokens or note text" (OB87, OB127). Name each Phase 2 action (`code.redeem`, revoke, reissue, kit move, batch creation, ...), the exact keys of its subject, and whether failed redemptions are audited. Audit rows carry kit ids inside `jsonb`, which the kit-deletion test's "every table that has a `kit_id` column" (OB91) does not see; no source gives the audit log a retention rule (OB127). Children: the audit log holds adult actor ids and anonymous kit ids; confirm it holds nothing about a child (OB93, rule 1).
10. **`delete_kit_data` coverage.** Phase 2 creates four tables with a `kit_id` column (`kits`, `kit_codes`, `class_kits`, `device_sessions`); DATA-MODEL's `delete_kit_data` lists only `device_sessions` of them (OB91), and the function and its enumerating test are Phase 9 (jade-l13). The JADE rubric says every new table with a `kit_id` is covered by `delete_kit_data` and its enumerating test. Say how Phase 2 meets that before the function exists (for example a committed classification of every kit-keyed table, activity or identity, that the Phase 9 test must consume, or a bead filed against jade-l13), without building Phase 9 work.
11. **jade-pe9 before Phase 3.** Its 404-for-non-staff acceptance (OB28) needs the staff role and sessions (jade-vcy) and the authorization matrix (jade-aq5, Phase 3); the registry has no `staff` class yet. "Reissue a new code ... (prints once)" (OB27) puts a plain code into a staff page response: say how it is never stored, logged or cached (rule 4, OB40).
12. **CLI output location.** "Writes two files outside the repo" (OB20) and "Output directory is gitignored" (OB23); no such directory exists or is ignored today (`git check-ignore` and `.gitignore` checked; see "Secrets and the snapshot" below). Resolve both: where the files go by default, what happens when the operator points inside the work tree, and the test.
13. **The QR needs an absolute origin**, and the production domain is open (jade-0za). Say where the CLI gets it and what a batch generated before the domain exists means.
14. **DATA-MODEL details the migration must handle:** `code_batches.created_by` references `users` before `users` is defined (creation order); `device_sessions` has no direct foreign key to `classes`; `invites.role` has no check constraint while `users.role` does (do not add or drop a constraint silently: "Constraints from DATA-MODEL.md are enforced", OB9); `users.email` is `citext`, an extension created by `jade_owner` (superuser in development, CI and the Compose stack). Every table's grants to `jade_app` are in the same file (OB134); choose least privilege per table (for example no UPDATE or DELETE on `audit_log`), and test the refusals over the app pool.
15. **Seed users without a password library.** `users.password_hash` is argon2id (OB63, OB81), but no argon2 library exists until jade-vcy. Say what the seeded staff user and facilitator get (a hash that cannot log in, or the library added now) and why no known development password reaches staging or production.
16. **"Usable local app in under 5 minutes" (OB25)** when Phase 2 has no sign-in and no redeem page: define "usable", and how the time is measured.
17. **Separate planloops (OB48).** CLAUDE.md asks for a separate planloop for each major implementation: work in a planloop risk domain, a new mechanism, a migration or an authorization-matrix change. jade-o07 (migration), jade-fd5 (secrets), jade-7if (concurrency, state machine) and jade-pe9 (authorization) each qualify. Say which beads this phase plan covers fully enough to need no run of their own, and bring that call to Mike; do not decide it.
18. **The pepper.** How key bytes come from the `CODE_PEPPER` string (the UTF-8 bytes, or the decoded 32 bytes) is fixed forever once a code is printed; changing it is a rotation, and rotation or loss invalidates every printed code (OB67, OB112). Record the derivation durably (a new ADR from 0026 follows docs/adr/README.md conventions). Say whether a mismatched or wrong pepper in the CLI's environment (codes HMAC'd under a different pepper than the app's) is detected before any card is printed, and how, without storing anything derived from the pepper that would weaken it.
19. **Who may mint codes.** The CLI writes `products`, `code_batches`, `kits` and `kit_codes`. Say which database role it uses (the app role, then the running app could mint codes too; or the owner role) and how a product row comes to exist (no kit name in a migration, OB7).

## The open questions the plan must answer or raise for Mike
- **jade-hap (OB31), decide here:** readiness over the app's own pool (with its 2 s limit applied per query or per transaction, never to app queries) or a separate pool accepted on purpose; either way `closeDatabase()` on `sveltekit:shutdown` ends every pool. The plan states the choice, its reason and its test.
- Rate-limit counter storage and semantics (item 8), given that IP addresses are never stored or logged (rule 4) and no per-IP limit exists for redemption.
- Whether `audit_log` holds anything about children, and the closed subject shape of each action (item 9).
- `delete_kit_data` coverage of the Phase 2 kit-keyed tables (item 10).
- The QR URL (item 6), the seed's environment refusal (item 2), seed passwords (item 15), the check-character algorithm and prefix normalisation (item 4), the pepper derivation (item 18), and the separate-planloop call (item 17).
- Message set and idempotency of `redeemCode`: "distinct, non-leaky messages" for revoked and already-redeemed (OB15) while an unknown code should not reveal whether a code exists; whether a second redemption of the same code by the same adult (a double submit, a rescan) is success or rejection, and whether it counts as a failed attempt.
- `display_number` in `class_kits`: how it is assigned on redemption into a class (the kit's `serial`? the next free number?), given `unique (class_id, display_number)` and the stability required by jade-bu6; and what redeeming a kit already active in another class does (`kit_in_one_active_class`, OB89).

## What the plan must deliver per bead
- **Order of work and dependencies.** The bead graph: jade-o07 and jade-fd5 are ready; jade-7if and jade-99j after both; jade-q01 after jade-o07; jade-pe9 after jade-7if and jade-vcy. Any dependency the plan adds (for example jade-q01 on jade-fd5 for its development codes, or jade-7if on the jade-hap decision) is named, with the `bd dep add` the orchestrator runs on Mike's go-ahead. Lowest phase and highest priority first (OB44).
- **Acceptance tests per bead**, each with the command that runs it and the file it lives in: one row per acceptance line (OB8 to OB30) and per exit criterion (OB3 to OB5); constraint tests that insert violating rows for every DATA-MODEL constraint (OB9); a test that no column can hold a plain code or token (OB10; how is that proven: column types, names, a canary?); property tests (OB12, and which library or generator); a parallel-transaction test that fails on a build without the row lock (OB16); the lockout test (OB17); audit tests asserting the absence of the code (OB18). Oracles reuse production logic (the rubric): a test that re-implements the check character or the HMAC to judge production output is a finding unless kept byte-identical by a CI assertion.
- **Stop points** for this phase (above), plus: any new dependency (QR, PDF, argon2, property testing) named with its version, licence and why it makes no network request at runtime; the printed sheet is self-contained (no remote font, script or image) so that opening it in a browser requests nothing from another origin (rule 5, OB41, OB68, OB74).
- **Interleavings to trace** (stateful mechanisms; say for each what happens and which test proves it, or why it cannot happen):
  1. Two adults redeem the same code at once (OB16; jade-4el's invariants: at most one redemption per code, audit rows equal redemptions, each loser gets a distinct "already redeemed" reply).
  2. Two adults redeem different codes into the same class at once (`display_number` allocation under `unique (class_id, display_number)`).
  3. One adult's ten-plus failed attempts in parallel (the counter cannot be raced past the limit; a failed attempt is counted even though the redemption transaction rolls back).
  4. The CLI run twice with the same batch label (OB21), including two runs started at the same moment.
  5. The CLI crashes after the database insert and before the files are written (codes that exist only as HMACs, which nobody can ever print), and the reverse: files written, then the transaction fails (cards that will never redeem). Which order makes both recoverable, and what the operator does next (the batch label is now taken).
  6. Pepper rotation or absence: CLI and app with different peppers; `CODE_PEPPER` missing in the CLI's environment; the derivation changed between releases.
  7. A migration compatible with the previous release (OB62, OB131): the previous build on the new schema (migration-compat), and rollback after a Phase 2 migration; each later Phase 2 migration (for example a counter table for jade-7if) against the release before it.
  8. Revoke or reissue racing a redemption of the same kit (`one_live_code_per_kit`, OB88; jade-pe9, specified now).
  9. App shutdown while queries run on the pool(s) of the jade-hap decision.

## Rubric (every round)
Contradictions; missing requirements (every obligation row OB1 to OB136 is answered, each by a concrete step and an acceptance check, or stated as deferred with its owner); incorrect assumptions (what exists in the repository today, library and Postgres behaviour); affected call sites and consumers (Phase 3 jade-vcy, jade-bu6, jade-5nj, jade-8lt, jade-9tk, jade-aq5 on these tables; Phase 4 jade-dfj; Phase 6 jade-7j8 as the next migration; Phase 9 jade-l13, jade-6cq, jade-ada; Phase 10 jade-lnn.1, jade-lnn.2, jade-t17, jade-fgs); architectural incompatibilities (modules talk only through `index.ts`, OB60, OB104); failure and recovery; concurrency, order and idempotency; migration and backward compatibility; test coverage; missing failure scenarios; verifiable acceptance criteria; unnecessary scope expansion (no Phase 3 routes, sign-in or classes UI; no Phase 6 tables; no Phase 9 deletion function); oracles reuse production logic; stateful mechanisms trace crash mid-step, timeout, partial write, retry, duplicate delivery, reordering, concurrent writers and rollout overlap, or say why not applicable.

**JADE invariants, every round:** CLAUDE.md rules 1 to 6 hold on every path the plan adds or changes (no child accounts, names or free text; zero activity stored with logging off, and `p6-nolog-invariant` neither skipped nor weakened; class and kit from the session only; no plain codes, tokens or IPs stored or logged; no third-party origin; step ids permanent; rule 6 is not touched by this phase, since it creates no content); every new route is in the authorization matrix (OB50); every new table with a `kit_id` is covered by `delete_kit_data` and its enumerating test (item 10); event or table shape changes bump `catalog_version` and update the generated docs and consent appendix where they add a new kind of information (no event shape changes in this phase; say so if that holds); migrations are forward-only and compatible with the previous release; decisions in `docs/adr/` are followed, not reargued (rule 8, OB43: an ADR that looks wrong becomes a `decision` bead). Implementation waits for Mike's go-ahead after approval and sign-off; the plan contains no authorization to self-start.

Findings need a severity (high/medium/low) and concrete evidence (file and line, bead and field, or OB id).

## Change map (navigation only)
New: `migrations/0001_*.sql` and later files (with `manifest.json` and `meta/` updates), the Drizzle tables in `src/lib/server/db/schema.ts`, an app pool in `src/lib/server/db/` (jade-hap), `src/lib/server/codes/` (format, normalise, check character, HMAC, redeem, limits; public API in `index.ts`), `tools/codes/` (the generator) and `tools/db/seed.ts`, `package.json` scripts `codes:generate` and `db:seed` and any new dependency, tests under `tests/unit/`, `tests/integration/` and `tests/blackbox/`, and later (jade-pe9, after Phase 3) staff routes under `src/routes/(staff)/` with their registry entries. Changed: `src/lib/server/http/readiness.ts` and `src/hooks.server.ts` (jade-hap), `src/lib/server/config/index.ts` and `.env.example` (only for keys the plan adds), `.gitignore` (CLI output), `README.md` (seed step), `docs/adr/` (a new ADR only where the plan records a decision, such as the pepper derivation).

## Secrets and the snapshot (checked before the first bundle)
`.env` and `.env.*` are ignored (`.gitignore` lines 23 and 24, `!.env.example` at 25); only `.env.example` is tracked. No code-card or packing-CSV output directory exists yet, and none is listed in `.gitignore` or `.dockerignore`; jade-99j must add it (OB23) before the CLI first writes anything inside the work tree. The snapshot overlays three tracked, modified files under `.claude/skills/bugfix/` (no secrets). No bundled input contains a secret, `.env` contents, a real code or pilot data; development examples use the demo product only.

## Checking the plan's obligations
OB1 to OB136 are frozen in the bundle (`obligations.json`) with their sources: bead fields (descriptions, acceptance criteria, jade-8w4 and jade-4el notes) and exact lines of CLAUDE.md, the phase file, the ADRs and their README, DATA-MODEL (sections 1 to 3 verbatim, section 6), PRIVACY, ARCHITECTURE, the threat model and migrations/README.md. Check that the plan answers each with a step and a check, and that nothing it states contradicts one.

## Reviewing the snapshot
The snapshot is a `git archive` export with no `.git` directory, so git commands do not work in it and are not needed: the repository facts they would show are stated in this brief. Beads are frozen in the bundle (`beads/<id>.json`); `bd` is not available to the reviewer.

--- OBLIGATIONS (exact source text) ---
OB1 [bead:jade-8w4 description]: The tables everything hangs off, and the kit code lifecycle: generate, print, redeem once, revoke.
OB2 [bead:jade-8w4 notes]: 2026-11-18: Q4=YES (Mike, 2026-11-17): Phase 2 may start before staging exists; exit criterion 'core schema migrated on staging' waits on jade-0za/jade-4zw. Phase 2 planloop run jade-8w4.pl1 starting (escalated).
OB3 [docs/handoff/phases/phase-02-data-model-and-kit-codes.md Exit criteria]: - [ ] Core schema migrated on staging
OB4 [docs/handoff/phases/phase-02-data-model-and-kit-codes.md Exit criteria]: - [ ] A batch of codes can be generated, printed as cards, and redeemed exactly once
OB5 [docs/handoff/phases/phase-02-data-model-and-kit-codes.md Exit criteria]: - [ ] Plain codes exist only on the printed sheet and the packing CSV, never in the database
OB6 [docs/handoff/phases/phase-02-data-model-and-kit-codes.md Tasks]: | `p2-staff-codes` | P2 | task | Staff screen: batches, code status, revoke and reissue, move kit between classes | `p2-redeem`, `p3-adult-auth` | codes, staff-ui |
OB7 [bead:jade-o07 description]: Implement the tables in docs/handoff/DATA-MODEL.md sections 1 to 3 as Drizzle schema plus SQL migrations, with the constraints and indexes listed there. Kits are product-agnostic: nothing in the schema names a specific kit.
OB8 [bead:jade-o07 acceptance_criteria]: Migrations apply cleanly on an empty database and on staging
OB9 [bead:jade-o07 acceptance_criteria]: Constraints from DATA-MODEL.md are enforced (tests insert violating rows and expect failure)
OB10 [bead:jade-o07 acceptance_criteria]: No column stores a plain kit code or plain join-session token
OB11 [bead:jade-fd5 description]: Format PREFIX-XXXX-XXXX-C: 3-letter product prefix, 8 random Crockford Base32 characters from a CSPRNG, 1 check character. Normalise input (case, spaces, dashes, O to 0, I and L to 1). Lookup key is HMAC-SHA256(CODE_PEPPER, normalised code). Plain SHA-256 is not acceptable: 40 bits of entropy is brute-forceable from a leaked table.
OB12 [bead:jade-fd5 acceptance_criteria]: Property tests: generate then validate round-trips; single-character typos are rejected by the check character
OB13 [bead:jade-fd5 acceptance_criteria]: Normalisation accepts lower case, missing dashes and O/I/L confusions
OB14 [bead:jade-fd5 acceptance_criteria]: HMAC uses the pepper from config and constant-time comparison
OB15 [bead:jade-7if description]: redeemCode(user, code, classId?) in one transaction with row lock: unused becomes redeemed, kit attached to class. Reject revoked and already-redeemed codes with distinct, non-leaky messages. Rate limit per account and per IP (IP held in memory only). Write an audit row.
OB16 [bead:jade-7if acceptance_criteria]: Concurrent redemption of the same code succeeds exactly once (test with parallel transactions)
OB17 [bead:jade-7if acceptance_criteria]: Ten failed attempts in an hour locks further attempts for that account
OB18 [bead:jade-7if acceptance_criteria]: Audit log records who redeemed which kit and when, never the code
OB19 [bead:jade-7if acceptance_criteria]: Failed redemptions limited per account (10 an hour, then locked) plus a global failed-code throttle; no per-IP limit (jade-8n2.5). Replaces 'per account and per IP' in the description
OB20 [bead:jade-99j description]: `pnpm codes:generate --product <slug> --batch <label> --count <n>` creates kits and code rows, and writes two files outside the repo: packing CSV (kit number, code) and a printable A4/Letter sheet of code cards with the code in large type plus a QR that opens /redeem?code=... The plain codes are shown once and never stored.
OB21 [bead:jade-99j acceptance_criteria]: Running the CLI twice with the same batch label fails instead of duplicating
OB22 [bead:jade-99j acceptance_criteria]: Printed sheet is legible in greyscale and each QR scans on a phone
OB23 [bead:jade-99j acceptance_criteria]: Output directory is gitignored and the CLI warns that the files are the only copy
OB24 [bead:jade-q01 description]: `pnpm db:seed` creates a demo product, a batch of 15 kits with known dev codes, a staff user, a facilitator, and a class. Dev-only; refuses to run when NODE_ENV=production.
OB25 [bead:jade-q01 acceptance_criteria]: Fresh clone to a usable local app in under 5 minutes following the README
OB26 [bead:jade-q01 acceptance_criteria]: Seed refuses to run in production
OB27 [bead:jade-pe9 description]: Staff-only pages listing batches and per-kit status. Actions: revoke a code, reissue a new code for the same kit (prints once), detach a kit from a class and attach to another keeping its kit id so history carries across pilots.
OB28 [bead:jade-pe9 acceptance_criteria]: Non-staff users get 404 on every staff route
OB29 [bead:jade-pe9 acceptance_criteria]: Reissue keeps kit_id and invalidates the old code
OB30 [bead:jade-pe9 acceptance_criteria]: Every action writes an audit row
OB31 [bead:jade-hap description]: Reviewer B (jade-alt) B5: src/lib/server/http/readiness.ts owns a private pg pool (max 4, 2 s query_timeout, statement_timeout). Plan A3 says readiness runs 'over the app pool'. When the bead that adds the app's Drizzle pool lands, either readiness must use that pool (without imposing its 2 s limit on app queries, e.g. per-query timeout) or the divergence must be accepted; and closeDatabase on sveltekit:shutdown must close the app pool too.
OB32 [bead:jade-4el description]: FaultForge load scenario for jade-7if. Many concurrent redemptions of one demo-kit code. Invariants: redemptions per code <= 1; audit rows == redemptions; every loser gets a distinct 'already redeemed' reply. Demo kit only, throwaway sandbox DB; no real codes. Adds a load check alongside jade-7if's own tests; does not replace them.
OB33 [bead:jade-4el notes]: 2026-11-17 Mike: use the Vultr VM (remote runtime) for JADE FaultForge runs, not local. So runtime auto/remote; source snapshot leaves the machine (repo is public); results are gate_trust remote-reported. propose_fix still mode='client'.
OB34 [bead:jade-4el notes]: For JADE pass mode='client' to propose_fix
OB35 [bead:jade-4el notes]: env raises/disables p2-redeem per-account and per-IP rate limits in the sandbox and sets APP_ENV
OB36 [bead:jade-4el notes]: reset_sql seeds the demo kit only
OB37 [CLAUDE.md Rules that are not up for negotiation]: 1. No accounts, names or free-text input for children. Ever.
OB38 [CLAUDE.md Rules that are not up for negotiation]: 2. When a kit's `logging_enabled` is false, the server stores nothing about that kit's activity. The `p6-nolog-invariant` test must never be skipped, weakened or deleted.
OB39 [CLAUDE.md Rules that are not up for negotiation]: 3. Class and kit identity come from the session, never from a request body.
OB40 [CLAUDE.md Rules that are not up for negotiation]: 4. Plain kit codes, join codes and tokens are never stored or logged. IP addresses are never stored or logged.
OB41 [CLAUDE.md Rules that are not up for negotiation]: 5. No request from the browser to any origin but our own. No third-party scripts, fonts, analytics or embeds. The one exception is the embedded YouTube player's origins, on pages that show a module video ([ADR 0025](docs/adr/0025-youtube-embedded-module-video.md)).
OB42 [CLAUDE.md Rules that are not up for negotiation]: 7. Do not write teaching content for the kit. Use the `demo` kit for development. Real content comes from Given.
OB43 [CLAUDE.md Rules that are not up for negotiation]: 8. The decisions in `docs/adr/` stand. If one looks wrong, file a `decision` bead and stop.
OB44 [CLAUDE.md Work tracking: beads]: - Work one bead at a time, lowest phase and highest priority first.
OB45 [CLAUDE.md Work tracking: beads]: - **Never start a bead labelled `human`.** If one blocks you, say so and stop, or pick other ready work.
OB46 [CLAUDE.md Work tracking: beads]: - A bead is done when every acceptance criterion is met, tests pass locally and in CI, and the change is merged. Not before.
OB47 [CLAUDE.md Work tracking: beads]: - Found something out of scope? `bd create "..." -t task -p 2 --deps discovered-from:<current-id>` and carry on. Do not widen the current bead.
OB48 [CLAUDE.md How each bead is worked]:    - Run a separate planloop for each major implementation. That means work in one of planloop's risk domains (it would start on the escalated track), a new mechanism, or a change to a migration, the event catalog, the content format or the authorization matrix.
OB49 [CLAUDE.md How each bead is worked]:    - An approved plan is not authorization to implement. Implementation waits for Mike's go-ahead.
OB50 [CLAUDE.md How each bead is worked]: 3. Implement with tests. Every new route goes into the authorization matrix test.
OB51 [CLAUDE.md How each bead is worked]: 4. Run `pnpm lint && pnpm check && pnpm test && pnpm e2e`.
OB52 [CLAUDE.md How each bead is worked]: 5. Commit with the bead ID in the message. Merge once CI is green; staging deploys itself.
OB53 [CLAUDE.md Stop and ask the human when]: - A bead is blocked by an open `decision` bead labelled `human`: bring Mike that decision when the work reaches it.
OB54 [CLAUDE.md Stop and ask the human when]: - A change would touch rules 1 to 6 above.
OB55 [CLAUDE.md Stop and ask the human when]: - A secret, payment, DNS change or production deploy is needed.
OB56 [CLAUDE.md Stop and ask the human when]: - The same test has failed three times after three different fixes.
OB57 [docs/adr/README.md Amendments to the handoff documents]: Where a phase file and a bead's acceptance criteria that cite a jade-8n2.<k> decision differ, the bead is current.
OB58 [docs/adr/README.md Open questions]: | 1 | **Kit name and code prefix.** Needed before production codes are printed. | jade-6is | open |
OB59 [docs/adr/0001-kit-agnostic-platform.md Decision]: The platform serves any kit. A kit is a `products` row (slug, name, code prefix) and a `content/<slug>/` folder. First product: the mechanical arm, slug `arm`, prefix `ARM`. Both are placeholders until the team names the kit; changing them before codes are printed is a one-line change.
OB60 [docs/adr/0002-modular-monolith-in-sveltekit.md Decision]: Server code is split into `auth`, `codes`, `content`, `events`, `analytics` modules that talk through their `index.ts`.
OB61 [docs/adr/0003-postgresql-with-drizzle-and-sql-migrations.md Decision]: PostgreSQL 16. Drizzle for typed queries. Migrations are SQL files, forward-only, run on deploy. Analytics is SQL views in the same database.
OB62 [docs/adr/0003-postgresql-with-drizzle-and-sql-migrations.md Consequences]: - Migrations stay compatible with the previous app version, so rollback to the previous image works (ARCHITECTURE.md section 10; p10-cd jade-kn0 description).
OB63 [docs/adr/0005-authentication-without-email.md Decision]: Adults: email + password, argon2id, server-side sessions. Signup requires a valid unused kit code or a staff invite. Password reset is a staff action. Students: class join code plus kit selection, yielding a device-session cookie bound to class and kit. No accounts for children.
OB64 [docs/adr/0009-consent-gated-logging.md Decision]: `logging_enabled` per kit per class, default off, switched on by an adult who confirms consent. Off means zero activity stored server-side. A required test enforces this.
OB65 [docs/adr/0011-kit-code-format-and-storage.md Decision]: `PREFIX-XXXX-XXXX-C`, Crockford Base32, CSPRNG, check character. Stored as HMAC-SHA256 under a server-side pepper. Plain codes exist only on print and in an offline CSV.
OB66 [docs/adr/0011-kit-code-format-and-storage.md Consequences]: - Each card's QR opens `/redeem?code=...` (p2-code-cli jade-99j description), so the plain code also travels in a URL, into the adult device's browser history and the request line. The Decision's "Plain codes exist only on print and in an offline CSV" does not cover this. The conflict is open; this ADR does not settle it, and the threat model written by p0-threat (jade-okb) records it.
OB67 [docs/adr/0011-kit-code-format-and-storage.md Consequences]: - Losing the pepper invalidates every printed code (ARCHITECTURE.md section 6).
OB68 [docs/adr/0013-no-third-party-requests-from-the-browser.md Decision]: No analytics, fonts, CDNs, embeds or error trackers that load in the user's browser. CSP enforces it and an e2e test asserts it.
OB69 [docs/adr/0014-staging-from-phase-1.md Decision]: Staging exists before feature work and is deployed on every merge to main. Production receives the image that passed staging.
OB70 [docs/adr/0020-rate-limit-keys-for-redemption-and-signup.md Decision]: Decided (Mike, 2026-11-14): global throttle for now; per-IP signup limit kept as a toggle (config flag, off by default) for later. Redeem stays per account.
OB71 [docs/adr/0020-rate-limit-keys-for-redemption-and-signup.md Consequences]: - The global throttle is shared by everyone, so anyone submitting wrong codes can delay legitimate redemption and signup for everyone. The threat model written by p0-threat (jade-okb) records this lockout risk.
OB72 [docs/adr/0020-rate-limit-keys-for-redemption-and-signup.md Consequences]: - The sources do not say how the per-account redeem limit and the global throttle interact.
OB73 [docs/adr/0021-split-human-and-agent-work.md Decision]: Production actions stay human.
OB74 [docs/adr/0025-youtube-embedded-module-video.md Decision]: - Everything else in ADR 0013 stays: no third-party scripts, fonts, analytics, error trackers or other embeds. No page without a module video makes any request to another origin.
OB75 [docs/handoff/DATA-MODEL.md Data model]: Names are binding, exact column types may be adjusted if a test shows a reason.
OB76 [docs/handoff/DATA-MODEL.md Data model]: Conventions: `id uuid primary key default gen_random_uuid()` unless stated, `created_at timestamptz not null default now()`, all timestamps `timestamptz`, text enums as `text` with a `check`.
OB77 [docs/handoff/DATA-MODEL.md 1. Products, kits, codes]: create table products (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,            -- 'arm' (placeholder), matches content/<slug>/
  name        text not null,
  code_prefix text not null unique check (code_prefix ~ '^[A-Z]{3}$'),
  created_at  timestamptz not null default now()
);
OB78 [docs/handoff/DATA-MODEL.md 1. Products, kits, codes]: create table code_batches (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references products(id),
  label       text not null,                   -- 'pilot1-v1'
  created_by  uuid references users(id),
  created_at  timestamptz not null default now(),
  unique (product_id, label)
);
OB79 [docs/handoff/DATA-MODEL.md 1. Products, kits, codes]: create table kits (
  id          uuid primary key default gen_random_uuid(),   -- the anonymous kit ID; lifelong
  product_id  uuid not null references products(id),
  batch_id    uuid not null references code_batches(id),
  serial      int  not null,                   -- number printed on the kit label within its batch
  created_at  timestamptz not null default now(),
  unique (batch_id, serial)
);
OB80 [docs/handoff/DATA-MODEL.md 1. Products, kits, codes]: create table kit_codes (
  id            uuid primary key default gen_random_uuid(),
  kit_id        uuid not null references kits(id),
  code_hmac     bytea not null unique,         -- HMAC-SHA256(pepper, normalised code). Never the code.
  entitlements  text[] not null default '{core}',
  status        text not null default 'unused' check (status in ('unused','redeemed','revoked')),
  redeemed_by   uuid references users(id),
  redeemed_at   timestamptz,
  created_at    timestamptz not null default now()
);
OB81 [docs/handoff/DATA-MODEL.md 2. Adults, sessions, invites]: create table users (
  id             uuid primary key default gen_random_uuid(),
  email          citext not null unique,
  password_hash  text not null,                -- argon2id
  display_name   text,
  role           text not null default 'adult' check (role in ('adult','staff')),
  created_at     timestamptz not null default now(),
  disabled_at    timestamptz
);
OB82 [docs/handoff/DATA-MODEL.md 2. Adults, sessions, invites]: create table auth_sessions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  token_hash    bytea not null unique,         -- sha256 of a 256-bit random token
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  expires_at    timestamptz not null
);
OB83 [docs/handoff/DATA-MODEL.md 2. Adults, sessions, invites]: create table invites (
  id           uuid primary key default gen_random_uuid(),
  token_hash   bytea not null unique,
  role         text not null default 'adult',
  created_by   uuid not null references users(id),
  expires_at   timestamptz not null,
  accepted_by  uuid references users(id),
  accepted_at  timestamptz
);
OB84 [docs/handoff/DATA-MODEL.md 3. Classes and student devices]: create table classes (
  id             uuid primary key default gen_random_uuid(),
  owner_id       uuid not null references users(id),
  name           text not null,
  kind           text not null check (kind in ('classroom','camp','home')),
  pilot_label    text,                          -- 'pilot-1', 'pilot-2'; used by analytics filters
  join_code_hash bytea,                         -- set while a session is open
  join_open      boolean not null default false,
  ended_at       timestamptz,                   -- retention clock starts here
  created_at     timestamptz not null default now()
);
OB85 [docs/handoff/DATA-MODEL.md 3. Classes and student devices]: create table class_kits (
  class_id              uuid not null references classes(id) on delete cascade,
  kit_id                uuid not null references kits(id),
  display_number        int  not null,          -- 'Kit 07' as shown to students
  logging_enabled       boolean not null default false,
  consent_confirmed_by  uuid references users(id),
  consent_confirmed_at  timestamptz,
  active                boolean not null default true,
  primary key (class_id, kit_id),
  unique (class_id, display_number)
);
OB86 [docs/handoff/DATA-MODEL.md 3. Classes and student devices]: create table device_sessions (
  id            uuid primary key default gen_random_uuid(),
  class_id      uuid not null,
  kit_id        uuid not null,
  token_hash    bytea not null unique,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  revoked_at    timestamptz,
  foreign key (class_id, kit_id) references class_kits(class_id, kit_id) on delete cascade
);
OB87 [docs/handoff/DATA-MODEL.md 3. Classes and student devices]: create table audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  actor_id    uuid references users(id),
  action      text not null,                    -- 'code.redeem', 'kit.logging_on', 'kit.delete_data', ...
  subject     jsonb not null                    -- ids and counts only; never codes, tokens or note text
);
OB88 [docs/handoff/DATA-MODEL.md 1. Products, kits, codes]: create unique index one_live_code_per_kit on kit_codes(kit_id) where status <> 'revoked';
OB89 [docs/handoff/DATA-MODEL.md 3. Classes and student devices]: create unique index kit_in_one_active_class on class_kits(kit_id) where active;
OB90 [docs/handoff/DATA-MODEL.md 2. Adults, sessions, invites]: Adult email is the only personal information in the system.
OB91 [docs/handoff/DATA-MODEL.md 6. Deletion and retention]: - `delete_kit_data(kit_id)` removes the kit's rows from `events`, `kit_progress`, `facilitator_notes`, `quiz_responses`, `exit_cards` and `device_sessions` in one transaction and writes an `audit_log` row with counts. A test enumerates every table that has a `kit_id` column so a table added later cannot be forgotten.
OB92 [docs/handoff/DATA-MODEL.md 6. Deletion and retention]:   - `kit_progress` and `device_sessions` rows are deleted;
OB93 [docs/handoff/PRIVACY.md Who the data is about]: | Child | Nothing that identifies them. Their group's kit has an anonymous ID. If a quiz is entered, a participant letter (A to D) assigned on paper in class |
OB94 [docs/handoff/PRIVACY.md Who the data is about]: | Facilitator, teacher, parent | Email, optional display name, password hash |
OB95 [docs/handoff/PRIVACY.md Data inventory]: | Adult email, password hash | `users` | Account creation | The adult; staff |
OB96 [docs/handoff/PRIVACY.md Data inventory]: | Audit trail | `audit_log` | Staff and consent actions | Staff |
OB97 [docs/handoff/PRIVACY.md Data inventory]: | Server logs | VM disk, 14 days | Every request | Staff with server access. No IPs, emails, codes, tokens or bodies |
OB98 [docs/handoff/PRIVACY.md Data inventory]: Not collected by JADE at all: child names, photos, audio, free text from students, IP addresses, location, device identifiers, advertising identifiers, third-party cookies.
OB99 [docs/handoff/PRIVACY.md Data inventory]: An optional per-IP limit on code-gated signup holds IP addresses in memory only. It is off by default, and IP addresses are never stored or logged ([ADR 0020](../adr/0020-rate-limit-keys-for-redemption-and-signup.md)).
OB100 [docs/handoff/PRIVACY.md Consent and opt-out]: - Logging is off for every kit until an adult confirms that consent is in hand for each child in that group. The confirmation records who and when.
OB101 [docs/handoff/ARCHITECTURE.md 4. Components]: | `auth` module | Adult accounts and sessions, staff role, invites, student device sessions, authorization | |
OB102 [docs/handoff/ARCHITECTURE.md 4. Components]: | `codes` module | Generate, normalise, HMAC, redeem, revoke kit codes | |
OB103 [docs/handoff/ARCHITECTURE.md 4. Components]: tools/                                                  code generator, video prepare, QR export
OB104 [docs/handoff/ARCHITECTURE.md 4. Components]: Modules call each other only through their `index.ts`. That is the whole "architecture enforcement" for a monolith this size.
OB105 [docs/handoff/ARCHITECTURE.md 5. Users and access]: | Staff | Adult account with staff role | Everything, plus codes admin, analytics, exports, deletion |
OB106 [docs/handoff/ARCHITECTURE.md 5. Users and access]: 1. Facilitator signs in, creates a class, redeems the kit codes into it (scan each card's QR).
OB107 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: Format `ARM-7KQ4-XM2H-9`: a 3-letter product prefix (placeholder `ARM` until the kit is named), 8 random Crockford Base32 characters, 1 check character. Crockford drops I, L, O and U, so codes survive being read aloud by a child.
OB108 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: - 8 Base32 characters are 40 bits, about 1.1 trillion combinations. That defeats online guessing behind a rate limit. It does **not** defeat offline brute force of a leaked table of plain hashes, which is why the database stores `HMAC-SHA256(pepper, code)` with a server-side secret, not `SHA-256(code)`.
OB109 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: - The plain code exists in two places only: the printed card and the packing CSV kept offline.
OB110 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: - A code maps to a `kit_id`. The kit keeps that ID for life, across pilots and classes, so a reused kit has one history.
OB111 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: - Redemption is single-use, transactional and audited. Staff can revoke and reissue.
OB112 [docs/handoff/ARCHITECTURE.md 6. Kit codes]: - Losing the pepper invalidates every printed code. Its backup procedure is a launch task (`p10-secrets`).
OB113 [docs/handoff/ARCHITECTURE.md 9. Security and privacy]: | Guessing kit codes online | Rate limit per account, lockout, check character rejects most typos before the server |
OB114 [docs/handoff/ARCHITECTURE.md 9. Security and privacy]: | Brute-forcing a leaked code table | HMAC with server-side pepper |
OB115 [docs/handoff/ARCHITECTURE.md 9. Security and privacy]: | Student reaching adult or staff pages | Route-group authorization matrix, 404 not 403 |
OB116 [docs/handoff/ARCHITECTURE.md 9. Security and privacy]: | IP addresses as hidden identifiers | Not logged by Caddy or the app; used in memory for rate limiting only |
OB117 [docs/handoff/ARCHITECTURE.md 10. Deployment]: - **Releases:** build image, run forward-only migrations, start, health-check, switch. Rollback is the previous image. Migrations stay compatible with the previous app version.
OB118 [docs/threat-model.md 5. Abuse cases]: | AB1 | Guessing kit codes online | Check character rejects most typos before the server (jade-fd5); failed redemptions limited per account, 10 an hour then locked (jade-7if); a global failed-code throttle on redeem and code-gated signup (jade-7if, jade-vcy, jade-6cq); per-IP signup limit behind a flag, off by default (jade-vcy, jade-6cq) (ADR 0020) | Phase 2 p2-code-lib jade-fd5, p2-redeem jade-7if; Phase 3 p3-adult-auth jade-vcy; Phase 9 p9-ratelimit jade-6cq | jade-fd5 typo property test; jade-7if lockout test; jade-6cq flag off/on and global-throttle tests; jade-sio |
OB119 [docs/threat-model.md 5. Abuse cases]: | AB2 | Brute-forcing a leaked code table | HMAC-SHA256 under the server-side pepper (jade-fd5, jade-o07; ADR 0011); pepper only in the env file and the offline store (jade-8v4, jade-lnn.1, jade-fgs); backups encrypted (jade-6o3) | Phase 1 p1-config jade-8v4; Phase 2 p2-code-lib jade-fd5, p2-schema-core jade-o07; Phase 10 jade-lnn.1, p10-secrets jade-fgs, p10-backups jade-6o3 | jade-fd5 "HMAC uses the pepper from config"; jade-o07 "No column stores a plain kit code"; jade-sio |
OB120 [docs/threat-model.md 5. Abuse cases]: | AB7 | Student reaching adult or staff pages | Route-group authorization matrix, 404 not 403 (jade-aq5); every new route enters the matrix test (jade-aq5) | Phase 3 p3-authz-tests jade-aq5 | jade-aq5 matrix test; jade-sio |
OB121 [docs/threat-model.md 5. Abuse cases]: | AB11 | Tripping the global failed-code throttle to block legitimate redemption and signup (beyond ARCHITECTURE.md section 9) | Accepted consequence of ADR 0020 (TM-6); the throttle threshold is set and tested (jade-6cq). The sources do not say how the per-account redeem limit and the global throttle interact, and code-gated signup has no account to limit (ADR 0020) | Phase 9 p9-ratelimit jade-6cq | jade-6cq global-throttle test; jade-sio |
OB122 [docs/threat-model.md 5. Abuse cases]: | AB16 | A plain kit code leaking from the QR redeem URL (`/redeem?code=...`) into server logs or a Referer header (beyond ARCHITECTURE.md section 9) | App log lines contain no code values (jade-alt); a grep of staging logs after a full e2e run finds no codes (jade-ada); `Referrer-Policy: no-referrer` (jade-c42, p9-headers description) | Phase 1 p1-observability jade-alt; Phase 9 p9-logs jade-ada, p9-headers jade-c42 | jade-alt "no IP, cookie or code values" test; jade-ada grep; jade-c42 header assertions; jade-sio |
OB123 [docs/threat-model.md 7. Open until the human beads close]: - TM-4 (open): Scanning a code card's QR leaves the plain kit code in the adult device's browser history (`/redeem?code=...`, p2-code-cli jade-99j). No bead addresses it, and only single-use redemption (jade-7if) limits its value. Whether p2-redeem should keep the code out of the URL after the scan, or this is accepted, is not decided. ADR 0011 records the same conflict with its statement that plain codes exist only on print and in an offline CSV.
OB124 [docs/threat-model.md 7. Open until the human beads close]: - TM-5 (open): Joining writes a `device_sessions` row (which has a `last_seen_at` column, DATA-MODEL.md section 3) for a kit with logging off. Whether that is stored activity under CLAUDE.md rule 2 ("the server stores nothing about that kit's activity") is not decided; the no-log invariant of p6-nolog-invariant (jade-hhp) lists events, kit_progress, notes and quiz tables only. This document records the fact; it does not answer the question.
OB125 [docs/threat-model.md 6. Retention and deletion paths]: - **Rate-limit counters.** IP addresses are used in memory only and never written to disk (p9-ratelimit jade-6cq; ADR 0020). Where the other counters live is not decided (section 4, `RL_MEM`).
OB126 [docs/threat-model.md 6. Retention and deletion paths]: - **Kits and kit codes.** A kit keeps its id for life (ARCHITECTURE.md section 6); staff can revoke and reissue a code, keeping the kit id (p2-staff-codes jade-pe9), and a revoked code row stays with status `revoked` (DATA-MODEL.md section 1). No source gives `kits` or `kit_codes` a deletion rule.
OB127 [docs/threat-model.md 6. Retention and deletion paths]: - **Audit log.** `audit_log` holds actor ids and ids and counts only, never codes, tokens or note text (DATA-MODEL.md section 3); kit deletion adds a row to it (jade-l13). No source gives it a retention or deletion rule.
OB128 [docs/threat-model.md 6. Retention and deletion paths]: - **Printed cards and packing CSV.** The CLI warns that the files are the only copy (jade-99j), and the CSV is stored offline (p10-codes jade-t17). No source says when they are destroyed; a used code is spent by single-use redemption (jade-7if).
OB129 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **Files are immutable once merged.** A merged file is never edited, renamed, reordered or
  removed. There is no down migration and no way to reapply a file: a mistake is corrected by a
  new migration.
OB130 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **`manifest.json` is the lock.** It lists every file's name and SHA-256 in order. The runner
  refuses files that do not match it, and stops with `MIGRATION_HISTORY_MISMATCH`, applying
  nothing, when an applied file's name or hash differs from the ledger (`schema_migrations`).
  The manifest is also what the app ships to know which migrations it needs (readiness).
OB131 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **Compatible with the previous release.** A deploy migrates before the new app starts, and a
  rollback runs the previous image on the new schema. So a migration may add schema objects
  (tables, columns, indexes, grants), and may drop or rename only an object that the previous
  release's code no longer reads: a destructive change ships one release after the code stops
  using the object.
OB132 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **Destructive statements are marked.** A file with `DROP`, `TRUNCATE`, `RENAME`, `REVOKE`,
  `DELETE`, a column type change or `SET NOT NULL` carries a line
  `-- jade:contract <bead>` naming the bead that removed the last reader. `pnpm db:check`
  refuses the file without it.
OB133 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **One transaction per file.** The runner applies each file in its own transaction together
  with its ledger row; a failure rolls the file back. A statement that cannot run inside a
  transaction is out of scope until one is needed. A file holds no transaction-control
  statement (`BEGIN`, `COMMIT`, `ROLLBACK`, `END`, `ABORT`, `START TRANSACTION`, `SAVEPOINT`,
  `RELEASE`): one would commit the file apart from its ledger row. `pnpm db:check` refuses it.
OB134 [migrations/README.md Rules (forward-only, plan U5 and INV5)]: - **Grants to `jade_app` by name.** The app connects as `jade_app` and owns nothing; the owner,
  `jade_owner`, runs migrations. Every new table needs its grants to `jade_app` in the same file.
OB135 [migrations/README.md Writing one]: - Commit the `.sql` file, `manifest.json` and `meta/` (Drizzle Kit's journal and snapshot)
  together. `pnpm db:check` must pass.
OB136 [migrations/README.md Migrations]: Drizzle Kit's `migrate` and
`push` commands are never used.

--- DISPOSITIONS IN THIS REVISION ---
SHRINK ## 3. Contradictions and gaps: C9's sentence on subject values says row ids (uuids) and non-negative integers instead of row ids, integers and booleans, and points to PD10 (R18); no obligation affected.
SHRINK ## 4. Cross-cutting decisions: the black-box row of PD11's table names generatedEnv(appEnv) instead of generatedEnv(), as section 1 states it (R18 sweep); no behaviour or obligation affected.
SHRINK ## 6. jade-o07: core schema: SC5's value types for audit subjects drop booleans to match PD10 and say a boolean is refused (R18); no obligation affected.
SHRINK ## 9. jade-7if: redemption service: RD3 step 2 uses appCodeKey and its keyed cache (R16) and the seam sentence is replaced by prepareRedemption, PreparedCode and the typed redeemWithin (R17); RD7's redeem, audit-subject and key-check sentences gain cases (R16, R17, R18); RD8's caching sentence is replaced by the keyed cache (R16); RD10's codeContext and redeemWithin sentences are restated (R16, R17); no check removed, no obligation affected.
SHRINK ## 10. jade-99j: batch generator: GN1's opening and context lines state loadCodeToolConfig, createBatch and ensureProduct in one form each (R18); GN2's start-order line uses that form in step (ii) and says createBatch() runs steps 1 to 8 in step (v) (R17 sweep, R18), followed by a new line on checks living in the functions; GN6 names generatedToolEnv(appEnv) and GN8 createBatch(ctx, input, output) (R18); no check removed, no obligation affected.
SHRINK ## 13. Interleavings: T2's test goes through prepareRedemption and redeemWithin instead of redeemWithin alone (R17); no check removed, no obligation affected.
SHRINK ## 14. Later-phase consumers: the jade-vcy row gets prepareRedemption and PreparedCode and must call prepareRedemption before the signup transaction (R17); no obligation affected.
FIX R16
FIX R17
FIX R18

--- FINDINGS (Beads, at dispatch) ---
| ID | severity | state | raised in call | fixes proposed | resolution |
|---|---|---|---|---|---|
| R1 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R2 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R3 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R4 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R5 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R6 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R7 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R8 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R9 | medium | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R10 | low | verified | 2 | 1 | reviews/call-003-a1/receipt.json |
| R11 | low | verified | 3 | 1 | reviews/call-004-a1/receipt.json |
| R12 | medium | verified | 4 | 1 | reviews/call-005-a1/receipt.json |
| R13 | low | verified | 4 | 1 | reviews/call-005-a1/receipt.json |
| R14 | low | verified | 4 | 1 | reviews/call-005-a1/receipt.json |
| R15 | low | verified | 4 | 1 | reviews/call-005-a1/receipt.json |
| R16 | low | fix_proposed | 5 | 1 | - |
| R17 | low | fix_proposed | 5 | 1 | - |
| R18 | low | fix_proposed | 5 | 1 | - |

