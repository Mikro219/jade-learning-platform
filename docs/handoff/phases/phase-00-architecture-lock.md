# Phase 0: Architecture lock

**Goal.** Freeze the decisions the build depends on, and start the slow human-side items (host, school IT, consent wording) on day one because they have lead times the code does not.

## Exit criteria

- [ ] ADRs committed under docs/adr/ and referenced from CLAUDE.md
- [ ] Threat model and data-flow doc committed
- [ ] Host chosen, domain bought, pilot-site IT contacted, consent wording under review (human beads closed or explicitly deferred with a date)

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p0-adr` | P0 | task | Commit ADRs from the handoff decisions | none | docs |
| `p0-threat` | P1 | task | Write threat model and data-flow document | `p0-adr` | docs, security |
| `p0-open-decisions` | P0 | decision | HUMAN: answer the open product questions | none | human |
| `p0-host` | P0 | task | HUMAN: choose Canadian host, create account, buy domain | none | human, infra |
| `p0-school-it` | P0 | task | HUMAN: contact pilot-site IT about devices and network | none | human, pilot |
| `p0-consent` | P0 | task | HUMAN: update consent form and research application for the platform | none | human, privacy, pilot |

### `p0-adr` Commit ADRs from the handoff decisions

Turn each ADR in docs/handoff/DECISIONS.md into its own file under docs/adr/NNNN-title.md (status: accepted). Do not change the decisions. If one looks wrong, file a `decision` bead and stop instead of silently deviating.

Acceptance:

- One file per ADR, numbered, each with Context / Decision / Consequences
- docs/adr/README.md indexes them
- CLAUDE.md links to docs/adr/ and docs/handoff/ARCHITECTURE.md

### `p0-threat` Write threat model and data-flow document

Write docs/threat-model.md: actors (student device, facilitator, staff, outsider on school Wi-Fi, outsider on internet), assets (kit codes, code pepper, adult credentials, event data), trust boundaries, and the abuse cases listed in ARCHITECTURE.md section 9. Include a data-flow diagram (Mermaid).

Acceptance:

- Every abuse case has a named mitigation and the phase that implements it
- Data-flow diagram shows every place adult PII and kit-level data is stored

### `p0-open-decisions` HUMAN: answer the open product questions

Mike/Given/Kai to answer the questions in docs/handoff/DECISIONS.md section 'Open questions': kit name and code prefix, module and step outline for the arm kit, whether the arm has any networked electronics, device availability at the pilot site, retention period. Record answers in docs/adr/ and close this bead.

Acceptance:

- Kit slug and 3-letter code prefix recorded
- Module list with step counts recorded (or a date when Given will deliver it)
- Explicit yes/no on networked electronics and AI assistant for the arm kit

### `p0-host` HUMAN: choose Canadian host, create account, buy domain

Pick a VM provider with a Canadian region (see DECISIONS.md ADR-04 for candidates), create the account with billing, and register the domain. Give the agent: provider name, region, domain, and how it will receive SSH/API access (never paste secrets into a bead).

Acceptance:

- Provider and region recorded in docs/adr/0004
- Domain registered and DNS manageable
- Access method for deploys agreed

### `p0-school-it` HUMAN: contact pilot-site IT about devices and network

Ask the pilot site: which devices and how many (Chromebook / iPad / other), browser versions, whether new domains must be allowlisted and how long that takes, whether video streaming is throttled, and whether devices keep cookies between sessions (managed Chromebooks often wipe on sign-out).

Acceptance:

- Device type, count and browser recorded
- Allowlist process and lead time recorded
- Cookie/session persistence behaviour on the school devices recorded

### `p0-consent` HUMAN: update consent form and research application for the platform

The consent form and school board application were written before the pivot and before the web platform existed. They must describe what the platform logs (see docs/handoff/EVENTS.md and PRIVACY.md) and the opt-out behaviour (no-log mode). Phase 9 produces a plain-language appendix to attach.

Acceptance:

- Consent form text covers the web platform, kit-level logging and deletion on request
- School board / research reviewer has the event list appendix
