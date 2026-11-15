# 0009. Consent-gated logging

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-09
- Related: [0017](0017-live-stuck-alerts-for-no-log-kits.md)

## Context

v1 handled consent by form wording only, with no mechanism for a group whose parents did not consent (REVIEW.md finding 5). Design principle 3 is "Nothing is recorded without consent": logging is off per kit until a facilitator confirms consent, and with it off the content still works and the server stores no activity (ARCHITECTURE.md section 2). `class_kits.logging_enabled` is the single switch, and a required CI test (`p6-nolog-invariant`) is the evidence behind the opt-out sentence in the consent form (ARCHITECTURE.md section 8, "The consent gate").

## Decision

`logging_enabled` per kit per class, default off, switched on by an adult who confirms consent. Off means zero activity stored server-side. A required test enforces this.

## Consequences

- p3-consent-flag (jade-8lt) builds the per-kit logging switch with consent confirmation, default off; p6-nolog-invariant (jade-hhp) is the required test that no activity row is written with logging off (bead descriptions and acceptance).
- CLAUDE.md rule 2: when a kit's `logging_enabled` is false, the server stores nothing about that kit's activity, and the `p6-nolog-invariant` test must never be skipped, weakened or deleted.
- How a stuck alert from a kit with logging off reaches the facilitator is [0017](0017-live-stuck-alerts-for-no-log-kits.md).
