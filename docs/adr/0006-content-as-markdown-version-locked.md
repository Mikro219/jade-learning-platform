# 0006. Content as Markdown in the repo, version-locked

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-06

## Context

v1 put a Git-backed CMS in v1, which adds an auth integration and its own failure modes before a single step is written (REVIEW.md finding 12). v1 said every step carries a `content_version` but nothing enforced it, so one un-bumped edit makes version comparisons silently wrong (REVIEW.md finding 13). A printed QR that encodes a versioned URL goes stale when the step is revised (REVIEW.md finding 21). The v2 content model has permanent step IDs, a `version` per step, `content.lock.json` checked in CI, and stable `/s/<step_id>` short links (ARCHITECTURE.md section 7).

## Decision

Markdown with YAML frontmatter under `content/`. Permanent step IDs. `content.lock.json` and a CI lint enforce version bumps. No CMS in v1.

## Consequences

- p4-schema (jade-5kj) defines the content format and its validation; p4-lock (jade-as7) adds `content.lock.json` and the content lint that fails CI on a changed step without a version bump; p4-shortlinks (jade-b4j) adds the stable `/s/<step_id>` short links (bead descriptions).
- CLAUDE.md rule 6: step IDs are permanent, a changed step gets a version bump, and CI enforces it.
- A visual CMS is deferred to extension point E3 (ARCHITECTURE.md sections 7 and 12).
