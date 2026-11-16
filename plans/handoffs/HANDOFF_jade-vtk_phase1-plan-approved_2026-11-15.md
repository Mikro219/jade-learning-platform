# Phase 1 plan approved (jade-vtk.pl1 rev 5); next: Mike's go-ahead to implement, jade-h8i first

**Date:** 2026-11-15
**Status:** COMPLETED (Phase 1 planloop approved). Implementation not started, and it waits on Mike's explicit go-ahead.
**Bead(s):**
- run bead jade-vtk.2 (planloop run jade-vtk.pl1)
- benchmark/round-log bead jade-yvx
- next implementation bead jade-h8i
- jade-ahw closed this session
**Epic:** jade-vtk, Phase 1: Foundation and walking skeleton
**Chain:** `jade-vtk` seq `2`
**Parent:** `HANDOFF_jade-vtk_phase0-done-phase1-next_2026-11-14.md`
**Prior chain:** `HANDOFF_jade-vtk_phase0-done-phase1-next_2026-11-14.md` > this

---

## Since Last Handoff

- Parent step 1 (start the Phase 1 planloop, escalated track): done.
  - `planloop.py init` created run jade-vtk.pl1 with run bead jade-vtk.2, track escalated, risk domains secrets, privacy and schema-migration.
  - Fable drafted revision 1.
- Parent step 2 (binding sources as OB rows): done. OB1 to OB80, byte-exact, re-verified by the host. OB33 is from jade-h8i's `notes` field, which records Mike's Node 24 choice.
- Parent step 3 (full finding text in briefs): done by hand.
  - Host-verified issues went into the briefs as H-items (`brief-r2.md` holds H1 to H16).
  - The reviewer feedback carries only the findings table, so later reviewers noted "R texts not in the bundle". See Risks.
- Parent step 4 (rounds until a fresh high gate approves, then sign-off): done.
  - 6 calls in all: 3 voided attempts on call 1, then calls 2 to 6.
  - Gate call 6 approved revision 5.
  - Mike signed off (decisions/A1.json) and accepted RR1 to RR14 (decisions/D2.json).
  - `gate --publish` printed `PLAN APPROVED: revision 5, approval-r005-395ba4f5f0a0.json`.
- Parent step 5 (implement after go-ahead): NOT started. Mike has not said "go ahead" for implementation.
- Unplanned work:
  - The planloop claude-backend write checker was fixed (jade-ahw, commit 133969f).
  - A Sol-vs-Opus reviewer benchmark ran (jade-yvx) at Mike's request.
- Trajectory is on path. The open questions shrank: Q2 and Q3 were answered by Mike. Q1 and Q4 to Q7 are still open.

## Reference Documents

- `CLAUDE.md`:
  - rules 1 to 8;
  - the bead workflow;
  - the orchestrator/subagent model;
  - the context thresholds;
  - the Conservative git profile (no commit without Mike's OK).
- `docs/handoff/ARCHITECTURE.md`, `docs/adr/` (0001 to 0023, plus 0024 to be written by jade-h8i per the plan), `docs/handoff/DATA-MODEL.md`, `EVENTS.md`, `PRIVACY.md`, `docs/threat-model.md`.
- `docs/handoff/phases/phase-01-foundation.md`: the Phase 1 bead order and exit criteria.
- `.claude/skills/planloop/SKILL.md` and `references/handback.md`: the planner contract.
- **The approved plan:** `plans/planloop/jade-vtk.pl1/rev-005/plan.md`, 142,195 bytes, plan sha256 `6b86e6aa1953d7095cbee9aff644213b0eeb6382b0bc5949cf9ce28b4f6395cc`.

## The Goal

Build JADE's Phase 1 "Foundation and walking skeleton". The eight agent beads are:

| Bead | Plan key | What it builds |
|---|---|---|
| jade-h8i | scaffold | SvelteKit adapter-node, TypeScript strict, pnpm 12, ESLint/Prettier, Vitest, Playwright, module folders, Node 24 pinned |
| jade-urd | db | Postgres 16, Drizzle, forward-only migrations, parallel-safe test DB harness |
| jade-8v4 | config | zod typed config, fail-fast, no production secret defaults |
| jade-alt | observability | /healthz, /readyz, a closed JSON logger, request ids |
| jade-lhq | ui-shell | three shells, tokens, accessibility baseline, no off-origin requests |
| jade-xu0 | ci | GitHub Actions workflow |
| jade-80h | docker | multi-stage non-root image, compose.prod.yml with Caddy |
| jade-4zw | staging | blocked by the human bead jade-0za |

This session's goal was the CLAUDE.md-required phase planloop. That is done: the plan is approved and signed off. The end state Mike wants is the beads implemented one at a time by subagents, in the plan's section 16 order. Only he can start that, with a go-ahead.

## Where We Are

- **planloop run jade-vtk.pl1 is APPROVED** on revision 5.
  - Approval record: `plans/planloop/jade-vtk.pl1/approvals/approval-r005-395ba4f5f0a0.json`, referenced by `APPROVAL`.
  - `gate --publish` appended the gate outcome and Mike's words to run bead jade-vtk.2's notes.
- Revisions published:

  | Rev | Plan sha (prefix) | Size | Answers |
  |---|---|---|---|
  | 1 | 2365c1c1 | 84,397 B | Fable draft |
  | 2 | c406af9e | 132,010 B | FIX R1 to R8, plus H1 to H16 |
  | 3 | e9ae16eb | 129,429 B | R9 to R11 |
  | 4 | 445b6231 | 140,691 B | R12 to R14 |
  | 5 | 6b86e6aa | 142,195 B | R15 to R17 |

- Finding ledger (`plans/planloop/jade-vtk.pl1/ledger.md`, regenerated):
  - R1 to R17 are `verified`.
  - R18 is `decided` (decisions/D1.json, deferred to jade-80h as an implementation instruction).
- Decisions on disk in `plans/planloop/jade-vtk.pl1/decisions/`:
  - D1.json: R18, outcome `deferred`, follow_up jade-80h.
  - D2.json: RR1 to RR14, `accepted-risk`, each subject bound to the sha256 of its RR line text taken from `rev-005/handback.json`.
  - A1.json: the sign-off, written by `planloop.py signoff`, bound to rev 5's plan sha and gate call 6's receipt sha.
- Mike's exact words for D2 and A1: "accept RR1–RR14 as written; sign off rev 5; Q2 (a); Q3 yes".
- Q2 and Q3 answers are recorded in jade-vtk.2's notes:
  - Q2 (a): beads stay open with local gate evidence until the first green CI run covers them and they are merged. The go-ahead names the section 16 order, so the next bead can be worked while its predecessor is open.
  - Q3 yes: a subagent may install pnpm 12.21.0 at user level (standalone installer, edits `~/.bashrc`). Mike runs `pnpm exec playwright install --with-deps chromium webkit` once, after the scaffold's `pnpm install`.
- jade-80h notes carry D1's instruction: in the AC8 fresh-image-store procedure, step (1) is bounded. If `docker ps -a --filter name=bugfix-` still lists a container when no gate process runs, remove nothing, record the listing and ask Mike.
- **Commit 133969f** (jade-ahw, authorized by Mike: "yes, commit the jade-ahw checker fix") changed `.claude/skills/planloop/scripts/planloop.py`, `tests/test_planloop.py` and `SKILL.md` line 55. jade-ahw is closed.
- Test suites on that change: planloop `python3 .claude/skills/planloop/tests/test_planloop.py` gives 466 OK; fixpatch `bash .claude/skills/bugfix/tests/test_fixpatch.sh` gives 66 passed.
- **Uncommitted:** `plans/planloop/jade-vtk.pl1/` (untracked, the whole run) and `.beads/interactions.jsonl` (modified). Mike has not yet OK'd committing these. The proposed message is `chore(planloop): record Phase 1 run jade-vtk.pl1, approved rev 5 [jade-vtk]`.
- Branch is `master`. No git remote exists (Q1).
- Beads: `bd list --status=in_progress` is empty. Stats: 157 total, 110 open, 90 blocked.
- jade-yvx (benchmark bead) is open. Its notes hold the per-reviewer scoring table and a log line for every planloop review round.
- The planloop state directory `~/.local/state/planloop/jade-vtk.pl1/` holds snapshots snap-r001..r005 and call artifact dirs. The isolated copies are under `~/.local/state/planloop-isolated/r-*`.
- Benchmark scratch: `/tmp/claude-1000/-home-mikep-projects-jade/2ce41db7-f587-4071-a8ce-dc6121c8a6d1/scratchpad/bench/`.
  - Codex reviewer copies sol, sol-low-2, sol-low-3, sol-med-1, sol-med-2 (plus opus).
  - `run.sh <name> <effort>`.
  - `<name>-events.jsonl`, `<name>-final.json`, `<name>-stderr.txt`.
  - The scratchpad can be wiped; the durable record is jade-yvx's notes.
- Large-draft files the Plan agents wrote (kept per handback.md):
  - `/tmp/planloop-draft-16c639fb4ff05616.md` (rev 2)
  - `/tmp/planloop-draft-3646b5b1d255eef6.md` (rev 3)
  - `/tmp/planloop-draft-2ad2728ab10a487f.md` (rev 4)
  - `/tmp/planloop-draft-c0a0d453b7343ed3.md` (rev 5)
  - The handback records them; the published copies are in `rev-NNN/`.

## What We Tried (Chronological)

1. **Onboarding and init.** Read the parent handoff and narrated it. Mike said "go ahead, pin Node 24".
   - I created a duplicate run bead jade-vtk.1 by hand before learning that `init` creates the run bead itself (jade-vtk.2). jade-vtk.1 was closed as a duplicate.
   - Lesson: let `init` create the run bead.
2. **Discovery + obligations.**
   - A subagent ran 84 searches: 25 binding, 24 candidate, 29 irrelevant sources.
   - OB1 to OB80 were drafted. The host re-verified each as a byte-exact substring of its source.
   - inputs-r1.json: 35 repo_files, dir_inventories `docs/adr` and `docs/handoff/phases`.
3. **Rev 1 by Fable**, 84,397 B. `handback` needed `--revision 1`; it failed without it.
4. **Call 1 attempts 1 and 2 (Opus high): both VOIDED.**
   - Cause: the reviewers ran read-only `git branch -a`, and the claude-backend write checker counted any `git branch` as a write.
   - Their findings were still good. The host verified them as H1 to H8 and put them in `brief-r2.md`.
5. **Rev 2 draft by Opus (H1 to H8)** came out shrink-only, because H-items are not R findings, so no `FIX R<k>` line was possible.
   - Shrink-only forces a meaning check.
   - Mike chose: relax the checker, re-review rev 1 to get real R findings, then FIX them.
6. **Checker fix (jade-ahw)** by a subagent, with host review:
   - First version newly allowed `git -c ...` and `--exec-path` (command execution). The host caught it; both are now always writes.
   - Mike then asked to close the `-C` hole too. Global options are now skipped before reading the subcommand.
7. **Usage-window pause.** Mike asked for a 2 h wait at 06:54 EST. The in-flight Sol-medium runs were killed; a cron resume fired at 08:57 EST.
8. **Call 1 attempt 3 (Opus high) VOIDED** with "relevant inputs changed during the review: .claude/skills/planloop/SKILL.md changed".
   - The uncommitted jade-ahw doc line differed from rev 1's snapshot, and SKILL.md is a rev-1 repo_file.
   - This was the third invalid attempt in a row, so planloop set the run `blocked`.
   - Its findings were good and were host-verified into H14 to H16.
9. **Unblock.** Mike chose "Revert line, rerun".
   - SKILL.md was restored to HEAD bytes (equal to the snapshot), with the edited copy saved in scratchpad as `SKILL.md.jade-ahw`.
   - `state --set active --reason ...` was recorded.
   - Attempt 4 was refused ("1 to 3 attempts per call"), so the re-review became **call 2 attempt 1**.
10. **Call 2 a1 (Opus high, rev 1): COUNTED.** REVISE 4M/4L, ingested as R1 to R8 (all `new`). The SKILL.md line was reapplied after the receipt.
11. **Rev 2 FIX, first try:** written by a *general-purpose* Opus agent into a draft file. `handback` refused: "the planner must be the read-only Plan agent, not 'general-purpose'".
    - Fix: a fresh read-only Opus **Plan** agent audited that candidate and handed it back via the large-draft path (`--transcript ... --draft /tmp/planloop-draft-<nonce>.md`).
    - It made 3 corrections: stack_frames built from V8 call sites; compat passes when the base has no migrations; "Three profiles".
12. **Rev 2 published.** brief-r2 gained the H9 to H16 section. `findings propose` was run (dispatch refuses without it).
    - **Call 3 a1 (working): APPROVED** with 3 lows, R9 to R11.
13. **Rev 3** (PD14 one image, PD15 refusal tests, PD16 container-written files).
    - **Gate call 4: REVISE**, with R12 medium: `--pull never` is global in Compose, so postgres/caddy were never pulled. This regression came from the R9 fix. Also R13 and R14 low.
14. **Rev 4** (pull third-party images first; per-checkout/per-run tags; one build definition via buildx bake).
    - **Gate call 5: APPROVED** with 3 lows, R15 to R17. Mike chose "Fix in rev 5".
15. **Rev 5.** **Gate call 6: APPROVED** with 1 low, R18. Mike chose "Decide it now"; recorded as D1.
16. **Sign-off.** D2 (RR acceptance) was written by the host via a small Python script that hashed each RR line from `rev-005/handback.json`. `signoff --quote` wrote A1, then `gate --publish`.
    - A first D1 attempt failed with `subjects[0]: missing text_sha256`. The schema requires the key, but its value may be null for a finding subject.

## Key Decisions

- **Escalated track, claude backend.** Fable wrote rev 1. Opus Plan agents wrote the FIX revisions. Every review and gate was a fresh Opus Plan agent at high effort. Codex/Sol was used only in the side benchmark, never as a planloop reviewer (memory: planloop-opus-reviews).
- **Relax the checker and re-review rev 1** rather than accept a shrink-only rev 2 with a meaning check (Mike: "Relax checker, then re-review (Recommended)"). Rejected alternative: publish rev 2 as shrink-only and let a meaning check judge it.
- **Close the `-C` hole and fail closed on `-c` / `--exec-path`** (Mike: "yes, close the -C hole too"). Rejected: a narrower fix that only allowlisted `git branch -a`.
- **Unblock by reverting SKILL.md line 55 during the review window** (Mike: "Revert line, rerun"). Rejected:
  - skipping straight to rev 2 with the current SKILL.md bundled;
  - committing first, which would not help, because the committed bytes still differ from the rev-1 snapshot.
- **The host verifies every reviewer finding** against the plan before ingesting. All ingested findings were mapped `new`; none was rejected.
- **Gate lows:** R15 to R17 were fixed in rev 5 (Mike: "Fix in rev 5 (Recommended)"). R18 was decided rather than fixed (Mike: "Decide it now (Recommended)"), because each gate kept raising one or two new lows of that size. Rejected: a rev 6 plus another gate, about 15 more minutes for a one-line liveness bound.
- **R18 recorded as outcome `deferred` with follow_up jade-80h**, plus a jade-80h note, so the implementer sees it. Rejected: `accepted-risk`, because it is an instruction to carry out, not a risk.
- **Planner must be a read-only Plan agent.** A general-purpose writer is refused by `handback`. Use the large-draft procedure for plans over about 100 KB.
- **Benchmark conclusion (for Mike's "is Sol low as good as Opus medium" question):**
  - Opus high is the most complete single reviewer.
  - Sol (medium) finds different, real issues cheaply but misses most known ones.
  - Sol is useful as a cheap second opinion, not as a replacement.
  - Mike has not decided to change the reviewer backend.

## Evidence & Data

### Planloop calls (all Opus Plan agent, high)

| Call/att | Kind | Rev | Receipt | Verdict | Findings | Tool calls | Tokens | Time |
|---|---|---|---|---|---|---|---|---|
| 1/1 | working | 1 | invalid (git branch -a) | — | (H1 to H7 found) | — | 144,554 | 438 s |
| 1/2 | working | 1 | invalid (git branch -a) | — | (H2, H4, H5, H8, H3 partial) | — | 145,188 | 452 s |
| 1/3 | working | 1 | invalid (SKILL.md changed) | REVISE | 1M/5L, became H14 to H16 | 12 | 129,485 | 312 s |
| 2/1 | working | 1 | counted | REVISE | 4M/4L, R1 to R8 | 11 | 136,889 | 400 s |
| 3/1 | working | 2 | counted | APPROVED | 3L, R9 to R11 | 14 | 146,866 | 375 s |
| 4/1 | gate | 3 | counted | REVISE | 1M/2L, R12 to R14 | 13 | 149,855 | 377 s |
| 5/1 | gate | 4 | counted | APPROVED | 3L, R15 to R17 | 12 | 129,656 | 217 s |
| 6/1 | gate | 5 | counted | APPROVED | 1L, R18 (decided D1) | 12 | 127,451 | 219 s |

### Findings ledger

| R | Sev | Short | Fixed in | State |
|---|---|---|---|---|
| R1 | M | compose-up probes fixed host ports (=H1) | rev 2 | verified |
| R2 | M | ensureAppRole cluster-wide race (=H2) | rev 2 | verified |
| R3 | M | migration-compat runs base schema (=H8) | rev 2 | verified |
| R4 | M | dev raw-error print breaks rule 4 (=H3) | rev 2 | verified |
| R5 | L | non-test boots vs test-only DB URL | rev 2 (V8) | verified |
| R6 | L | COMPOSE_PROJECT_NAME overrides `name:` (=H6) | rev 2 | verified |
| R7 | L | src/lib/shared/events/ out of scope | rev 2 | verified |
| R8 | L | jade-alt needs jade-urd, not in bead graph | rev 2 (section 16 deps) | verified |
| R9 | L | infra stack ran jade-app:local, not the tested image | rev 3 (PD14) | verified |
| R10 | L | reset-refusal test passed via V2, not U6 | rev 3 (PD15) | verified |
| R11 | L | env-init writes VM env file as uid 1000 | rev 3 (PD16) | verified |
| R12 | M | `--pull never` global, so postgres/caddy never pulled | rev 4 | verified |
| R13 | L | daemon-wide jade-app:ci tag | rev 4 | verified |
| R14 | L | build stanza untested, build defined twice | rev 4 | verified |
| R15 | L | gha cache needs Actions runtime in run: steps | rev 5 | verified |
| R16 | L | stack-up rebuild not a cache hit | rev 5 | verified |
| R17 | L | fresh-store guard vs devdb container | rev 5 | verified |
| R18 | L | fresh-store step 1 can wait forever | — | decided (D1, jade-80h) |

### H-items (host-verified, in brief-r2.md)

| H | Sev | Issue |
|---|---|---|
| H1 | M | compose-up probes host port 5432 |
| H2 | M | ensureAppRole race across databases |
| H3 | H | dev raw-error print breaks INV1 |
| H4 | M | compose.prod.yml env contract, JADE_APP_DB_PASSWORD |
| H5 | L | D1 omits tools/load-env.ts |
| H6 | L | COMPOSE_PROJECT_NAME precedence |
| H7 | L | image job budget |
| H8 | L | migration-compat template |
| H9 | M | CI env wiring (Sol N2 + Opus-medium F4) |
| H10 | L | U5 "remove or rename" wording |
| H11 | M | stack_frames can carry message lines (Sol med 2) |
| H12 | L | Z4 post-switch rollback (Sol med 2) |
| H13 | M | base ref / fetch depth undefined (Sol med 2) |
| H14 | M | config fail-fast message swallowed by A4 handlers (c1a3) |
| H15 | L | ADR 0024 "0015 unchanged" wording (c1a3) |
| H16 | L | clean-clone tests the previous commit (c1a3) |

### Reviewer benchmark (rev 1, same copy and prompt, scored against H1 to H10)

| Reviewer | Found | New valid | Invalid | Cost |
|---|---|---|---|---|
| Opus high c1a1 | H1 to H7 (7/8) | — | — | 144,554 tok, 438 s |
| Opus high c1a2 | ~4.5/8 | — | — | 145,188 tok, 452 s |
| Opus high c2a1 | 5/10 (H1 H2 H3 H6 H8) | 2 (R7, R8) | 0 | 136,889 tok, 400 s |
| Opus high c1a3 | 2/10 (H1, H2) + H4 partial | up to 4 | 0 | 129,485 tok, 312 s |
| Opus medium | 3/8 (H1, H2 low, H8) | 1 (F4) | 0 | 116,442 tok, 246 s, 11 calls |
| Sol low 1 | 1 (H3) | 1 (N2) | 0 | 6 cmds, 1,403 out tok |
| Sol low 2 | 1 (H3) | 0 | 1 (U5 misread) | 9 cmds, 297,014 in, 1,841 out, 51 s |
| Sol low 3 | 0 | 0 | 1 (U5 misread) | 9 cmds, 371,663 in, 1,921 out, 54 s |
| Sol medium 1 | 1/10 (H3) | 0 | 1 overstated (Q2(b)) | 30 cmds, 674,844 in, 4,203 out, 137 s |
| Sol medium 2 | 1/10 (H9) | 3 (H11, H12, H13) | 0 | 26 cmds, 671,249 in, 5,007 out, 152 s |

Codex command used:
```
codex exec -m gpt-6-sol -c 'model_reasoning_effort="<low|medium>"' -s read-only -C <copy> --skip-git-repo-check --ephemeral --json -o <final.json> "<prompt>"
```

### Revision 5 CI budget (12.2)

The image job is 8:05 cold (1:15 setup + 0:20 pull + 3:00 build + 2:15 infra + 1:15 stack-up rebuild) and 5:55 warm. The slack under the 9-min timeout is 0:55 cold and 3:05 warm. OB10 (under 10 min) holds on estimates only (RR2).

### Key hashes

- Bundles:

  | Rev | Bundle sha256 |
  |---|---|
  | 1 | f3b2247e22c6d7365d5a5ad900070fdf25d28d34cbef9e8946bfd977bdeb6f89 |
  | 2 | dcced5b315f7bea4791c3e030e8ff0f475fe2da0570ecf9a68652e971b13d232 |
  | 3 | fa000c2550afb5e518041b1693add57a4b44823a0869859e85079b2e81e4459e |
  | 4 | 5a9ec3424e3f71b7c5b75c3e91664f3fa49760787fa76671270e749038bcbf7a |
  | 5 | ad02336e31f169c779fe7242a92b8ca9658f0aefae575e0cbb35e41f2441ecab |

- Planner nonces: rev 2 16c639fb4ff05616, rev 3 3646b5b1d255eef6, rev 4 2ad2728ab10a487f, rev 5 c0a0d453b7343ed3. Rev 2's refused general-purpose draft used 5274ae2d508a7c9d.

## Code Analysis

- The `jade-ahw` change in `.claude/skills/planloop/scripts/planloop.py`:
  - `git_writes(args)` skips `GIT_GLOBAL_FLAGS` (`-P`, `--no-pager`, `-p`, `--paginate`, `--no-replace-objects`, `--bare`, the pathspec flags, `--no-optional-locks`) and `GIT_GLOBAL_VALUED` (`-C`, `--git-dir`, `--work-tree`, `--namespace`, the latter three also in `=` form).
  - Any unknown option, including `-c` and `--exec-path`, counts as a write.
  - `--version`, `--help` and `-h` count as non-writes only as the last word.
  - For `branch`, it returns `not git_branch_lists_only(rest)`, a fail-closed allowlist:
    - list flags `-a -r -l -v -vv -i --all --remotes --list --show-current --verbose --column --color --no-abbrev ...`;
    - valued `--sort --format --points-at --abbrev`;
    - commit filters `--contains --merged ...`;
    - a bare word is a pattern only with `-l`/`--list`;
    - bundles `-[arlvi]+`.
  - Called from `writes_files()`.
- Planloop mechanics learned (not obvious from SKILL.md at a glance):
  - Each call allows at most 3 attempts. After 3 invalid in a row the run is `blocked` until `state --set active --reason`.
  - `receipt` compares every bundled repo_file against the current working tree. Editing a bundled file (even a skill doc) while a review runs voids it.
  - `dispatch` refuses while a published revision has not been through `findings propose`.
  - `handback` checks that the planner agent type is `Plan`. `--draft` needs a nonce-named file whose sha256 the agent's final message states.
  - Gate readiness needs:
    - no open finding, lows included (verified, withdrawn or decided);
    - an accepted-risk decision per RR bound to `sha256(RR line text)` from `rev-NNN/handback.json["residual_risks"]`;
    - a sign-off bound to the gate receipt;
    - `gate --publish`.
  - Decision schema `planloop-decision/1`:
    - fields: id, by=Mike, quote, recorded_at, recorded_by, subjects[{id, text_sha256 (key required, may be null)}], outcome ∈ {accepted-risk, rejected-finding, deferred, scope-out}, follow_up (required for deferred);
    - the file must be `decisions/<id>.json`;
    - applied with `findings decide --decision`.
- The receipt path for the claude backend is `~/.claude/projects/-home-mikep-projects-jade/<session>/subagents/agent-<id>.jsonl`. The session dir for this conversation is `2ce41db7-f587-4071-a8ce-dc6121c8a6d1`.

## Files Changed

### Committed (133969f)
- `.claude/skills/planloop/scripts/planloop.py`: `git_writes`, `git_branch_lists_only` and the flag tables (+76).
- `.claude/skills/planloop/tests/test_planloop.py`: `ClaudeBackend.test_a_list_only_git_branch_is_not_a_write`, including an end-to-end receipt counted for the formerly voided command shape (+33).
- `.claude/skills/planloop/SKILL.md` line 55: "writing git subcommands (a list-only `git branch` is allowed)".

### Uncommitted (await Mike's OK)
- `plans/planloop/jade-vtk.pl1/`:
  - run.json, HEAD, APPROVAL;
  - discovery.json, obligations-draft.json, brief-r1.md, brief-r2.md (with H1 to H16), inputs-r1.json, inputs-r2.json (used for revs 2 to 5);
  - rev-001 … rev-005 (plan.md, handback.json, bundle manifest);
  - reviews/call-001-a1..a3, call-002-a1 … call-006-a1 (input/prompt.txt, receipt.json);
  - intents/, decisions/{D1,D2,A1}.json, approvals/, ledger.md;
  - drafts/ (the old Opus rev-2 drafts: e909df6d..., 5274ae2d...).
- `.beads/interactions.jsonl`.

### Beads written this session
- jade-yvx (created): benchmark plus round log.
- jade-ahw: created, then closed.
- jade-vtk.1: duplicate, closed.
- jade-vtk.2: run bead; notes carry the gate outcome and the Q2/Q3 answers.
- jade-80h: D1 note.

## User Feedback & Preferences (REQUIRED — never omit)

- "go ahead, pin Node 24": Node 24 over 26. It is recorded in jade-h8i notes, and jade-h8i writes it as ADR 0024.
- On the checker: first "Later, after the Phase 1 plan", then, once he understood, "Relax checker, then re-review (Recommended)". "Sorry for the earlier denial, I didn't fully understand." Explain mechanism-level consequences clearly before asking.
- "yes, close the -C hole too": he prefers security holes closed when found.
- Asked why the checker issue never arose in quartz-rs. The answer was the different workflow; he accepted it ("okay that makes sense").
- "run the sol vs opus benchmark on rev 1. Keep a bead deatiling this benchmark and each review round we run": keep logging every round in jade-yvx.
- "try codex at medium after a few more low codex so we get ample data to make a decision here": data-driven model choice. No backend decision has been made yet.
- "quick note, before launching the codex, wait 2 hours before continhing, just need to let the window reset": respect his usage windows; pause Codex work when asked.
- "Revert line, rerun", "Fix in rev 5 (Recommended)", "Decide it now (Recommended)": he picked the recommended option each time. Give a clear recommendation first.
- "yes, commit the jade-ahw checker fix": commits only on explicit OK (Conservative profile).
- "accept RR1–RR14 as written; sign off rev 5; Q2 (a); Q3 yes": the terse batch format worked well. Offer a one-line answer template.
- Standing memories: delegate edits to subagents; Opus high reviews unless Mike says Codex; binding sources stay binding; handoff via this skill only.

## Where We're Going

1. **Ask Mike to OK the commit** of `plans/planloop/jade-vtk.pl1/` and `.beads/interactions.jsonl` (`chore(planloop): record Phase 1 run jade-vtk.pl1, approved rev 5 [jade-vtk]`).
2. **Wait for Mike's explicit implementation go-ahead.** The plan approval is not authorization. The go-ahead should name the section 16 order (Q2 (a)).
3. **At go-ahead, before the first claim:** add the bead dependencies the plan's section 16 lists (jade-urd on jade-8v4, jade-alt on jade-urd, jade-xu0 on jade-80h, jade-lhq on jade-alt) with `bd dep add`, plus a note on each bead (R8).
4. **Implement jade-h8i** via a subagent with a full brief from rev-005 section 7:
   - user-level pnpm 12.21.0 install (Q3 yes);
   - Node 24 via `.nvmrc` / devEngines.runtime;
   - ADR 0024 plus one Consequences line in 0015 and a README row.
   - Then Mike runs the Playwright `--with-deps` step.
   - The gate is `pnpm lint && pnpm check && pnpm test && pnpm e2e`.
   - `pnpm ci:clean-clone` runs after the commit, against that SHA (H16).
5. Then the beads in section 16 order (8v4, urd, lhq, alt, xu0, 80h). jade-4zw stays blocked by jade-0za. A small bead covered by this plan needs no new planloop. A mechanism change beyond the plan goes back to planloop (RR4).
6. Raise Q1 (remote) when jade-xu0's AC2 is reached, Q4 at the end of the workable Phase 1 beads, Q5 with jade-0za, and Q6/Q7 whenever convenient. The older Q7/TM-2 (jade-7s7.1/.2 placement) and the product questions are raised when the work reaches them.
7. Optional: Mike may decide on the reviewer backend from the jade-yvx data. Close jade-yvx when he does, or when he says the benchmark is done.

## Risks & Blockers

- **RR4:** the tool versions (SvelteKit 3.2, pnpm 12, Vite 8, Vitest 5, Compose 5.4 bake, Node 24 `Error.prepareStackTrace`) were never installed. A mismatch that changes a mechanism is a stop point back to planloop. jade-h8i will be the first real test.
- **No remote or CI (RR2, Q1):** no bead can close under Q2 (a) until CI exists. Work proceeds with beads left open and their evidence in notes.
- **CI budget is tight:** 0:55 of cold slack on the image job, all estimates.
- **Reviewers noted that the R finding texts are not in the bundle** (`findings.json` holds only state and severity). Later reviewers judged fixes from FIX lines. Worth a planloop improvement bead (put the finding evidence text in feedback.md).
- **Do not edit a bundled repo file** (for example `.claude/skills/*/SKILL.md`, CLAUDE.md or docs) while a planloop review is running. It voids the receipt.

## Open Questions

- **Q1:**
  - Where is the remote (GitHub?), and which CI host?
  - May the trunk be renamed `master`→`main`?
  - What is the merge flow, and who sets branch protection?
  - Which registry?
  - Blocks AC2.
- **Q4:** may Phase 2 start without staging if jade-0za is still open?
- **Q5:** how is port 22 limited with hosted runners? Settle with jade-0za (RR10).
- **Q6:** confirm `/media` stays closed until jade-u8z (RR1).
- **Q7:** is a development-only error view wanted? It is a rule-4 question; nothing is planned.
- Reviewer backend: will Mike switch any rounds to Sol, or add Sol as a second opinion, based on jade-yvx?

## Quick Start for Next Session

```bash
# Restore context
bd prime
bd show jade-vtk.2      # run bead: gate outcome, Q2/Q3 answers
bd show jade-yvx        # benchmark + every review round
bd show jade-h8i        # first implementation bead

# Approval state
python3 .claude/skills/planloop/scripts/planloop.py gate --run jade-vtk.pl1   # expect PLAN APPROVED, rev 5
cat plans/planloop/jade-vtk.pl1/ledger.md

# Key files to read first
plans/planloop/jade-vtk.pl1/rev-005/plan.md        # sections 7 (h8i), 16 (order, deps, gates), 17 (AC), 18 (Q1-Q7)
CLAUDE.md
docs/handoff/phases/phase-01-foundation.md
.claude/skills/planloop/SKILL.md

# Verify current state
git status -s        # expect: M .beads/interactions.jsonl, ?? plans/planloop/jade-vtk.pl1/
python3 .claude/skills/planloop/tests/test_planloop.py   # 466 OK

# Next action
# Ask Mike: OK to commit the run dir? And: go-ahead to implement Phase 1, starting jade-h8i in section 16 order?
```

## Session Closed
**Closed at:** 2026-11-15 19:29 EST
**Commit:** 4d20022
**Session status:** Handed off to next session
