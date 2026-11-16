# Privacy design

This describes what the platform is built to do. It is not legal advice. The consent form, the school board research application and any pre-launch legal review need a person to check them against this document (`p0-consent`). Phase 9 (`p9-privacy-doc`) rewrites this file against what was actually built.

> Amended 2026-11-14 by [ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md), [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md), [ADR 0020](../adr/0020-rate-limit-keys-for-redemption-and-signup.md) and [ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md); [ADR 0019](../adr/0019-participant-letters-a-to-d.md) confirms "A to D". The handoff text is in git commit 079e846 and jade-handoff.zip.
>
> Amended 2026-11-16 by [ADR 0025](../adr/0025-youtube-embedded-module-video.md): module videos play from YouTube ("Data inventory", "Consent and opt-out", "Where it runs", "Sentences the consent form can borrow").

## Who the data is about

| Person | What the system holds |
|---|---|
| Child | Nothing that identifies them. Their group's kit has an anonymous ID. If a quiz is entered, a participant letter (A to D) assigned on paper in class |
| Facilitator, teacher, parent | Email, optional display name, password hash |
| Team | Staff accounts, same as above |

## Data inventory

| Data | Where | Stored when | Who can see it |
|---|---|---|---|
| Adult email, password hash | `users` | Account creation | The adult; staff |
| Kit activity events | `events` | Only while logging is on for that kit | Staff. Owner of the class sees progress and stuck state, not raw events |
| Step progress | Device (always); `kit_progress` (logging on) | | The group's device; class owner; staff |
| Live stuck alerts for kits with logging off (whether kits with logging on use the same store is open) | App memory, per class | From "I'm stuck" until resolved or the session closes; never written to the database or logs ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)) | Class owner; staff |
| Facilitator notes | `facilitator_notes` | When an adult writes one | Class owner; staff |
| Quiz and exit-card entries | `quiz_responses`, `exit_cards` | When an adult enters them, logging on | Class owner; staff |
| Audit trail | `audit_log` | Staff and consent actions | Staff |
| Server logs | VM disk, 14 days | Every request | Staff with server access. No IPs, emails, codes, tokens or bodies |
| Backups | Encrypted, Canadian object storage, 30 days | Nightly | Whoever holds the backup key (team) |

Not collected by JADE at all: child names, photos, audio, free text from students, IP addresses, location, device identifiers, advertising identifiers, third-party cookies. The one other company a student's device talks to is YouTube, when a step shows a video (see "Where it runs").

An optional per-IP limit on code-gated signup holds IP addresses in memory only. It is off by default, and IP addresses are never stored or logged ([ADR 0020](../adr/0020-rate-limit-keys-for-redemption-and-signup.md)).

## Consent and opt-out

- Logging is off for every kit until an adult confirms that consent is in hand for each child in that group. The confirmation records who and when.
- A group without consent takes part fully. Their tablet shows the same steps and videos. Nothing about what they do is stored on JADE's server.
- For such a group, "I'm stuck" still alerts the facilitator in the moment. The alert is held in the server's memory only, until it is resolved or the session closes, and is never stored or logged ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)).
- Consent withdrawn later: the facilitator switches logging off (collection stops at once) and staff run the kit deletion, which removes everything recorded for that kit.
- Because consent is per group, one child without consent means the whole group is not logged. Facilitators should group children accordingly, or accept the smaller sample.

## Retention

Retention is tiered ([ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md)). When `RETENTION_MONTHS` (default 12, configurable; confirm against the research approval) have passed since the class ended: raw events are replaced by per-step aggregates that contain no kit IDs; step progress and device sessions are deleted; facilitator notes are kept, no longer linked to a kit; quiz and exit-card entries are reduced to per-question and per-module counts with no kit IDs, then deleted. The job that does this ships after launch and runs in production before the first class reaches that date ([ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md)). Adult accounts are deleted on request.

## Where it runs

One VM and one object-storage bucket, both in Canada. Apart from module videos, no student traffic goes to any other company: no analytics service, no font or script CDN, no error tracker in the browser.

Module videos are the one exception ([ADR 0025](../adr/0025-youtube-embedded-module-video.md)):

- The videos are hosted on YouTube and play in YouTube's player inside the step, in YouTube's privacy-enhanced mode.
- When a step with a video loads, the student's device connects to YouTube (Google). YouTube receives the device's network address and standard browser information, such as the browser type and version. This happens whether or not logging is on for the kit: the consent switch controls what JADE stores, not what a video player receives.
- Privacy-enhanced mode means YouTube sets no cookies before a video is played. Once a video plays, YouTube may store information in the browser.
- The videos are unlisted: they do not appear in YouTube search, but anyone with a video's link can watch it. A video's link is the same for every kit and identifies no child or kit.
- The videos are marked "made for kids", so YouTube shows no personalised ads and no comments on them.
- What YouTube does with what it receives is set by YouTube's and Google's own terms and privacy policy, not by this document. JADE does not choose where YouTube's servers are.
- JADE itself stores nothing new because of this.
- School networks must allow YouTube for the videos to play.

## Laws the team should check with a person qualified to say

- **PIPEDA** (Canada) and Ontario's education privacy rules as applied by the specific school board. School boards often have their own vendor and research requirements beyond the statute.
- **COPPA** (United States), only if kits are later sold there. Persistent identifiers can count as personal information under COPPA even without a name; whether kit-level IDs used only for improving the product fall within its exceptions is a question for counsel, not for this document.

## Sentences the consent form can borrow

> The kit's online guide can record how each group uses it: which steps they open, how long steps take, when they press "I'm stuck", and their answers to short check questions. This is recorded against the kit's number only. We do not collect your child's name, photo, voice or any writing. Recording is switched on for a group only when every child in it has permission. If you say no, your child still takes part in everything and nothing about their group is recorded. You can ask us to delete your child's group's records at any time.

> The guide's videos play from YouTube, inside the guide, in YouTube's privacy-enhanced mode. When a video loads, YouTube (owned by Google) receives the device's internet address and basic browser information. The videos are marked as made for kids, so they show no personalised ads and no comments. We do not send YouTube your child's name or anything we record about the group.
