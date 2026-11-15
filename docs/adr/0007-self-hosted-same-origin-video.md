# 0007. Self-hosted, same-origin video

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-07
- Related: [0013](0013-no-third-party-requests-from-the-browser.md)

## Context

v1 used a privacy-focused third-party video host, which adds a vendor in the student data path and a second domain for school IT to allowlist (REVIEW.md finding 11). In v2 Caddy serves `/media` with Range requests from a media volume, and media is served same-origin through short-lived signed URLs (ARCHITECTURE.md section 4). "Sharing a video URL" is an abuse case whose mitigation is that media URLs are signed and short-lived (ARCHITECTURE.md section 9).

## Decision

H.264/AAC MP4 at 720p with faststart, on a volume served by Caddy with Range support, behind short-lived signed URLs. No third-party video host.

## Consequences

- p4-video (jade-u8z) builds the transcode script, the `/media` storage layout and same-origin serving; its acceptance requires unsigned or expired media URLs to return 403.
- Same origin means one domain for school IT to allowlist (jade-u8z description); the pilot site's allowlist process and lead time stay open until p0-school-it (jade-tw4) records them (jade-tw4 acceptance).
- No third-party requests from the browser is [0013](0013-no-third-party-requests-from-the-browser.md).
