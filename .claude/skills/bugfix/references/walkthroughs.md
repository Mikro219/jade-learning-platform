# bugfix walkthroughs (procedural validation, quartz-rs-p49, quartz-rs-3bm)

Twelve scenarios traced through `../SKILL.md` as revised on 2026-10-23 (p49; 11 and 12 and the edits to 4 and 8 for `quartz-rs-3bm`). Adapted for JADE on 2026-11-14: the examples now use JADE's files and gates; each scenario's logic and its test citations are unchanged, and the `quartz-rs-*` ids are provenance only. These are reasoning checks of the procedure, not tests: each names the step that catches the problem and whether the catch is **mechanical** (a script or exit status decides) or **judgement** (an agent or the orchestrator decides). The mechanical parts that rest on `scripts/fixpatch.sh` are exercised by `../tests/test_fixpatch.sh`; scenarios 4, 5, 7, 8, 11 and 12 cite those cases. A walkthrough never stands in for a test, and a test never shows that the procedure around it is followed.

## 1. A correction introduces a new regression
Review of patch P1 finds F1 (MEDIUM); the implementer fixes it, producing P2, which breaks a path P1 left correct.
- Step 5: a behavior-changing correction means a new patch (`fixpatch.sh patch` → P2, new hash) and a new review of the **whole** P2 with P1's hash given, so the interaction is in view. The reviewer raises F2 (related: caused by the fix) → blocks closure.
- Step 6.3: the gates recorded for P1 are void; they must be re-run on P2 after `verify` matches P2.
- Outcome: no closure until a review of the final patch is clean. Catch: judgement (review) + mechanical (hash change voids old checks).
- If corrections keep breaking adjacent invariants → Routing (planloop).

## 2. The builder wrongly rejects a valid finding
The implementer proposes "reject F3: the lock already covers this", citing code that does not in fact cover the failure scenario.
- Step 4: a rejection is a proposal. F3's bead stays open until the reviewer accepts the evidence or Mike decides. The reviewer, shown the evidence against F3's scenario, does not accept → F3 stays open and blocks closure (related HIGH/MEDIUM).
- Outcome: the finding is fixed or goes to Mike; it is never closed by the implementer. Catch: judgement (reviewer), enforced by the closure checklist (every finding bead closed with an independent resolution).

## 3. A related failure appears in another file
The fix in `src/lib/server/events/ingest.ts` changes a return value; `src/lib/server/events/progress.ts` consumes it and now writes `kit_progress` for a rejected event.
- Step 3: "related" is causal, not by file: the fix exposes an unsafe interaction elsewhere → related, blocks closure, even though `progress.ts` was not in the original scope.
- Step 2: the corrected patch now includes `progress.ts`; the orchestrator records why (caused by the bug fix), so the out-of-scope check does not reject it.
- Contrast: an unrelated defect noticed in `progress.ts` (present before the fix, independent of it) becomes a linked bead and does not enter the patch.
- Catch: judgement (reviewer's causal test), with the "related until shown otherwise" default.

## 4. Unrelated edits share the file with the fix
Mike has an uncommitted edit at the top of `src/lib/server/auth/sessions.ts`; the bug is lower in the same file.
- Step 0.2–0.3: the baseline captures his edit as part of the starting state; it is listed as pre-existing work and never reset or stashed.
- Step 2: `fixpatch.sh patch` diffs baseline → current, so his edit is absent from the patch (test: "unrelated edit in the same file is excluded, the fix is included").
- Step 0.5: the fix will be committed, so the delivery candidate is HEAD + patch (`fixpatch.sh candidate`, tree `T`; test: "candidate holds HEAD + the fix only ..."); the review and the gates run there, so they describe the tree the commit will hold.
- Delivery: nothing may be staged beforehand (`git diff --cached --quiet`, else ask Mike); `git apply --cached` then stages only the fix, or refuses when his edit is inside a hunk's context (tests: "fix far from unrelated edit stages alone", "... refuses to stage (fail closed)") → ask Mike. `fixpatch.sh staged <T>` then compares the whole staged tree with `T` (tests: "staged filenames match but content differs ...", "the exact validated candidate stages ... and commits as that tree").
- Catch: mechanical.

## 5. An untracked test is omitted from the review patch
The implementer adds a new regression test file, `src/lib/server/auth/sessions.regress.test.ts` (untracked); a plain `git diff -- <path>` would not show it.
- Step 2: fixpatch snapshots untracked non-ignored files, so the new test is in the patch and its file list (test: "untracked regression test is included"); the reviewer sees and judges it.
- Catch: mechanical.

## 6. The regression test fails before the fix for the wrong reason
On the original code the new test fails, but with a TypeScript or import error (it imports a helper the fix adds, which does not exist in the original code).
- Step 6.1: "fails" must be the bug's assertion or behaviour; a type or import error, missing fixture, unrelated exception or timeout does not count. The orchestrator reads the recorded log, sees the type or import error, and the evidence is not accepted.
- Remedy: restructure the test so it type-checks and imports against the original code (exercise the public behaviour through the module's `index.ts`, not the new helper), re-run in the candidate's no-fix counterpart (step 6.1: `candidate <bead> none` for a HEAD + fix candidate), record the expected failure; then the pass on the fixed code with the same command.
- Catch: judgement on the recorded log (the log and exit status are mechanical; "right reason" is read).

## 7. Files change after a clean review or passing gates
After a clean review of P3 and green gates, someone edits a file in the fix.
- Step 6 start / 6.3: `fixpatch.sh verify <bead> P3` fails (test: "verify fails after a post-review change"), so the review and gate records no longer apply to the tree; back to step 2 with a new patch.
- Resume step 2 catches the same thing after an interruption (hash differs from the last recorded patch).
- Catch: mechanical.

## 8. A gate fails for an independently demonstrated pre-existing reason
`pnpm e2e` fails one check on the fixed tree.
- Step 6.2: it counts as a regression until the same command fails the same way on the same base without the fix: for a HEAD + fix candidate that is `candidate <bead> none` at the same HEAD, not `materialize <bead> none`, whose unrelated uncommitted work can hide or add failures (tests: "the dirty baseline passes the check the candidate fails ...", "candidate ... none (same HEAD, no fix) reproduces it ..."). Run it with the same `pnpm e2e` command, in an equivalent fresh worktree with its own Compose project and fresh database, and record both logs (paths, hashes, exit codes). If that run fails identically, it is pre-existing and gets its own linked bead. Closure may proceed without asking Mike only if the fix's relevant checks pass and the independent reviewer, shown both logs, confirms the failure does not undermine validation of the fix; the report then says "validated with a confirmed pre-existing gate failure", never "all gates green". If attribution is uncertain or the failure prevents meaningful validation, stop and ask Mike. If it passes, it is a regression. A gate that stopped before its own final status line has not run at all.
- Not acceptable: "that's a known WebKit flake" from memory without the baseline run.
- Catch: mechanical comparison of two recorded runs, plus judgement that "the same way" holds.

## 9. An interrupted run resumes with unresolved findings
The session ends after review of P2 raised F4 and F5 and the implementer was mid-correction.
- Resume 1: `bd list --parent <bead> --all --json` shows F4, F5 open with the patch hash they were raised on.
- Resume 2: `fixpatch.sh patch` gives P2' with a new hash (the partial correction) → the last review does not cover it → step 2/3 for the new patch.
- Resume 3: any gate without a recorded exit status is treated as not run.
- Outcome: nothing is assumed from the conversation; bead states are the status. Catch: mechanical (hash comparison, bead states).

## 10. Repeated corrections reveal an architectural problem
F6 is still unresolved after two corrections; the reviewer argues the dispatch design itself cannot keep the invariant.
- Routing: two failed corrections and an architectural disagreement → stop bugfix, record the reason on the bug bead, open a planloop run (`init --track escalated --risk-domains <e.g. consent-gate,idempotency> --rationale ...`).
- The partial patch stays on disk and in its baseline ref; nothing is reverted. No further code until planloop's plan is approved and Mike authorizes implementation.
- Catch: judgement on the trigger (the correction count is recorded in the finding bead's notes; a third consecutive review with new related HIGH/MEDIUM findings also triggers it), then planloop's gates.

## 11. An unrelated uncommitted edit makes the fix look correct
Mike has an uncommitted local change that adds a missing default (a config value, a guard). The fix silently relies on it, and the fix will be committed without it.
- Step 0.5: the delivery candidate is HEAD + fix, which lacks his edit (test: "an unrelated uncommitted file that makes the fix pass is absent from the delivery candidate, whose gate fails").
- Step 3: the reviewer reads the candidate worktree, so a claim that only holds with his edit present is a finding against the fix, not a pass.
- Step 6: the gates run in the same candidate and fail there, even though they would pass in his tree. Evidence recorded against the working-tree variant's tree does not match `T` (test: "check binds evidence to the candidate tree ...").
- Catch: mechanical (the candidate's content, tree hash binding) plus judgement (the reviewer reads the right tree).

## 12. Cleanup while a gate is still running, next to a user's worktree
After an interruption, the bead has two recorded worktrees: one with `pnpm e2e` still running in it, and one idle. Mike also has a worktree of his own.
- Resume 4: `fixpatch.sh cleanup <bead>` removes the idle one and refuses the busy one, so the running gate is not cut off (test: "cleanup refuses a worktree a running process ... is using"); that gate's result still counts only when its log has a final status line and `check` passes.
- Mike's worktree is not in the record, so it is refused even if named explicitly; a recorded path he has since reused fails the owner check (tests: "cleanup refuses the user's worktree ...", "... a recorded path the user has since reused ...").
- Catch: mechanical. Limit: a Docker container (the gate's Postgres, run by the Docker daemon) or a browser holding no file or cwd in the worktree is outside the process scan: check `docker ps` and the worktree's Compose project, and stop them before cleanup.
