# Phase 2: Data model and kit codes

**Goal.** The tables everything hangs off, and the kit code lifecycle: generate, print, redeem once, revoke.

## Exit criteria

- [ ] Core schema migrated on staging
- [ ] A batch of codes can be generated, printed as cards, and redeemed exactly once
- [ ] Plain codes exist only on the printed sheet and the packing CSV, never in the database

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p2-schema-core` | P0 | task | Core schema: products, kits, code batches, kit codes, users, sessions, classes, class kits, device sessions, audit log | `p1-db` | db |
| `p2-code-lib` | P0 | task | Kit code library: generate, normalise, validate, HMAC | `p1-config` | codes, security |
| `p2-redeem` | P0 | task | Redemption service: single use, transactional, rate limited, audited | `p2-schema-core`, `p2-code-lib` | codes, security |
| `p2-code-cli` | P1 | task | Batch generator CLI with printable code cards and packing CSV | `p2-schema-core`, `p2-code-lib` | codes, tooling |
| `p2-staff-codes` | P2 | task | Staff screen: batches, code status, revoke and reissue, move kit between classes | `p2-redeem`, `p3-adult-auth` | codes, staff-ui |
| `p2-seed` | P2 | task | Development seed data | `p2-schema-core` | tooling |

### `p2-schema-core` Core schema: products, kits, code batches, kit codes, users, sessions, classes, class kits, device sessions, audit log

Implement the tables in docs/handoff/DATA-MODEL.md sections 1 to 3 as Drizzle schema plus SQL migrations, with the constraints and indexes listed there. Kits are product-agnostic: nothing in the schema names a specific kit.

Acceptance:

- Migrations apply cleanly on an empty database and on staging
- Constraints from DATA-MODEL.md are enforced (tests insert violating rows and expect failure)
- No column stores a plain kit code or plain join-session token

### `p2-code-lib` Kit code library: generate, normalise, validate, HMAC

Format PREFIX-XXXX-XXXX-C: 3-letter product prefix, 8 random Crockford Base32 characters from a CSPRNG, 1 check character. Normalise input (case, spaces, dashes, O to 0, I and L to 1). Lookup key is HMAC-SHA256(CODE_PEPPER, normalised code). Plain SHA-256 is not acceptable: 40 bits of entropy is brute-forceable from a leaked table.

Acceptance:

- Property tests: generate then validate round-trips; single-character typos are rejected by the check character
- Normalisation accepts lower case, missing dashes and O/I/L confusions
- HMAC uses the pepper from config and constant-time comparison

### `p2-redeem` Redemption service: single use, transactional, rate limited, audited

redeemCode(user, code, classId?) in one transaction with row lock: unused becomes redeemed, kit attached to class. Reject revoked and already-redeemed codes with distinct, non-leaky messages. Rate limit per account and per IP (IP held in memory only). Write an audit row.

Acceptance:

- Concurrent redemption of the same code succeeds exactly once (test with parallel transactions)
- Ten failed attempts in an hour locks further attempts for that account
- Audit log records who redeemed which kit and when, never the code

### `p2-code-cli` Batch generator CLI with printable code cards and packing CSV

`pnpm codes:generate --product <slug> --batch <label> --count <n>` creates kits and code rows, and writes two files outside the repo: packing CSV (kit number, code) and a printable A4/Letter sheet of code cards with the code in large type plus a QR that opens /redeem?code=... The plain codes are shown once and never stored.

Acceptance:

- Running the CLI twice with the same batch label fails instead of duplicating
- Printed sheet is legible in greyscale and each QR scans on a phone
- Output directory is gitignored and the CLI warns that the files are the only copy

### `p2-staff-codes` Staff screen: batches, code status, revoke and reissue, move kit between classes

Staff-only pages listing batches and per-kit status. Actions: revoke a code, reissue a new code for the same kit (prints once), detach a kit from a class and attach to another keeping its kit id so history carries across pilots.

Acceptance:

- Non-staff users get 404 on every staff route
- Reissue keeps kit_id and invalidates the old code
- Every action writes an audit row

### `p2-seed` Development seed data

`pnpm db:seed` creates a demo product, a batch of 15 kits with known dev codes, a staff user, a facilitator, and a class. Dev-only; refuses to run when NODE_ENV=production.

Acceptance:

- Fresh clone to a usable local app in under 5 minutes following the README
- Seed refuses to run in production
