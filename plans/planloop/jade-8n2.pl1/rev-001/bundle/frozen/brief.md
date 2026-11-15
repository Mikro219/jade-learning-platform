# Review brief: jade-8n2.pl1 (Phase 0: Architecture lock), revision 1

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
