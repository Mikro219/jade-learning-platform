# 0001. Kit-agnostic platform

- Status: accepted
- Date: 2026-11-14
- Source: `docs/handoff/DECISIONS.md` ADR-01

## Context

v1 of the architecture was specific to the Pickney seed incubator: a `PKN` code prefix, `kit02` IDs, eight named modules, device sync and an AI proxy (REVIEW.md finding 1). The project has since pivoted to a DIY mechanical arm kit for the same age range and pilot dates (REVIEW.md, introduction). Architecture v2 makes the platform itself know nothing about arms: a kit is a row in a table plus a folder of content (ARCHITECTURE.md section 1). Content is modelled as Kit, Module, Step and blocks, written as Markdown in the repo (ARCHITECTURE.md section 7).

## Decision

The platform serves any kit. A kit is a `products` row (slug, name, code prefix) and a `content/<slug>/` folder. First product: the mechanical arm, slug `arm`, prefix `ARM`. Both are placeholders until the team names the kit; changing them before codes are printed is a one-line change.

## Consequences

- The slug `arm` and the prefix `ARM` stay placeholders until p0-open-decisions (jade-6is) records the kit slug and 3-letter code prefix (jade-6is acceptance; open question 1 in the [README](README.md#open-questions)).
- p2-schema-core (jade-o07) implements the `products` table with no column that names a specific kit (jade-o07 description); p2-seed (jade-q01) creates a demo product for development (jade-q01 description).
- Each kit's content lives under `content/<slug>/`, matching `products.slug` (DATA-MODEL.md section 1).
