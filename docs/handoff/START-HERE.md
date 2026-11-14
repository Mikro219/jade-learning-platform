# JADE learning platform: handoff pack

Everything a Claude Code session needs to build the learning-module platform from the architecture to a production deploy. Prepared 2026-11-14.

## How to use it

1. Open a Claude Code session in the platform repo (an empty repo is fine). It needs the `planloop` and `bugfix` skills.
2. Attach `jade-handoff.zip` (or unzip it in the repo root).
3. Paste the prompt in `prompts/01-beads-setup.md`. It unpacks this folder to `docs/handoff/`, installs and initialises beads, seeds 11 phase epics and 92 tasks with dependencies, and stops with a checklist for you.
4. Do the four `human` beads it lists. Staging is blocked until the host is chosen.
5. For each working session, paste `prompts/02-work-loop.md` with the phase number.

## What is in here

| File | What it is |
|---|---|
| `REVIEW.md` | Review of the October architecture: 24 findings and what changed |
| `ARCHITECTURE.md` | Architecture v2, the document the build follows |
| `architecture.png` / `.svg` | System diagram |
| `DECISIONS.md` | 15 accepted decisions, assumptions, and open questions for the team |
| `DATA-MODEL.md` | Target database schema |
| `EVENTS.md` | Event catalog: what is logged and its exact shape |
| `PRIVACY.md` | Data inventory, consent gate, retention, consent-form wording |
| `phases/` | One file per phase, 0 to 10, with tasks and acceptance criteria |
| `beads/plan.json` | The same plan as a beads graph (`bd create --graph`) |
| `beads/seed.sh` | Seeds and verifies the plan |
| `beads/expected.json` | Counts the seed is checked against |
| `prompts/` | The two prompts to paste |
| `CLAUDE-SECTION.md` | Project rules to merge into `CLAUDE.md` |
| `tools/build_plan.py` | Source of truth for phases and `plan.json`. Edit and re-run to change the plan before seeding |

## Phases

| # | Phase | Outcome |
|---|---|---|
| 0 | Architecture lock | Decisions committed; host, school IT and consent started |
| 1 | Foundation and walking skeleton | Empty app live on a Canadian staging URL, deployed by CI |
| 2 | Data model and kit codes | Codes generated, printed, redeemed once |
| 3 | Accounts, classes and student sessions | Facilitator runs a class; tablets join by code |
| 4 | Content pipeline | Markdown steps with enforced versions; video; print QR |
| 5 | Student experience | Step player with checkpoints, stuck button, offline |
| 6 | Event pipeline | Validated, idempotent, consent-gated event data |
| 7 | Facilitator dashboard | Live class view, stuck alerts, notes, quiz entry |
| 8 | Analytics and the redesign loop | Data-quality report and export first; dashboards after |
| 9 | Privacy, security and hardening | Deletion, retention, headers, rate limits, load test |
| 10 | Production deploy and pilot readiness | Production, backups, real codes, runbook, go/no-go |

Phase 8's dashboards are labelled `post-launch-ok`: they can ship in January while Pilot 1 runs. Only `p8-quality` and `p8-export` block launch.

## Suggested calendar

Assumes the freeze is still mid-December for a January classroom pilot. Nobody has confirmed that since the pivot; adjust if it moved.

| Dates | Phases |
|---|---|
| Nov 14 to 18 | 0, 1 |
| Nov 19 to 25 | 2, 3 |
| Nov 26 to Dec 3 | 4, 5 |
| Dec 4 to 8 | 6 |
| Dec 9 to 12 | 7, plus `p8-quality` and `p8-export` |
| Dec 13 to 16 | 9 |
| Dec 14 to 18 | 10 |
| January to February | Rest of Phase 8 |

The slow items are not code: choosing a host (blocks staging), school IT allowlisting, consent wording, and Given's content. Start all four today.

## Assumptions to check before you paste the prompt

1. The arm kit has no networked electronics and no AI assistant, so device sync and the AI proxy are out of v1.
2. SvelteKit + PostgreSQL + Docker Compose on one Canadian VM. Change the stack in `DECISIONS.md` now if you prefer another; it is expensive to change after Phase 1.
3. Kit slug `arm` and code prefix `ARM` are placeholders.
4. The repo is on GitHub.
