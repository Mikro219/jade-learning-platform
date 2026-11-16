# 0013. No third-party requests from the browser

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-13
- Related: [0007](0007-self-hosted-same-origin-video.md), [0025](0025-youtube-embedded-module-video.md)

Amended 2026-11-16 by [0025](0025-youtube-embedded-module-video.md): on pages that show a module video, the embedded YouTube player's origins are allowed. Nothing else in this decision changes.

## Context

Design principle 5 is "One deployable, one database, one origin", with no third-party scripts and one domain for a school to allowlist (ARCHITECTURE.md section 2). Among the other security commitments are a strict CSP with no third-party origins and no analytics or font CDNs (ARCHITECTURE.md section 9).

## Decision

No analytics, fonts, CDNs, embeds or error trackers that load in the user's browser. CSP enforces it and an e2e test asserts it.

## Consequences

- p9-headers (jade-c42) sets a CSP of `default-src 'self'`; its acceptance requires no CSP violations in the console during e2e runs.
- CLAUDE.md rule 5: no request from the browser to any origin but our own, and no third-party scripts, fonts, analytics or embeds.
- Same-origin video is [0007](0007-self-hosted-same-origin-video.md), superseded by [0025](0025-youtube-embedded-module-video.md).
