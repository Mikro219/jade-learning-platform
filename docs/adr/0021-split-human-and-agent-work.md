# 0021. Beads that mix human and agent work are split

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.6, close reason (Mike, 2026-11-14)

## Context

CLAUDE.md says "Never start a bead labelled `human`" (CLAUDE.md, "Work tracking: beads"). Several human-labelled beads described agent work: p4-real-content, p10-secrets, p10-codes, p10-accounts and p10-go-live, so as written an agent could never do its part (jade-8n2.6 description). The options were to split each into an agent bead and a human bead, or to have a human claim the bead and hand the agent its part in-session (jade-8n2.6 description).

## Decision

Decided (Mike, 2026-11-14): split into agent + human beads. New agent beads jade-buf.1, jade-lnn.1, jade-lnn.2, jade-lnn.3; new human bead jade-buf.2. Production actions stay human.

Notes this decision added:

- jade-x94: Split (Mike, 2026-11-14, jade-8n2.6): this bead is only the delivery of drafts. Conversion is jade-buf.1 (agent); review and sign-off is jade-buf.2 (human).
- jade-fgs: Split (Mike, 2026-11-14, jade-8n2.6): the script and runbook are jade-lnn.1 (agent). This bead is the human part: run it on production, store CODE_PEPPER and the backup key in two offline places.
- jade-t17: Split (Mike, 2026-11-14, jade-8n2.6): the runbook and staging rehearsal are jade-lnn.2 (agent). This bead is the human part: run against production, print, pack, store the CSV offline.
- jade-873: Split (Mike, 2026-11-14, jade-8n2.6): the setup script is jade-lnn.3 (agent). This bead is the human part: run it in production; each facilitator logs in once.

Titles of the beads this decision added:

- jade-buf.1: Convert supplied arm-kit drafts to the content format and pass lint
- jade-lnn.1: Script production secret generation and write the secrets runbook
- jade-lnn.2: Production code-batch runbook and staging rehearsal
- jade-lnn.3: Staff/facilitator account and pilot-class setup script, rehearsed on staging
- jade-buf.2: HUMAN: Given reviews the converted arm-kit content and signs off

## Consequences

- New agent beads jade-buf.1, jade-lnn.1, jade-lnn.2 and jade-lnn.3, and new human bead jade-buf.2 (titles above). The human beads jade-x94 (p4-real-content), jade-fgs (p10-secrets), jade-t17 (p10-codes) and jade-873 (p10-accounts) carry split notes naming their agent part.
- p10-go-live (jade-wb9) is not split; production actions stay human.
- The generated phase files describe p4-real-content, p10-secrets, p10-codes and p10-accounts unsplit, and the five new beads are not in them ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- jade-x94's acceptance still lists "All modules for Pilot 1 pass content lint" and "Given has reviewed the preview", while its split note gives conversion to jade-buf.1 and review to jade-buf.2. The two disagree, and this ADR does not settle it.
