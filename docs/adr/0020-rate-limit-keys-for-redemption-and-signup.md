# 0020. Rate-limit keys for code redemption and code-gated signup

- Status: accepted
- Date: 2026-11-14
- Source: bead jade-8n2.5, close reason (Mike, 2026-11-14)
- Related: [0005](0005-authentication-without-email.md), [0011](0011-kit-code-format-and-storage.md)

## Context

REVIEW.md finding 20 and ARCHITECTURE.md section 9 say login and redeem are limited per account, while p2-redeem said "Rate limit per account and per IP (IP held in memory only)" and locks the account after ten failures an hour (jade-8n2.5 description). Signup also takes a kit code (p3-adult-auth), but before signup there is no account to limit, so per-account limits cannot protect signup-time code guessing (jade-8n2.5 description). A per-IP limit is what REVIEW.md finding 20 warns about: a classroom shares one public IP, and naive per-IP limits lock out the whole class (REVIEW.md finding 20; jade-8n2.5 description).

## Decision

Decided (Mike, 2026-11-14): global throttle for now; per-IP signup limit kept as a toggle (config flag, off by default) for later. Redeem stays per account.

Acceptance criteria this decision added:

- jade-7if: Failed redemptions limited per account (10 an hour, then locked) plus a global failed-code throttle; no per-IP limit (jade-8n2.5). Replaces 'per account and per IP' in the description
- jade-vcy: Code-gated signup is protected by the global failed-code throttle. A per-IP limit (IP held in memory only) exists behind a config flag, off by default (jade-8n2.5)
- jade-6cq: Limits tested with the per-IP signup flag off (default) and on; the global throttle cuts off code guessing (jade-8n2.5)

## Consequences

- p2-redeem (jade-7if) limits failed redemptions per account (10 an hour, then locked) plus a global failed-code throttle, with no per-IP limit; p3-adult-auth (jade-vcy) protects code-gated signup with the global throttle and puts a per-IP limit behind a config flag, off by default; p9-ratelimit (jade-6cq) tests the limits with the flag off and on (bead acceptance).
- Corrected in place: PRIVACY.md "Data inventory" gains a sentence on the optional per-IP signup limit, which holds IP addresses in memory only ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The ARCHITECTURE.md section 9 row "Guessing kit codes online" names only the per-account limit; it is not edited ([README amendment map](README.md#amendments-to-the-handoff-documents)). The generated `phase-02` p2-redeem text still says "Rate limit per account and per IP" ([README amendment map](README.md#amendments-to-the-handoff-documents)).
- The global throttle is shared by everyone, so anyone submitting wrong codes can delay legitimate redemption and signup for everyone. The threat model written by p0-threat (jade-okb) records this lockout risk.
- The sources do not say how the per-account redeem limit and the global throttle interact.
