# Prompt 1: set up beads and seed the plan

Attach `jade-handoff.zip` to the Claude Code session (or unzip it in the repo root first), then paste everything below the line.

---

You are setting up work tracking for the JADE learning platform. Do exactly the steps below, in order. Do not start building the platform in this session.

**0. Unpack**

- If `jade-handoff.zip` is present and `docs/handoff/` does not exist, unzip it and move the contents of the `jade-handoff/` folder to `docs/handoff/`. Do not overwrite any existing file; if there is a collision, stop and tell me.
- If this directory is not a git repository, run `git init` and make an initial commit of what is there.

**1. Read**

Read, in this order: `docs/handoff/START-HERE.md`, `docs/handoff/REVIEW.md`, `docs/handoff/ARCHITECTURE.md`, `docs/handoff/DECISIONS.md`, `docs/handoff/phases/README.md`. Skim `DATA-MODEL.md`, `EVENTS.md`, `PRIVACY.md`. Do not summarise them back to me.

**2. Install beads**

- Check `bd --version`. If it is missing, install it with the first of these that works: `npm install -g @beads/bd`, `brew install beads`, or the install script from `https://github.com/gastownhall/beads` (read the script before running it).
- If none can be installed in this environment, stop and tell me what failed. Do not substitute another tracker or a markdown TODO list.

**3. Initialise**

- If `.beads/` does not exist: `bd init --prefix jade --non-interactive`
- Then `bd setup claude` and confirm with `bd setup claude --check`.
- Run `bd prime` once and read its output so you follow this version's workflow.
- `bd init` may create or update `AGENTS.md`. Keep it.

**4. Seed the plan**

- Run `bash docs/handoff/beads/seed.sh` from the repo root. It dry-runs `docs/handoff/beads/plan.json`, creates 11 phase epics and 92 tasks with their dependencies in one atomic `bd create --graph` call, writes `docs/handoff/beads/id-map.json`, and verifies the result against `docs/handoff/beads/expected.json`.
- If the script fails because this `bd` version rejects the plan format, run `bd create --help` and read the "Graph plan schema" section, fix `plan.json` to match (or fix `tools/build_plan.py` and re-run it), and try again. Do not create the issues one by one by hand unless the graph route is impossible; if you must, the edge rule is: `from_key` depends on `to_key`.
- Do not seed twice. If issues already exist, stop and ask.

**5. Verify**

Run and check each:

- `bd dep cycles` reports none.
- `bd ready --exclude-type epic --exclude-label human` shows exactly one task: "Commit ADRs from the handoff decisions".
- `bd ready --exclude-type epic --label human` shows four tasks (open product questions, host, school IT, consent).
- `bd list --type epic` shows 11 epics, Phase 0 to Phase 10.

**6. Wire up the repo instructions**

- Merge `docs/handoff/CLAUDE-SECTION.md` into `CLAUDE.md` (create the file if it does not exist; never delete what is already there).
- Confirm the `planloop` and `bugfix` skills are available in this session. If either is missing or named differently, tell me the names you do see and stop before step 7.

**7. Commit**

Commit `docs/handoff/`, `.beads/` files that beads says to track, `AGENTS.md`, `CLAUDE.md` and any hook or settings files `bd setup claude` created, with the message `chore: add JADE handoff docs and seed beads plan`. If a git remote exists, also run `bd dolt push` so the issue database is backed up; if there is no remote, tell me the issues exist only on this machine.

**8. Report and stop**

Reply with:

1. The bd version and the number of epics, tasks and dependencies created.
2. The four `human` beads that are ready now, with their bead IDs, as a checklist for me.
3. The one agent-ready bead and its ID.
4. Anything in the handoff docs that contradicts itself or cannot be built as written. File each as a bead of type `decision` labelled `human` and list them.

Then stop. Do not begin Phase 0 work until I say so.
