# 0019. Participant letters are A to D

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.4, close reason (Mike, 2026-11-14)
- Related: [0010](0010-kit-is-the-unit-of-analysis.md)

## Context

DATA-MODEL.md checks `participant ~ '^[A-D]$'` on `quiz_responses` and `exit_cards`, and PRIVACY.md says "A to D", while p7-quiz said "participant letter (A/B/C)" (jade-8n2.4 description). Assumption A2 says groups of 2 or 3 share one device (jade-8n2.4 description; [README](README.md#assumptions-unconfirmed)).

## Decision

Decided (Mike, 2026-11-14): A-D, as DATA-MODEL and PRIVACY. p7-quiz wording corrected in its acceptance.

Acceptance criteria this decision added:

- jade-e6m: Participant letters A to D (DATA-MODEL check constraint), not A/B/C (jade-8n2.4)

## Consequences

- DATA-MODEL.md section 5 (`check (participant ~ '^[A-D]$')` on `quiz_responses` and `exit_cards`) and PRIVACY.md "Who the data is about" ("A to D") already agree, so no correction to them is needed; their banners record this confirmation.
- p7-quiz (jade-e6m) carries the A to D range in its acceptance.
- The generated `phase-07` p7-quiz text still says "participant letter (A/B/C)" ([README amendment map](README.md#amendments-to-the-handoff-documents)).
