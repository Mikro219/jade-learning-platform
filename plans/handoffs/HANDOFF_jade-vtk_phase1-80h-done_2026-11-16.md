# Phase 1: jade-h8i, 8v4, urd, alt, the review-correction round and jade-80h committed; next is jade-xu0 (blocked on Q1) or jade-lhq

**Date:** 2026-11-16
**Status:** IN PROGRESS (Phase 1, 5 of 8 beads implemented and committed; none closed, by Q2(a))
**Bead(s):**
- jade-h8i, jade-8v4, jade-urd, jade-alt, jade-80h (implemented, committed, claimed, open)
- jade-f1w, jade-7yz, jade-r7c, jade-zwq (review-correction round, committed in 320e73a, open)
- jade-e9a (FaultForge MCP wiring, closed)
**Epic:** jade-vtk, Phase 1: Foundation and walking skeleton
**Chain:** `jade-vtk` seq `3`
**Parent:** `HANDOFF_jade-vtk_phase1-plan-approved_2026-11-15.md`
**Prior chain:** `HANDOFF_jade-vtk_phase0-done-phase1-next_2026-11-14.md` > `HANDOFF_jade-vtk_phase1-plan-approved_2026-11-15.md` > this

---

## Since Last Handoff

- Parent step 1 (commit the planloop run dir): done at the start of the previous session.
- Parent step 2 (Mike's go-ahead): given as "go, section 16 order; trunk stays master for now", then "actually rename master to main". The trunk is now `main` (`git branch -m master main`).
- Parent step 3 (plan-added dependencies): added before the first claim.
- Parent step 4 (jade-h8i): done, 30b291b. Mike ran the Playwright `--with-deps` install himself through `~/jade-pw-install.sh`, after three failed attempts (see What We Tried).
- Parent step 5 (beads in section 16 order): jade-8v4 (48a0bec), jade-urd (4e7790a), jade-alt (e3641ae), then a correction round for retro review findings (320e73a), then jade-80h (6533ba8). The order actually followed is section 16's: h8i, 8v4, urd, alt, 80h. The next in that order is jade-xu0, then jade-lhq.
- New standing rules from Mike this chain: two Opus post-implementation reviewers after every implementation round, and lows-only reviews are fixed and committed by the orchestrator directly. See User Feedback.
- Q1 is still unanswered and now blocks the next bead in order (jade-xu0).
- A FaultForge MCP server was wired up (jade-e9a, closed), with three scenario beads blocked on FaultForge M11.

## Reference Documents

- `CLAUDE.md`: rules 1 to 8, the orchestrator/subagent model, context thresholds, the handoff rule.
- `plans/planloop/jade-vtk.pl1/rev-005/plan.md`: the approved Phase 1 plan. Section 11 is jade-80h, section 12 is jade-xu0, section 13 is jade-lhq, section 14 is jade-4zw, section 16 is the order and stop points, section 18 is the open questions.
- `docs/adr/README.md` and `docs/adr/0015-tooling.md` (k6 for load; checked for the FaultForge decision).
- `/home/mikep/projects/fault-forge/docs/MCP.md`: the FaultForge MCP server's docs (read-only; never edit that repo).
- `~/projects/quartz-rs/CLAUDE.md` "Post-implementation review": the pattern the two-reviewer rule copies.

## The Goal

Build Phase 1 (Foundation and walking skeleton) of the JADE learning platform, bead by bead in the approved plan's section 16 order, each implemented by a subagent, re-verified by the orchestrator, reviewed by two independent Opus reviewers, and committed on its own branch with Mike's authorization. Phase 1 ends with a scaffold, typed config, a Postgres migration tool and test harness, health endpoints and a closed logger, a production image and Compose stack, CI, a layout baseline, and (blocked on jade-0za) staging. Beads stay open until CI exists (Q2 (a)).

## Where We Are

- Branch chain (each cut from the previous): `jade-h8i` → `jade-8v4` → `jade-urd` → `jade-alt` → `jade-f1w` → `jade-80h`. HEAD is `jade-80h` at 6533ba8. Nothing is merged into `main`; no remote exists.
- Working tree: clean except `.beads/interactions.jsonl` (bd's own log; never staged without being asked) and the untracked, locally excluded `.mcp.json`.
- No Docker leftovers: no jade Compose projects, no `jade-app:*` tags, no `.env`. The dev DB `jade-dev-255efdb2` is down with `-v`.
- Pinned images present locally: `postgres:16.16-bookworm`, `caddy:2.11.9-alpine`, `node:24.22.3-alpine3.24`.
- jade-80h delivered:
  - `Dockerfile`: two `node:24.22.3-alpine3.24` stages; build stage `pnpm install --frozen-lockfile --no-runtime`, `ARG APP_VERSION` right before `pnpm build`, then `rm -rf node_modules && pnpm install --prod --frozen-lockfile --no-runtime --offline`; runtime holds `build/`, prod `node_modules`, `package.json`, `migrations/`, `tools/`, `src/lib/server/{config,db,log}`; `USER node`; `HEALTHCHECK --start-interval=1s` on `/healthz`; `CMD ["node","build"]`. No `# syntax=` line (removed: unpinned network fetch).
  - `.dockerignore`: denylist incl. `.git`, `.env*`, `node_modules`, `docs/`, `plans/`, `.beads/`, `.claude/`, `tests/`, plus `.mcp.json`, `.npmrc`, `*.pem`, `*.key` at root and `**/`.
  - `compose.prod.yml`: services `db` (named volume `db-data`, backend only), `migrate` (one-shot, read-only, caps dropped), `app` (`image: ${JADE_IMAGE:-jade-app:local}` with the one `build:` stanza, read-only root, tmpfs `/tmp`, caps dropped, no-new-privileges), `caddy` (only service with ports `${JADE_HTTP_PORT:?}:80`, `${JADE_HTTPS_PORT:?}:443`; `cap_drop: [ALL]`, `cap_add: [NET_BIND_SERVICE]`, no-new-privileges; volumes `caddy-data`, `caddy-config`, `media` read-only). Networks `edge` and `backend` (internal). json-file logs 10m × 5. Top-level `name: jade-stack`. Reads none of `${APP_ENV`, `${DATABASE_URL`, `${MIGRATION_DATABASE_URL`, `${JADE_DEV_DB_PORT`; `APP_ENV` comes from `JADE_STACK_APP_ENV`.
  - `deploy/caddy/Caddyfile`: `{$SITE_ADDRESS}`, `encode zstd gzip`, no site `log`, global `log default { format filter { wrap json; fields { request delete } }; exclude http.stdlib }`, `skip_install_trust`, `servers { protocols h1 h2 }`, `handle /media/* { respond 403 }`, `reverse_proxy app:3000 { header_up -X-Forwarded-For }`. `deploy/caddy/media-files.caddy` holds the file-server directives, not imported. The whole `deploy/caddy` folder mounts read-only at `/etc/caddy`.
  - `package.json`: `ci:image` = `node tools/compose.ts with-stack-env docker buildx bake --file compose.prod.yml --load app`; `test:infra` = `vitest run --project infra`; `stack:up` / `stack:down`; `pnpm test` excludes infra (`--project '!infra'`).
  - `tools/compose.ts`: `run(command, args, env, {timeoutMs, quiet, newGroup})`, `imageCacheArgs()` (`JADE_CI_IMAGE_CACHE`), `withStackEnv` (refuses with exit 2 if `JADE_IMAGE` unset), `stackUp`, `stackDown(project, env)`, `stackUpArgs`, `downArgs(project, dir)`, `minimalDockerEnv()`, `stackProjectName()` = `jade-stack-<8 hex of sha256 of checkout realpath>`.
  - `tools/env-init.ts`: `stack` profile (`--app-env staging|production`, `--site <host>`), refuses misplaced flags, never echoes `--site`; generated passwords `[A-Za-z0-9_-]`.
  - `tests/infra/`: `image`, `compose-config`, `compose-up`, `caddy-logs`, `media`, `stack-up` `.test.ts`, `global-setup.ts`, fixtures (`caddy/Caddyfile`, `migrations/0001_infra_fixture.sql`). Helper `tests/support/infra.ts` (`INFRA_PROJECT_SUFFIXES`, `infraProject`, `startStack`, `stopStack`, `downProject`, `isRunProject`, `mediaFilesContainer`, `MEDIA_FILES_LABEL`). New `tests/unit/compose-tool.test.ts`.
  - `.claude/skills/bugfix/SKILL.md` "The gates": the U8 sentence that `compose.prod.yml` never joins a gate's project.
- Final measured: image `.Size` 65,571,491 B; unpacked (`du -skx /` ×1024) 208,859,136 B; `docker images` DISK USAGE 275MB, CONTENT SIZE 65.6MB.
- Final gates on 6533ba8's tree: lint 0, check 0 (961 files), test 0 (24 files / 349), e2e 0 (6), test:infra 0 (6 files / 89, ~190-270 s). `pnpm ci:clean-clone` exit 0 for 6533ba87276fabffe2903c11be8237ea902d988c.
- The correction round 320e73a: clean-clone exit 0 for 320e73a8533756d3ad0965073475e440832dd45b.
- FaultForge: `faultforge_status` ok; `faultforge_list_scenarios` on this repo returns `config_invalid` (no `faultforge.yaml`), so the allowlist works.

## What We Tried (Chronological)

1. **Playwright browser install (jade-h8i).** Attempt 1 used the plan's PATH line without `/bin`, so the Windows pnpm shim ran on Node 20 and crashed. Attempt 2: the pasted line wrapped. Attempt 3: `sudo` had no TTY through `!`. Fix: a script `~/jade-pw-install.sh` that Mike ran in his own terminal. Lesson: the PATH prefix must include `$HOME/.local/share/pnpm/bin`, and multi-line or sudo commands go in a script, not a `!` paste.
2. **jade-urd `migrations-static` timeout.** `db:check` hit the 5 s default under parallel load; raised to 30 s.
3. **jade-alt review fixes.** A1 EADDRINUSE retry broken, A2/B2 readiness label, B1 (statement/lock timeouts so stalled queries end server-side), B3, A3, A4 (logger never throws). All fixed before e3641ae.
4. **Retro review of the three earlier commits** (Mike: "yes, review the three earlier commits too"). Found jade-f1w (DB URL `?host=`/`?user=` bypass of the reset guard and app-role check), jade-7yz (build read `.env`), jade-r7c (Playwright URL readiness could pass against a foreign process) plus lows. Pass 1 of the fixes found SvelteKit's own `loadEnv`, the isolation test needing 2 workers, and the env-init temp file not gitignored; pass 2 fixed those; pass-2 reviewers READY with lows (jade-a5u).
5. **Committing 320e73a.** The auto-mode classifier returned no verdict on Bash/Write 6 times in a row; stopped short of the 10-in-a-row turn limit and reported. Mike's `!` commit failed because the pasted path wrapped (pathspec error, nothing committed). The classifier recovered next turn and the commit went through from a message file in the scratchpad.
6. **clean-clone refused a dirty tree** because of `.beads/interactions.jsonl`. Rather than touch bd's log, ran `tools/ci/clean-clone.sh` from a temporary `git worktree add --detach` of the commit, then removed the worktree. Used for both 320e73a and 6533ba8.
7. **FaultForge `.mcp.json`.** Written at the root, uncommitted, excluded via `.git/info/exclude`. Prettier then failed `pnpm lint` on it (Prettier doesn't read `.git/info/exclude`); fixed by formatting the file, not by editing `.prettierignore`.
8. **jade-80h implementation.** Subagent built it to plan section 11. `pnpm install --prod` left 209 MB of dev packages in `node_modules/.pnpm`; replaced with `rm -rf node_modules && pnpm install --prod ... --offline`. Node type stripping works in the image, so D1's fallback (compile the migration tool) was not needed. Negative control: removing the Caddy log filter made 4 checks fail (request object, canaries, client address 172.22.0.1 appear).
9. **jade-80h review pass 1.** A: NOT READY (M1 size test measured compressed `.Size` on the containerd store; M2 CI can't pass gha cache flags). B: two mediums (B1 a stack still starting isn't torn down on hook timeout; B2 interrupted runs leak `jade-infra-*` projects that self-restart). Fix round 1: 16 items (4 mediums + 12 lows).
10. **Fresh-image-store pass** (plan section 11 last check, bead note D1), combined with the host gate after round 1. Passed (see Evidence). `pnpm test` hit a 5 s timeout in `log-schema.test.ts` "the app registers its own fixed tags" (dynamic import under load), the second time it was seen.
11. **Review pass 2.** Both READY WITH LOWS; B had one medium (ciImage timeout killed only pnpm and waited on 'close', so a stalled bake hung the run). Round 2: 6 items (process-group kill, exact project suffix matching, media container sweep, file-less `down` with `--project-directory` an empty dir and a minimal env, teardown robustness, 30 s timeout on the flaky test).
12. **Reviewer B check of round 2: NOT READY** (M1 nested process groups: `with-stack-env` called `run()` again, putting bake in its own group G2 that the outer timeout missed; M2 destroying pipes on 'exit' dropped trailing output, including the port-taken message). Round 3: `RunOptions.newGroup` (with-stack-env passes false), wait up to 2 s for 'close' before destroy, README Ctrl-C wording, stackDown temp dir cleanup on exit. A nested-group unit test fails deterministically on the old code (pg ≠ ppid).
13. **Stopping my stale gate run** (it would `down -v` the dev DB the agent's round-3 gates were using) leaked one `jade-app:ci-255efdb2-d0cc0c41d1bca2bd` tag: the same single-Ctrl-C leak the reviewer described. Removed by exact tag.
14. **Reviewer B check of round 3: READY WITH LOWS.** Under Mike's new rule the orchestrator fixed L1 itself (test cleanup could SIGKILL an unrelated process group after pid reuse; now gated on `/proc/<bg>/cmdline` = `sleep\060\0`, pgid ≠ own pgid, pgid ∈ {pg, ppid, bg}), re-ran lint/check/test, and committed 6533ba8 without a separate OK.

## Key Decisions

- **`.mcp.json` not committed.** It names an absolute path to Mike's local fault-forge checkout; it would break elsewhere and in CI. Excluded via `.git/info/exclude`. Rejected: committing it, or adding it to `.gitignore` (a committed change for a machine-local file). Recorded in jade-e9a.
- **No planloop and no decision bead for FaultForge.** One local config file, no app code; ADR 0015's k6 stays the load tool, FaultForge only adds checks.
- **FaultForge use timing.** Not in Phase 1 (no concurrency rule exists). First use is jade-7if (p2-redeem) in Phase 2, then jade-zg3 and jade-hhp in Phase 6; scenario beads jade-4el, jade-bnk, jade-0nf are blocked on their feature bead and on jade-cdw (FaultForge M11). An image-source run (prebuilt `jade-app` in `allowed_images`) could come earlier, but only if Mike chooses; his brief said not to work around M11.
- **clean-clone from a detached worktree** instead of committing or stashing bd's `interactions.jsonl`.
- **Image size measured both ways.** `.Size` on the containerd store is compressed; the AC means unpacked, so `du -skx /` (run as 0:0 with `--entrypoint du`) is also asserted < 300,000,000. Rejected: engine disk-usage fields (differ by store).
- **CI cache via one variable** `JADE_CI_IMAGE_CACHE=gha` mapped to exactly `--set app.cache-from=type=gha --set app.cache-to=type=gha,mode=max`; anything else refused. Keeps `package.json`'s `ci:image` free of `--set` (a compose-config test requires that).
- **`ci:image` refuses without `JADE_IMAGE`**, so it never retags the shared `jade-app:local` (reserved for the bare README command).
- **Process groups:** `run()` owns a group by default; `with-stack-env` uses `newGroup: false` so bake stays in its caller's group (global setup's, or the terminal's).
- **Teardown by exact name only:** `isRunProject` = equality with `infraProject(suffix, runId)` for a suffix in `INFRA_PROJECT_SUFFIXES = ['pull','config','up','caddylogs','media','stackup']`. Rejected: a regex prefix (hyphenated run ids widened it to other runs).
- **Deferred lows** filed rather than fixed: jade-3nx (jade-80h), jade-a5u (correction round).

## Evidence & Data

### Commits (all on the branch chain, none on main)

| SHA | Branch | Summary | clean-clone |
|---|---|---|---|
| 30b291b | jade-h8i | scaffold, Node 24 pin, ADR 0024 | 0 |
| 48a0bec | jade-8v4 | typed zod config, fail-fast boot, env:init | 0 |
| 4e7790a | jade-urd | dev compose, migration runner, test DB harness | 0 |
| e3641ae | jade-alt | closed JSON logger, /healthz, /readyz, request ids, error page (+jade-b1f) | 0 |
| 320e73a | jade-f1w | review corrections (jade-f1w, 7yz, r7c, zwq) | 0 |
| 6533ba8 | jade-80h | production image, compose.prod.yml with Caddy, infra suite | 0 |

### jade-80h review iterations

| Round | Reviewer A | Reviewer B | Action |
|---|---|---|---|
| Pass 1 | NOT READY: M1 size, M2 CI cache | READY WITH LOWS, 2 mediums (B1, B2) + 8 lows | fix round 1 (16 items) |
| Pass 2 | READY WITH LOWS (4 lows) | READY WITH LOWS, 1 medium (ciImage timeout) + 6 lows | fix round 2 (6 items) |
| Round-2 check | not run | NOT READY: M1 nested groups, M2 trailing output | fix round 3 (4 items) |
| Round-3 check | not run | READY WITH LOWS (4 lows) | orchestrator fixed L1, committed |

### Gate history for jade-80h

| Run | lint | check | test | e2e | test:infra | Notes |
|---|---|---|---|---|---|---|
| Implementer, initial | 1 (.mcp.json) | 0 | 0 (23/329) | 0 (6) | 0 (6/84, 316 s) | |
| Host, initial | 0 | 0 | 0 (23/329) | 0 (6) | 0 (6/84) | after formatting .mcp.json |
| Implementer, round 1 | 0 | 0 | 0 (24/344) | 0 | 0 (6/89, 211 s) | one log-schema flake on first run |
| Host + fresh store, round 1 | 0 | 0 | 1 (log-schema 5 s timeout) | 0 | 0 (6/89, 271 s) | |
| Implementer, round 2 | 0 | 0 | 0 (24/347) | 0 | 0 (6/89, 198 s) | |
| Implementer, round 3 | 0 | 0 | 0 (24/349) | 0 | 0 (6/89, 191 s) | |
| Host, round 3 | 0 | 0 | 0 (24/349) | 0 (6) | 0 (6/89) | |
| Host, after L1 edit | 0 | 0 | 0 (24/349) | — | — | committed |

### Image sizes

| Measure | Initial | Round 1 | Final |
|---|---|---|---|
| `.Size` (containerd: compressed) | 65,568,796 | 65,569,921 | 65,571,491 |
| unpacked `du -skx /` ×1024 | ~210 MB (implementer) | 208,855,040 | 208,859,136 |
| `docker images` DISK USAGE / CONTENT SIZE | 275MB / 65.6MB | same | same |

### Fresh-image-store pass (recorded in jade-80h notes)

```
bugfix- containers: []
db:down=0
ancestor postgres:16.16-bookworm: []
ancestor caddy:2.11.9-alpine: []
rmi=0  (pg absent, caddy absent)
test:infra=0 (271s)
infra setup: pulling caddy, db (caddy:2.11.9-alpine, postgres:16.16-bookworm)
db:up(2)=0
ledger rows before=1, after=1
```

### FaultForge verification (jade-e9a close reason)

```
faultforge_status: status ok; docker reachable, 0 sandbox containers; images faultforge-target/runner/stack-hooks:dev present;
  runtimes.local.available true, remote unavailable (M12); fix_modes.client.available true, vultr unavailable (M10), auto=client;
  allowed_roots [/home/mikep/projects/fault-forge/demo, /home/mikep/projects/jade]; config_problems []; credit null (M10)
faultforge_list_scenarios(/home/mikep/projects/jade): error_class config_invalid, "faultforge.yaml doesn't exist"
```

### Data files (scratchpad; may be cleared by a reboot)

- `/tmp/claude-1000/-home-mikep-projects-jade/30ab10e7-96ae-4ef5-aa6c-f5b4427fb995/scratchpad/fs/` — fresh-store run logs (`infra.log`, `test.log`, ...).
- `.../scratchpad/g4/`, `.../scratchpad/g5/` — round-3 and post-L1 gate logs.
- `.../scratchpad/clean-clone-320e73a.log`, `.../scratchpad/clean-clone-6533ba8.log`.
- `.../scratchpad/fresh-store.sh` — the fresh-store procedure script (reusable for CI-host checks).
- `.../scratchpad/commit-msg-f1w.txt`, `.../scratchpad/commit-msg-80h.txt`.

### Bead index (state at handoff)

| Bead | What | State |
|---|---|---|
| jade-h8i | scaffold | in progress (committed 30b291b) |
| jade-8v4 | typed config, secrets | in progress (48a0bec) |
| jade-urd | Postgres, migrations, test harness | in progress (4e7790a) |
| jade-alt | health, logs, request ids | in progress (e3641ae) |
| jade-b1f | jade-alt review fix | closed |
| jade-f1w | bug: DB URL query bypass | in progress (320e73a) |
| jade-7yz | bug: build read .env | in progress (320e73a) |
| jade-r7c | bug: Playwright URL readiness | in progress (320e73a) |
| jade-zwq | err_tag tightening (Mike-authorized schema change) | in progress (320e73a) |
| jade-80h | prod image + compose.prod.yml | in progress (6533ba8) |
| jade-xu0 | CI pipeline | open, next in order, needs Q1 |
| jade-lhq | layout, tokens, a11y | open, workable now |
| jade-4zw | staging | blocked by human bead jade-0za |
| jade-a5u | lows from correction-round reviews | open P2 |
| jade-3nx | lows from jade-80h reviews | open P2 |
| jade-cev | bugfix skill step 6.2 gate command | open P2 |
| jade-hap | readiness pool vs app pool | open P2 (decide before Phase 2 adds a Drizzle pool) |
| jade-hh8 | watch-mode blackbox build staleness | open P3 |
| jade-hwu | TEMP privilege | deferred (Mike: "hwu: defer") |
| jade-e9a | FaultForge MCP wiring | closed |
| jade-cdw | external: FaultForge M11 placeholder (label external) | open P3 |
| jade-4el / jade-bnk / jade-0nf | FaultForge scenarios for jade-7if / jade-zg3 / jade-hhp | open P2, blocked on feature + jade-cdw |

### Earlier beads in this chain (from the previous session, before compaction)

- jade-h8i: SvelteKit 3.2.0, adapter-node 6.0.2, Vite 8.3.8, Vitest 5.1.0, Playwright 1.65.1 (Chromium + WebKit), TypeScript 6.0.3, ESLint 10; route registry and its tests; e2e smoke and no-off-origin; `tools/ci/clean-clone.sh`; `tools/free-port.ts`; ADR 0024 (Node 24) plus ADR 0015/README edits.
- jade-8v4: `loadAppConfig`/`getConfig`/`ConfigError`/`reportConfigError` (names only in errors), the `init` hook exits 1 on ConfigError and is skipped while building; `tools/env-init.ts` (atomic write via `<basename>.tmp-<pid>-<hex>` + `linkSync`, EPERM/ENOTSUP/EXDEV fallback), `tools/load-env.ts`, `.env.example`.
- jade-urd: `compose.dev.yml` (`devdb`, `127.0.0.1:${JADE_DEV_DB_PORT:?}`, volume `devdb-data`), own migration runner (per-database and cluster-wide advisory locks via `pg_try_advisory_lock` loop with 60 s limit, SCRAM verifier, ledger `schema_migrations` + manifest), roles `jade_owner` (migrations) and `jade_app`, per-test-file template-cloned DBs.
- jade-alt: closed JSON logger (forbidden-key parts; stack frames only from `Error.prepareStackTrace` call sites in a WeakMap), request id generated per request (client id ignored), `/healthz`, `/readyz` (one query on the app-role pool, 2 s limit, `statement_timeout`/`lock_timeout`, `readinessOfFailure` maps SQLSTATE classes 08/28/3D/53/57 to `db: fail`), `/dev/boom`, `+error.svelte`.

### Working method that held up this session

- Implementer: one `general-purpose` subagent on `model: opus` per bead, resumed with `SendMessage` for each fix round so it keeps context. Its brief names the plan section, the files to read, the gates, and the hard limits (no other projects' Docker resources, no prune/`--remove-orphans`/broad `rmi`, keep pinned tags, no git/bd writes, no secrets printed, no ADR/logger-schema changes, no scope widening).
- Reviewers: read-only `Plan` agents on `model: opus`, static review only while gates run (they share the tree, not the Docker state). Different mandates for A (correctness, tests prove claims, PD15) and B (failure modes, teardown, signals, foreign resources). After a fix round, a targeted re-review of only the changed files is enough; list already-deferred items so they aren't repeated.
- The orchestrator verifies every medium by reading the cited lines before sending it on, files lows not worth fixing in one deferred-lows bead per round, and records every gate exit status in the bead's notes.

### Environment gotchas

- PATH prefix for every pnpm call: `export PNPM_HOME="$HOME/.local/share/pnpm" PATH="$HOME/.local/share/pnpm/bin:$PATH"`. System Node is v20; Node 24.22.3 comes via `devEngines.runtime`.
- Port 5432 is held by quartz; `pnpm env:init` picks a free port. Always `unset COMPOSE_PROJECT_NAME` before `pnpm db:up`.
- Docker uses the containerd image store (`.Size` is compressed). Compose v5.4.0, Docker client 29.7.2.
- Long-running `sleep 300` loops on the machine belong to a quartz-rs Claude session; leave them alone.
- `docker compose ls --format '{{.Name}}'` is not supported; use `--format json`.
- The `!` prefix wraps long pasted commands; give Mike scripts or short commands.

## Code Analysis

- `tools/compose.ts` `run()`: spawns with `detached: newGroup` (default true), stdin ignored; on timeout SIGTERM to the group (or child if `newGroup:false`), SIGKILL after 10 s; resolves on 'exit' after waiting ≤2 s for both pipes' 'close'; after timeout/forwarded signal waits ≤15 s for `groupGone(pgid)` then a last SIGKILL; timeout → code 124; forwarded SIGINT/SIGTERM → `process.exit(130|143)`; guarded against double finish.
- `groupGone` uses `kill(-pgid, 0)`, which also succeeds on zombies (jade-3nx L4).
- `stackDown` registers `process.once('exit', rmSync)` for its temp project dir; removed in `finally`.
- `tests/support/infra.ts` `UP_FLAGS` = `up -d --wait --wait-timeout 180 --no-build --pull never`; each `up` exec limit 240 s; stack-up path 600 s; `pnpm stack:up` `--wait-timeout 300`; `vite.config.ts` infra project `hookTimeout: 900_000`, `fileParallelism: false`.
- Run ids: `JADE_INFRA_RUN_ID` (CI) or 16 random hex; tags `jade-app:ci-<checkout hash>-<run id>`, `jade-app:build-<hash>-<run>` (stack-up test), `jade-app:local-<hash>` (`pnpm stack:up`), shared `jade-app:local` (bare README command only).
- vitest 5.1.0 exits ~1 ms after SIGINT in `vitest run` without globalSetup teardown or afterAll; a single Ctrl-C leaves stacks and the tag (README documents the cleanup commands).
- `docker compose port app 3000` prints `invalid IP:0` on this Docker; tests treat host port 0 as no binding; the `PortBindings` and `Publishers` checks are the real exposure proof.
- Logger `err_tag` (jade-zwq): SQLSTATE `^[0-9A-Z]{5}$`, `^ERR_[A-Z0-9_]{1,60}$`, a name on `NODE_ERRNO_NAMES` (EACCES removed), or a tag registered with `registerErrorTags()`; `isErrTag()` exported.
- `/healthz` returns `{status, version}` with `version` from `$app/env`, wired through `vite.config.ts` `version.name` from `APP_VERSION`; `stack-up.test.ts` proves the build arg reaches it.

## Files Changed

### Source / infra (6533ba8)
- `Dockerfile`, `.dockerignore`, `compose.prod.yml`, `deploy/caddy/Caddyfile`, `deploy/caddy/media-files.caddy` — new.
- `tools/compose.ts` — stack commands, `run()` with process groups, `imageCacheArgs`, `withStackEnv`.
- `tools/env-init.ts` — `stack` profile.
- `package.json` — `ci:image`, `test:infra`, `stack:up`, `stack:down`.
- `vite.config.ts` — infra vitest project.
- `.env.example`, `README.md` — stack variables, `JADE_CI_IMAGE_CACHE`, local stack and cleanup sections.
- `.claude/skills/bugfix/SKILL.md` — D6 sentence (bugfix suite 66 passed; planloop suite 466 OK on rerun).

### Tests (6533ba8)
- `tests/infra/{image,compose-config,compose-up,caddy-logs,media,stack-up}.test.ts`, `tests/infra/global-setup.ts`, `tests/infra/fixtures/**`, `tests/support/infra.ts`.
- `tests/unit/compose-tool.test.ts` (new), `tests/unit/{env-init,repo-hygiene,toolchain-pins,log-schema}.test.ts`.

### Correction round (320e73a)
- `vite.config.ts` (`JADE_BUILD_ENV_DIR`), `src/lib/server/config/index.ts` (`database_url_query`), `tools/db/reset.ts`, `src/lib/server/db/{roles,migrate,index}.ts`, `src/lib/server/log/index.ts` (err_tag), `playwright.config.ts`, `tests/support/*`, `tools/ci/clean-clone.sh`, `tools/env-init.ts` (atomic write), `tools/db/check-migrations.ts`, `migrations/README.md`, many tests; `tests/integration/harness-isolation.test.ts` replaced `-a/-b`.

### Local only (not committed)
- `/home/mikep/projects/jade/.mcp.json` (FaultForge server), `.git/info/exclude` line `/.mcp.json`.
- Memory: `~/.claude/projects/-home-mikep-projects-jade/memory/{post-impl-two-opus-reviewers,lows-only-fix-and-commit}.md` + MEMORY.md pointers; `bd remember` keys `post-impl-two-opus-reviewers`, `lows-only-fix-and-commit`.

## User Feedback & Preferences (REQUIRED — never omit)

- "go, section 16 order; trunk stays master for now", then "actually rename master to main".
- "remember from now on that after every implemntation round, run 2 opus reviewers. The specifics should be in quartz" and "also save it in memory".
- "yes, review the three earlier commits too".
- "commit; A5: tighten; plan: ok" (err_tag tightening authorized as a line-schema change, jade-zwq).
- "yes, commit; hwu: defer" (jade-hwu deferred).
- "commit; kill it" (320e73a, and stop the leftover `pnpm dev` pid 1112008).
- Pasted the FaultForge prompt: set it up per JADE process, don't commit/push without approval, don't edit `~/.config/faultforge/mcp.toml` or the fault-forge repo, don't write `faultforge.yaml`/`stack.yaml`, demo kit only, never replace or weaken p6-nolog-invariant.
- "verify" (after restarting Claude Code and approving the MCP server).
- "go, and while you're at it, tell me if you need to use fault forge right now or when you'll use it".
- **"when the reviewers come back with only low, you fix it and commit it, instead of sending it back to an agent."** Saved to memory and `bd remember`. Mediums/highs still go to a subagent round and to Mike for the commit OK. Never push; CLAUDE.md stop points still go to Mike.
- Earlier constraints still in force: commit only on Mike's OK (except the lows-only case), no sudo by agents, never touch other projects' containers (`quartz-*`, Compose project `docker`), never print or commit secrets.

## Where We're Going

1. **Ask Mike Q1** (remote host and CI host, merge flow, branch protection, registry). jade-xu0 (plan section 12, CI) is next in section 16 order and needs it; creating a remote or pushing is a stop point.
2. **If Mike wants to keep going without Q1:** jade-lhq (plan section 13, layout, tokens, accessibility baseline) depends on jade-alt only. Cut branch `jade-lhq` from `jade-80h`, claim, brief a subagent with section 13, then gates, two Opus reviewers, fix/commit per the rules, clean-clone from a detached worktree.
3. **jade-xu0 when Q1 is answered:** the CI `image` job uses `pnpm test:infra` with `JADE_CI_IMAGE_CACHE=gha`, `JADE_INFRA_KEEP_IMAGE=1`, and the Actions runtime variables exposed to later steps (X2). The jade-3nx timing item (A-L12) is checked there.
4. **After the workable Phase 1 beads:** raise Q4 (Phase 2 without staging if jade-0za is open). jade-4zw stays blocked by human bead jade-0za.
5. **Later:** jade-a5u and jade-3nx lows, jade-cev (bugfix skill step 6.2), jade-hh8, jade-hap, jade-hwu (deferred). FaultForge scenario beads wait on jade-cdw (M11) and their features.

## Risks & Blockers

- **Q1 unanswered** blocks jade-xu0, and so closing every Phase 1 bead (Q2 (a): beads close only once CI exists).
- **Auto-mode classifier outages:** it returned no verdict 6 times in a row once this session. Stop before 10 consecutive failures; read-only Read calls still work.
- **Flaky-under-load tests:** dynamic imports and `db:check` time out at 5 s when gates and reviewers run concurrently; both now have 30 s. Don't run two gate runs that share the dev DB at once (a stale run's teardown can remove the DB under another).
- **A killed infra run leaks** its stacks and `jade-app:ci-*` tag (vitest exits without teardown); clean up by exact name per the README.

## Open Questions

- **Q1:** remote (GitHub?), CI host, merge flow, branch protection owner, registry. Blocks jade-xu0.
- **Q4:** may Phase 2 start without staging if jade-0za is still open?
- **Q5:** how is port 22 limited with hosted runners (with jade-0za)?
- **Q6:** confirm `/media` stays closed until jade-u8z (it answers 403 now).
- **Q7:** is a development-only error view wanted (rule-4 question)?
- Whether Mike wants an early FaultForge image-source run of the redemption flow once jade-7if exists (would need `jade-app` in `allowed_images`).

## Quick Start for Next Session

```bash
# Restore context
bd prime
bd show jade-80h        # notes: gates, fresh-store pass, sizes, review history
bd show jade-lhq        # alternative next bead
bd show jade-xu0        # next in order; blocked on Q1
bd show jade-3nx        # deferred jade-80h lows

# Reference docs
plans/planloop/jade-vtk.pl1/rev-005/plan.md   # sections 12, 13, 16, 18

# Key files
compose.prod.yml  Dockerfile  tools/compose.ts  tests/support/infra.ts  tests/infra/global-setup.ts

# Verify current state (PATH prefix is required)
export PNPM_HOME="$HOME/.local/share/pnpm" PATH="$HOME/.local/share/pnpm/bin:$PATH"; unset COMPOSE_PROJECT_NAME
pnpm env:init && pnpm db:up && pnpm lint && pnpm check && pnpm test && pnpm e2e && pnpm test:infra
docker compose -p jade-dev-255efdb2 down -v && rm .env

# Next action
Ask Mike Q1 (remote/CI host/merge flow/registry); if he'd rather continue, start jade-lhq from branch jade-80h.
```

## Session Closed
**Closed at:** 2026-11-16 10:31 UTC
**Commit:** e8e7d53
**Session status:** Handed off to next session
