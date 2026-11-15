# PLAN jade-8n2: Phase 0 architecture lock: ADRs, handoff-doc corrections, threat model (revision 3, 2026-11-14)

Documentation-only plan for the two agent beads of Phase 0: jade-hqq (p0-adr) and jade-okb (p0-threat). No code, schema or migration.

## 0. Summary
- jade-hqq writes 23 ADR files under `docs/adr/`: 0001-0015 from `docs/handoff/DECISIONS.md` ADR-01 to ADR-15, and 0016-0023 from the close reasons of decision beads jade-8n2.1 to jade-8n2.8. It adds `docs/adr/README.md` (the index, the amendment map, assumptions A1-A7 and the open questions), edits the three handoff data docs in place (with a dated banner), and edits one line of `CLAUDE.md`. One commit.
- jade-okb writes `docs/threat-model.md`: actors, assets, trust boundaries, abuse cases AB1-AB16 (AB1-AB9 are the nine rows of ARCHITECTURE.md section 9) each with a named mitigation, phase, plan key, bead id and verification, a Mermaid data-flow diagram of every store of adult PII and kit-level data (including the staging VM's restore-drill copy), and what stays open until the human beads close. It files two discovered-from beads for mitigation gaps as children of the Phase 7 epic jade-7s7 (the phase is for Mike to confirm, Q7). It appends the threat-model link to the same `CLAUDE.md` line. One commit.

## 1. Obligations
Byte-exact acceptance criteria from the beads (`bd show <id> --json`, field `acceptance_criteria`, leading `- ` dropped):
- OB1 [bead:jade-hqq]: One file per ADR, numbered, each with Context / Decision / Consequences
- OB2 [bead:jade-hqq]: docs/adr/README.md indexes them
- OB3 [bead:jade-hqq]: CLAUDE.md links to docs/adr/ and docs/handoff/ARCHITECTURE.md
- OB4 [bead:jade-hqq]: Decisions jade-8n2.1 to jade-8n2.8 (decided 2026-11-14, see each bead's close reason) recorded as ADRs after ADR-15, and DATA-MODEL.md, EVENTS.md and PRIVACY.md corrected to match them
- OB5 [bead:jade-okb]: Every abuse case has a named mitigation and the phase that implements it
- OB6 [bead:jade-okb]: Data-flow diagram shows every place adult PII and kit-level data is stored

Also binding: the jade-hqq description ("Do not change the decisions. If one looks wrong, file a decision bead and stop"), the jade-okb description (actors, assets, trust boundaries, ARCHITECTURE.md section 9, Mermaid), and CLAUDE.md rules 1-8. Phase 0 exit criteria 1 and 2 are OB1-OB3 and OB5-OB6 once committed; exit criterion 3 belongs to the human beads.

## 2. Placement decisions this plan makes
- PD1. Corrected text lives in the handoff files themselves: `docs/handoff/DATA-MODEL.md`, `docs/handoff/EVENTS.md`, `docs/handoff/PRIVACY.md`, edited in place, each with a dated banner naming the ADRs that amend it. Why: CLAUDE.md ("Data shapes", "Privacy promises") and every phase file point implementers at these paths, so a parallel copy elsewhere would leave a cold reader with two versions and no rule for which wins. The handoff snapshot is not lost: it is in git commit `079e846` and in `jade-handoff.zip`, and both are byte-identical to the current files (checked with `unzip -p jade-handoff.zip jade-handoff/<F>.md | cmp - docs/handoff/<F>.md` for all three). The banner names both. The later owners stay as they are: p9-privacy-doc (jade-771) writes `docs/PRIVACY.md` from this file, and p6-catalog (jade-3ek) generates `docs/events.md`, which wins over EVENTS.md (EVENTS.md line 3).
- PD2. No other handoff file is edited. `docs/handoff/phases/*` and `docs/handoff/beads/plan.json` are generated from `docs/handoff/tools/build_plan.py`, which was a pre-seed tool; the 2026-11-14 decisions were applied to the beads, not to it. `ARCHITECTURE.md`, `DECISIONS.md`, `REVIEW.md`, `START-HERE.md`, `CLAUDE-SECTION.md` and `prompts/` stay as the snapshot. Where their text is incomplete or superseded, `docs/adr/README.md` section "Amendments to the handoff documents" says so, statement by statement. Regenerating the phase files is an open question (Q4), not part of this plan.
- PD3. ADR numbering: `NNNN` equals the DECISIONS.md number for 0001-0015 (so `docs/adr/0004` is ADR-04, as jade-0za's acceptance "Provider and region recorded in docs/adr/0004" expects), then 0016-0023 in bead order jade-8n2.1 to jade-8n2.8.
- PD4. Assumptions A1-A7 and open questions 1-8 are not decisions, so they are not ADR files. They are recorded in `docs/adr/README.md` (sections "Assumptions (unconfirmed)" and "Open questions"), verbatim, with the bead that will settle each. When jade-6is, jade-0za, jade-tw4 or jade-bi5 records an answer "in docs/adr/", it adds ADR 0024 onward (or the 0004 provider line) and updates the row's status. Item 9 (the freeze date) is added because jade-8n2.7 put it into jade-6is.
- PD5. ADRs 0016-0023 state the decision as the close reason verbatim, followed by the acceptance-criteria lines it added to other beads, verbatim. The ADR does not paraphrase what Mike decided.

## 3. Invariants
- INV1: No decision is changed. In 0001-0015 the `## Decision` section contains the DECISIONS.md body of that ADR verbatim (paragraphs, bold and code spans as in the source). In 0016-0023 it contains the bead's close reason verbatim. Context and Consequences add only statements the cited sources support, each with its source.
- INV2: These paths are not modified by either commit: `docs/handoff/phases/`, `docs/handoff/tools/`, `docs/handoff/beads/`, `docs/handoff/prompts/`, `docs/handoff/ARCHITECTURE.md`, `docs/handoff/DECISIONS.md`, `docs/handoff/REVIEW.md`, `docs/handoff/START-HERE.md`, `docs/handoff/CLAUDE-SECTION.md`, `jade-handoff.zip`.
- INV3: In DATA-MODEL.md, EVENTS.md and PRIVACY.md only the edits listed in section 4.5 are made; every other line stays byte-identical.
- INV4: `CLAUDE.md` changes on exactly one line (the "Read before any work" line, today line 84). Rules 1-8 are byte-identical.
- INV5: No teaching content, no code, no schema, no migration, and no new table or column is invented. Where a decision names a table that is not yet defined (`step_aggregates`, the quiz and exit-card aggregate tables), the docs say which bead defines it.
- INV6: Where a source is silent or two sources disagree, the new docs say so and point at an open question or a bead; they do not pick an answer.

## 4. jade-hqq: ADRs, index, corrections

### 4.1 Files
Create exactly these 24 files:

| File | Title line | Source |
|---|---|---|
| `docs/adr/0001-kit-agnostic-platform.md` | `# 0001. Kit-agnostic platform` | DECISIONS ADR-01 |
| `docs/adr/0002-modular-monolith-in-sveltekit.md` | `# 0002. Modular monolith in SvelteKit` | ADR-02 |
| `docs/adr/0003-postgresql-with-drizzle-and-sql-migrations.md` | `# 0003. PostgreSQL with Drizzle and SQL migrations` | ADR-03 |
| `docs/adr/0004-one-canadian-vm-docker-compose.md` | `# 0004. One Canadian VM, Docker Compose` | ADR-04 |
| `docs/adr/0005-authentication-without-email.md` | `# 0005. Authentication without email` | ADR-05 |
| `docs/adr/0006-content-as-markdown-version-locked.md` | `# 0006. Content as Markdown in the repo, version-locked` | ADR-06 |
| `docs/adr/0007-self-hosted-same-origin-video.md` | `# 0007. Self-hosted, same-origin video` | ADR-07 |
| `docs/adr/0008-event-integrity.md` | `# 0008. Event integrity` | ADR-08 |
| `docs/adr/0009-consent-gated-logging.md` | `# 0009. Consent-gated logging` | ADR-09 |
| `docs/adr/0010-kit-is-the-unit-of-analysis.md` | `# 0010. The kit is the unit of analysis` | ADR-10 |
| `docs/adr/0011-kit-code-format-and-storage.md` | `# 0011. Kit code format and storage` | ADR-11 |
| `docs/adr/0012-device-telemetry-and-ai-assistant-out-of-scope.md` | `# 0012. Device telemetry and AI assistant are out of scope` | ADR-12 |
| `docs/adr/0013-no-third-party-requests-from-the-browser.md` | `# 0013. No third-party requests from the browser` | ADR-13 |
| `docs/adr/0014-staging-from-phase-1.md` | `# 0014. Staging from Phase 1` | ADR-14 |
| `docs/adr/0015-tooling.md` | `# 0015. Tooling` | ADR-15 |
| `docs/adr/0016-step-views-and-retention-post-launch-ok.md` | `# 0016. Step-metrics views and the retention job are post-launch-ok` | jade-8n2.1 |
| `docs/adr/0017-live-stuck-alerts-for-no-log-kits.md` | `# 0017. Live stuck alerts for kits with logging off` | jade-8n2.2 |
| `docs/adr/0018-stale-timestamps-flagged-not-clamped.md` | `# 0018. Stale client timestamps are flagged, not clamped` | jade-8n2.3 |
| `docs/adr/0019-participant-letters-a-to-d.md` | `# 0019. Participant letters are A to D` | jade-8n2.4 |
| `docs/adr/0020-rate-limit-keys-for-redemption-and-signup.md` | `# 0020. Rate-limit keys for code redemption and code-gated signup` | jade-8n2.5 |
| `docs/adr/0021-split-human-and-agent-work.md` | `# 0021. Beads that mix human and agent work are split` | jade-8n2.6 |
| `docs/adr/0022-open-product-questions-scope.md` | `# 0022. The open-product-questions bead covers retention, quiz entry and the freeze date` | jade-8n2.7 |
| `docs/adr/0023-tiered-retention-for-kit-keyed-data.md` | `# 0023. Tiered retention for kit-keyed data` | jade-8n2.8 |
| `docs/adr/README.md` | `# Architecture decision records` | section 4.4 |

The 0016 title follows the close reason of jade-8n2.1, which labels both beads post-launch-ok (allowed after launch); only for the retention job does a bead say it "ships after launch" (jade-771), and ADR 0016's Consequences say so in those terms.

### 4.2 ADR file template
```
# NNNN. <Title>

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-NN            (0001-0015)
- Source: bead jade-8n2.K, close reason (Mike, 2026-11-14)   (0016-0023)
- Related: [NNNN](NNNN-....md), ...                      (only where 4.3 lists one)

## Context
<2-6 sentences: the problem, from the cited sources, each claim with its source in parentheses, e.g. (REVIEW.md finding 4; ARCHITECTURE.md section 6)>

## Decision
<0001-0015: the DECISIONS.md body verbatim. 0016-0023: the close reason verbatim, then "Acceptance criteria this decision added:" and the lines from 4.3, verbatim, each prefixed with its bead id>

## Consequences
<bullets: what follows, which beads implement it (plan key and bead id from docs/handoff/beads/id-map.json), what stays open and which bead settles it, and which handoff statements it amends (link the README amendment map)>
```
Date is the decision date for all 23 (DECISIONS.md and the eight beads are all dated 2026-11-14). A "Related" line only links; it never restates another ADR.

### 4.3 Per-ADR content outline
Context sources and Consequences per file. Bead ids are from `docs/handoff/beads/id-map.json`.

| ADR | Context from | Consequences must state | Related |
|---|---|---|---|
| 0001 | REVIEW 1; ARCHITECTURE 1, 7 | Slug `arm` and prefix `ARM` stay placeholders until jade-6is records them; p2-schema-core jade-o07 (`products`), p2-seed jade-q01; content under `content/<slug>/` | |
| 0002 | REVIEW 10; ARCHITECTURE 2 (principle 5), 4 | p1-scaffold jade-h8i follows the module layout; modules call each other only through `index.ts`; the framework-swap window is Phase 0 only, by human decision, and closes when epic jade-8n2 closes | |
| 0003 | ARCHITECTURE 4, 10, 11 | p1-db jade-urd; forward-only migrations compatible with the previous app version (ARCHITECTURE 10); analytics as views, p8-views jade-lx4 | 0016 |
| 0004 | ARCHITECTURE 2 (principle 7), 10; REVIEW 18, 19 | Line "Provider and region: not yet chosen; recorded here by jade-0za (p0-host)". p1-docker jade-80h, p1-staging jade-4zw, p10-prod-infra jade-dvm, p10-backups jade-6o3 | 0014 |
| 0005 | REVIEW 9; ARCHITECTURE 5 | p3-adult-auth jade-vcy, p3-invites jade-9tk, p3-join jade-5nj; email-based reset deferred to extension E4; rate-limit keys are in 0020 | 0020 |
| 0006 | REVIEW 12, 13, 21; ARCHITECTURE 7 | p4-schema jade-5kj, p4-lock jade-as7, p4-shortlinks jade-b4j; CLAUDE.md rule 6; CMS deferred to E3 | |
| 0007 | REVIEW 11; ARCHITECTURE 4, 9 | p4-video jade-u8z; one domain for school IT to allowlist (open until jade-tw4) | 0013 |
| 0008 | REVIEW 2, 3, 6; ARCHITECTURE 8 "Event integrity" | p6-catalog jade-3ek, p6-client jade-4a7, p6-ingest jade-zg3, p6-table jade-7j8; CLAUDE.md rule 3; timestamp handling of stale events made explicit by 0018 | 0018 |
| 0009 | REVIEW 5; ARCHITECTURE 2 (principle 3), 8 "The consent gate" | p3-consent-flag jade-8lt, p6-nolog-invariant jade-hhp; CLAUDE.md rule 2; how a no-log kit's stuck alert reaches the facilitator is 0017 | 0017 |
| 0010 | REVIEW 7; ARCHITECTURE 2 (principle 2) | No seat or participant field in the event envelope (EVENTS.md); letters only on `quiz_responses` and `exit_cards`, range in 0019; depends on assumption A2 | 0019 |
| 0011 | REVIEW 4; ARCHITECTURE 6 | p2-code-lib jade-fd5, p2-code-cli jade-99j, p2-redeem jade-7if; pepper handling p1-config jade-8v4, p10-secrets jade-fgs (human) and jade-lnn.1 (agent); CLAUDE.md rule 4; losing the pepper invalidates every printed code (ARCHITECTURE 6) | 0020, 0021 |
| 0012 | REVIEW 1; ARCHITECTURE 12 (E1, E2); assumption A1 | Revisited only if jade-6is answers yes to networked electronics or an AI assistant | |
| 0013 | ARCHITECTURE 2 (principle 5), 9 | p9-headers jade-c42 (CSP, no CSP violations in e2e); CLAUDE.md rule 5 | 0007 |
| 0014 | REVIEW 18; ARCHITECTURE 10 | p1-staging jade-4zw (blocked by jade-0za); p10-cd jade-kn0 promotes the image that passed staging | 0004 |
| 0015 | DECISIONS ADR-15 only | p1-scaffold jade-h8i, p1-ci jade-xu0, p9-load jade-0d8 (k6); beads and the planloop and bugfix skills per CLAUDE.md | |
| 0016 | jade-8n2.1 description (START-HERE "Only p8-quality and p8-export block launch" against the p8-views -> p9-retention -> p9-privacy-doc -> p10-go-live chain) | jade-lx4 and jade-8vo labelled post-launch-ok; jade-8vo due 2027-06-30; jade-771 no longer depends on jade-8vo; the START-HERE sentence now holds; `phase-08`/`phase-09` files still show the old edge (README amendment map) | 0003, 0023 |
| 0017 | jade-8n2.2 description (ARCHITECTURE 8 and p7-live-stuck against EVENTS.md client rule 5 and server rule 2) | Corrections E2, E3, D2, P2, P3 of 4.5; for kits with logging off the alert store is process memory, so a restart drops their open alerts, and whether kits with logging on use the same store is open (Q3); the no-log invariant now covers the live endpoint (jade-hhp depends on jade-p99) | 0009 |
| 0018 | jade-8n2.3 description; REVIEW 2 | Correction E4; `phase-06` p6-ingest text still says "Clamp ... older than 14 days" (README amendment map) | 0008 |
| 0019 | jade-8n2.4 description; assumption A2 | DATA-MODEL and PRIVACY already say A to D (no correction needed); `phase-07` p7-quiz text still says A/B/C | 0010 |
| 0020 | jade-8n2.5 description; REVIEW 20; ARCHITECTURE 9 | p2-redeem jade-7if, p3-adult-auth jade-vcy, p9-ratelimit jade-6cq; correction P5; ARCHITECTURE 9 row "Guessing kit codes online" names only the per-account limit (README amendment map); the global throttle is shared by everyone, so the threat model records the lockout risk (AB11) | 0005, 0011 |
| 0021 | jade-8n2.6 description; CLAUDE.md "Never start a bead labelled human" | New agent beads jade-buf.1, jade-lnn.1, jade-lnn.2, jade-lnn.3 and human bead jade-buf.2; the split notes on jade-x94, jade-fgs, jade-t17, jade-873; p10-go-live jade-wb9 is not split, production actions stay human | |
| 0022 | jade-8n2.7 description; REVIEW "could not settle" item 6; assumption A3 | jade-6is acceptance now includes retention period, quiz entry and the freeze date; the calendar in START-HERE (Phase 9 Dec 13-16 overlapping Phase 10 Dec 14-18) is re-sequenced by jade-6is once the freeze is confirmed, not by this plan | 0023 |
| 0023 | jade-8n2.8 description (DATA-MODEL 6 and PRIVACY gave a rule for raw events only) | Corrections D3, P4; `step_aggregates` and the quiz and exit-card aggregate tables are defined by jade-8vo; RETENTION_MONTHS stays open until jade-6is; the tiers were to be checked against the research approval (jade-bi5, open) | 0016 |

Verbatim acceptance lines for the Decision sections of 0016-0023 (copy from `bd show <id> --json`, which does not wrap):
- 0016: jade-8vo "Running in production before the first class reaches classes.ended_at + RETENTION_MONTHS (jade-8n2.1)"; jade-771 "Describes the agreed retention policy (tiered, jade-8n2.8) and states that the retention job ships after launch (jade-8n2.1)".
- 0017: the jade-8n2.2 lines of jade-4a7, jade-zg3, jade-p99 and jade-hhp.
- 0018: the jade-8n2.3 line of jade-zg3.
- 0019: the jade-8n2.4 line of jade-e6m.
- 0020: the jade-8n2.5 lines of jade-7if, jade-vcy and jade-6cq.
- 0021: the jade-8n2.6 notes of jade-x94, jade-fgs, jade-t17 and jade-873, and the titles of the five new beads.
- 0022: every acceptance line of jade-6is after its third (the three it gained).
- 0023: the jade-8n2.8 line of jade-8vo and the "step_aggregates and the quiz/exit-card aggregate tables are defined in a migration and documented in the data model" line of jade-8vo.
Find them with `bd list --all --json -n 0` and a search for `jade-8n2.<k>` in `description`, `acceptance_criteria` and `notes`.

### 4.4 docs/adr/README.md
Sections, in order:
1. One paragraph: these are the accepted decisions; CLAUDE.md rule 8 applies (if one looks wrong, file a `decision` bead and stop); new ADRs take the next number and use the template of 4.2.
2. `## Index`: table `| ADR | Title | Status | Source |` with one row per file 0001-0023, the title linked to the file.
3. `## Amendments to the handoff documents`: table `| Handoff statement (file, section) | Amended by | Where the current text is |`. Rows: DATA-MODEL 6 retention bullet (0016, 0023: corrected in place); DATA-MODEL 4 live alerts (0017: corrected in place); EVENTS client rule 5 and server rule 2 (0017: corrected in place); EVENTS server rule 4 (0018: corrected in place); PRIVACY inventory, consent, retention, IP (0017, 0016, 0023, 0020: corrected in place); ARCHITECTURE 8 consent-gate bullets (0017: not edited; the ADR is current); ARCHITECTURE 9 kit-code row and "retention job" sentence (0020, 0023: not edited); START-HERE calendar (0022: not edited); phase files p0-open-decisions (`phase-00` still lists three acceptance lines for jade-6is), p6-ingest, p6-client, p6-nolog-invariant, p7-quiz, p7-live-stuck, p2-redeem, p3-adult-auth, p8-views (labels: `phase-08` still shows it launch-blocking), p9-ratelimit, p9-retention, p9-privacy-doc, p4-real-content, p10-secrets, p10-codes, p10-accounts (0016-0023: generated, not edited; the bead's acceptance criteria and labels are current). One sentence under the table: where a phase file and a bead's acceptance criteria that cite a jade-8n2.<k> decision differ, the bead is current.
   The phase-file list is checked mechanically before commit: every bead the `jade-8n2.<k>` search of 4.3 finds (in `description`, `acceptance_criteria` or `notes`), and every bead whose labels a jade-8n2.<k> close reason names (jade-lx4, jade-8vo), has its plan key in that row; a bead found and missing is added.
4. `## Assumptions (unconfirmed)`: the A1-A7 table copied verbatim from DECISIONS.md, plus a column "Settled by": A1 jade-6is; A2 jade-tw4 (device count); A3 jade-6is (ADR 0022); A4 jade-tw4; A5, A6, A7 "no bead; revisit if wrong". Note for A6: the repository has no git remote configured today (`git remote -v` is empty), so A6 is unconfirmed.
5. `## Open questions`: the eight questions verbatim from DECISIONS.md with columns "Owner bead" and "Status": 1, 2, 3, 7, 8 jade-6is; 4 jade-0za; 5 jade-tw4; 6 jade-bi5; all "open". Row 9 "Freeze date: is mid-December still the freeze? (added by ADR 0022)", jade-6is, open. One sentence: answers are recorded as new ADRs from 0024 (the host goes into 0004), and the row's status is updated in the same commit.

### 4.5 Corrections to the handoff data docs
Line numbers are today's. The banner wording is fixed; the inserted sentences may be wrapped differently, but no meaning may be added.

DATA-MODEL.md (`docs/handoff/DATA-MODEL.md`):
- D1. After line 3, insert a blank line and: `> Amended 2026-11-14 by [ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md), [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md) and [ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md); [ADR 0019](../adr/0019-participant-letters-a-to-d.md) confirms the `^[A-D]$` checks. The handoff text is in git commit 079e846 and jade-handoff.zip.`
- D2. After line 180 (the app database role paragraph), insert, as one line like the paragraphs around it: "Live stuck alerts for kits with logging off ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)) have no table. The app holds them in memory per class until resolved or the session closes; they are never written to the database or logs. Whether kits with logging on use the same store is open." The scope follows P2 and the jade-8n2.2 close reason ("in no-log mode"); the logging-on path is Q3.
- D3. Replace line 230 (the "Retention:" bullet) with a bullet "Retention ([ADR 0023](...)): at `classes.ended_at + RETENTION_MONTHS` (default 12 months, set by config), for that class:" and four sub-bullets: `events` are reduced to rows in `step_aggregates` (same shape as the `step_metrics` view, no kit id) and the raw rows removed; `kit_progress` and `device_sessions` rows are deleted; `facilitator_notes` are kept with `kit_id` set to null; `quiz_responses` and `exit_cards` are reduced to per-question and per-module counts with no kit id, then deleted. Then one sentence: "`step_aggregates` and the quiz and exit-card aggregate tables are defined by the retention job's migration (p9-retention, jade-8vo) and documented here when it lands. The job ships after launch and must run in production before the first class reaches `classes.ended_at + RETENTION_MONTHS` ([ADR 0016](...))."
- No change for 0019: lines 202 and 216 already read `check (participant ~ '^[A-D]$')`.

EVENTS.md (`docs/handoff/EVENTS.md`):
- E1. After line 3, insert a blank line and: `> Amended 2026-11-14 by [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md) and [ADR 0018](../adr/0018-stale-timestamps-flagged-not-clamped.md). The handoff text is in git commit 079e846 and jade-handoff.zip.`
- E2. Line 52, client rule 5, becomes: "5. If the join response or any ingest response says logging is off, clear the queue and stop queueing. From then on the client sends only `stuck` and `stuck_resolved`, live, to the live alert endpoint (p7-live-stuck); they are never queued offline, and nothing else is sent ([ADR 0017](...))."
- E3. Line 57, server rule 2, becomes: "2. If `class_kits.logging_enabled` is false: respond 204, write nothing. That kit's `stuck` and `stuck_resolved` go to the separate live alert endpoint, which authenticates by device session, takes class and kit from the session, holds alerts in memory per class until resolved or the session closes, and never writes them to the database or logs ([ADR 0017](...))."
- E4. Line 59, server rule 4, becomes: "4. `client_ts` more than 5 minutes in the future is clamped to `received_at` and flagged `future`; older than 14 days keeps its `client_ts` and is flagged `stale`, not clamped ([ADR 0018](...))."

PRIVACY.md (`docs/handoff/PRIVACY.md`):
- P1. After line 3, insert a blank line and: `> Amended 2026-11-14 by [ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md), [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md), [ADR 0020](../adr/0020-rate-limit-keys-for-redemption-and-signup.md) and [ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md); [ADR 0019](../adr/0019-participant-letters-a-to-d.md) confirms "A to D". The handoff text is in git commit 079e846 and jade-handoff.zip.`
- P2. After line 19 (the "Step progress" row), insert the row: `| Live stuck alerts for kits with logging off (whether kits with logging on use the same store is open) | App memory, per class | From "I'm stuck" until resolved or the session closes; never written to the database or logs ([ADR 0017](...)) | Class owner; staff |`. The scope follows the jade-8n2.2 close reason ("in no-log mode"), ARCHITECTURE 8 and jade-p99, which speak only of kits with logging off; the logging-on path is Q3.
- P3. After line 31 (the "A group without consent takes part fully" bullet), insert: "- For such a group, \"I'm stuck\" still alerts the facilitator in the moment. The alert is held in the server's memory only, until it is resolved or the session closes, and is never stored or logged ([ADR 0017](...))."
- P4. Replace line 37 with: "Retention is tiered ([ADR 0023](...)). When `RETENTION_MONTHS` (default 12, configurable; confirm against the research approval) have passed since the class ended: raw events are replaced by per-step aggregates that contain no kit IDs; step progress and device sessions are deleted; facilitator notes are kept, no longer linked to a kit; quiz and exit-card entries are reduced to per-question and per-module counts with no kit IDs, then deleted. The job that does this ships after launch and runs in production before the first class reaches that date ([ADR 0016](...)). Adult accounts are deleted on request."
- P5. After line 26 ("Not collected at all: ..."), insert: "An optional per-IP limit on code-gated signup holds IP addresses in memory only. It is off by default, and IP addresses are never stored or logged ([ADR 0020](...))."
- No change for 0019: line 9 already says "A to D". The "Sentences the consent form can borrow" block is not touched (consent wording belongs to jade-bi5; see Q6).

### 4.6 CLAUDE.md
Replace line 84 (`**Read before any work:** ...`) with:
`**Read before any work:** [docs/handoff/ARCHITECTURE.md](docs/handoff/ARCHITECTURE.md) and the accepted decisions in [docs/adr/](docs/adr/README.md) (0001 to 0015 are DECISIONS.md ADR-01 to ADR-15; 0016 to 0023 are the decisions of 2026-11-14, and the README lists which handoff statements they amend). Data shapes: `docs/handoff/DATA-MODEL.md`, `docs/handoff/EVENTS.md`. Privacy promises: `docs/handoff/PRIVACY.md`. Phase detail: `docs/handoff/phases/` (generated before the beads were seeded; where a bead's acceptance criteria cite a decision, the bead is current).`
Nothing else in CLAUDE.md changes in this commit.

### 4.7 Commit
One commit, message `docs(adr): record ADRs 0001-0023 and amend handoff data docs (jade-hqq)`, body listing the 24 new files and the four edited files, ending with the attribution trailer from the session. Then `bd close jade-hqq --reason "<summary>, commit <sha>"`. There is no CI or pnpm project yet (Phase 1 creates them), so the gates are the checks in section 7; say so in the close reason.

## 5. jade-okb: threat model

### 5.1 Document outline (`docs/threat-model.md`)
Headings, in order: `# Threat model and data flow`; status line (date, scope: v1 as designed in the handoff docs and ADRs 0001-0023, not as built; p9-authz-sweep jade-sio walks every abuse case here); `## 1. Actors`; `## 2. Assets`; `## 3. Trust boundaries`; `## 4. Data-flow diagram`; `## 5. Abuse cases`; `## 6. Retention and deletion paths`; `## 7. Open until the human beads close`; `## 8. Sources`. Every claim cites a doc section, an ADR or a bead.

### 5.2 Actors
The five required, each with how it gets in, what it can reach, and what it must not (from ARCHITECTURE 5 and ADR 0005):
- Student device (a group of 2-3 children on one shared school device; device-session cookie bound to class and kit).
- Facilitator (adult: facilitator, teacher, parent; email + password; owns classes).
- Staff (adult with staff role; codes admin, analytics, exports, deletion; also holds VM and backup-key access, named as the insider path).
- Outsider on school Wi-Fi (same network and same public IP as the class; can see the join code on the board; school web filter or proxy in the path).
- Outsider on the internet (reaches Caddy on 80/443 only; ARCHITECTURE 10, p1-docker).
Plus two non-human parties named but not modelled in depth: the hosting and object-storage provider (open until jade-0za) and the repository/CI path (GitHub assumed, A6; content arrives through it, ADR 0006).

### 5.3 Assets
Table `| Asset | Where it lives | Why it matters | Rule or ADR |`:
- Kit codes: plain on the printed card (in large type and in a QR that opens `/redeem?code=...`, p2-code-cli jade-99j) and in the offline packing CSV; once the QR is scanned, also in the redeem URL, so in the adult device's browser history and in the request line that Caddy and the app receive (CLAUDE.md rule 4: plain codes are never logged); `kit_codes.code_hmac` in the DB (ADR 0011, CLAUDE.md rule 4).
- Code pepper `CODE_PEPPER`: app env file on the VM and the team's offline store (jade-fgs, jade-lnn.1); never in the DB, so a dump alone does not allow offline guessing.
- Other secrets: `SESSION_SECRET`, backup encryption key (jade-lnn.1).
- Adult credentials and PII: `users` (email, optional display name, argon2id hash), `auth_sessions.token_hash`, `invites.token_hash`, staff-issued reset links (p3-adult-auth), adult session cookie; adult ids in `audit_log`, `classes.owner_id`, `class_kits.consent_confirmed_by`, `kit_codes.redeemed_by`, `facilitator_notes.author_id` and `note` text, `entered_by`.
- Join codes: shown in class, `classes.join_code_hash` while open (p3-join).
- Device-session tokens: cookie on the student device, `device_sessions.token_hash`.
- Kit-level data: `events`, `kit_progress`, `facilitator_notes`, `quiz_responses`, `exit_cards`, `device_sessions`, `class_kits`, live stuck alerts for kits with logging off, in memory (ADR 0017; whether kits with logging on use the same store is open, Q3), the student device's IndexedDB queue and local progress (p6-client, p5-progress), retention aggregates (ADR 0023), staff exports (p8-export).
- Backups: nightly encrypted dump, Canadian object storage, 30 days (ARCHITECTURE 10); restored in full onto the staging VM for the restore drill (p10-backups jade-6o3: "Perform a full restore onto staging"), so after the drill staging holds a copy of production adult PII and kit-level data, decrypted with the production backup key; when that copy is wiped is not decided (Q8).
- Media: signed, short-lived URLs (ADR 0007); no personal data.

### 5.4 Trust boundaries
- TB1 Browser to Caddy (internet or school Wi-Fi; TLS; only 80/443 published).
- TB2 Caddy to app (internal Compose network; Caddy logs no IPs).
- TB3 Route groups inside the app: `(student)`, `(adult)`, `(staff)`, `api/`; authorization matrix, 404 not 403 (p3-authz-tests).
- TB4 App to PostgreSQL (app role: insert and select on `events`, delete only through `delete_kit_data`; DATA-MODEL 4).
- TB5 VM to object storage (encrypted dump; key held offline).
- TB6 CI and repository to the VM (image built in CI, promoted from staging; ADR 0014).
- TB7 Physical and offline: printed cards, packing CSV, offline pepper and backup-key store.
- TB8 The shared student device: cookie and IndexedDB readable by the next user of the device; school-managed devices may wipe cookies (open until jade-tw4).
- TB9 Object storage to the staging VM (p1-staging jade-4zw, ADR 0014): staging "uses its own secrets" (p1-staging), but the p10-backups restore drill brings a decrypted copy of production data onto it and needs the production backup key there; whether and when that copy is wiped is not decided (Q8, RR8).

### 5.5 Abuse cases
Table `| ID | Abuse case | Mitigation (named) | Phase, plan key, bead | Verified by |`. AB1-AB9 use the first-column text of ARCHITECTURE section 9 verbatim; AB10-AB16 are marked "beyond ARCHITECTURE 9". Every "Verified by" cell includes p9-authz-sweep jade-sio.
In the Mitigation cell, each mitigation (clauses separated by a `;` outside parentheses; a `;` inside a parenthesised citation does not split) names the bead that implements it, and that bead appears with its phase in the next cell. Epic ids are not cited in the Mitigation cell. `<filed id>` in AB4 and AB12 stands for the id of the bead filed in 5.8; the document carries the real id.

| ID | Abuse case | Mitigation (named) | Phase, plan key, bead | Verified by |
|---|---|---|---|---|
| AB1 | Guessing kit codes online | Check character rejects most typos before the server (jade-fd5); failed redemptions limited per account, 10 an hour then locked (jade-7if); a global failed-code throttle on redeem and code-gated signup (jade-7if, jade-vcy, jade-6cq); per-IP signup limit behind a flag, off by default (jade-vcy, jade-6cq) (ADR 0020) | Phase 2 p2-code-lib jade-fd5, p2-redeem jade-7if; Phase 3 p3-adult-auth jade-vcy; Phase 9 p9-ratelimit jade-6cq | jade-fd5 typo property test; jade-7if lockout test; jade-6cq flag off/on and global-throttle tests; jade-sio |
| AB2 | Brute-forcing a leaked code table | HMAC-SHA256 under the server-side pepper (jade-fd5, jade-o07; ADR 0011); pepper only in the env file and the offline store (jade-8v4, jade-lnn.1, jade-fgs); backups encrypted (jade-6o3) | Phase 1 p1-config jade-8v4; Phase 2 p2-code-lib jade-fd5, p2-schema-core jade-o07; Phase 10 jade-lnn.1, p10-secrets jade-fgs, p10-backups jade-6o3 | jade-fd5 "HMAC uses the pepper from config"; jade-sio |
| AB3 | Guessing a join code | Valid only while a session is open, stored hashed (jade-5nj); rotated on demand (jade-axr); join attempts rate limited per device, not per IP (jade-6cq) | Phase 3 p3-join jade-5nj, p3-session-controls jade-axr; Phase 9 p9-ratelimit jade-6cq | jade-6cq join brute-force and "30 devices from one IP" tests; jade-sio |
| AB4 | A group joins as another group's kit | Facilitator resets a kit's devices (jade-axr); facilitator sees duplicate device joins per kit on the class dashboard (`<filed id>`, the first bead of 5.8, phase to be confirmed at Q7) | Phase 3 p3-session-controls jade-axr; Phase 7 `<filed id>` (Q7) | the filed bead's test; jade-sio |
| AB5 | Spoofing events for another kit | Class and kit from the device session, never the payload (jade-5nj, jade-zg3; ADR 0008, CLAUDE.md rule 3); the same rule on the live alert endpoint (jade-p99) | Phase 3 p3-join jade-5nj; Phase 6 p6-ingest jade-zg3; Phase 7 p7-live-stuck jade-p99 | jade-zg3 "Payload cannot write events for another kit (tested)"; jade-sio |
| AB6 | Sharing a video URL | Signed, short-lived media URLs; unsigned or expired returns 403 (jade-u8z) | Phase 4 p4-video jade-u8z | jade-u8z 403 test; jade-sio |
| AB7 | Student reaching adult or staff pages | Route-group authorization matrix, 404 not 403; every new route enters the matrix test (jade-aq5) | Phase 3 p3-authz-tests jade-aq5 | jade-aq5 matrix test; jade-sio |
| AB8 | Free text capturing a child's name | No student free-text fields: preset stuck reasons (jade-fy1); the catalog rejects extra fields (jade-3ek); the adult note field (500 chars) carries a reminder (jade-p4p) | Phase 5 p5-stuck jade-fy1; Phase 6 p6-catalog jade-3ek; Phase 7 p7-notes jade-p4p | jade-3ek extra-field rejection; jade-sio |
| AB9 | IP addresses as hidden identifiers | Not logged by Caddy or the app (jade-80h, jade-alt, jade-ada); used in memory only, for rate limiting (jade-6cq; ADR 0020) | Phase 1 p1-docker jade-80h, p1-observability jade-alt; Phase 9 p9-logs jade-ada, p9-ratelimit jade-6cq | jade-alt log-line test; jade-ada log grep; jade-sio |
| AB10 | Facilitator reaching another class | Class ownership enforced in the authorization matrix (jade-bu6, jade-aq5) | Phase 3 p3-classes jade-bu6, p3-authz-tests jade-aq5 | jade-aq5 matrix test; jade-sio |
| AB11 | Tripping the global failed-code throttle to block legitimate redemption and signup | Accepted consequence of ADR 0020 (RR1); the throttle threshold is set and tested (jade-6cq). The sources do not say how the per-account redeem limit and the global throttle interact, and code-gated signup has no account to limit | Phase 9 p9-ratelimit jade-6cq | jade-6cq global-throttle test; jade-sio |
| AB12 | Flooding or spoofing the live stuck alert endpoint | Device-session auth, class and kit from the session (jade-p99); the in-memory alert store for kits with logging off is bounded and the endpoint rate-limited (`<filed id>`, the second bead of 5.8, phase to be confirmed at Q7) | Phase 7 p7-live-stuck jade-p99; Phase 7 `<filed id>` (Q7) | the filed bead's test; jade-sio |
| AB13 | A no-log kit's activity reaching storage or logs through the live alert path | Memory only (jade-p99); the no-log invariant covers a stuck/resolved cycle (jade-hhp) | Phase 6 p6-nolog-invariant jade-hhp; Phase 7 p7-live-stuck jade-p99 | jade-hhp invariant test; jade-sio |
| AB14 | Theft of a backup or the VM disk | Encrypted backups, key offline (jade-6o3, jade-lnn.1, jade-fgs); pepper not in the dump (jade-fd5; ADR 0011) | Phase 2 p2-code-lib jade-fd5; Phase 10 p10-backups jade-6o3, p10-secrets jade-fgs, jade-lnn.1; host open until jade-0za | jade-6o3 restore drill; jade-sio |
| AB15 | A staff export leaking kit-level data | Staff-only, audited, kit ids only, never adult emails (jade-1cc) | Phase 8 p8-export jade-1cc | jade-1cc tests; jade-sio |
| AB16 | A plain kit code leaking from the QR redeem URL (`/redeem?code=...`) into server logs or a Referer header | App log lines contain no code values (jade-alt); a grep of staging logs after a full e2e run finds no codes (jade-ada); `Referrer-Policy: no-referrer` (jade-c42, p9-headers description) | Phase 1 p1-observability jade-alt; Phase 9 p9-logs jade-ada, p9-headers jade-c42 | jade-alt "no IP, cookie or code values" test; jade-ada grep; jade-c42 header assertions; jade-sio |

"Verified by" for each row: jade-sio plus the bead's own test where its acceptance names one (for example jade-7if's parallel-redeem test, jade-zg3's "Payload cannot write events for another kit (tested)", jade-u8z's 403 test, jade-ada's log grep).
Under the table, two sentences that AB16 does not cover: the Caddy access log is "off or IP-stripped" (ARCHITECTURE 4), so whether it records the query string depends on which, and jade-ada's grep covers it only if the Caddy log is among the staging logs searched; and the code stays in the adult device's browser history, which no bead addresses (single-use redemption, jade-7if, limits a code seen there to whoever redeems it first) (RR9, Q9).

### 5.6 Data-flow diagram
One fenced `mermaid` block, `flowchart LR`, with subgraphs for TB1 (devices), the VM (Caddy, app, PostgreSQL, process memory), TB5 (object storage), TB9 (staging VM) and TB7 (offline). Required node ids, each labelled with what it holds and whether it is adult PII, kit-level, secret or neither:
`STU_DEV` (student device: device-session cookie, IndexedDB event queue, local progress), `ADULT_DEV` (adult session cookie; browser history holding scanned `/redeem?code=` URLs), `CADDY`, `APP`, `ALERTS` (live stuck alerts for kits with logging off, memory only, per class, until resolved or session closes; ADR 0017; whether logging-on kits use it is open, Q3), `RL_MEM` (rate-limit counters in memory; IP only when the per-IP signup flag is on; ADR 0020), `DB_USERS` (users, auth_sessions, invites), `DB_CLASSES` (classes, class_kits), `DB_KITS` (products, code_batches, kits, kit_codes), `DB_DEVSESS` (device_sessions), `DB_EVENTS`, `DB_PROGRESS` (kit_progress), `DB_NOTES` (facilitator_notes), `DB_QUIZ` (quiz_responses, exit_cards), `DB_AUDIT` (audit_log), `DB_AGG` (step_aggregates and quiz/exit-card aggregates, no kit id; ADR 0023), `LOGS` (server logs, 14 days, no IPs, emails, codes, tokens or bodies), `BACKUP` (encrypted dump, Canadian object storage, 30 days), `EXPORT` (staff CSV/JSON exports, off-platform), `PRINT` (printed code cards), `CSV` (packing CSV, offline), `SECRETS_ENV` (env file: CODE_PEPPER, SESSION_SECRET), `SECRETS_OFFLINE` (offline pepper and backup-key store), `RETENTION` (retention job, post-launch; ADR 0016).
`STAGING` (staging VM and its PostgreSQL: after the restore drill, a copy of production adult PII and kit-level data; wipe not decided, Q8).
Required edges: STU_DEV to ALERTS labelled "stuck / stuck_resolved, logging off (logging-on path: open, Q3)"; STU_DEV to DB_EVENTS and DB_PROGRESS labelled "only when logging_enabled"; ADULT_DEV to DB_NOTES and DB_QUIZ ("kit rows only when logging_enabled"); APP reads ALERTS for the facilitator view; the DB nodes to BACKUP; RETENTION from DB_EVENTS to DB_AGG, from DB_QUIZ to DB_AGG, deleting DB_PROGRESS and DB_DEVSESS, and nulling kit_id in DB_NOTES, each labelled "classes.ended_at + RETENTION_MONTHS"; DB nodes to EXPORT via staff only; CSV and PRINT from the code generator (p2-code-cli). Wherever a store is missing from the sources (for example where account lockout counters live), the node label says "storage not decided" rather than guessing.
Also: PRINT to ADULT_DEV labelled "QR opens /redeem?code= (plain code in the URL)", and ADULT_DEV to CADDY labelled "redeem request: plain code in the request line (AB16)"; BACKUP to STAGING labelled "restore drill (p10-backups jade-6o3): copy of production data", and SECRETS_OFFLINE to STAGING labelled "backup key for the drill".

### 5.7 Open until the human beads close
Section 7 of the document lists, per bead, what the model cannot settle yet:
- jade-0za (host): provider, region, object-storage provider, who holds VM and SSH access, DNS registrar; TB5, TB6 and AB14 stay provisional.
- jade-tw4 (school IT): device type and whether devices are shared across classes, cookie wiping (TB8), whether the school filter intercepts TLS (TB1 for the Wi-Fi outsider), allowlisting; assumptions A2 and A4.
- jade-6is (product questions): networked electronics or an AI assistant (A1; would add a device-key actor via E1 or a new module via E2), RETENTION_MONTHS, who enters quiz results (affects which adults hold `entered_by`), the kit prefix.
- jade-bi5 (consent): whether the approval covers the tiers of ADR 0023, the memory-only alerts for kits with logging off of ADR 0017, and backups that outlive a deletion by up to 30 days (RR2).
The document's section 7 also lists the items for Mike that are not tied to a human bead: Q3 (logging-on alert path), Q7 (phase of the two filed beads), Q8 (the staging copy) and Q9 (the code in browser history).

### 5.8 Gaps found, beads to file
While writing, file with `bd create "..." -t task -p 2 --parent jade-7s7 --deps discovered-from:jade-okb` and cite the ids, with "Phase 7", in AB4 and AB12, where the table of 5.5 shows `<filed id>`:
- "Show duplicate device joins per kit on the class dashboard" (ARCHITECTURE 9 names the mitigation; no bead implements it).
- "Bound the live stuck alert store and rate-limit its endpoint" (no bead's acceptance covers it; jade-6cq lists login, signup, redeem, join and ingest only).
The beads are not widened and these are not implemented here.
Phase 7 (epic jade-7s7) is proposed because it owns the two surfaces: the class dashboard (p7-class-view jade-d03) and the live alert endpoint (p7-live-stuck jade-p99). Mike confirms or changes the phase before implementation (Q7); if he names another phase epic, `--parent` and the "Phase" text in AB4 and AB12 use that epic instead.

### 5.9 CLAUDE.md and commit
Append to the same CLAUDE.md line as 4.6: ` Threat model: [docs/threat-model.md](docs/threat-model.md).` One commit, `docs: threat model and data-flow diagram (jade-okb)`, with the attribution trailer. Then `bd close jade-okb --reason "<summary>, commit <sha>, filed <ids>"`.

## 6. Order of work
1. Record `BASE=$(git rev-parse HEAD)` before starting.
2. jade-hqq: `bd update jade-hqq --claim`; write 0001-0023 (4.1-4.3), then README (4.4), then corrections D1-D3, E1-E4, P1-P5 (4.5), then CLAUDE.md (4.6); run checks AC1-AC7 and AC11; commit (4.7). If writing an ADR shows a decision that looks wrong, file a `decision` bead and stop (CLAUDE.md rule 8).
3. jade-okb (depends on jade-hqq): claim; file the two beads (5.8); write `docs/threat-model.md` (5.1-5.7); edit CLAUDE.md (5.9); run AC4 (CLAUDE.md part), AC8-AC11; commit; close.
4. Commits wait for Mike's go-ahead (CLAUDE.md: an approved plan is not authorization to implement).
5. AC13 runs with jade-hqq's checks for PRIVACY.md and DATA-MODEL.md and again with jade-okb's for `docs/threat-model.md`; AC14 runs with jade-okb's checks.

## 7. Acceptance checks
Run from the repo root.
- AC1 (OB1): `ls docs/adr` lists exactly README.md and the 23 files of 4.1; `ls docs/adr | grep -cE '^[0-9]{4}-[a-z0-9-]+\.md$'` prints 23.
- AC2 (OB1): for each `docs/adr/0*.md`, `grep -c '^- Status: accepted$'`, `grep -c '^## Context$'`, `grep -c '^## Decision$'`, `grep -c '^## Consequences$'` each print 1.
- AC3 (INV1): a script splits DECISIONS.md at `## ADR-NN` headings up to the first `---`, and asserts each body (stripped) is a substring of `docs/adr/00NN-*.md`; and for k in 1..8 that `bd show jade-8n2.<k> --json` `close_reason` is a substring of ADR `00(15+k)`.
- AC4 (OB2, OB3): `grep -c '](00[0-9][0-9]-' docs/adr/README.md` is at least 23 and every ADR file name appears in it; README has headings `## Index`, `## Amendments to the handoff documents`, `## Assumptions (unconfirmed)`, `## Open questions`, and contains A1 to A7 and questions 1 to 9; `grep -F '](docs/adr/README.md)' CLAUDE.md` and `grep -F '](docs/handoff/ARCHITECTURE.md)' CLAUDE.md` each match; `git diff $BASE -- CLAUDE.md` changes only the "Read before any work" line, and the eight numbered rules are unchanged.
- AC5 (OB4): ADR files 0016-0023 exist and each names its bead `jade-8n2.<k>`; `grep -F 'not clamped' docs/handoff/EVENTS.md`, `grep -F 'live alert endpoint' docs/handoff/EVENTS.md`, `grep -F 'step_aggregates' docs/handoff/DATA-MODEL.md`, `grep -F 'set to null' docs/handoff/DATA-MODEL.md`, `grep -F 'memory' docs/handoff/PRIVACY.md`, `grep -F 'per-IP' docs/handoff/PRIVACY.md` each match; `grep -c "'\^\[A-D\]\$'" docs/handoff/DATA-MODEL.md` prints 2; each of the three files has exactly one line starting `> Amended 2026-11-14`.
- AC6 (INV3): `git diff $BASE -- docs/handoff/DATA-MODEL.md docs/handoff/EVENTS.md docs/handoff/PRIVACY.md` shows only the hunks D1-D3, E1-E4, P1-P5 (reviewer reads the diff against 4.5).
- AC7 (INV2): `git diff --name-only $BASE HEAD -- docs/handoff/phases docs/handoff/tools docs/handoff/beads docs/handoff/prompts docs/handoff/ARCHITECTURE.md docs/handoff/DECISIONS.md docs/handoff/REVIEW.md docs/handoff/START-HERE.md docs/handoff/CLAUDE-SECTION.md jade-handoff.zip` prints nothing.
- AC8 (jade-okb description): `docs/threat-model.md` has the eight `## ` headings of 5.1; section 1 names the five actors; section 2 names kit codes, code pepper, adult credentials and event data.
- AC9 (OB5): the section 5 table has five columns in every row and rows AB1 to AB16; for each first-column text of the ARCHITECTURE.md section 9 table, `grep -F` finds a row in `docs/threat-model.md` section 5; in every row, the Mitigation cell is split at each `;` outside parentheses (a `;` inside a parenthesised citation such as `(jade-fd5; ADR 0011)` does not split), each clause names at least one `jade-` id, and every id named in the cell appears in the "Phase, plan key, bead" cell after a `Phase [0-9]+` (a short script splits the cells, tracking parenthesis depth, and prints any clause or id that fails); no row still contains `<filed id>`; AB4 and AB12 contain `Phase 7` (or the phase Mike chose at Q7) followed by the ids filed in 5.8, and `bd show <id>` shows each filed bead with parent jade-7s7 (or that phase's epic) and a discovered-from link to jade-okb. AB11's first clause cites ADR 0020 and RR1 and is checked by the reviewer, not the script.
- AC10 (OB6): the file has exactly one ```` ```mermaid ```` block and it contains every node id of 5.6; it renders (GitHub preview or `mmdc` if available; no install is part of this plan).
- AC11: relative-link check over `docs/adr/*.md`, `docs/threat-model.md`, `CLAUDE.md` and the three corrected files: every `](target)` that is not a URL or bare anchor resolves to an existing path relative to the file (a 10-line Python script; prints the broken links and exits non-zero).
- AC12: `git log --format=%s $BASE..HEAD` contains one commit whose subject names `jade-hqq` and, after it, one whose subject names `jade-okb`; `git show --stat` of each touches only the files that section 4 or section 5 lists for that bead.
- AC13 (OB4, INV6): `grep -F 'Live stuck alerts for kits with logging off' docs/handoff/PRIVACY.md` and `grep -F 'Live stuck alerts for kits with logging off' docs/handoff/DATA-MODEL.md` each match; and for each of `docs/handoff/PRIVACY.md`, `docs/handoff/DATA-MODEL.md` and `docs/threat-model.md`, `grep -i 'alert' <file> | grep -ci -E 'every kit|all kits'` prints 0, so no alert statement claims every kit. PRIVACY.md line 30 ("Logging is off for every kit until an adult confirms ...") has no "alert", is not an alert claim, and stays byte-identical under INV3.
- AC14 (OB6): the mermaid block contains the edge labels `restore drill` and `/redeem?code=` and the node id `STAGING`, and `docs/threat-model.md` section 3 contains `TB9`.

## 8. Open questions for Mike
- Q1. Join creates and updates a `device_sessions` row (with `last_seen_at`) for a kit with logging off. Is that outside "stores nothing about that kit's activity" (CLAUDE.md rule 2)? jade-hhp lists events, kit_progress, notes and quiz tables only. The docs record the fact; they do not answer it (RR3).
- Q2. Backups keep 30 days (PRIVACY.md, ARCHITECTURE 10), so a kit deletion or retention reduction stays in backups for up to 30 days, while the consent sentence says records can be deleted "at any time" (RR2).
- Q3. ADR 0017 fixes the alert path for kits with logging off. For kits with logging on, does the facilitator's live alert come from the same endpoint or from ingested `stuck` events? p7-live-stuck must not guess; the threat model shows the no-log path only as decided.
- Q4. Regenerate the phase files from an updated `build_plan.py` so they match the amended beads, or leave them as a snapshot with the README amendment map (this plan's default) (RR4)?
- Q5. jade-x94's acceptance still lists "All modules for Pilot 1 pass content lint" and "Given has reviewed the preview", which ADR 0021 moved to jade-buf.1 and jade-buf.2.
- Q6. For jade-bi5: should the borrowed consent sentences mention that a no-log group's "I'm stuck" press reaches the facilitator live?
- Q7. The two mitigation beads of 5.8 (duplicate-join visibility; bounding and rate-limiting the live alert store) are filed under the Phase 7 epic jade-7s7, which owns p7-class-view jade-d03 and p7-live-stuck jade-p99. Confirm Phase 7, or name another phase (RR6).
- Q8. The p10-backups restore drill puts a decrypted copy of production data on the staging VM, which otherwise "uses its own secrets". Should that copy be wiped after the drill, and when, or restored somewhere else? No source decides it; the threat model records it (TB9, RR8).
- Q9. Scanning a code card's QR leaves the plain code in the adult device's browser history (`/redeem?code=...`, p2-code-cli). Should p2-redeem keep the code out of the URL after the scan, or is this accepted? The threat model records it (RR9); this plan does not change p2-redeem.

## Residual risks
- RR1: The global failed-code throttle of ADR 0020 is shared by every user, so anyone submitting wrong codes can delay legitimate redemption and signup for everyone; the decision accepts this, and only p9-ratelimit's threshold tuning limits it.
- RR2: Kit deletion and retention reductions do not reach the 30-day backups, which may conflict with the consent promise of deletion at any time; no decision covers it (Q2).
- RR3: Whether `device_sessions` rows for logging-off kits count as stored activity under CLAUDE.md rule 2 is undecided (Q1).
- RR4: The generated phase files and `build_plan.py` disagree with the amended beads (p6-ingest clamping, p7-quiz A/B/C, p9-privacy-doc's dependency, p6-client and p7-live-stuck alert path); a reader who skips CLAUDE.md and the README amendment map can build the old rule.
- RR5: The retention tiers of ADR 0023 have not been checked against the research approval (jade-bi5 open), and `facilitator_notes` keep adult free text with its class indefinitely after retention.
- RR6: Two mitigations had no implementing bead (duplicate-join visibility, a bounded and rate-limited live alert store); 5.8 files them under the Phase 7 epic jade-7s7, a phase this plan proposes and Mike confirms (Q7), and the new beads carry only a title until Phase 7 planning scopes them.
- RR7: Editing the handoff data docs in place means the files no longer match `jade-handoff.zip`; the banner and commit 079e846 keep the original reachable.
- RR8: After the p10-backups restore drill, the staging VM holds a copy of production adult PII and kit-level data, and the production backup key has been used there; no source says when it is wiped, so kit deletions and retention do not reach it either (Q8).
- RR9: A scanned QR leaves the plain kit code in the adult device's browser history; no bead addresses it, and only single-use redemption (jade-7if) limits its value (Q9).

## Change log
- FIX R8: AC13 now tests the claim, not the phrase: the positive grep for "Live stuck alerts for kits with logging off" runs on PRIVACY.md and DATA-MODEL.md, and the negative check is `grep -i 'alert' <file> | grep -ci -E 'every kit|all kits'` printing 0 on PRIVACY.md, DATA-MODEL.md and the threat model, so PRIVACY.md line 30 (no "alert") passes untouched and INV3 holds; section 6 item 5 adds DATA-MODEL.md to jade-hqq's AC13 run.
- FIX R9: AC9 splits the Mitigation cell only at a `;` outside parentheses (the script tracks parenthesis depth) and fails if `<filed id>` remains; 5.5 says so and bans epic ids from the Mitigation cell; AB4 and AB12 drop "the Phase 7 epic jade-7s7" from the Mitigation cell and cite `<filed id>` (the 5.8 bead) in both the Mitigation and Phase cells; 5.8 says the filed ids replace `<filed id>`. The parent link to jade-7s7 is still checked by AC9's `bd show`.
- FIX R10: D2 now reads "Live stuck alerts for kits with logging off ... Whether kits with logging on use the same store is open.", with its source and Q3. The same class is closed elsewhere: the 0017 row of 4.3 and the 5.3 Kit-level data asset are limited to kits with logging off with the logging-on path open (Q3), AB12's in-memory store is limited to kits with logging off, and 5.7's jade-bi5 item says "the memory-only alerts for kits with logging off". A sweep of the draft for "live alert", "live stuck alert" and "ALERTS" leaves only headings, file names, bead titles, citations and mitigation references unscoped.
- SHRINK ### 4.3 Per-ADR content outline: the 0017 row's Consequences cell limits the memory-only alert store to kits with logging off and says the logging-on path is open (Q3) (R10); no consequence removed.
- SHRINK ### 4.5 Corrections to the handoff data docs: D2's inserted DATA-MODEL sentence is limited to kits with logging off, says the logging-on store is open, is to be one line, and cites its source and Q3 (R10); no correction removed.
- SHRINK ### 5.3 Assets: the Kit-level data row's live-alert item is limited to kits with logging off, logging-on path open (Q3) (R10); nothing removed.
- SHRINK ### 5.5 Abuse cases: the clause rule says a `;` inside parentheses does not split and epic ids are not cited; AB4 and AB12 cite `<filed id>` instead of the epic, and AB12's store is limited to kits with logging off (R9, R10); every mitigation is kept.
- SHRINK ### 5.8 Gaps found, beads to file: the filing line says the filed ids replace `<filed id>` in AB4 and AB12 (R9); the command and the two titles are unchanged.
- SHRINK ### 5.7 Open until the human beads close: the jade-bi5 item limits the memory-only alerts of ADR 0017 to kits with logging off (R10); no item removed.
- SHRINK ## 6. Order of work: item 5 adds DATA-MODEL.md to the jade-hqq run of AC13 (R8); order unchanged.
- SHRINK ## 7. Acceptance checks: AC9 splits at `;` outside parentheses and rejects a leftover `<filed id>` (R9); AC13 checks alert lines, not the bare phrase, and covers DATA-MODEL.md (R8, R10); no check removed.

## Artifact inventory
- section: ## 0. Summary
- section: ## 1. Obligations
- section: ## 2. Placement decisions this plan makes
- section: ## 3. Invariants
- section: ## 4. jade-hqq: ADRs, index, corrections
- section: ### 4.1 Files
- section: ### 4.2 ADR file template
- section: ### 4.3 Per-ADR content outline
- section: ### 4.4 docs/adr/README.md
- section: ### 4.5 Corrections to the handoff data docs
- section: ### 4.6 CLAUDE.md
- section: ### 4.7 Commit
- section: ## 5. jade-okb: threat model
- section: ### 5.1 Document outline (`docs/threat-model.md`)
- section: ### 5.2 Actors
- section: ### 5.3 Assets
- section: ### 5.4 Trust boundaries
- section: ### 5.5 Abuse cases
- section: ### 5.6 Data-flow diagram
- section: ### 5.7 Open until the human beads close
- section: ### 5.8 Gaps found, beads to file
- section: ### 5.9 CLAUDE.md and commit
- section: ## 6. Order of work
- section: ## 7. Acceptance checks
- section: ## 8. Open questions for Mike
- section: ## Residual risks
- section: ## Change log
- section: ## Artifact inventory
- id: OB1
- id: OB2
- id: OB3
- id: OB4
- id: OB5
- id: OB6
- id: INV1
- id: INV2
- id: INV3
- id: INV4
- id: INV5
- id: INV6
- id: AC1
- id: AC2
- id: AC3
- id: AC4
- id: AC5
- id: AC6
- id: AC7
- id: AC8
- id: AC9
- id: AC10
- id: AC11
- id: AC12
- id: AC13
- id: AC14
- id: RR1
- id: RR2
- id: RR3
- id: RR4
- id: RR5
- id: RR6
- id: RR7
- id: RR8
- id: RR9
