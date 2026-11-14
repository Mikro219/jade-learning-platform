<!-- Merge this section into the repo's CLAUDE.md. Do not replace an existing CLAUDE.md. -->

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
2. Use the **planloop** skill to plan the bead against its acceptance criteria before writing code.
3. Implement with tests. Every new route goes into the authorization matrix test.
4. Run `pnpm lint && pnpm check && pnpm test && pnpm e2e`.
5. Commit with the bead ID in the message. Merge once CI is green; staging deploys itself.
6. `bd close <id> --reason "..."`. When a phase's last bead closes, check the phase's exit criteria, then `bd epic close-eligible`.

### Stop and ask the human when

- A `human` bead blocks all remaining ready work.
- A change would touch rules 1 to 6 above.
- A secret, payment, DNS change or production deploy is needed.
- The same test has failed three times after three different fixes.
