# Architecture review: v1 (2026-10-25) to v2 (2026-11-14)

v1 was written for the Pickney seed incubator. Since then the project pivoted to a DIY mechanical arm kit with the same age range and pilot dates. This review covers both the pivot fallout and problems v1 had regardless.

Severity: **High** = would produce wrong data, a privacy gap or a missed pilot. **Medium** = avoidable cost or risk. **Low** = cleanup.

## Findings and changes

| # | Sev | v1 said | Problem | v2 change |
|---|---|---|---|---|
| 1 | High | Platform is "Pickney": `PKN` prefix, `kit02` IDs, 8 named modules, device sync, AI proxy | All incubator-specific. Device sync and AI proxy were two of the five backend services and the arm kit (knobs and joystick) has no stated need for either | Platform is kit-agnostic: a kit is a table row plus a content folder. Device ingest and AI proxy are removed from v1 and kept as extension points E1 and E2 |
| 2 | High | Events carry a server-set `ts` only | With an offline queue, events from a 40-minute session all arrive stamped with the moment Wi-Fi came back. Time-on-step, the main redesign metric, would be garbage | Client-assigned `client_ts` plus server `received_at`; clock-skew clamping and flagging |
| 3 | High | Offline queue, no deduplication described | A retried batch double-counts stuck presses and completions | Client-assigned UUIDv7 `event_id`, idempotent insert |
| 4 | High | `code_hash` = SHA-256 of the code | A code has 40 bits of entropy. Anyone with a copy of the table can brute-force every code in hours | HMAC-SHA256 with a server-side pepper, plus a pepper backup procedure |
| 5 | High | Consent handled by form wording only | No mechanism for a group whose parents did not consent. Either they are excluded from the activity or they are logged anyway | Per-kit `logging_enabled`, default off; no-log mode stores nothing; a required CI test proves it |
| 6 | High | Kit ID and seat sent with events | Identity in the payload means any tablet can write events for any kit | Class and kit come from the device session; payload identity is ignored |
| 7 | Medium | Every event carries seat A/B/C | Two or three children share one tablet. Seat-level attribution of taps is fiction and adds per-child data for no analytical gain | Events are per kit. A participant letter exists only on quiz and exit-card entries, where it is real |
| 8 | Medium | Student "picks kit number", device "remembers the seat" | Unspecified. Join codes never expired; nothing stopped a group joining as the wrong kit | Device-session cookie bound to class + kit; join code valid only while a session is open; facilitator can rotate the code and reset a kit's devices |
| 9 | Medium | Adult sign-in by emailed magic link | Needs a mail provider (another vendor holding adult emails) and depends on school mail filters delivering a link in the first five minutes of a lesson | Email + password, signup gated by a kit code or staff invite, staff-assisted reset. No mail service in v1 |
| 10 | Medium | Separate API service, CMS, third-party video host, staff analytics app | Four deployables and two vendors for one developer with five weeks | One SvelteKit app, one Postgres, Caddy. Video is self-hosted on the same origin |
| 11 | Medium | Privacy-focused third-party video host | Extra vendor in the student data path and a second domain for school IT to allowlist | Same-origin MP4 with signed URLs; one domain to allowlist |
| 12 | Medium | Git-backed CMS (Decap or Keystatic) in v1 | Adds an auth integration and its own failure modes before a single step is written | Markdown in the repo, edited in the GitHub web editor, with an authoring guide and preview. CMS is extension E3 |
| 13 | Medium | "Every step carries a content_version" | Nothing enforced it. One un-bumped edit and v1/v2 comparisons are silently wrong | `content.lock.json` with a hash per `id@version`; CI fails on a changed step without a bump |
| 14 | Medium | `active_time` = seconds on screen and in focus | A group reads the step, then builds for ten minutes with the tablet lit. "On screen" measures build time plus idle time, not confusion | Active time counts only while visible and interacted with in the last 60 s; build time is the gap between view and complete |
| 15 | Medium | Thresholds as percentages (stuck rate above 25%) | With 12 to 15 kits, one group moves a rate by 7 to 8 points | Every rate shown with counts; friction used as a rank for attention only |
| 16 | Medium | Stuck button records a reason | No record of how or when the group got unstuck | `stuck_resolved` event with outcome and elapsed time |
| 17 | Medium | "Hardware link" metric from device fault logs | No device logs after the pivot | Stuck reason "it doesn't work" plus facilitator note issue type `hardware` |
| 18 | Medium | Deploy at the end (December week 3 load test) | First contact with the host, TLS, the school network and backups would all happen in the last week | Staging live in Phase 1 and deployed on every merge; school network test as soon as the student flow exists; restore drill before launch |
| 19 | Medium | No backups, monitoring or rollback described | Pilot data is not reproducible. Losing it loses the pilot | Encrypted nightly backups with a restore drill, uptime and error alerts, health-gated releases with rollback |
| 20 | Medium | Rate limits unspecified | A classroom shares one public IP. Naive per-IP limits lock out the whole class at the join screen | Join and ingest limits are per device or class; login and redeem per account |
| 21 | Low | Printed-step QR codes point at the step | If the QR encodes a versioned URL it goes stale when the step is revised | Stable `/s/<step_id>` short link |
| 22 | Low | A/B variants designed in | Meaningless at this sample size and it complicates the player | One nullable column reserved; nothing built |
| 23 | Low | No IP addresses "stored with events" | Reverse-proxy access logs would still hold them | Caddy and app logging configured and tested to hold no IPs |
| 24 | Low | All dashboards before Pilot 1 | Only verification and export are needed in January; the heatmap is needed in February | Data-quality report and export are launch-blocking; dashboards are labelled `post-launch-ok` |

## What v1 got right and v2 keeps

- Adults hold accounts, children do not.
- One code per kit, mapped to a lifelong anonymous kit ID.
- Steps as the unit of content and of analysis, with permanent IDs and versions.
- First-party analytics only, data in Canada.
- The printed guide works without the platform.
- The redesign loop: rank steps, diagnose, revise, compare versions.

## Things this review could not settle

These need a person. They are in `DECISIONS.md` and seeded as `human` beads.

1. The kit's name and code prefix.
2. The arm kit's module and step outline.
3. Whether the arm has any networked electronics (v2 assumes none).
4. Which devices the pilot site has, and whether they keep cookies between sessions.
5. Whether the consent form and research application, written before the pivot and before this platform, cover it.
6. Whether mid-December is still the freeze date. The phase plan assumes it is.
7. The retention period the research approval requires.

## Timeline reality check

v1's build plan started in the first week of November. It is now 14 November. Assuming a freeze around 18 December, that is five weeks for Phases 0 to 7, 9 and 10. It fits only because of the cuts above (no mail, no CMS, no video vendor, no device sync, no AI proxy, dashboards deferred). If more time is lost, cut in this order: `p4-print`, `p5-entitlement`, `p7-guide`, `p5-pwa` video pre-download, `p7-quiz` (fall back to a spreadsheet).
