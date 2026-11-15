# Data model

PostgreSQL 16. This is the target shape; Phase 2 and Phase 6 implement it as Drizzle schema plus SQL migrations. Names are binding, exact column types may be adjusted if a test shows a reason.

> Amended 2026-11-14 by [ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md), [ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md) and [ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md); [ADR 0019](../adr/0019-participant-letters-a-to-d.md) confirms the `^[A-D]$` checks. The handoff text is in git commit 079e846 and jade-handoff.zip.

Conventions: `id uuid primary key default gen_random_uuid()` unless stated, `created_at timestamptz not null default now()`, all timestamps `timestamptz`, text enums as `text` with a `check`.

## 1. Products, kits, codes

```sql
create table products (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,            -- 'arm' (placeholder), matches content/<slug>/
  name        text not null,
  code_prefix text not null unique check (code_prefix ~ '^[A-Z]{3}$'),
  created_at  timestamptz not null default now()
);

create table code_batches (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references products(id),
  label       text not null,                   -- 'pilot1-v1'
  created_by  uuid references users(id),
  created_at  timestamptz not null default now(),
  unique (product_id, label)
);

create table kits (
  id          uuid primary key default gen_random_uuid(),   -- the anonymous kit ID; lifelong
  product_id  uuid not null references products(id),
  batch_id    uuid not null references code_batches(id),
  serial      int  not null,                   -- number printed on the kit label within its batch
  created_at  timestamptz not null default now(),
  unique (batch_id, serial)
);

create table kit_codes (
  id            uuid primary key default gen_random_uuid(),
  kit_id        uuid not null references kits(id),
  code_hmac     bytea not null unique,         -- HMAC-SHA256(pepper, normalised code). Never the code.
  entitlements  text[] not null default '{core}',
  status        text not null default 'unused' check (status in ('unused','redeemed','revoked')),
  redeemed_by   uuid references users(id),
  redeemed_at   timestamptz,
  created_at    timestamptz not null default now()
);
create unique index one_live_code_per_kit on kit_codes(kit_id) where status <> 'revoked';
```

## 2. Adults, sessions, invites

```sql
create table users (
  id             uuid primary key default gen_random_uuid(),
  email          citext not null unique,
  password_hash  text not null,                -- argon2id
  display_name   text,
  role           text not null default 'adult' check (role in ('adult','staff')),
  created_at     timestamptz not null default now(),
  disabled_at    timestamptz
);

create table auth_sessions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  token_hash    bytea not null unique,         -- sha256 of a 256-bit random token
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  expires_at    timestamptz not null
);

create table invites (
  id           uuid primary key default gen_random_uuid(),
  token_hash   bytea not null unique,
  role         text not null default 'adult',
  created_by   uuid not null references users(id),
  expires_at   timestamptz not null,
  accepted_by  uuid references users(id),
  accepted_at  timestamptz
);
```

Adult email is the only personal information in the system.

## 3. Classes and student devices

```sql
create table classes (
  id             uuid primary key default gen_random_uuid(),
  owner_id       uuid not null references users(id),
  name           text not null,
  kind           text not null check (kind in ('classroom','camp','home')),
  pilot_label    text,                          -- 'pilot-1', 'pilot-2'; used by analytics filters
  join_code_hash bytea,                         -- set while a session is open
  join_open      boolean not null default false,
  ended_at       timestamptz,                   -- retention clock starts here
  created_at     timestamptz not null default now()
);

create table class_kits (
  class_id              uuid not null references classes(id) on delete cascade,
  kit_id                uuid not null references kits(id),
  display_number        int  not null,          -- 'Kit 07' as shown to students
  logging_enabled       boolean not null default false,
  consent_confirmed_by  uuid references users(id),
  consent_confirmed_at  timestamptz,
  active                boolean not null default true,
  primary key (class_id, kit_id),
  unique (class_id, display_number)
);
create unique index kit_in_one_active_class on class_kits(kit_id) where active;

create table device_sessions (
  id            uuid primary key default gen_random_uuid(),
  class_id      uuid not null,
  kit_id        uuid not null,
  token_hash    bytea not null unique,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  revoked_at    timestamptz,
  foreign key (class_id, kit_id) references class_kits(class_id, kit_id) on delete cascade
);

create table audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  actor_id    uuid references users(id),
  action      text not null,                    -- 'code.redeem', 'kit.logging_on', 'kit.delete_data', ...
  subject     jsonb not null                    -- ids and counts only; never codes, tokens or note text
);
```

## 4. Content registry, events, progress

```sql
create table content_steps (
  step_id             text not null,            -- 'arm.m3.s04'
  version             int  not null,
  product_slug        text not null,
  module_id           text not null,
  track               text not null check (track in ('beginner','advanced','both')),
  title               text not null,
  expected_seconds    int  not null,
  content_hash        text not null,
  first_published_at  timestamptz not null default now(),
  primary key (step_id, version)
);

create table events (
  event_id         uuid primary key,            -- client-assigned UUIDv7
  received_at      timestamptz not null default now(),
  client_ts        timestamptz not null,
  ts_flag          text check (ts_flag in ('future','stale')),
  device_session   uuid not null,
  seq              int  not null,               -- per device session, for ordering and gap detection
  class_id         uuid not null,
  kit_id           uuid not null,
  step_id          text,
  content_version  int,
  track            text,
  variant          text,                        -- reserved (E6); always null in v1
  type             text not null,
  data             jsonb not null default '{}',
  app_version      text not null,
  catalog_version  int  not null
);
create index events_kit_time on events (class_id, kit_id, client_ts);
create index events_step     on events (step_id, content_version, type);

create table kit_progress (                     -- written only when logging is enabled
  class_id         uuid not null,
  kit_id           uuid not null,
  step_id          text not null,
  content_version  int  not null,
  state            text not null check (state in ('viewed','completed')),
  updated_at       timestamptz not null default now(),
  primary key (class_id, kit_id, step_id)
);
```

The application's database role has `insert` and `select` on `events`, no `update`, and `delete` only through the `delete_kit_data(kit_id)` function added in Phase 9.

Live stuck alerts for kits with logging off ([ADR 0017](../adr/0017-live-stuck-alerts-for-no-log-kits.md)) have no table. The app holds them in memory per class until resolved or the session closes; they are never written to the database or logs. Whether kits with logging on use the same store is open.

## 5. Adult-entered data

```sql
create table facilitator_notes (
  id               uuid primary key default gen_random_uuid(),
  class_id         uuid not null references classes(id) on delete cascade,
  kit_id           uuid references kits(id),    -- null = whole class
  step_id          text not null,
  content_version  int  not null,
  issue_type       text not null check (issue_type in ('wording','video','diagram','hardware','sequencing','other')),
  severity         int  not null check (severity between 1 and 3),
  note             text check (char_length(note) <= 500),
  author_id        uuid not null references users(id),
  created_at       timestamptz not null default now()
);

create table quiz_responses (
  id           uuid primary key default gen_random_uuid(),
  class_id     uuid not null references classes(id) on delete cascade,
  kit_id       uuid not null references kits(id),
  participant  text not null check (participant ~ '^[A-D]$'),
  phase        text not null check (phase in ('pre','post')),
  question_id  text not null,                   -- stable id from kit content
  answer       text not null,
  correct      boolean not null,
  entered_by   uuid not null references users(id),
  created_at   timestamptz not null default now(),
  unique (class_id, kit_id, participant, phase, question_id)
);

create table exit_cards (
  id           uuid primary key default gen_random_uuid(),
  class_id     uuid not null references classes(id) on delete cascade,
  kit_id       uuid not null references kits(id),
  participant  text not null check (participant ~ '^[A-D]$'),
  module_id    text not null,
  fun_rating   int  not null check (fun_rating between 1 and 5),
  entered_by   uuid not null references users(id),
  created_at   timestamptz not null default now(),
  unique (class_id, kit_id, participant, module_id)
);
```

Rows in section 5 that name a kit are only accepted when that kit's `logging_enabled` is true.

## 6. Deletion and retention

- `delete_kit_data(kit_id)` removes the kit's rows from `events`, `kit_progress`, `facilitator_notes`, `quiz_responses`, `exit_cards` and `device_sessions` in one transaction and writes an `audit_log` row with counts. A test enumerates every table that has a `kit_id` column so a table added later cannot be forgotten.
- Retention ([ADR 0023](../adr/0023-tiered-retention-for-kit-keyed-data.md)): at `classes.ended_at + RETENTION_MONTHS` (default 12 months, set by config), for that class:
  - `events` are reduced to rows in `step_aggregates` (same shape as the `step_metrics` view, no kit id) and the raw rows removed;
  - `kit_progress` and `device_sessions` rows are deleted;
  - `facilitator_notes` are kept with `kit_id` set to null;
  - `quiz_responses` and `exit_cards` are reduced to per-question and per-module counts with no kit id, then deleted.

  `step_aggregates` and the quiz and exit-card aggregate tables are defined by the retention job's migration (p9-retention, jade-8vo) and documented here when it lands. The job ships after launch and must run in production before the first class reaches `classes.ended_at + RETENTION_MONTHS` ([ADR 0016](../adr/0016-step-views-and-retention-post-launch-ok.md)).

## 7. Analytics views (Phase 8)

`step_metrics(class_id, pilot_label, step_id, content_version, track, kits_viewed, kits_completed, median_active_s, p90_active_s, expected_seconds, kits_stuck, stuck_reasons jsonb, median_unstuck_s, kits_rewatched, checkpoint_first_try jsonb, notes_count, notes_severity_sum)`

Every rate shown in the UI is computed from the count columns at display time; the view stores counts.
