# 0025. Module videos play from YouTube in an embedded player

- Status: accepted
- Date: 2026-11-16
- Source: bead jade-d48 (Mike and Given, 2026-11-16)
- Related: [0007](0007-self-hosted-same-origin-video.md) (superseded), [0013](0013-no-third-party-requests-from-the-browser.md) (amended), [0009](0009-consent-gated-logging.md)

## Context

ADR 0007 decided self-hosted MP4 on a Caddy media volume, served same-origin behind short-lived signed URLs, with no third-party video host. ADR 0013 and CLAUDE.md rule 5 forbid any browser request to another origin and any third-party embed. On 2026-11-16 Mike said that module video will be uploaded to YouTube, a decision made by Mike and Given (jade-d48 description). That conflicts with ADR 0007, ADR 0013, CLAUDE.md rule 5 and `docs/handoff/PRIVACY.md` "Where it runs" ("no video platform"). It also conflicts with work built on them: the e2e off-origin test (INV3, `tests/e2e/no-offorigin.spec.ts`), the Caddy `/media` gate in `deploy/caddy/Caddyfile`, and the p4-video (jade-u8z) acceptance that unsigned or expired media URLs return 403 (jade-d48 description). Given manages the pilot school, and its network does not block YouTube.

## Decision

Decided (Mike and Given, 2026-11-16):

- Module videos are hosted on YouTube. Students watch them in an embedded YouTube player on the student pages.
- The videos are unlisted and marked "made for kids".
- Anyone with a video's link may watch it. Kit codes no longer gate video.

Scope of the exception to ADR 0013 and CLAUDE.md rule 5:

- The one allowed exception is the YouTube embed player's origins, and only on pages that show a module video.
- Everything else in ADR 0013 stays: no third-party scripts, fonts, analytics, error trackers or other embeds. No page without a module video makes any request to another origin.

Confirmed by Mike, 2026-11-16: the embed origin is YouTube's privacy-enhanced mode, `https://www.youtube-nocookie.com/embed/<video id>`, not `www.youtube.com`.

## Consequences

- **What Google receives.** When the player loads, the student device connects to YouTube (Google). Google receives the device's network address and standard request metadata: the user agent, and the referrer to the extent the page's referrer policy sends one. Privacy-enhanced mode does not set cookies before the video is played. It does not prevent all storage in the browser after playback starts. What Google does with this data is set by YouTube's and Google's own terms and privacy policy, not by JADE. This ADR makes no claim about it.
- **The consent switch does not cover it.** The request to YouTube happens whenever a video page loads, whatever the kit's `logging_enabled` state. JADE's own storage does not change: with logging off the server stores nothing about the kit's activity (ADR 0009; CLAUDE.md rule 2; p6-nolog-invariant jade-hhp), and JADE never stores or logs IP addresses (CLAUDE.md rule 4).
- **"Made for kids".** YouTube turns off personalised ads and comments on the video.
- **Unlisted.** The video does not appear in YouTube search, but anyone with the link can watch it. ADR 0007's signed short-lived URLs and per-kit entitlement no longer apply to video. Sharing a video link is allowed by design (`docs/threat-model.md` AB6).
- **School networks.** School IT must allow YouTube and the player's origins. For the pilot this is Given's responsibility. Allowlisting at other sites stays part of p0-school-it (jade-tw4).
- **Phase 4.** p4-video (jade-u8z) is rescoped. Its transcode script and same-origin video serving go, and so does its acceptance that unsigned or expired media URLs return 403 for video. What the Caddy `/media` gate becomes (closed, removed, or kept for images) is open.
- **Phase 9.** p9-headers (jade-c42): the CSP `frame-src` allows the embed origin only, and `default-src 'self'` stays for everything else. Whether the iframe needs its own `referrerpolicy` for the player to work under the site-wide `Referrer-Policy: no-referrer` is open.
- **INV3 tests.** The e2e off-origin test (`tests/e2e/no-offorigin.spec.ts`) and its static half (`tests/unit/no-external-refs.test.ts`) get an allowlist limited to the embed origins, on video pages only. That is future work and is not done in this change. The player itself loads further Google origins inside its frame. Which of those the e2e test must allow is open.
- **Offline or blocked networks.** A video that cannot load must not block the step: the rest of the step still shows, and Done and Next still work. The fallback shown in place of the video is open.
- **Video events.** The EVENTS.md video events (`video_play`, `video_pause`, `video_seek`, `video_ended`, `video_ranges`) and the "video playback" input to active time come from p6-video-events (jade-iwr). Reading playback state from the YouTube player without loading YouTube's script into our page is open, and ADR 0013 still forbids that script.
- ADR 0007 is superseded by this ADR. ADR 0013's Decision stands except for the exception above; a note in it points here. CLAUDE.md rule 5 names the exception and points here.
