# Phase 10: Production deploy and pilot readiness

**Goal.** A production environment that can be restored from backup, real content and real codes loaded, and a rehearsed plan for the pilot day including what happens when the Wi-Fi fails.

## Exit criteria

- [ ] Production is live in a Canadian region with backups restored at least once in a drill
- [ ] Printed code cards match the kits; smoke test passes on the pilot's device types
- [ ] Go/no-go checklist signed by the team

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p10-prod-infra` | P0 | task | Provision production VM | `p9-load`, `p0-host` | infra, deploy |
| `p10-secrets` | P0 | task | Production secrets and the code pepper backup procedure | `p10-prod-infra` | infra, security, human |
| `p10-backups` | P0 | task | Encrypted nightly backups and a restore drill | `p10-prod-infra`, `p10-secrets` | infra |
| `p10-cd` | P0 | task | Release pipeline with health gate and rollback | `p10-prod-infra`, `p1-staging` | deploy, ci |
| `p10-dns-tls` | P0 | task | Domain, DNS and TLS for production | `p10-prod-infra` | infra, deploy |
| `p10-monitoring` | P1 | task | Uptime, resource and error alerts to Discord | `p10-dns-tls` | infra |
| `p10-content-release` | P0 | task | Content v1 freeze and release | `p4-real-content`, `p4-registry`, `p10-cd` | content, deploy |
| `p10-codes` | P0 | task | Generate the production code batch and print code cards | `p2-code-cli`, `p10-secrets`, `p0-open-decisions` | codes, human |
| `p10-accounts` | P1 | task | Create staff and facilitator accounts and the pilot class | `p10-dns-tls`, `p3-invites` | deploy, human |
| `p10-smoke` | P0 | task | Production smoke test | `p10-content-release`, `p10-codes`, `p10-backups`, `p10-monitoring` | deploy, tests |
| `p10-school-test` | P0 | task | HUMAN: test on the pilot site's network and devices | `p0-school-it`, `p10-dns-tls`, `p5-e2e` | human, pilot |
| `p10-runbook` | P0 | task | Pilot-day runbook and offline fallback | `p10-smoke` | docs, pilot |
| `p10-dry-run` | P0 | task | HUMAN: facilitator dry run with all kits | `p10-runbook`, `p10-accounts`, `p10-school-test` | human, pilot |
| `p10-go-live` | P0 | task | Go/no-go checklist and launch | `p10-dry-run`, `p0-consent`, `p9-privacy-doc`, `p9-authz-sweep`, `p9-headers`, `p9-ratelimit`, `p6-nolog-invariant`, `p8-export` | pilot, human |

### `p10-prod-infra` Provision production VM

Production VM sized from the load test, same region as staging, separate from staging. Firewall, automatic security updates, non-root deploy user, Docker, separate volumes for database and media, time sync.

Acceptance:

- Only 80/443 public; SSH restricted
- Infra steps are scripted or documented so the VM can be rebuilt from scratch

### `p10-secrets` Production secrets and the code pepper backup procedure

Generate production secrets on the server. HUMAN: store CODE_PEPPER and the backup encryption key in two offline places the team controls. Losing the pepper invalidates every printed code; leaking it weakens them. Document rotation.

Acceptance:

- Secrets exist only on the server and in the team's offline store
- docs/runbook/secrets.md explains recovery and rotation

### `p10-backups` Encrypted nightly backups and a restore drill

Nightly pg_dump, encrypted client-side, to object storage in Canada, 30-day retention; media volume synced separately. Perform a full restore onto staging and record the time taken.

Acceptance:

- Restore drill completed and documented with elapsed time
- Backup failure raises an alert

### `p10-cd` Release pipeline with health gate and rollback

Tagged release promotes the exact image tested on staging: migrate, start, health-check, switch. Rollback is one documented command to the previous image. Migrations must be backward compatible with the previous app version.

Acceptance:

- A deliberately broken release is rejected by the health gate and the old version stays up
- Rollback rehearsed once on staging

### `p10-dns-tls` Domain, DNS and TLS for production

Point the production hostname at the VM, Caddy obtains certificates, HTTP redirects to HTTPS, HSTS on. Give the final hostname to the pilot site for allowlisting.

Acceptance:

- TLS test grade A or better
- Hostname sent to pilot-site IT (note on the p0-school-it bead)

### `p10-monitoring` Uptime, resource and error alerts to Discord

External uptime check on /readyz, disk/CPU/memory alerts, alert on 5xx spikes and on backup failure, all to a Discord webhook channel. No third-party script runs in users' browsers.

Acceptance:

- Stopping the app triggers an alert within 3 minutes
- Alert channel documented in the runbook

### `p10-content-release` Content v1 freeze and release

Freeze v1 content for Pilot 1, deploy, sync the registry, upload videos, verify every step and video in production.

Acceptance:

- Every step opens and every video plays in production
- content.lock.json tagged as pilot-1

### `p10-codes` Generate the production code batch and print code cards

Run the generator against production for the Pilot 1 batch (kits plus spares). HUMAN: print cards, match each card to its kit during packing using the CSV, store the CSV offline.

Acceptance:

- One card per kit and spare, QR scans to the production redeem page
- Packing check recorded: card number equals kit label for every kit

### `p10-accounts` Create staff and facilitator accounts and the pilot class

Create staff accounts for the team, invite facilitators and the teacher, create the Pilot 1 class. Kits are redeemed into it during the dry run.

Acceptance:

- Each facilitator has logged in once before pilot day

### `p10-smoke` Production smoke test

Scripted end-to-end check against production using a spare kit's real code: redeem, open session, join from a second device, complete a step, get stuck, see it on the dashboard, verify events arrive, then delete that kit's data.

Acceptance:

- Smoke script passes and leaves no test data behind
- Script is re-runnable before every pilot session

### `p10-school-test` HUMAN: test on the pilot site's network and devices

On site or with a borrowed school device on the school network: load the site, join, play a video, go offline and back. Earlier is better: run it against staging as soon as Phase 5 is done, then again against production.

Acceptance:

- Site and video load on the school network on the actual device type
- Join and resume behaviour confirmed with the school's cookie policy

### `p10-runbook` Pilot-day runbook and offline fallback

docs/runbook/pilot-day.md: setup checklist, how to open a session, what to do when a tablet will not join, when the Wi-Fi drops, when the site is down (printed guides plus videos on USB or a facilitator laptop), who to message, and the after-session data-quality check.

Acceptance:

- Runbook fits on two printed pages
- Offline fallback kit list is specific (how many printed guides, which files on the USB)

### `p10-dry-run` HUMAN: facilitator dry run with all kits

Full rehearsal with every kit and tablet, facilitators following the runbook. File every problem as a bead.

Acceptance:

- All kits redeemed into the pilot class
- Problems filed and triaged; P0/P1 fixed

### `p10-go-live` Go/no-go checklist and launch

Team signs off: consent and approval in hand and matching what the platform does, dry run clean, backups restorable, no open P0/P1 beads, runbook printed.

Acceptance:

- Checklist committed with names and date
- `bd list` shows no open P0 or P1 beads outside post-launch-ok and post-pilot
