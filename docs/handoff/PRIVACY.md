# Privacy design

This describes what the platform is built to do. It is not legal advice. The consent form, the school board research application and any pre-launch legal review need a person to check them against this document (`p0-consent`). Phase 9 (`p9-privacy-doc`) rewrites this file against what was actually built.

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
| Facilitator notes | `facilitator_notes` | When an adult writes one | Class owner; staff |
| Quiz and exit-card entries | `quiz_responses`, `exit_cards` | When an adult enters them, logging on | Class owner; staff |
| Audit trail | `audit_log` | Staff and consent actions | Staff |
| Server logs | VM disk, 14 days | Every request | Staff with server access. No IPs, emails, codes, tokens or bodies |
| Backups | Encrypted, Canadian object storage, 30 days | Nightly | Whoever holds the backup key (team) |

Not collected at all: child names, photos, audio, free text from students, IP addresses, location, device identifiers, advertising identifiers, third-party cookies.

## Consent and opt-out

- Logging is off for every kit until an adult confirms that consent is in hand for each child in that group. The confirmation records who and when.
- A group without consent takes part fully. Their tablet shows the same steps and videos. Nothing about what they do is stored on the server.
- Consent withdrawn later: the facilitator switches logging off (collection stops at once) and staff run the kit deletion, which removes everything recorded for that kit.
- Because consent is per group, one child without consent means the whole group is not logged. Facilitators should group children accordingly, or accept the smaller sample.

## Retention

Raw events are kept until 12 months after the class ends (configurable; confirm against the research approval), then replaced by per-step aggregates that contain no kit IDs. Adult accounts are deleted on request.

## Where it runs

One VM and one object-storage bucket, both in Canada. No student traffic goes to any other company: no analytics service, no video platform, no font or script CDN, no error tracker in the browser.

## Laws the team should check with a person qualified to say

- **PIPEDA** (Canada) and Ontario's education privacy rules as applied by the specific school board. School boards often have their own vendor and research requirements beyond the statute.
- **COPPA** (United States), only if kits are later sold there. Persistent identifiers can count as personal information under COPPA even without a name; whether kit-level IDs used only for improving the product fall within its exceptions is a question for counsel, not for this document.

## Sentences the consent form can borrow

> The kit's online guide can record how each group uses it: which steps they open, how long steps take, when they press "I'm stuck", and their answers to short check questions. This is recorded against the kit's number only. We do not collect your child's name, photo, voice or any writing. Recording is switched on for a group only when every child in it has permission. If you say no, your child still takes part in everything and nothing about their group is recorded. You can ask us to delete your child's group's records at any time.
