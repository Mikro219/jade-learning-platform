# Phase 9: Privacy, security and hardening

**Goal.** Make the promises in the consent form true and testable, and make sure fifteen tablets streaming video in one room do not take the site down.

## Exit criteria

- [ ] Deletion, retention and no-log behaviour are covered by tests
- [ ] Security headers and rate limits verified on staging
- [ ] Load test passed at twice the pilot size

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p9-delete` | P0 | task | Kit data deletion | `p6-table`, `p7-notes`, `p7-quiz` | privacy |
| `p9-retention` | P1 | task | Retention job | `p8-views`, `p9-delete` | privacy |
| `p9-headers` | P0 | task | Security headers, cookies and CSRF | `p3-join` | security |
| `p9-ratelimit` | P0 | task | Rate limiting and lockout review | `p3-join`, `p2-redeem`, `p6-ingest` | security |
| `p9-logs` | P0 | task | Log and PII audit | `p1-observability`, `p1-docker` | privacy, security |
| `p9-authz-sweep` | P1 | task | Abuse-case sweep against the threat model | `p3-authz-tests`, `p6-ingest`, `p7-quiz`, `p8-export`, `p0-threat` | security, tests |
| `p9-deps` | P2 | task | Dependency audit and pinned images | `p1-docker` | security |
| `p9-load` | P0 | task | Load test at twice pilot size | `p6-instrument`, `p4-video`, `p1-staging` | infra, tests |
| `p9-privacy-doc` | P0 | task | Final privacy documentation and consent appendix | `p6-catalog`, `p9-delete`, `p9-retention`, `p9-logs` | privacy, docs |

### `p9-delete` Kit data deletion

Staff action: delete all activity data for a kit (events, progress, notes, quiz, exit cards) in one transaction. Record an audit row with counts only. This is how a parent withdrawal is honoured.

Acceptance:

- After deletion no table contains the kit's activity rows (test enumerates all tables with a kit_id column)
- Deletion is idempotent and audited

### `p9-retention` Retention job

Scheduled job that, after the configured period, replaces raw events with per-step aggregates. Period comes from config (default 12 months after class end, to be confirmed against the research approval). Supports dry run.

Acceptance:

- Dry run reports what would be removed
- Aggregates are preserved after raw rows are removed

### `p9-headers` Security headers, cookies and CSRF

CSP default-src 'self' with no inline script, HSTS, Referrer-Policy no-referrer, Permissions-Policy denying camera/mic/geolocation (except camera on the adult QR-scan page if used), X-Content-Type-Options. CSRF protection on all state-changing requests.

Acceptance:

- Playwright asserts headers on every route group
- No CSP violations in the console during e2e runs

### `p9-ratelimit` Rate limiting and lockout review

Review and test limits for login, signup, redeem, join and ingest. A whole classroom shares one public IP, so join and ingest limits are per device session or per class, not per IP. IPs are used in memory only and never written to disk.

Acceptance:

- 30 devices joining within one minute from one IP all succeed
- Brute-forcing join codes from one device is cut off well before the expected number of guesses

### `p9-logs` Log and PII audit

Verify end to end on staging: Caddy stores no client IPs, app logs contain no emails, codes, tokens or bodies, database has no IP columns. Document log retention (14 days).

Acceptance:

- Grep of staging logs after a full e2e run finds no IPs, emails or codes
- Log retention configured and documented

### `p9-authz-sweep` Abuse-case sweep against the threat model

Walk every abuse case in docs/threat-model.md and add a test or a documented manual check: join-code guessing, kit-code brute force, event spoofing for another kit, media URL sharing, student reaching adult or staff pages, facilitator reaching another class.

Acceptance:

- Each abuse case links to a passing test or a signed-off manual check

### `p9-deps` Dependency audit and pinned images

pnpm audit clean or exceptions documented, Docker base images pinned by digest, Dependabot or Renovate enabled, lockfile committed.

Acceptance:

- No high or critical advisories without a written exception

### `p9-load` Load test at twice pilot size

k6 (or similar) scenario on staging: 30 devices joining within a minute, stepping through a module, sending events and each streaming a 720p video. Record CPU, memory, bandwidth and p95 latency; size the production VM from the result.

Acceptance:

- p95 page response under 500 ms and no errors at 30 devices
- Capacity note committed with the chosen production VM size and expected monthly bandwidth

### `p9-privacy-doc` Final privacy documentation and consent appendix

Finalize docs/PRIVACY.md from the handoff version against what was actually built: data inventory, where it is stored, who can see it, retention, deletion. Produce a one-page plain-language appendix with the generated event list for the consent form and research application.

Acceptance:

- Every table and log is in the data inventory
- Appendix is readable by a parent (no jargon) and matches the generated event catalog
