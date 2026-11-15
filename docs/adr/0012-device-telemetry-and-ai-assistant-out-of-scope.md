# 0012. Device telemetry and AI assistant are out of scope

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-12

## Context

v1 included device sync and an AI proxy, and the arm kit (knobs and joystick) has no stated need for either (REVIEW.md finding 1). Architecture v2 keeps them as extension points: E1, device telemetry ingest, if a kit has networked electronics, and E2, an AI question assistant, if the team brings it back (ARCHITECTURE.md section 12). The decision rests on assumption A1, that the arm kit has no Wi-Fi board and no AI assistant, which is unconfirmed ([README](README.md#assumptions-unconfirmed)).

## Decision

Neither is built in v1. See extension points E1 and E2 in `ARCHITECTURE.md`.

## Consequences

- Neither device telemetry nor an AI assistant is built in v1. This decision is revisited only if p0-open-decisions (jade-6is) answers yes to networked electronics or an AI assistant for the arm kit (jade-6is acceptance). Assumption A1 says that in that case E1 and/or E2 are built and a phase is added after Phase 6 ([README](README.md#assumptions-unconfirmed)).
