# Phase 1: CI live on GitHub, jade-xu0 + jade-lhq + bug jade-h3k merged, ADR 0025 (YouTube video); Phase 1 waits only on staging (jade-0za)

**Date:** 2026-11-17
**Status:** IN PROGRESS. Phase 1 is 8 of 10 done. What's left: jade-4zw (staging), blocked by the human bead jade-0za, and jade-vtk.2 (bookkeeping).
**Bead(s):**
- Closed this session:
  - jade-xu0, jade-lhq, jade-d48, jade-h3k (+ findings jade-h3k.1, jade-h3k.2), jade-cdw
  - from earlier sessions, closed under Q2(a): jade-h8i, jade-8v4, jade-urd, jade-alt, jade-80h, jade-f1w, jade-7yz, jade-r7c, jade-zwq
- Filed this session: jade-cnm, jade-tmm, jade-68l, jade-y0i, jade-lpm
**Epic:** jade-vtk, Phase 1: Foundation and walking skeleton
**Chain:** `jade-vtk` seq `4`
**Parent:** `HANDOFF_jade-vtk_phase1-80h-done_2026-11-16.md`
**Prior chain:** `HANDOFF_jade-vtk_phase0-done-phase1-next_2026-11-14.md` > `HANDOFF_jade-vtk_phase1-plan-approved_2026-11-15.md` > `HANDOFF_jade-vtk_phase1-80h-done_2026-11-16.md` > this

---

## Since Last Handoff

- **The parent's step 1 (ask Mike Q1)** was answered at session start. The remote is GitHub, with one PR per bead. Mike then created `Mikro219/jade-learning-platform` (private at first, public later).
- **The parent's step 3 (jade-xu0):** done. Section 12 says X1 to X4 can be delivered without a remote, so it went ahead before the remote existed. It took 3 implementation rounds and 3 review rounds, and the orchestrator fixed the final lows itself. Committed 5c5909b, then pushed and merged through PR #7.
  - X5 has three parts: the first host run, branch protection, and proof that a failing run uploads its report. All three are done.
  - Protection needed the repo made public, because GitHub Free refuses branch protection on private repos (HTTP 403).
- **The parent's step 2 (jade-lhq):** done after jade-xu0, as section 16's order says. Two review rounds, including 2 mediums. Mike OK'd the commit (acfee3e); merged through PR #10 (630d7a5).
- **Q2(a) materialised:** with CI live and green on `main`, all earlier Phase 1 beads (h8i, 8v4, urd, alt, 80h, f1w, 7yz, r7c, zwq) were closed, each citing its PR, merge commit and CI run.
- **New this session, not in the parent:**
  - **The YouTube video decision** (Mike and Given): ADR 0025, rule 5 amended, PRIVACY.md, the threat model and ARCHITECTURE.md all changed (PR #9).
  - **A CI flake on PR #10** turned out to be a real bug in jade-xu0's supervise library, jade-h3k. Fixed through the bugfix skill (PR #11).
  - **The FaultForge MCP server** now builds stack targets from source (M11), and Mike chose the remote Vultr VM runtime.
- **The parent's step 4 (Q4: Phase 2 without staging)** is still open. It is now the gating question, because jade-0za is still open.

## Reference Documents

- `CLAUDE.md`: rules 1 to 8, the orchestrator and subagent model, the context thresholds, the handoff rule. Rule 5 now has the YouTube exception (ADR 0025).
- `plans/planloop/jade-vtk.pl1/rev-005/plan.md`: the approved Phase 1 plan.
  - Section 12: jade-xu0, CI.
  - Section 13: jade-lhq.
  - Section 14: jade-4zw, staging. Specified but not started.
  - Section 16: the order of work and the stop points.
  - Section 17: the acceptance criteria.
  - Section 18: Q1 to Q7.
- `docs/adr/README.md` and `docs/adr/0025-youtube-embedded-module-video.md` (new): 0025 supersedes 0007 and amends 0013.
- `docs/handoff/PRIVACY.md`, `docs/threat-model.md`, `docs/handoff/ARCHITECTURE.md`: all amended for ADR 0025.
- `.claude/skills/bugfix/SKILL.md` and `.claude/skills/planloop/SKILL.md`: the JADE workflow skills.
- `/home/mikep/projects/fault-forge/docs/MCP.md`: the FaultForge docs. Read-only; never edit that repo or `~/.config/faultforge/mcp.toml`.
- Mike's FaultForge briefing, 2026-11-17: `/tmp/claude-1000/-home-mikep-projects-fault-forge/e9cd462b-2af3-44ad-8ba9-b07054138e4c/scratchpad/jade-faultforge-status.md`. It is in another session's scratchpad, so it may be cleared; its content is recorded on jade-4el.

## The Goal

Build Phase 1 (Foundation and walking skeleton) of the JADE learning platform, then move on to Phase 2. Phase 1's agent work is now complete:
- the scaffold, typed config, migrations and the DB harness;
- the health endpoints and the closed logger;
- the production image and Caddy stack;
- CI on GitHub Actions, with protected `main`;
- the layout, tokens and accessibility baseline.

The phase epic's remaining exit criterion, AC3 (staging serves `/healthz` over TLS from a Canadian region), waits on Mike's human bead jade-0za. The next work is either Phase 2 planning, if Mike answers Q4 "yes, start without staging", or helping Mike with jade-0za.

Every bead follows the same rhythm:
1. a subagent implements it;
2. two Opus reviewers check it (A: correctness; B: failure modes);
3. the fixes;
4. the orchestrator's own gate run;
5. a commit, with Mike's OK when the review raised mediums;
6. a PR, green CI, a merge commit, and closing the bead.

## Where We Are

- **Repo:** https://github.com/Mikro219/jade-learning-platform. It is **PUBLIC**; Mike made it public so branch protection would work.
  - Settings: merge commits only (squash and rebase off), and head branches are deleted on merge.
  - `main` is protected:
    - the required checks `check`, `e2e`, `image` and `migration-compat` (GitHub Actions app 15368);
    - strict, meaning a PR must be up to date with `main`;
    - enforce_admins true;
    - no force pushes, no deletion.
- **Local checkout:** `/home/mikep/projects/jade` is on `main` at **6e0beed**, in sync with origin. The only local branch is `main`.
  - Working tree: only `.beads/interactions.jsonl` is modified (bd's own log; never staged without being asked). There are no worktrees besides the main one.
- **Merged PRs, all with merge commits:**
  - #1 to #6: the earlier Phase 1 beads, as a stack.
  - #7: jade-xu0, CI.
  - #9: jade-d48, the ADR 0025 docs.
  - #10: jade-lhq.
  - #11: jade-h3k, the bugfix.
  - #8 was the throwaway upload-proof PR, closed and its branch deleted.
- **CI (`.github/workflows/ci.yml`):** four parallel jobs on `ubuntu-24.04`, each with `timeout-minutes: 9`.
  - Every action is SHA-pinned, and actionlint is pinned by digest.
  - There are no secrets. The checkout token is not persisted. The base fetch uses a masked header passed through `GIT_CONFIG_*` env only.
  - Concurrency groups: `ci-pr-<n>` (cancels superseded runs) and `ci-push-<run_id>`.
  - Measured wall time: 3:32 cold, about 2:40 warm. About 10 billed minutes per run.
- **CI scripts:**
  - `pnpm ci:check`: `pnpm lint && pnpm check && node tools/ci/base-ref.ts db-check && pnpm test`.
  - `pnpm ci:e2e`: `playwright test --project chromium --project webkit`.
  - `pnpm ci:compat`: `bash tools/ci/migration-compat.sh`. It supports `--base <ref>` and `--self-test`.
  - `pnpm ci:local`: `bash tools/ci/local.sh`. It runs the stages in order, prints the timings, stops on Ctrl-C or TERM, and runs each stage in a `setsid -w` group.
- **`tools/ci/base-ref.ts` (X1a), resolving the base:**
  - `JADE_CI_BASE` (a pull request's `base.sha`, or a push's `github.event.before`);
  - forty zeros means no base;
  - in CI (any non-empty `CI` other than false or 0), a missing base is an error;
  - a shallow clone without an explicit base is an error;
  - locally: the merge base with `main`, else `HEAD~1`, else a true root commit means no base;
  - a base without `migrations/manifest.json` means "no migrations; passed";
  - the `db-check` subcommand.
- **`tools/ci/migration-compat.sh` + `tools/ci/compat.ts` (X4):**
  - Step 1 (exit 11): the head runner migrates a fresh database and the template, and both ledgers must equal the head manifest.
  - Step 2: the base's `node build` must answer `/readyz` 200.
    - 12 means a 503 with `db === 'ok'` and migrations not ok;
    - 15 means the app did not start;
    - 16 means another step-2 failure.
  - Step 3: the base's integration tests run on the template.
    - 13 means the tests ran and some failed;
    - 17 means the harness failed.
  - 14 means the ledger changed after step 3.
  - `--self-test`: the harmless fixture must pass; the breaking fixture (`REVOKE SELECT ON schema_migrations FROM jade_app`) must be caught in step 2 or 3 only.
  - Its first real use is Phase 2's first migration PR.
- **`tools/ci/lib/supervise.sh`:**
  - `run` is `setsid -w "$@" &` followed by `wait`;
  - a held early signal (N4);
  - `signal_child` and `stop_child` (TERM, then KILL after 3 s, to both the pid and the group);
  - a one-shot cleanup;
  - it refuses job control and an interactive shell, and needs `setsid`;
  - **the jade-h3k owner-pid guard:** `_supervise_owner=$BASHPID`. A forked non-owner does nothing in the EXIT trap and re-raises signals silently.
- **jade-lhq UI:**
  - `src/lib/styles/tokens.css` and `base.css`.
  - `src/lib/components/shell/{Student,Adult,Staff}Shell.svelte`.
  - `/dev/shell/{student,adult,staff}` (dev-only, `assertDevRoute`).
  - The error page renders inside `StudentShell`.
  - `tests/e2e/a11y.spec.ts` and `layout.spec.ts`.
- **Test counts at 6e0beed:** `pnpm test` runs 28 files and 432 tests; `pnpm e2e` 72 tests on Chromium and WebKit; `pnpm test:infra` 6 files and 89 tests.
- **The route registry holds exactly:** `/`, `/healthz`, `/readyz`, `/dev/boom`, `/(student)/dev/shell/student`, `/(adult)/dev/shell/adult`, `/(staff)/dev/shell/staff` (AC12).
- **ADR 0025 (module videos):** YouTube embedded player, privacy-enhanced `www.youtube-nocookie.com/embed/<id>` (confirmed by Mike), unlisted, made for kids, anyone with the link may watch. The pilot school is managed by Given and does not block YouTube.
  - Rule 5 now has exactly one exception: the YouTube player's origins, on module-video pages only.
- **FaultForge:** working after Mike reconnected the MCP server.
  - Remote runtime available (deployed e00dcc6, Vultr, about $0.066 an hour; credit $189.67).
  - JADE is on the allowlist.
  - `allow_network_install=false`; Mike enables it for the first build.
  - **Mike: use the Vultr VM, not local.**
  - Nothing to run until p2-redeem (jade-7if) exists.
- **The dev DB `jade-dev-255efdb2`** may still be up (the gates ran `pnpm db:up`), and `.env` exists. No bugfix Compose projects or `jade-infra-*` leftovers remain. `rhysd/actionlint:1.7.12` stays pulled on purpose.

## What We Tried (Chronological)

1. **(early) Baseline gate on 1c2666c**, before any change: all green (table below). That confirmed the toolchain after the restart.
2. **(early) jade-xu0 implementation, round 0** (Opus implementer, plan section 12). All gates green.
   - Deviations accepted:
     - the `yaml` 2.9.1 devDependency, to parse the workflow;
     - when the merge base equals HEAD, use HEAD~1;
     - only the base is installed and built in compat;
     - ci:check calls `base-ref.ts db-check` directly.
   - Reviewer A: NOT READY (M1: concurrency drops pending push runs on main).
   - Reviewer B: NOT READY (M1: signals were deferred while a foreground child ran; M2: the self-test counted any failure as caught; M3: base-ref returned "no base" in shallow clones; M4: the same concurrency issue). Plus 10 and 8 lows.
3. **(early) Fix round 1:**
   - Exit codes 11 to 17;
   - base-ref fails closed;
   - concurrency per PR and per push run;
   - persist-credentials false, plus an explicit token fetch;
   - the heredoc moved to `compat.ts`;
   - setsid process groups.

   Re-reviews: A found M-R1 (`classifyReadyz` gave 12 for `{db:'fail', migrations:'unknown'}`, the shape `readiness.ts:61/71` returns when the database is down). B found the same (N1), plus N2 (`has_manifest` called inside `if !` ignored `set -e`; reproduced) and lows N3 to N9.
4. **(early) Fix round 2:**
   - classifyReadyz requires `db==='ok'`;
   - the sourceable `tools/ci/lib/supervise.sh`;
   - `setsid -w`, the job-control and missing-setsid refusals;
   - `drop_databases` runs twice (before and after `stop_child`);
   - database subcommands go through `run`;
   - the token passes through `GIT_CONFIG_*` plus `::add-mask::`;
   - an automated signal test.

   Negative control: `supervise.test.ts` failed 4 of 8 against a round-0 library (`scratchpad/round0-lib.sh`) and passed 8 of 8 on the new one. Both re-reviews: READY WITH LOWS.
5. **(early) The orchestrator fixed the lows itself** (Mike's lows-only rule).
   - R1: Node resets an inherited SIG_IGN; verified with `trap '' INT; node -e kill(SIGINT)`, which exited 130. Fix: cleanup's database drop runs under `setsid -w`.
   - R4: the traps go in before `mktemp`.
   - R2 and A's L-R2-1: local.sh `setsid -w` stage groups, TERM to the group, KILL after 15 s.
   - R3: test assertions.

   Manual checks of the Ctrl-C path:
   - Attempt 1 used `setsid bash -c ... &` from the tool shell. That shell has job control on, so setsid forked and the signal went nowhere. Invalid.
   - Attempt 2: pgrep's pattern matched the tool shell's own command line, and pnpm 12 runs scripts in their own process group. Invalid.
   - Attempt 3: a real ^C through a pty (`script -qfec`) and a pattern that couldn't match itself. Exit 130 in 7 s, nothing left behind. Valid.
   - Separately, TERM to local.sh: the stage group was gone in 313 ms.
6. **(mid) Remote and PRs.**
   - `git remote add origin https://github.com/Mikro219/jade-learning-platform.git`. HTTPS auth goes through the Windows Git Credential Manager.
   - The history scan before the push found nothing. But `git grep -I` skips binaries, so the committed `jade-handoff.zip` was only scanned afterwards, with a Python zipfile scan. Also clean.
   - Pushed `main` and the 6 bead branches, then opened stacked PRs #1 to #6 with `gh` (Mike installed it from `~/gh-install.sh`).
7. **(mid) CI minutes:** a side note warned about private-repo minutes. The estimate was corrected to about 10 billed minutes per run; jade-cnm was filed. Moot now that the repo is public, where minutes are unlimited.
8. **(mid) Merging the stack.**
   - A side note warned that stacked PRs only retarget when the base branch is deleted, so `delete_branch_on_merge` was turned on.
   - Merged #1 to #7 in order, each `--match-head-commit`, checking the retarget to `main` before each.
   - `main`'s tree equals the tested 5c5909b tree.
   - The main push run was green.
9. **(mid) Branch protection:** HTTP 403, "Upgrade to GitHub Pro or make this repository public". Mike made the repo public, and protection was applied from `scratchpad/protection.json`.
10. **(mid) The upload proof:** draft PR #8 with one deliberately failing e2e test. Only e2e failed, and the `playwright-report` artifact (661,867 B, 7 days) was uploaded. Closed, and the branch deleted; `gh pr close --delete-branch` couldn't delete the remote branch while a worktree held it, so `git push --delete` did.
11. **(mid) YouTube (jade-d48).**
    - Mike: "module video will be uploaded to yt", decided with Given.
    - Filed as a human decision bead.
    - Mike: option (a), embedded; unlisted; made for kids; anyone with the link; not blocked at the pilot school; "update the wording".
    - An Opus docs agent drafted ADR 0025 and the doc changes in the worktree `wt-d48`. Mike then asked for ARCHITECTURE.md to be corrected in place as well.
    - PR #9 merged. Follow-up beads: jade-tmm, jade-68l, jade-y0i.
12. **(late) jade-lhq round 0.**
    - Implemented (axe 4.14.0; Chromium `--disable-gpu --disable-software-rasterizer` because of a 90-105 s GPU stall on WSL2).
    - A: READY WITH LOWS. B: READY WITH LOWS but 2 mediums: M1, the error page had no `main` or axe check; M2, the global `.shell :global(a)` rule had specificity 0,2,1 plus inline-flex.
    - Fix round 1 by a subagent.
    - Re-reviews: READY WITH LOWS. The orchestrator fixed the lows: inline exemption by computed display; spacing uses all targets; checkVisibility with visibility and opacity; delays set to 0.
    - Gates green; Mike OK'd; merged `main` into the branch (docs only); PR #10.
13. **(late) CI flake on PR #10.**
    - `supervise.test.ts`, the early-signal case: `cleanup 143\ncleanup 0`.
    - Not caused by lhq. Filed jade-h3k (P1); re-ran only the failed job; green; merged.
14. **(late) The jade-h3k bugfix skill.**
    - Baseline tree 484d902.
    - Reproduced: 0 of 200 idle; 25 of 960 under 32 busy loops plus 24 parallel loops. Each bad log showed the second cleanup with a different BASHPID.
    - Fable mini-plan:
      - **Cause:** the forked pre-exec child of `setsid -w "$@" &` keeps the trap table. The owner's `stop_child` TERM kills it, and bash 5.2's fatal-signal path runs the inherited EXIT trap with status 0.
      - **Fix:** an owner-pid guard.
    - The orchestrator verified the deterministic probe 3 of 3.
    - Opus implemented. Patch 1 review: F1 MEDIUM (test (b) may not fail reliably) and F2 LOW (leftover processes).
      - F1: the orchestrator measured 15 of 15 failures on the original library, and the reviewer accepted the rejection.
      - F2: fixed in patch 2.
    - Patch 2: clean.
    - Evidence and gates: green.
    - `fixpatch verify` FAILED, only because bd appended to the tracked `.beads/interactions.jsonl` after patch 2 (filed jade-lpm).
    - Committed exactly patch 2 (`fixpatch staged` passed). PR #11 green on the first attempt; merged 6e0beed.
15. **(mid/late) Odd steps worth knowing.**
    - Gate runs: I edited files while the lhq2 and host2 gates were running, so both were downgraded to "indicative" and rerun.
    - Deleting `jade-d48`: `git branch -d jade-d48` refused ("not fully merged") because HEAD was `jade-lhq`. Verified with `merge-base --is-ancestor`, then `-D`.
    - Merging PR #9: the first `gh pr merge` used a mistyped SHA and was refused.
    - Closing PR #8: `gh pr close --delete-branch` failed on the local branch because the worktree held it; the remote branch was deleted by hand.
16. **(late) FaultForge.**
    - The first status check showed `mcp.toml` invalid ("unknown keys ['remote']") and the remote runtime "not built (M12)": a stale server.
    - After Mike reconnected it, both were OK.
    - jade-cdw closed: M11 delivered.
    - Requirements recorded on jade-4el.

## Key Decisions

- **jade-xu0 started before the remote existed.** Plan section 12.3 allows X1 to X4 without a remote. Rejected: waiting for Q1.
- **Stacked PRs, one per bead, merged with merge commits only.** They keep per-bead review and the SHAs cited in bead evidence. Squash and rebase are disabled on the repo. Rejected: one catch-up PR.
- **Merges pinned with `--match-head-commit <sha read from gh>`.** A typed-from-memory SHA once refused a merge (good). Always read the head SHA from `gh pr view --json headRefOid`.
- **Branch protection:** strict, enforce_admins, no reviews required (a solo developer can't approve his own PRs).
- **Closing earlier Phase 1 beads (Q2(a)):** done when jade-xu0's close was blocked by its open dependencies jade-80h and jade-urd. Rejected: `bd close --force`.
- **A CI flake in merged code becomes a bug bead plus the bugfix skill, and only the failed job is re-run** for the unrelated PR. A re-run is acceptable only when the PR doesn't touch the flaky code.
- **The jade-h3k fix is an owner-pid guard, not `( trap -; exec ... ) &`.** The subshell wrapper leaves a window after the fork. Guarding on `$$` never fires. A guard that calls `exit` turns a TERM death into success.
- **Test (b) kept as an end-to-end proof** after measuring 15 of 15 failures; the reviewer accepted.
- **The Chromium GPU flags apply in every environment, CI included:** deterministic and harmless; WebGL is unavailable in the Chromium project (the comment says so). Rejected: limiting them to WSL.
- **Skip link always visible**, not focus-only, so the hover-every-link off-origin test can hover it. **`data-shell` sits on the shell's outer element**, not `<html>`.
- **ADR 0025 follows the README convention** (its own ADR and an amendment table). ARCHITECTURE.md was corrected in place at Mike's request; `architecture.svg` and `.png` were not edited (listed as stale).
- **FaultForge runs JADE on the remote Vultr VM** (Mike). `propose_fix` must still use `mode="client"` for JADE.

## Evidence & Data

### Commits on main this session

| SHA | What |
|---|---|
| 2f451dc, fb4cf19, d53b4f1, 606a54b, 821c104, 1bfa2db | merges of PRs #1 to #6 (h8i, 8v4, urd, alt, f1w, 80h) |
| 5c5909b → 138838a | jade-xu0 CI (PR #7) |
| aa5d832, b08d972 → 5f47464 | ADR 0025 docs, then ARCHITECTURE.md corrections (PR #9) |
| acfee3e, 5ba7659 → 630d7a5 | jade-lhq, plus the merge of main (PR #10) |
| cf183b5 → 6e0beed | jade-h3k fix (PR #11) |

### jade-xu0 gate history (exit 0 everywhere; times in seconds)

| Run | lint | check | test | e2e | test:infra | self-test | ci:local |
|---|---|---|---|---|---|---|---|
| Baseline 1c2666c | 26 | 18 | 49 (349) | 22 (6) | 262 | — | — |
| Implementer r0 | 20 | 15 | 37 | 26 | 264 | 61 | 5:20 |
| Host host1 (r0) | 31 | 20 | 53 | 27 | 217 | 71 | — |
| Implementer r1 | 16 | 13 | 39 (409) | 18 | 194 | 60 | 4:23 |
| Host host2 (r1, indicative) | 20 | 12 | 40 | 16 | 189 | 83 | — |
| Implementer r2 | 17 | 12 | 34 | 15 | 194 | 59 | 4:10 |
| Host host3 (r2) | 47 | 25 | 50 | 29 | 273 | 86 | — |
| Host host4 (final 5c5909b) | 16 | 13 | 37 | 16 | 178 | 68 | 4:42 |

- `ci:local` stage times on the final tree: check 1:05, e2e 0:16, infra 3:21, compat 0:00 (the base has no manifest).
- `ci:clean-clone`: exit 0 on 5c5909b.

### jade-xu0 review iterations

| Round | Reviewer A | Reviewer B | Action |
|---|---|---|---|
| r0 | NOT READY: M1 concurrency, plus 8 lows | NOT READY: M1 to M4, plus 10 lows | fix round 1 (subagent) |
| r1 | NOT READY: M-R1 classifyReadyz db fail; L-R1 token in argv | NOT READY: N1 (same as M-R1), N2 `has_manifest` set -e (reproduced), N3 to N9 | fix round 2 (subagent) |
| r2 | READY WITH LOWS: L-R2-1 ci:local signal path | READY WITH LOWS: R1 Node SIG_IGN reset (verified), R2, R3, R4 | orchestrator fixed the lows and committed (lows-only rule) |

### GitHub Actions runs

| Run | Event | check | e2e | image | migration-compat | Result |
|---|---|---|---|---|---|---|
| 43876617875 | PR #7 | 2:18 | 1:50 | 3:32 (cold) | 0:28 | green |
| 43877827906 | push main (merge #7) | 2:15 | 1:50 | 2:36 | 0:24 | green; base = 1bfa2db |
| 43877971063 | PR #8 (upload proof) | ok | **fail (deliberate)** | ok | ok | artifact `playwright-report` 661,867 B |
| 43880694362 | PR #9 | ok | ok | ok | ok | green |
| 43898562289 | PR #10 | attempt 1 **fail** (supervise flake), attempt 2 ok | 1:52 | ok | ok | green on attempt 2 |
| 44056959718 | PR #11 | ok | ok | ok | ok | green on attempt 1 |

- Billing: about 10 billed minutes per run with per-job rounding (check 3, e2e 2, image 4, compat 1). The repo is public now, so minutes are unlimited; jade-cnm is mostly moot.

### jade-lhq gate history

| Run | lint | check | test | e2e | test:infra |
|---|---|---|---|---|---|
| Implementer r0 | 23 | 17 | 42 (430) | 31 (50) | — |
| Host lhq1 | 20 | 15 | 41 | 28 | 246 |
| Implementer r1 | 21 | 15 | 42 | 39 (72) | 240 (89) |
| Host lhq2 (mixed tree, indicative) | 25 | 17 | 48 | 48 | 229 |
| Host lhq3 (final) | 18 | 14 | 38 | 40 (72) | 201 |

- `ci:clean-clone`: exit 0 on acfee3e.
- The AC12 form-field grep finds nothing.

### jade-lhq token contrast (WCAG)

| Pair | Ratio |
|---|---|
| text `#1b1f1d` on `#ffffff` | 16.66 |
| muted `#4a524e` on bg / on surface `#f3f6f4` | 8.05 / 7.40 |
| link and accent `#0a5c47` on bg / on surface | 7.97 / 7.33 |
| white on accent-strong `#074536` | 10.97 |
| white on the staff band `#4b2a6e` | 11.32 |
| border `#6b7470` on bg / on surface | 4.82 / 4.43 (3:1 needed) |
| focus-on-dark `#ffd166` on the band | 7.85 |

- Type scale: 13, 14, 16, 18 (student body), 22, 28, 36 px.
- `--tap-min` 48px, `--target-min` 24px.

### jade-h3k evidence

| Item | Value |
|---|---|
| Baseline | tree 484d902c8efaf20a33dbf900bf685e0a90795882, HEAD 630d7a5 |
| Reproduction | idle 0/200; load 25/960; the second cleanup had BASHPID ≠ owner |
| Probe | `/bin/true $(sleep 0.6) & kill -TERM $!`: the child runs the EXIT trap with status 0, wait=143 (3/3) |
| Patch 1 | a11a3d60…baf, tree f8e22f3a. F1 MEDIUM (rejected and accepted: (b) fails 15/15 on the original), F2 LOW (fixed) |
| Patch 2 (delivered) | 1823ec26c9b0536f421079f06590afd0dd5e28c97285000c5b87c820f1dfb06c, tree b4909c2376a0d2e8db4ce4093a3c5d46c5b5128d. Review clean |
| Regression | no-fix: exit 1 with both expected assertions (log sha bf21044e…); fix: exit 0 (log sha 80c9d018…) |
| Fast gate | exit 0, 28 files, 432 tests (log sha 2b49ef29…) |
| Full gate | exit 0, 72 e2e (log sha 23fbc2c5…) |
| verify | FAILED, only on `.beads/interactions.jsonl`; fix hunks identical (jade-lpm) |
| Commit | cf183b5; `fixpatch staged` matched b4909c23 before and after the commit; clean-clone exit 0 |
| Logs | `~/.local/state/bugfix/jade-h3k/logs/` (step6-status.txt, p2-*.log, clean-clone-cf183b5.log); patches in `~/.local/state/bugfix/jade-h3k/` |

### Repo protection payload (`scratchpad/protection.json`, applied)

```json
{"required_status_checks":{"strict":true,"checks":[{"context":"check","app_id":15368},{"context":"e2e","app_id":15368},{"context":"image","app_id":15368},{"context":"migration-compat","app_id":15368}]},
 "enforce_admins":true,"required_pull_request_reviews":null,"restrictions":null,"allow_force_pushes":false,"allow_deletions":false}
```

### Action pins (ci.yml)

| Action | Tag | SHA |
|---|---|---|
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| pnpm/action-setup | v6.1.0 | ea17c68df8912ef543352723c149a84f56e3d413 |
| actions/setup-node | v7.1.0 | 949feb2413d6458794dcd2491c4babbbce0c15c1 |
| actions/upload-artifact | v7.0.2 | cf430e030ddbb5b0abf93d22962f4752f3646cd9 |
| docker/setup-buildx-action | v4.4.1 | f87e5991a6d7451dcb8d9637bfbc97413f497069 |
| crazy-max/ghaction-github-runtime | v4.0.0 | 04d248b84655b509d8c44dc1d6f990c879747487 |

- actionlint: `rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`.

### Bead index (state at handoff)

| Bead | What | State |
|---|---|---|
| jade-xu0 | CI pipeline | closed |
| jade-lhq | layout, tokens, a11y | closed |
| jade-h8i, 8v4, urd, alt, 80h, f1w, 7yz, r7c, zwq | earlier Phase 1 beads and fixes | closed (Q2(a)) |
| jade-d48 | YouTube decision, ADR 0025 | closed |
| jade-h3k (+ .1, .2) | supervise double cleanup | closed |
| jade-cdw | FaultForge M11 placeholder | closed |
| jade-4zw | staging | open, blocked by jade-0za (human) |
| jade-0za | HUMAN: Canadian host, account, domain | open (Mike) |
| jade-vtk.2 | planloop run bookkeeping | open P2 |
| jade-tmm | INV3 allowlist for YouTube origins | open P2 |
| jade-68l | decision (human): video events without YouTube's script | open; blocks jade-iwr |
| jade-y0i | decision (human): p4-video rescope (click-to-load, fallback, /media, referrer, ads) | open; blocks jade-u8z |
| jade-lpm | bugfix skill vs bd's interactions.jsonl | open P2 |
| jade-cnm | Actions minutes | open P3 (moot: repo public) |
| jade-3nx, jade-a5u | deferred lows (80h; correction round) | open P2 |
| jade-hap | readiness pool vs the app pool: decide before Phase 2's Drizzle pool | open P2 |
| jade-cev | bugfix skill step 6.2 gate command | open P2 (may already match: the gates ran env:init + db:up) |
| jade-4el, jade-bnk, jade-0nf | FaultForge scenarios | open; blocked on jade-7if, jade-zg3, jade-hhp |
| jade-hh8 | watch-mode blackbox build | open P3 |

## Code Analysis

- **`tools/ci/lib/supervise.sh`:**
  - `supervise_init <name> <cleanup>` sets `_supervise_owner=$BASHPID` and the EXIT, INT and TERM traps.
  - `run()`: `_supervise_starting=1; setsid -w "$@" &; [supervise_after_fork]; child=$!; starting=0; act on the pending signal; wait`.
  - `_supervise_signal`: a non-owner runs `trap - sig; kill -sig $BASHPID`. The owner, while starting, records the signal as pending; otherwise it prints "<name>: stopped by SIG…" and exits 130 or 143.
  - `_supervise_exit`: `local status=$?`; a non-owner returns at once; the owner runs `trap '' INT TERM`, the one-shot cleanup with `$status`, `stop_child`, then `exit $status`.
- **`migration-compat.sh`:**
  - `db()` is `run node tools/ci/compat.ts …`.
  - `compat()` (direct) is used only for count-at, count-dir and manifest.
  - `drop_databases()` is `setsid -w node tools/ci/compat.ts drop` and appears twice in `cleanup()`.
  - `work=""` before `supervise_init`, then `mktemp` after it.
- **`compat.ts`:** `classifyReadyz(status, body)` gives 12 only for 503 with `db==='ok'` and migrations not `ok`. `classifyStep3` reads Vitest's JSON report (`testResults[].status`, `numFailedTests`).
- **`readiness.ts:46-72`:** `readinessOfFailure` maps SQLSTATE class 42 (42501) to `{db:'ok', migrations:'unknown'}`, and connection, timeout and similar errors to `{db:'fail', migrations:'unknown'}`.
- **`base.css` target rules:** `:where(a[href], button, [role='button'], summary, .target)` gets min 24px, and the same under `:where([data-shell='student'])` gets 48px. Minimum sizes don't apply to `display:inline`. `layout.spec.ts` exempts targets whose computed display is inline, but still uses them as neighbours in `spacedEnough`.
- **Reduced motion:** 0.01ms durations, 0s delays, and an iteration count of 1. Svelte's transition directives (Web Animations API) are not covered and must read `prefersReducedMotion`.
- **pnpm 12** starts each script in a new process group with a `sh -c 'trap … INT; …'` wrapper. A background `&` from a non-interactive shell ignores SIGINT, and bash can't trap a signal that was ignored at entry.
- **Node** resets inherited signal dispositions at startup, so `trap ''` doesn't protect node children. Use `setsid -w` for those.

## Environment Gotchas (learned this session; add to the parent's list)

- **PATH prefix for every pnpm call:** `export PNPM_HOME="$HOME/.local/share/pnpm" PATH="$HOME/.local/share/pnpm/bin:$PATH"`. Node 24.22.3 comes through `devEngines.runtime`; the system Node is v20.
- **The Bash tool's shell has job control on** ("[1]+ Done" appears).
  - `setsid cmd &` from it forks, so `$!` is a short-lived parent.
  - Signal-path experiments must run inside `bash -c '…'` (non-interactive), or in a real pty: `( …; printf '\003'; sleep N ) | script -qfec "pnpm ci:local" log`.
- **`pgrep -f <pattern>` matches the tool shell itself** when the pattern appears in your command line. Build the pattern dynamically, for example `pat=$(printf 'esl%s' 'int/bin/eslint')`.
- **pnpm 12** runs each script in a new process group, through a `sh -c 'trap … INT; …'` wrapper. INT sent to pnpm's group does not reach the script.
- **A background `&` from a non-interactive shell starts with SIGINT ignored**, so bash can't trap INT there.
- **Node resets inherited signal dispositions at startup**, so `trap '' INT` doesn't shield node children. Use `setsid -w`.
- **`git branch -d X`** checks whether X is merged into the *current HEAD*, not `main`. Verify with `git merge-base --is-ancestor X main`, then `-D`.
- **`gh pr merge --match-head-commit`** needs the exact full SHA. Read it with `gh pr view N --json headRefOid -q .headRefOid`; a guessed SHA is refused as "Head branch was modified".
- **`gh pr close --delete-branch`** gives up on the remote delete if the local branch is checked out in a worktree. Use `git push origin --delete <branch>`.
- **`.prettierignore` excludes `/docs/` and `/CLAUDE.md`**, so `prettier --check` proves nothing for docs changes.
- **On this WSL2 machine a fresh Chromium's GPU process stalls for 90-105 s** before its first frame or canvas read. That is why `playwright.config.ts` passes `--disable-gpu --disable-software-rasterizer`.
- **GitHub Free refuses branch protection on private repos** (HTTP 403). The repo is public now.
- **Clean-clone needs a clean tree**, and `.beads/interactions.jsonl` is always dirty. Run it from a detached worktree: `git worktree add --detach <scratch>/cc-wt <sha> && (cd … && pnpm ci:clean-clone)`, then `git worktree remove --force`.
- **`docker compose ls --format '{{.Name}}'` is unsupported**; use `--format json`. Port 5432 belongs to quartz. Always `unset COMPOSE_PROJECT_NAME` before `pnpm db:up`. The bugfix gates are the exception: they export `COMPOSE_PROJECT_NAME=bugfix-<bead>-<purpose>`.
- **Agents:** some reviewers ran small read-only bash probes despite "no commands". Harmless, but say "static only" explicitly if probes must not run.

## Working Method That Held Up This Session

- **Implementer:** one `general-purpose` Opus subagent per bead, resumed with SendMessage for each fix round so it keeps its context. Each brief names:
  - the plan section;
  - the files to read;
  - the gates;
  - the hard limits: no git or bd writes, no remote, the Docker hygiene rules, no ADR changes, no scope widening;
  - a wait condition on the orchestrator's gate status file, so two gate runs never share the dev database.
- **Reviewers:** read-only `Plan` agents on Opus, A (correctness: the plan, the acceptance criteria, whether the tests prove their claims) and B (failure modes). They are resumed for targeted re-reviews with the changed-file list and the deferred items.
- **The orchestrator:**
  - verifies every medium against the code, and reproduces it where cheap (N2, R1, M-R1, the F1 measurement);
  - reruns the gates on the final tree itself;
  - records every exit status in bead notes;
  - when the reviews come back lows-only, fixes the lows itself and commits.
- **Gate scripts in the scratchpad** (`host1..4/run.sh`, `lhq1..3/run.sh`) run in the background and write `status.txt`. Edits made during a gate run make that run "indicative" only; rerun on the final tree.
- **The bugfix skill end to end** (jade-h3k):
  - baseline, then a reproduction loop, then a Fable mini-plan;
  - an Opus implementer;
  - `fixpatch patch`/`candidate`, and a fresh Opus review on the candidate worktree;
  - finding child beads;
  - no-fix versus fix regression evidence;
  - gates in a fresh candidate with its own Compose project;
  - `git apply --cached patch` plus `fixpatch staged T`, then the commit, then `fixpatch drop`/`cleanup`.

## Data and Script Files (scratchpad: `/tmp/claude-1000/-home-mikep-projects-jade/f3d2524e-12b2-4c39-9731-e58c4b74e027/scratchpad/`; may be cleared)

- `baseline/`: the baseline gate on 1c2666c (`status.txt`, per-stage logs).
- `host1/` to `host4/`: jade-xu0 host gates, with the reusable `run.sh` (db:up, lint, check, test, e2e, test:infra, compat self-test, compat --base 48a0bec).
- `lhq1/` to `lhq3/`: jade-lhq host gates, with the AC12 grep.
- `local-int*.log`, `local-pty*.log`: the ci:local Ctrl-C experiments (the first two invalid, the pty one valid).
- `round0-lib.sh`: the round-0 supervise design, used as a negative control (`JADE_SUPERVISE_LIB=…`).
- `h3k/fixture.sh`, `h3k/loop.sh`: the h3k reproduction (`loop.sh <n> <tag>`; run many in parallel with busy loops). `h3k/orig-supervise.sh` is the original library.
- `protection.json`: the branch-protection payload.
- `prs/*.md`: PR bodies. `commit-msg-xu0.txt`.
- Durable bugfix state (not the scratchpad): `~/.local/state/bugfix/jade-h3k/` (patch-1, patch-2, patch-3-diag, `logs/`).

## Files Changed

### CI (jade-xu0, 5c5909b)
- `.github/workflows/ci.yml` (new): the four jobs, pins, concurrency, the token-less base fetch, the upload on failure.
- `tools/ci/base-ref.ts` (new): X1a resolution and the `db-check` subcommand.
- `tools/ci/migration-compat.sh` and `tools/ci/compat.ts` (new): X4 and `--self-test`.
- `tools/ci/lib/supervise.sh` (new): child supervision.
- `tools/ci/local.sh` (new): `ci:local`.
- `package.json`: `ci:check`, `ci:e2e`, `ci:compat`, `ci:local`; devDependency `yaml` 2.9.1. Also `pnpm-lock.yaml`.
- `.env.example`: a CI section (`CI`, `JADE_CI_BASE`). `README.md`: a CI section.
- Tests: `tests/unit/{ci-workflow,base-ref,compat,supervise}.test.ts`.

### Docs (jade-d48, aa5d832 + b08d972)
- `docs/adr/0025-youtube-embedded-module-video.md` (new).
- `docs/adr/README.md`.
- `docs/adr/0007-…` (superseded) and `docs/adr/0013-…` (amended note).
- `CLAUDE.md`: rule 5 exception sentence.
- `docs/handoff/PRIVACY.md`, `docs/threat-model.md` (TB10, AB17, TM-9, TM-10), `docs/handoff/ARCHITECTURE.md` (sections 2, 3, 4, 9, 10, 14).

### UI (jade-lhq, acfee3e)
- `src/lib/styles/{tokens,base}.css`.
- `src/lib/components/shell/*Shell.svelte`.
- `src/routes/(student|adult|staff)/+layout.svelte`.
- `src/routes/(*)/dev/shell/*/+page.{svelte,server.ts}`.
- `src/routes/+error.svelte` (inside StudentShell).
- `tests/authz/route-registry.ts`.
- `tests/e2e/{a11y,layout}.spec.ts`.
- `playwright.config.ts` (GPU flags).
- `package.json`: `@axe-core/playwright` 4.14.0.

### Bugfix (jade-h3k, cf183b5)
- `tools/ci/lib/supervise.sh`: the owner guard.
- `tests/unit/supervise.test.ts`: tests (a) and (b), plus the sweeps.

### Local only (not committed)
- `.mcp.json` (FaultForge), excluded through `.git/info/exclude`.
- `~/gh-install.sh` (Mike ran it).
- The scratchpad: `protection.json`, `round0-lib.sh`, `h3k/` (fixture.sh, loop.sh), `prs/*.md`, gate dirs `host1..4`, `lhq1..3`.

## User Feedback & Preferences (REQUIRED — never omit)

- "go, GitHub, PR per bead; start jade-xu0" (Q1, in part).
- "wait does the actual git repo exist yet or do want me to create it? also what is a suitable repo name?" Mike then created `jade-learning-platform`.
- "yes, also can you install gh or should I do it via internet/installer?" That was the push authorization. Mike installed gh himself.
- "go ahead with 1 and 2": push jade-xu0 and open PR #7; turn on auto-delete of head branches.
- "Also module video will be uploaded to yt. This decision was made by me and Given."
- "Option a, it'll be unlisted."
- "go ahead. As for decisions: made for kids true, anyone with link can watch, pilot school is managed by Given so it is not blocked, update the wording." This also authorized merging #1 to #7, protection, the upload proof, and turning off squash and rebase.
- "repo is public now, proceed with branch protection and close the bead."
- "go ahead with 1-3, delete local branches a d start lhq": the nocookie origin, keep the consent sentence, the ARCHITECTURE convention.
- "edit the stale lines in architecture." This reversed the "leave unedited" choice.
- "ok for 1-4": commit jade-lhq, merge main into it, PR, close.
- "here's current status of fault forge: … go ahead with h3k."
- "Also, I just reconnect the faultforge mcp, chrck it out when you can."
- **"stick with vultr vm, no local"** (FaultForge runtime). Saved with `bd remember` as `faultforge-jade-runtime`.
- "yes": commit jade-h3k.
- Standing rules, unchanged:
  - two Opus post-implementation reviewers (A correctness, B systems);
  - lows-only reviews are fixed and committed by the orchestrator without a separate OK;
  - any medium or high needs Mike's commit OK;
  - merges and pushes only with authority;
  - no sudo for agents;
  - never touch other projects' containers;
  - never print or commit secrets.
- Mike answers tersely and expects the orchestrator to proceed within what he's authorized, flagging any mismatch (Q2(a) closures were explained after the fact).
- Side-agent notes he forwards ("Here is a note offered by a side agent") are advice to evaluate, not orders. Two were right: the minutes estimate, corrected, and stacked-PR retargeting.

## Where We're Going

1. **Ask Mike Q4:** may Phase 2 start while jade-0za (staging) is still open? Phase 2's exit criterion "Core schema migrated on staging" would wait. If yes:
2. **Phase 2 planloop** (CLAUDE.md: a planloop for each new phase before its first agent bead). It's on the escalated track: schema-migration, secrets (kit codes, the pepper) and privacy.
   - The ready P0s: jade-o07 (core schema), jade-fd5 (kit code library), then jade-7if (redemption).
   - Bring in jade-hap: the readiness pool vs the Drizzle app pool decision.
   - The plan must list the binding sources (rule docs, the ADRs including 0025) as OB rows.
   - Reviews by Opus at high effort, plus Mike's sign-off.
   - The first real `migration-compat` run happens on Phase 2's first migration PR.
3. **jade-lpm (small):** make `fixpatch` ignore `.beads/interactions.jsonl`, add a test in `test_fixpatch.sh`, update SKILL.md, then run both skill suites. Do it before the next bugfix. Also check whether jade-cev is already satisfied.
4. **Once jade-7if exists:** a bead to add FaultForge's `stack.yaml` and `faultforge.yaml`, modelled on `fault-forge/demo/redeem-code`. The requirements are on jade-4el. Ask Mike to set `allow_network_install`. Run on the remote VM with `mode="client"`.
5. **Phase 1 closure:** jade-4zw when jade-0za lands (plan section 14). jade-vtk.2 bookkeeping. Then `bd epic close-eligible`.
6. **Later:** jade-3nx and jade-a5u lows; per-group `+error.svelte` for adult and staff when they get pages; `data-shell` on an ancestor for modals; decisions jade-y0i and jade-68l when Phase 4 or 6 arrive.

## Risks & Blockers

- **jade-0za (human)** blocks jade-4zw and Phase 1's AC3. Q4 decides whether Phase 2 waits for it.
- **The repo is public:** everything committed is visible (docs, threat model, beads export). Keep the secret scans before every push. `git grep -I` skips binaries, so scan zips separately.
- **The bugfix skill's `verify` breaks on any bd write mid-fix** (jade-lpm) until fixed. Workaround used this session: diagnose with a fresh diagnostic patch, rely on `fixpatch staged <T>` at commit, and record the reason.
- **Flaky-test risk:** supervise's signal tests depend on timing. Test (b) fails on the original code about 99% of the time per run; (a) is deterministic. If CI flakes again, file a bug bead; never just re-run in a PR that touches that code.
- **The tool shell has job control on.** `setsid` there forks, so harness tests must use `bash -c` (non-interactive) or a pty (`script -qfec`). pgrep patterns must not match their own command line.

## Open Questions

- **Q4:** Phase 2 without staging (jade-0za open)?
- **Q5:** how port 22 is limited with hosted runners (with jade-0za).
- **Q6:** ADR 0025 made `/media` partly moot. It now sits under decision jade-y0i (images only, or closed?).
- **Q7:** a development-only error view (a rule-4 question). Still unanswered; nothing depends on it.
- **jade-y0i items:** click-to-load (recommended), the offline fallback, `/media`, referrer policy versus the embed, and confirming Given's channel is not monetised.

## Quick Start for Next Session

```bash
# Restore context
bd prime
bd show jade-vtk          # Phase 1: 8/10, remaining jade-4zw (blocked by jade-0za), jade-vtk.2
bd show jade-lpm          # small skill fix before the next bugfix
bd show jade-hap          # decide before Phase 2's Drizzle pool
bd show jade-4el          # FaultForge requirements, runtime = remote VM

# Reference docs
plans/planloop/jade-vtk.pl1/rev-005/plan.md   # section 14 (staging), section 18 (Q4)
docs/adr/0025-youtube-embedded-module-video.md
docs/handoff/phases/phase-02-*.md             # for the Phase 2 planloop

# Key files
.github/workflows/ci.yml  tools/ci/lib/supervise.sh  tools/ci/migration-compat.sh  tools/ci/base-ref.ts

# Verify current state (PATH prefix required)
export PNPM_HOME="$HOME/.local/share/pnpm" PATH="$HOME/.local/share/pnpm/bin:$PATH"; unset COMPOSE_PROJECT_NAME
git status && git log --oneline -1    # main 6e0beed, only .beads/interactions.jsonl modified
pnpm db:up && pnpm lint && pnpm check && pnpm test && pnpm e2e
gh run list --branch main --limit 3

# Next action
Ask Mike Q4 (start Phase 2 without staging?). If yes, run the Phase 2 planloop (escalated: schema-migration, secrets, privacy).
```
