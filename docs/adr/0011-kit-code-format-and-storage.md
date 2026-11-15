# 0011. Kit code format and storage

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-11
- Related: [0020](0020-rate-limit-keys-for-redemption-and-signup.md), [0021](0021-split-human-and-agent-work.md)

## Context

v1 stored `code_hash` as SHA-256 of the code; a code has 40 bits of entropy, so anyone with a copy of the table could brute-force every code in hours (REVIEW.md finding 4). Eight Crockford Base32 characters defeat online guessing behind a rate limit but not offline brute force of a leaked table of plain hashes, which is why the database stores `HMAC-SHA256(pepper, code)` (ARCHITECTURE.md section 6). A code maps to a lifelong `kit_id`, and redemption is single-use, transactional and audited (ARCHITECTURE.md section 6).

## Decision

`PREFIX-XXXX-XXXX-C`, Crockford Base32, CSPRNG, check character. Stored as HMAC-SHA256 under a server-side pepper. Plain codes exist only on print and in an offline CSV.

## Consequences

- p2-code-lib (jade-fd5) generates, normalises, validates and HMACs codes; p2-code-cli (jade-99j) writes the printable cards and the packing CSV; p2-redeem (jade-7if) redeems codes once, transactionally, with an audit row (bead titles and descriptions).
- Pepper handling: p1-config (jade-8v4) reads `CODE_PEPPER` from config with no production default (jade-8v4 description); jade-lnn.1 (agent) scripts its generation on the server, and p10-secrets (jade-fgs, human) runs that on production and stores `CODE_PEPPER` in two offline places (jade-lnn.1 description; jade-fgs notes; split by [0021](0021-split-human-and-agent-work.md)).
- CLAUDE.md rule 4: plain kit codes, join codes and tokens are never stored or logged.
- Losing the pepper invalidates every printed code (ARCHITECTURE.md section 6).
- Each card's QR opens `/redeem?code=...` (p2-code-cli jade-99j description), so the plain code also travels in a URL, into the adult device's browser history and the request line. The Decision's "Plain codes exist only on print and in an offline CSV" does not cover this. The conflict is open; this ADR does not settle it, and the threat model written by p0-threat (jade-okb) records it.
- Rate-limit keys for redemption are [0020](0020-rate-limit-keys-for-redemption-and-signup.md).
