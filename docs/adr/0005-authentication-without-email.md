# 0005. Authentication without email

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-05
- Related: [0020](0020-rate-limit-keys-for-redemption-and-signup.md)

## Context

v1 signed adults in by emailed magic link, which needs a mail provider (another vendor holding adult emails) and depends on school mail filters delivering a link in the first five minutes of a lesson (REVIEW.md finding 9). In v2 there is no open registration and no email service; for the two pilots the adults are the team's own facilitators and one teacher, so staff-assisted password reset is enough (ARCHITECTURE.md section 5). Students join with a class join code and a kit number and receive a device-session cookie bound to class and kit (ARCHITECTURE.md section 5).

## Decision

Adults: email + password, argon2id, server-side sessions. Signup requires a valid unused kit code or a staff invite. Password reset is a staff action. Students: class join code plus kit selection, yielding a device-session cookie bound to class and kit. No accounts for children.

## Consequences

- p3-adult-auth (jade-vcy) builds code-gated signup, login, sessions and the staff role; p3-invites (jade-9tk) builds staff invites; p3-join (jade-5nj) builds the student join flow and device session (bead titles and descriptions).
- Email-based password reset is deferred to extension point E4 (ARCHITECTURE.md sections 5 and 12). If many outside adults need accounts, assumption A5 says to bring E4 forward ([README](README.md#assumptions-unconfirmed)).
- The rate-limit keys for code redemption and code-gated signup are in [0020](0020-rate-limit-keys-for-redemption-and-signup.md).
