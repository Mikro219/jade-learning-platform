# Architecture decision records

These are the accepted decisions for the JADE learning platform. CLAUDE.md rule 8 applies: the decisions here stand, and an agent that believes one is wrong files a `decision` bead and stops; it does not quietly build something else. 0001 to 0015 are `docs/handoff/DECISIONS.md` ADR-01 to ADR-15; 0016 to 0023 are the decisions of 2026-11-14 recorded in the close reasons of beads jade-8n2.1 to jade-8n2.8. A new ADR takes the next number (0024 onward) and uses the same header lines (Status, Date, Source, Related) and the same sections (Context, Decision, Consequences) as the existing files.

## Index

| ADR | Title | Status | Source |
|---|---|---|---|
| 0001 | [Kit-agnostic platform](0001-kit-agnostic-platform.md) | accepted | DECISIONS.md ADR-01 |
| 0002 | [Modular monolith in SvelteKit](0002-modular-monolith-in-sveltekit.md) | accepted | DECISIONS.md ADR-02 |
| 0003 | [PostgreSQL with Drizzle and SQL migrations](0003-postgresql-with-drizzle-and-sql-migrations.md) | accepted | DECISIONS.md ADR-03 |
| 0004 | [One Canadian VM, Docker Compose](0004-one-canadian-vm-docker-compose.md) | accepted | DECISIONS.md ADR-04 |
| 0005 | [Authentication without email](0005-authentication-without-email.md) | accepted | DECISIONS.md ADR-05 |
| 0006 | [Content as Markdown in the repo, version-locked](0006-content-as-markdown-version-locked.md) | accepted | DECISIONS.md ADR-06 |
| 0007 | [Self-hosted, same-origin video](0007-self-hosted-same-origin-video.md) | accepted | DECISIONS.md ADR-07 |
| 0008 | [Event integrity](0008-event-integrity.md) | accepted | DECISIONS.md ADR-08 |
| 0009 | [Consent-gated logging](0009-consent-gated-logging.md) | accepted | DECISIONS.md ADR-09 |
| 0010 | [The kit is the unit of analysis](0010-kit-is-the-unit-of-analysis.md) | accepted | DECISIONS.md ADR-10 |
| 0011 | [Kit code format and storage](0011-kit-code-format-and-storage.md) | accepted | DECISIONS.md ADR-11 |
| 0012 | [Device telemetry and AI assistant are out of scope](0012-device-telemetry-and-ai-assistant-out-of-scope.md) | accepted | DECISIONS.md ADR-12 |
| 0013 | [No third-party requests from the browser](0013-no-third-party-requests-from-the-browser.md) | accepted | DECISIONS.md ADR-13 |
| 0014 | [Staging from Phase 1](0014-staging-from-phase-1.md) | accepted | DECISIONS.md ADR-14 |
| 0015 | [Tooling](0015-tooling.md) | accepted | DECISIONS.md ADR-15 |
| 0016 | [Step-metrics views and the retention job are post-launch-ok](0016-step-views-and-retention-post-launch-ok.md) | accepted | bead jade-8n2.1 |
| 0017 | [Live stuck alerts for kits with logging off](0017-live-stuck-alerts-for-no-log-kits.md) | accepted | bead jade-8n2.2 |
| 0018 | [Stale client timestamps are flagged, not clamped](0018-stale-timestamps-flagged-not-clamped.md) | accepted | bead jade-8n2.3 |
| 0019 | [Participant letters are A to D](0019-participant-letters-a-to-d.md) | accepted | bead jade-8n2.4 |
| 0020 | [Rate-limit keys for code redemption and code-gated signup](0020-rate-limit-keys-for-redemption-and-signup.md) | accepted | bead jade-8n2.5 |
| 0021 | [Beads that mix human and agent work are split](0021-split-human-and-agent-work.md) | accepted | bead jade-8n2.6 |
| 0022 | [The open-product-questions bead covers retention, quiz entry and the freeze date](0022-open-product-questions-scope.md) | accepted | bead jade-8n2.7 |
| 0023 | [Tiered retention for kit-keyed data](0023-tiered-retention-for-kit-keyed-data.md) | accepted | bead jade-8n2.8 |
| 0024 | [Node 24 is the pinned Node LTS line](0024-node-24-pinned.md) | accepted | bead jade-h8i |

## Amendments to the handoff documents

The handoff snapshot is in git commit 079e846 and in `jade-handoff.zip`.

| Handoff statement (file, section) | Amended by | Where the current text is |
|---|---|---|
| `DATA-MODEL.md` section 6, "Retention" bullet | [0016](0016-step-views-and-retention-post-launch-ok.md), [0023](0023-tiered-retention-for-kit-keyed-data.md) | Corrected in place in `docs/handoff/DATA-MODEL.md` |
| `DATA-MODEL.md` section 4, live stuck alerts for kits with logging off (paragraph after the app database role) | [0017](0017-live-stuck-alerts-for-no-log-kits.md) | Corrected in place in `docs/handoff/DATA-MODEL.md` |
| `EVENTS.md` client rule 5 and server rule 2 | [0017](0017-live-stuck-alerts-for-no-log-kits.md) | Corrected in place in `docs/handoff/EVENTS.md` |
| `EVENTS.md` server rule 4 | [0018](0018-stale-timestamps-flagged-not-clamped.md) | Corrected in place in `docs/handoff/EVENTS.md` |
| `PRIVACY.md` "Data inventory" (live stuck alerts row; per-IP signup limit sentence), "Consent and opt-out" (live stuck alert bullet), "Retention" | [0017](0017-live-stuck-alerts-for-no-log-kits.md), [0016](0016-step-views-and-retention-post-launch-ok.md), [0023](0023-tiered-retention-for-kit-keyed-data.md), [0020](0020-rate-limit-keys-for-redemption-and-signup.md) | Corrected in place in `docs/handoff/PRIVACY.md` |
| `ARCHITECTURE.md` section 8, "The consent gate" bullets on live stuck alerts and on the client stopping queueing | [0017](0017-live-stuck-alerts-for-no-log-kits.md) | Not edited; the ADR is current |
| `ARCHITECTURE.md` section 9, row "Guessing kit codes online" (per-account limit only) and the "retention job that reduces raw events to aggregates" sentence | [0020](0020-rate-limit-keys-for-redemption-and-signup.md), [0023](0023-tiered-retention-for-kit-keyed-data.md) | Not edited; the ADRs are current |
| `START-HERE.md` "Suggested calendar" (Phase 9 Dec 13-16 overlapping Phase 10 Dec 14-18) | [0022](0022-open-product-questions-scope.md) | Not edited; jade-6is re-sequences it once the freeze is confirmed |
| Phase files in `docs/handoff/phases/`: p0-open-decisions (`phase-00` still lists three acceptance lines for jade-6is), p0-adr (`phase-00` lists three acceptance lines for jade-hqq), p6-ingest, p6-client, p6-nolog-invariant, p7-quiz, p7-live-stuck, p2-redeem, p3-adult-auth, p8-views (labels: `phase-08` still shows it launch-blocking), p9-ratelimit, p9-retention, p9-privacy-doc, p4-real-content, p10-secrets, p10-codes, p10-accounts; the new beads jade-buf.1, jade-buf.2, jade-lnn.1, jade-lnn.2 and jade-lnn.3 are not in the phase files | [0016](0016-step-views-and-retention-post-launch-ok.md) to [0023](0023-tiered-retention-for-kit-keyed-data.md) | Generated, not edited; the bead's acceptance criteria and labels are current |

Where a phase file and a bead's acceptance criteria that cite a jade-8n2.<k> decision differ, the bead is current.

## Assumptions (unconfirmed)

Copied from `docs/handoff/DECISIONS.md`, "Assumptions made without confirmation".

| # | Assumption | If wrong | Settled by |
|---|---|---|---|
| A1 | The arm kit has no Wi-Fi board and no AI assistant | Build E1 and/or E2; add a phase after Phase 6 | jade-6is |
| A2 | Groups of 2 or 3 share one device | If one device per child, revisit ADR-10 and the consent wording | jade-tw4 (device count) |
| A3 | Freeze is still mid-December for a January classroom pilot | Re-plan dates in `START-HERE.md`; phase order stays | jade-6is ([0022](0022-open-product-questions-scope.md)) |
| A4 | The pilot site has tablets or Chromebooks with a current browser | If not, the team supplies devices or runs print-first with QR lookups on a few shared devices | jade-tw4 |
| A5 | Adults in the pilots are the team's facilitators plus one teacher | If many outside adults need accounts, bring E4 (email) forward | no bead; revisit if wrong |
| A6 | The repo is hosted on GitHub | Swap the CI and authoring-guide details | no bead; revisit if wrong |
| A7 | English only | Content format would need a locale dimension | no bead; revisit if wrong |

A6: the repository has no git remote configured today (`git remote -v` is empty), so A6 is unconfirmed.

## Open questions

Copied from `docs/handoff/DECISIONS.md`, "Open questions for the team"; question 9 is added by [0022](0022-open-product-questions-scope.md).

| # | Question | Owner bead | Status |
|---|---|---|---|
| 1 | **Kit name and code prefix.** Needed before production codes are printed. | jade-6is | open |
| 2 | **Module and step outline for the arm kit**, with a rough expected time per step. Needed before real content is loaded; the build proceeds on demo content until then. | jade-6is | open |
| 3 | **Networked electronics or AI assistant on the arm?** Confirms or overturns A1. | jade-6is | open |
| 4 | **Host and domain.** Blocks staging. | jade-0za | open |
| 5 | **Pilot-site devices and network.** Device type, browser, allowlisting lead time, cookie persistence. | jade-tw4 | open |
| 6 | **Consent and research approval.** Do the current documents describe a web platform that logs kit-level activity? If the application was approved for the incubator, does the pivot need an amendment? | jade-bi5 | open |
| 7 | **Retention period.** Default in the build is 12 months after a class ends. | jade-6is | open |
| 8 | **Who enters quiz results**, and is the quiz still picture-based on paper? | jade-6is | open |
| 9 | Freeze date: is mid-December still the freeze? (added by ADR 0022) | jade-6is | open |

Answers are recorded as new ADRs from 0024 (the host and region go into [0004](0004-one-canadian-vm-docker-compose.md)), and the row's status is updated in the same commit.
