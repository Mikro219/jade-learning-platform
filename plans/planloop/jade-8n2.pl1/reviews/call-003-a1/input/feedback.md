PLANLOOP-BUNDLE run=jade-8n2.pl1 revision=3 call=3 attempt=1 sha256=f4618aa3433b6be93f85a794dfc3a629fd5be962564b3816cd4fc242d8718339
Policy planloop/3 (quartz-rs-lur, 2026-10-22).

/home/mikep/.local/state/planloop-isolated/r-eace18831539469e/repo is a frozen, read-only snapshot of the repository for this revision. Read only files
under it; a relative path below is relative to it. Never read the original checkout or any other path
outside it: such reads are detected in your transcript and void the review.
/home/mikep/.local/state/planloop-isolated/r-eace18831539469e/repo/.planloop-bundle/ holds the frozen plan, brief, obligations, binding bead text, evidence and
the discovery record; bead text cannot be fetched any other way (never run bd).

Coverage must contain, for every finding listed below in state fix_proposed, exactly one entry
`finding R<k>: resolved` or `finding R<k>: unresolved`. To withdraw an open finding you judge invalid,
write `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, at least 40 chars>`.
When re-raising a known finding, use its R id as your finding id.
Check every REMOVED and SHRINK disposition below: each must say what was removed, why, and which
obligations or capabilities it affects; an unexplained removal is a finding.

--- REVIEW BRIEF (host) ---
# Review brief: jade-8n2.pl1 (Phase 0: Architecture lock), revision 3

## Scope
Documentation only. The plan covers the two agent beads of Phase 0:
- jade-hqq (p0-adr): ADR files under docs/adr/ from docs/handoff/DECISIONS.md ADR-01..15, plus the eight decisions of 2026-11-14 (beads jade-8n2.1 .. jade-8n2.8, see their close reasons and the acceptance criteria they amended), docs/adr/README.md, the CLAUDE.md link, and corrections to DATA-MODEL.md, EVENTS.md and PRIVACY.md.
- jade-okb (p0-threat): docs/threat-model.md with actors, assets, trust boundaries, every ARCHITECTURE.md section 9 abuse case with a named mitigation and implementing phase/bead, and a Mermaid data-flow diagram of every store of adult PII and kit-level data.
The four human beads (jade-0za, jade-6is, jade-tw4, jade-bi5) are out of scope.

## Rubric (every round)
Contradictions; missing requirements (every obligation row); incorrect assumptions; affected consumers (p1-scaffold depends on p0-adr; p9-authz-sweep walks every abuse case in docs/threat-model.md); test coverage, here mechanical acceptance checks; verifiable acceptance criteria; unnecessary scope expansion; every claim the documents make must be one the sources support.

JADE invariants: the plan must not change or relax any decision (CLAUDE.md rule 8) or CLAUDE.md rules 1-6; ADRs record decisions, they do not reargue them; a contradiction between sources is raised as an open question or residual risk, not silently resolved; no teaching content (rule 7); generated files (docs/handoff/phases/*, from docs/handoff/tools/build_plan.py) are not hand-edited.

Findings need a severity (high/medium/low) and concrete evidence (file and line, or bead and field).

## Change map (navigation only)
New: docs/adr/*.md, docs/adr/README.md, docs/threat-model.md. Changed: CLAUDE.md (link), and wherever the plan puts the corrected DATA-MODEL/EVENTS/PRIVACY text.

## Decision close reasons (verbatim, from `bd show jade-8n2.<k> --json` field close_reason)

### jade-8n2.1: DECISION: p8-views is launch-blocking, but START-HERE says only p8-quality and p8-export are

Decided (Mike, 2026-11-14): retention post-launch. p9-retention and p8-views labelled post-launch-ok; p9-retention due 2027-06-30; p9-privacy-doc no longer depends on p9-retention and documents the policy instead.

### jade-8n2.2: DECISION: how live stuck alerts reach the facilitator for kits with logging off

Decided (Mike, 2026-11-14): separate live endpoint, memory-only, device-session auth; client sends only stuck/stuck_resolved there in no-log mode; no-log invariant extended (now depends on p7-live-stuck).

### jade-8n2.3: DECISION: stale client timestamps flagged only (EVENTS.md) or clamped too (p6-ingest)

Decided (Mike, 2026-11-14): flag only, per EVENTS.md. Future clamped and flagged; stale flagged, not clamped.

### jade-8n2.4: DECISION: participant letters A-C (p7-quiz) or A-D (DATA-MODEL, PRIVACY)

Decided (Mike, 2026-11-14): A-D, as DATA-MODEL and PRIVACY. p7-quiz wording corrected in its acceptance.

### jade-8n2.5: DECISION: rate-limit keys for code redemption and code-gated signup

Decided (Mike, 2026-11-14): global throttle for now; per-IP signup limit kept as a toggle (config flag, off by default) for later. Redeem stays per account.

### jade-8n2.6: DECISION: beads labelled human that also contain agent work

Decided (Mike, 2026-11-14): split into agent + human beads. New agent beads jade-buf.1, jade-lnn.1, jade-lnn.2, jade-lnn.3; new human bead jade-buf.2. Production actions stay human.

### jade-8n2.7: DECISION: p0-open-decisions acceptance omits retention, quiz entry and the freeze date

Decided (Mike, 2026-11-14): extend jade-6is acceptance with retention period, quiz entry and freeze date; calendar re-sequenced once the freeze is confirmed.

### jade-8n2.8: DECISION: retention for kit-keyed data other than raw events

Decided (Mike, 2026-11-14): tiered retention (see p9-retention acceptance).

## Checking the plan's obligations
OB1-OB6 are the acceptance criteria of jade-hqq and jade-okb, frozen as bead fields in the bundle. Check the plan answers each, and that every quoted verbatim source (DECISIONS.md bodies, close reasons above, amended acceptance lines in the frozen beads) matches.

## Open findings this revision answers (full text from the call 2 receipt; reviewer ids F1-F3 are R8-R10)

### R8 (medium) ## 7. Acceptance checks (AC13); docs/handoff/PRIVACY.md line 30

Evidence: AC13 requires `grep -ci 'every kit'` to print 0 for docs/handoff/PRIVACY.md. Line 30 of the current file reads '- Logging is off for every kit until an adult confirms that consent is in hand for each child in that group.' None of the 4.5 edits touches that line, and INV3 makes every other line byte-identical. So after a correct implementation AC13 prints 1 and fails. The implementer then has to break INV3, rewriting a consent sentence, or ignore a failing check. Also, a threat model that quotes that PRIVACY sentence would fail the same way.

Suggested fix: Make AC13 test the claim itself, not the phrase. For example, check that no line containing 'alert' also contains 'every kit' (`grep -i 'alert' <file> | grep -ci 'every kit'` prints 0) in PRIVACY.md and docs/threat-model.md, together with the existing positive grep for 'Live stuck alerts for kits with logging off'. Or require a count of exactly 1 for PRIVACY.md, as line 30's baseline.

### R9 (low) ## 7. Acceptance checks (AC9); ### 5.5 Abuse cases

Evidence: AC9's script splits each Mitigation cell on ';' and requires every clause to name a jade- id. It also requires every id named there to appear in the Phase cell after 'Phase N'. Several planned cells put ';' inside parentheses: AB2 '(jade-fd5, jade-o07; ADR 0011)', AB5 '(jade-5nj, jade-zg3; ADR 0008, CLAUDE.md rule 3)', AB9 '(jade-6cq; ADR 0020)', AB14 '(jade-fd5; ADR 0011)', AB4 and AB12 '(the bead filed in 5.8 under the Phase 7 epic jade-7s7; phase to be confirmed, Q7)'. Each of these yields a clause with no id, such as 'ADR 0011)' or 'phase to be confirmed, Q7)'. In AB4 and AB12, jade-7s7 is also named in the Mitigation cell but not in the Phase cell. Only AB11's first clause is exempted, so the check as written reports failures on six rows of the plan's own text.

Suggested fix: Split only on ';' outside parentheses, or use ',' inside the parenthetical citations. In AB4 and AB12, replace the epic reference in the Mitigation cell with the filed bead id (the parent link is already checked separately), or exempt epic ids from the Phase-cell match.

### R10 (low) ### 4.5 Corrections to the handoff data docs (D2)

Evidence: D2 inserts into DATA-MODEL.md: 'Live stuck alerts (ADR 0017) have no table. The app holds them in memory per class until resolved or the session closes; they are never written to the database or logs.' This applies to all kits. The R1 fix limits P2 and the ALERTS node to kits with logging off and leaves the logging-on path open (Q3). If Q3 settles that a logging-on kit's alert comes from ingested `stuck` events, which are stored in `events`, D2 is false. That is the same over-claim R1 fixed in PRIVACY.md, now in DATA-MODEL.md. INV6 forbids picking an answer to an open question.

Suggested fix: Limit D2 to match P2: 'Live stuck alerts for kits with logging off (ADR 0017) have no table... (whether kits with logging on use the same store is open, Q3).'

R1-R7 were verified resolved in call 2. R10 is the second finding of R1's class (unscoped claims that live alerts are memory-only); check that no live-alert statement in the plan claims a scope beyond kits with logging off.

## Findings R1-R7 (closed after call 2): full original text from the call 1 attempt 2 receipt (reviewer ids F1-F7 are R1-R7)

Call 2's reviewer did not have this text and judged R1-R7 from the plan and its change log. Recheck each against the original failure scenario below. If a scenario can still occur in this revision, raise it as a new finding that names the R id it reopens.

### R1 (medium) plan 4.5 P2; plan 5.6 required edges; plan 8 Q3

Evidence: P2 inserts the PRIVACY.md row 'Live stuck alerts (every kit, including kits with logging off) | App memory, per class ...'. Section 5.6 labels STU_DEV->ALERTS 'stuck / stuck_resolved, every kit incl. logging off'. The plan's own Q3 says it is undecided whether logging-on kits use the same endpoint ('p7-live-stuck must not guess; the threat model shows the no-log path only as decided'). The sources are silent or limited to no-log kits. The jade-8n2.2 close reason says 'client sends only stuck/stuck_resolved there in no-log mode'. ARCHITECTURE.md line 168 and the jade-p99 description speak only of kits with logging off. Writing 'every kit' into PRIVACY.md, the privacy-promise doc that p9-privacy-doc and the consent work build from, settles an open question. That breaks INV6 and the brief's invariant ('a contradiction between sources is raised as an open question ..., not silently resolved'). It also contradicts Q3 inside the plan.

Suggested fix: Change the P2 row to 'Live stuck alerts for kits with logging off' (or add 'whether logging-on kits use the same store: open, Q3'). Label the diagram edge 'stuck / stuck_resolved, logging off (logging-on path: open, Q3)'. Add an AC5 grep confirming that PRIVACY.md does not contain 'every kit'.

### R2 (medium) plan 5.6 Data-flow diagram; 5.4 trust boundaries (OB6)

Evidence: OB6 requires the diagram to show 'every place adult PII and kit-level data is stored'. The p10-backups section of docs/handoff/phases/phase-10-production-deploy.md says 'Perform a full restore onto staging and record the time taken'. The staging VM (p1-staging jade-4zw, ADR 0014) therefore holds a restored copy of the production database (users, audit_log, any kit data present at drill time), and the production backup key must be used there. The required node list (STU_DEV ... RETENTION) has only production VM, object-storage and offline subgraphs. No staging node, edge or trust boundary exists, so a store of adult PII is missing and OB6 fails.

Suggested fix: Add a STAGING node or subgraph (staging VM and its PostgreSQL), with an edge BACKUP -> STAGING labelled 'restore drill (p10-backups jade-6o3): copy of production data'. Name it in section 3 as a trust boundary (staging uses its own secrets per p1-staging but receives production data during the drill). Add an RR or Q on whether staging data is wiped after the drill. Add STAGING to the AC10 node-id list.

### R3 (medium) plan 5.5 AB4 and AB12; plan 5.8; AC9 (OB5)

Evidence: OB5 requires 'Every abuse case has a named mitigation and the phase that implements it'. AB4's ARCHITECTURE.md section 9 mitigation ('Facilitator sees duplicate joins', line 182) and AB12's bounding and rate-limiting mitigation are assigned to 'the filed bead'. Section 5.8 files that bead with `bd create ... -t task -p 2 --deps discovered-from:jade-okb`, with no parent phase epic, so it is unscheduled and has no phase (RR6 admits this). AC9 passes only because these rows also contain an unrelated 'Phase 3' or 'Phase 7' citation. p9-authz-sweep (jade-sio) must link each abuse case to a passing test, and it cannot do that for an unscheduled mitigation.

Suggested fix: Either file the two beads under the phase that owns the surface: p7-class-view and p7-live-stuck are Phase 7 (epic jade-7s7), so file with --parent jade-7s7 or a dependency from that epic, and write 'Phase 7, <new id>' in AB4 and AB12. Or, if choosing a phase is Mike's call, add it as an explicit question in section 8, mark OB5 as not met for the duplicate-join and alert-store mitigations until he answers, and tighten AC9 so each named mitigation, not just each row, carries a phase.

### R4 (medium) plan 5.3 Assets (kit codes); 5.5; 5.6

Evidence: The asset row says 'Kit codes: plain only on the printed card and the offline packing CSV'. But p2-code-cli (docs/handoff/phases/phase-02-data-model-and-kit-codes.md) prints 'a QR that opens /redeem?code=...', and the classroom flow (ARCHITECTURE.md section 5, step 1) has facilitators scan each card's QR. The plain code therefore travels as a URL query string. It lands in the adult device's browser history. It is in the request line seen by Caddy, whose access log may be 'IP-stripped' rather than off (ARCHITECTURE.md section 4), and by app request logging. It is a potential Referer value. CLAUDE.md rule 4 says plain kit codes are never logged. The threat model is the document p9-authz-sweep walks, and as planned it never names this path, so no abuse case or mitigation (p1-observability no-code logging, p9-logs grep, p9-headers Referrer-Policy no-referrer) is tied to it.

Suggested fix: Correct the asset row to list the QR redeem URL (adult device history, request URLs). Add an abuse case beyond ARCHITECTURE 9, e.g. 'Plain kit code leaking from the QR redeem URL into logs, history or Referer', with mitigations p1-observability jade-alt, p9-logs jade-ada and p9-headers jade-c42 (Phase 1/9). Add an edge PRINT -> ADULT_DEV 'QR /redeem?code=' to the diagram.

### R5 (low) plan 4.4 item 3 (amendment map phase-file row)

Evidence: PD2 promises the README lists superseded statements 'statement by statement', but the phase-file row omits several beads the 2026-11-14 decisions amended. p6-nolog-invariant (jade-hhp gained a jade-8n2.2 acceptance line). p0-open-decisions (jade-6is gained three lines, and phase-00-architecture-lock.md lines 45-49 still show three). p8-views (jade-lx4 newly labelled post-launch-ok, while phase-08 still shows the old labels).

Suggested fix: Add p6-nolog-invariant, p0-open-decisions and p8-views (labels) to the phase-file row, or derive the row mechanically from the `bd list` search for jade-8n2.<k> that 4.3 already prescribes.

### R6 (low) plan 4.6 CLAUDE.md line; 4.1 title of 0016

Evidence: The new CLAUDE.md line says '0016 onward are later decisions that amend the handoff docs'. But 0021 (bead split) and 0022 (jade-6is scope) amend beads, not handoff docs, and 0019 changes no handoff text. Separately, ADR 0016's title 'Step-metrics views and the retention job ship after launch' turns p8-views' 'post-launch-ok' label (allowed after launch) into a firm 'ship after launch'. The close reason supports only the label, and jade-771 states 'ships after launch' only for the retention job.

Suggested fix: Reword the CLAUDE.md line to '0016 onward are decisions of 2026-11-14 (see docs/adr/README.md)'. Retitle 0016 to e.g. 'Step-metrics views and the retention job are post-launch-ok'.

### R7 (low) plan 5.5 table and AB11

Evidence: The declared header `| ID | Abuse case | Mitigation (named) | Phase, plan key, bead | Verified by |` has five columns, but the table shown has four, and Verified-by is described in a separate paragraph. AB11's mitigation 'per-account limits apply first' is not supported by any source. jade-7if and jade-vcy name the limits but give no order, and signup has no account to limit.

Suggested fix: Settle on one table shape (keep the Verified-by column, as AC9 and jade-sio need it). Drop 'per-account limits apply first' from AB11, or mark the ordering as not specified by the sources.

--- OBLIGATIONS (exact source text) ---
OB1 [bead:jade-hqq acceptance_criteria]: One file per ADR, numbered, each with Context / Decision / Consequences
OB2 [bead:jade-hqq acceptance_criteria]: docs/adr/README.md indexes them
OB3 [bead:jade-hqq acceptance_criteria]: CLAUDE.md links to docs/adr/ and docs/handoff/ARCHITECTURE.md
OB4 [bead:jade-hqq acceptance_criteria]: Decisions jade-8n2.1 to jade-8n2.8 (decided 2026-11-14, see each bead's close reason) recorded as ADRs after ADR-15, and DATA-MODEL.md, EVENTS.md and PRIVACY.md corrected to match them
OB5 [bead:jade-okb acceptance_criteria]: Every abuse case has a named mitigation and the phase that implements it
OB6 [bead:jade-okb acceptance_criteria]: Data-flow diagram shows every place adult PII and kit-level data is stored

--- DISPOSITIONS IN THIS REVISION ---
SHRINK ### 4.3 Per-ADR content outline: the 0017 row's Consequences cell limits the memory-only alert store to kits with logging off and says the logging-on path is open (Q3) (R10); no consequence removed.
SHRINK ### 4.5 Corrections to the handoff data docs: D2's inserted DATA-MODEL sentence is limited to kits with logging off, says the logging-on store is open, is to be one line, and cites its source and Q3 (R10); no correction removed.
SHRINK ### 5.3 Assets: the Kit-level data row's live-alert item is limited to kits with logging off, logging-on path open (Q3) (R10); nothing removed.
SHRINK ### 5.5 Abuse cases: the clause rule says a `;` inside parentheses does not split and epic ids are not cited; AB4 and AB12 cite `<filed id>` instead of the epic, and AB12's store is limited to kits with logging off (R9, R10); every mitigation is kept.
SHRINK ### 5.8 Gaps found, beads to file: the filing line says the filed ids replace `<filed id>` in AB4 and AB12 (R9); the command and the two titles are unchanged.
SHRINK ### 5.7 Open until the human beads close: the jade-bi5 item limits the memory-only alerts of ADR 0017 to kits with logging off (R10); no item removed.
SHRINK ## 6. Order of work: item 5 adds DATA-MODEL.md to the jade-hqq run of AC13 (R8); order unchanged.
SHRINK ## 7. Acceptance checks: AC9 splits at `;` outside parentheses and rejects a leftover `<filed id>` (R9); AC13 checks alert lines, not the bare phrase, and covers DATA-MODEL.md (R8, R10); no check removed.
FIX R10
FIX R8
FIX R9

--- FINDINGS (Beads, at dispatch) ---
| ID | severity | state | raised in call | fixes proposed | resolution |
|---|---|---|---|---|---|
| R1 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R2 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R3 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R4 | medium | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R5 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R6 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R7 | low | verified | 1 | 1 | reviews/call-002-a1/receipt.json |
| R8 | medium | fix_proposed | 2 | 1 | - |
| R9 | low | fix_proposed | 2 | 1 | - |
| R10 | low | fix_proposed | 2 | 1 | - |

