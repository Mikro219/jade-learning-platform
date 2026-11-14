# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->


## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

_Add your project-specific conventions here_


## JADE learning platform

Web platform that hosts the learning modules for JADE STEM kits. Kit codes unlock content; kit-level usage data is collected, with consent, to redesign the modules.

**Read before any work:** `docs/handoff/ARCHITECTURE.md`, `docs/handoff/DECISIONS.md`. Data shapes: `docs/handoff/DATA-MODEL.md`, `docs/handoff/EVENTS.md`. Privacy promises: `docs/handoff/PRIVACY.md`. Phase detail: `docs/handoff/phases/`.

### Rules that are not up for negotiation

1. No accounts, names or free-text input for children. Ever.
2. When a kit's `logging_enabled` is false, the server stores nothing about that kit's activity. The `p6-nolog-invariant` test must never be skipped, weakened or deleted.
3. Class and kit identity come from the session, never from a request body.
4. Plain kit codes, join codes and tokens are never stored or logged. IP addresses are never stored or logged.
5. No request from the browser to any origin but our own. No third-party scripts, fonts, analytics or embeds.
6. Step IDs are permanent. A changed step gets a version bump; CI enforces it.
7. Do not write teaching content for the kit. Use the `demo` kit for development. Real content comes from Given.
8. The decisions in `docs/adr/` stand. If one looks wrong, file a `decision` bead and stop.

### Work tracking: beads

All work is tracked with `bd`. Do not keep a separate TODO list.

```bash
bd prime                                              # workflow context, run at session start
bd ready --exclude-type epic --exclude-label human    # what can be worked now
bd show <id>                                          # full description + acceptance criteria
bd update <id> --claim                                # take it
bd close <id> --reason "what was done, commit sha"    # finish it
```

- Work one bead at a time, lowest phase and highest priority first.
- **Never start a bead labelled `human`.** If one blocks you, say so and stop, or pick other ready work.
- A bead is done when every acceptance criterion is met, tests pass locally and in CI, and the change is merged. Not before.
- Found something out of scope? `bd create "..." -t task -p 2 --deps discovered-from:<current-id>` and carry on. Do not widen the current bead.
- Found a bug? `bd create "..." -t bug -p <0-3> -l bug` with reproduction steps, then use the **bugfix** skill on it.
- `docs/handoff/beads/id-map.json` maps plan keys (`p3-join`) to bead IDs.

### How each bead is worked

1. `bd show <id>`; read the linked phase file section.
2. Plan with the **planloop** skill before writing code.
   - Run a **planloop** for each new phase, before its first agent bead is implemented. That plan covers the phase's agent beads against their acceptance criteria and the phase's exit criteria.
   - Run a separate planloop for each major implementation. That means work in one of planloop's risk domains (it would start on the escalated track), a new mechanism, or a change to a migration, the event catalog, the content format or the authorization matrix.
   - A small bead already covered by the approved phase plan does not need its own run.
   - An approved plan is not authorization to implement. Implementation waits for Mike's go-ahead.
3. Implement with tests. Every new route goes into the authorization matrix test.
4. Run `pnpm lint && pnpm check && pnpm test && pnpm e2e`.
5. Commit with the bead ID in the message. Merge once CI is green; staging deploys itself.
6. `bd close <id> --reason "..."`. When a phase's last bead closes, check the phase's exit criteria, then `bd epic close-eligible`.

### Stop and ask the human when

- A `human` bead blocks all remaining ready work.
- A bead is blocked by an open `decision` bead labelled `human`: bring Mike that decision when the work reaches it.
- A change would touch rules 1 to 6 above.
- A secret, payment, DNS change or production deploy is needed.
- The same test has failed three times after three different fixes.

### Working model: orchestrator and subagents

The main Claude Code session is the **orchestrator**. It delegates tasks (code, tests, docs, skill edits) to subagents with a complete brief and makes minimal to no changes itself, except the steps the `planloop` or `bugfix` skills or this file assign to the host: running `bd`, verifying findings by reading the code, risk classification, capturing baselines and patches, building bundles and dispatching reviews, running gates, staging and committing under authorization, and reporting to Mike.

The `planloop` and `bugfix` skills in `.claude/skills/` were adapted from another project (quartz-rs). If a statement in them does not hold for JADE (a command, path, gate or risk domain), have a subagent correct the skill, and run its test suite (`python3 .claude/skills/planloop/tests/test_planloop.py`, `bash .claude/skills/bugfix/tests/test_fixpatch.sh`) after any change.

### Context management (long sessions)

- **<50% context used:** normal operation.
- **50-60%:** make sure durable state is current, so a forced stop wouldn't
  lose anything: the bead's notes (`bd update <id> --append-notes ...`), an
  in-flight planloop run's files under `plans/planloop/<run>/` (regenerate
  `ledger.md` with `planloop.py ledger --run R`), and a bugfix bead's
  recorded baseline, patch hashes and checks.
- **~65%:** the preferred point to hand off, if there's a sensible boundary
  right there.
- **70-75%:** finish the current atomic unit, then hand off.
- **80%+:** do not begin substantial new work; wrap up and hand off.

**Do not interrupt an atomic unit solely to hit 65%.** A planloop review
round (dispatch through receipt and ingest), a bugfix correction mid-flight,
a diagnosis in progress: finish it, then hand off at the next real boundary,
even past 65% toward the 70-75% band.

- Hand off by invoking the `handoff` skill (`Skill(skill: "handoff")`), never
  by hand-writing a handoff document, not even a short one.
- A handoff must let the next session recover without re-deriving anything:
  objective, the bead(s) and approved plan, decisions made, invariants,
  completed work, commits/diffs, tests and validation performed, open
  findings, unresolved questions, and the exact next action. Prefer durable
  repository and Beads state over conversational context.
