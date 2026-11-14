# Phase 3: Accounts, classes and student sessions

**Goal.** Adults hold accounts and own classes. Students never have accounts: a tablet joins a class with a short code and is bound to one kit.

## Exit criteria

- [ ] A facilitator can sign up with a kit code, create a class, redeem kits, open a session and see a join code
- [ ] A student device can join, pick a kit, and stay joined across page reloads
- [ ] Authorization matrix tests pass

## Tasks

| Key | Pri | Type | Title | Depends on | Labels |
|---|---|---|---|---|---|
| `p3-adult-auth` | P0 | task | Adult accounts: code-gated signup, login, sessions, staff role | `p2-redeem` | auth, security |
| `p3-invites` | P1 | task | Staff invites for facilitators | `p3-adult-auth` | auth, staff-ui |
| `p3-classes` | P0 | task | Classes: create, redeem kits into a class, list kits | `p3-adult-auth` | classes, adult-ui |
| `p3-join` | P0 | task | Student join flow: join code, kit picker, device session | `p3-classes`, `p1-ui-shell` | auth, student-ui, security |
| `p3-session-controls` | P1 | task | Facilitator session controls: open, close, rotate code, reset a kit's devices | `p3-join` | classes, adult-ui |
| `p3-consent-flag` | P0 | task | Per-kit logging switch with consent confirmation | `p3-classes` | privacy, adult-ui |
| `p3-authz-tests` | P0 | task | Authorization matrix tests | `p3-join`, `p3-consent-flag` | security, tests |
| `p3-home-mode` | P3 | task | Home mode: parent redeems one code, device joins without a class code | `p3-join` | post-pilot, auth |

### `p3-adult-auth` Adult accounts: code-gated signup, login, sessions, staff role

Email + password (argon2id). Signup requires a valid unused kit code or a staff invite, so there is no open registration and no email service in v1. Server-side sessions in Postgres, httpOnly + Secure + SameSite=Lax cookie, rotation on login, idle and absolute expiry. Roles: adult, staff. Password reset is a staff action in v1 (generates a one-time reset link shown to staff).

Acceptance:

- Signup without a valid code or invite is impossible
- Login is rate limited and returns the same message for unknown email and wrong password
- Session cookie flags verified by test; logout invalidates server-side

### `p3-invites` Staff invites for facilitators

Staff create a single-use, expiring invite link to hand to a facilitator or teacher in person or over Discord. Accepting it creates an adult account without consuming a kit code.

Acceptance:

- Invite works once and expires after 7 days
- Invite token is stored hashed

### `p3-classes` Classes: create, redeem kits into a class, list kits

Adult creates a class (name, kind: classroom / camp / home). Redeem by typing a code or opening the QR link while signed in. Class page lists kits with their display number.

Acceptance:

- A user only ever sees their own classes
- Redeeming 15 codes in a row takes under 2 minutes with the QR flow
- Kit display numbers are stable within a class

### `p3-join` Student join flow: join code, kit picker, device session

Facilitator opens a session, which shows a 6-character join code (same alphabet as kit codes) valid only while the session is open. Student device enters the code, taps its kit number, and receives a device-session cookie (random token, stored hashed, bound to class + kit). Rate limit join attempts. If p0-school-it reports that devices wipe cookies, re-joining must take under 15 seconds.

Acceptance:

- Join code stops working when the facilitator closes the session
- A device session can only read and write for its own kit (tested)
- Join attempts are rate limited; join codes are not guessable within the limit

### `p3-session-controls` Facilitator session controls: open, close, rotate code, reset a kit's devices

Controls on the class page. Reset revokes all device sessions for one kit (for when a group joined as the wrong kit).

Acceptance:

- Rotating the code does not disconnect devices already joined
- Reset forces the kit's devices back to the join screen on next request

### `p3-consent-flag` Per-kit logging switch with consent confirmation

Each kit in a class has logging_enabled, default off. Facilitator turns it on only after confirming consent is in hand for every child in that group; the confirmation (who, when) is stored. Turning it off stops collection immediately. This flag is the single switch Phase 6 ingestion checks.

Acceptance:

- Default is off for every newly redeemed kit
- Toggle writes an audit row with user and time
- UI states plainly what is and is not recorded in each mode

### `p3-authz-tests` Authorization matrix tests

Table-driven tests over every route and API endpoint for five actors: anonymous, student device (own kit), student device (other kit), adult (other owner's class), staff. Add new routes to the matrix as later phases create them; CI fails if a route is missing from it.

Acceptance:

- Matrix covers 100% of routes (enforced by a test that enumerates the route manifest)
- No IDOR: other-kit and other-class access returns 404

### `p3-home-mode` Home mode: parent redeems one code, device joins without a class code

Retail path. Parent account with a single kit; the parent's own browser session can open the student view directly. Not needed for either pilot.

Acceptance:

- Parent can reach the student view for their kit in two taps after login
