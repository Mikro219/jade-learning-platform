# Prompt 2: work the plan

Use this to start each working session after the plan is seeded. Replace `<N>` with the phase you want worked, or delete that line to let it take whatever is ready.

---

Continue the JADE platform build.

1. Run `bd prime`, then `bd ready --exclude-type epic --exclude-label human`.
2. Work only beads in Phase <N> (label `phase-<N>`). Take the highest-priority ready bead: `bd update <id> --claim`.
3. `bd show <id>` and read its section in `docs/handoff/phases/`. Use the planloop skill to plan it against its acceptance criteria, then implement it with tests.
4. Before closing: every acceptance criterion met, `pnpm lint && pnpm check && pnpm test && pnpm e2e` green, CI green, merged to main, staging healthy.
5. `bd close <id> --reason "<what was done> (<commit sha>)"`, then take the next ready bead.
6. Bugs you hit: file a `bug` bead with reproduction steps and fix it with the bugfix skill. Out-of-scope discoveries: file a bead linked with `discovered-from` and keep going.
7. Never start a `human` bead. Never weaken the rules in CLAUDE.md under "Rules that are not up for negotiation".

Stop when: no agent-ready beads remain in the phase, a `human` bead blocks you, or you have closed 5 beads (so I can review). When you stop, give me: beads closed with their commit SHAs, beads filed, what is blocked and on whom, and whether the phase's exit criteria are now met.
