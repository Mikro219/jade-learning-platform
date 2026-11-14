# planloop planner handback contract

The one source for what a planner hands back. The orchestrator's prompt points here and adds the task (findings, brief, run id, revision, nonce); it never restates these rules, and its example text is never format. `scripts/planloop.py handback` enforces every rule below that is marked as a refusal. Tool file formats: `formats.md`. Policy: `../SKILL.md`.

## The envelope

Hand back the **complete plan, never a diff**, in one message, wrapped in exactly two marker lines with the run, revision and nonce the orchestrator gave you:

```
<<<PLANLOOP-HANDBACK run=<run> revision=<N> nonce=<nonce>>>>
# PLAN <bead>: <title> (revision <N>, <YYYY-MM-DD>)
...the whole plan...
<<<PLANLOOP-HANDBACK-END run=<run> revision=<N> nonce=<nonce>>>>
```

- Exactly one start and one end marker, in that order; a missing end marker reads as truncation. Text before the start marker is ignored; put **nothing after the end marker**.
- The first plan line is the title, exactly `# PLAN <bead>: <title> (revision <N>, <YYYY-MM-DD>)`, with the bead and revision of this run. No byte-order mark.
- Headings are `## ` or `### ` lines outside code fences, each unique. The plan needs `## Change log` and `## Artifact inventory`.
- Write no files, except the self-check scratch file described at the end. The plan travels only in the handback message.

## Change log (`## Change log`)

One line per entry, each starting `- `:

- `- FIX R<k>: <what changed>`, `- REDESIGN R<k>: <the mechanism replaced, why earlier fixes failed, the new mechanism>`, `- REJECT R<k>: <evidence the finding is wrong>`. **Each finding is answered exactly once**: a second line for the same `R<k>` is refused; replace the earlier line instead. Every open or reopened high/medium finding must be answered. A finding the orchestrator says needs a redesign must be answered with `REDESIGN`. Answering a finding that does not exist is refused.
- `- REMOVED <heading or ID>: <what was removed, why, which obligations or capabilities it affects>`, for every section heading or inventoried ID of the previous revision that is gone.
- `- SHRINK <heading>: <what was cut from the section, why, what it affects>`, for every section that kept its heading but **lost a line** (below).
- `- PRESERVED <ID>: <where it is stated now, and what wording changed if any>`, only in a shrink-only revision (below), for every id inventoried in both revisions; ignored in other revisions.
- `REMOVED`, `SHRINK` and `PRESERVED` need at least 20 characters after the colon, on the same line. `<heading>` is the full heading with its `#`s, e.g. `- SHRINK ## 3. Invariants: tightened the wording of two invariants; no obligation affected`. A `REMOVED`/`SHRINK` line must not name an ID that is gone from the plan, other than the `<ID>` of its own `- REMOVED <ID>:` line (see the inventory rules).

The change log describes this revision against the previous one; it is not a running history.

## What counts as a lost line

A **lost line** is any non-blank line of the previous revision's section that does not appear, byte-identical, in the new section of the same heading. So all of these need a `SHRINK` line for the section:

- a line deleted;
- a line **edited in place** (one changed word makes the old line absent, even if the section grew);
- two lines merged, one line split, or a paragraph rewrapped;
- a line moved to another section (it is lost from this one).

Blank lines, reordering within a section, and new lines are free. `## Change log` and `## Artifact inventory` are exempt, because neither can carry a requirement: the inventory holds only heading and id entries, and the change log describes one revision and is replaced by the next, so **state every requirement in a section or the preamble, never only in the change log**. A section whose heading text changed is a removed section (`REMOVED` the old heading) plus a new one. Lines in fenced blocks and `####` lines are lines of the section around them.

The **preamble** (the title and every line above the first heading) is compared the same way, with only the title's revision and date ignored. A lost preamble line needs no `SHRINK` line, but it counts as lost text: a revision that answers no open finding and changes the preamble or the title's text is shrink-only (below).

If you edited a section at all, assume it needs a `SHRINK` line and run the check below; it lists the exact old lines it could not find.

## Shrink-only revisions

A revision is **shrink-only** when it answers no finding that is open or reopened and loses something of the previous revision: a lost line of a section or of the preamble, or a whole section. Whether it is smaller does not matter; a rewording that answers no finding is shrink-only. `--check` and `handback` print the classification, and `handback.json` records it.

- A shrink-only revision changes wording, never meaning. Write a `PRESERVED <ID>:` change-log line for every id inventoried in both revisions, saying where it is stated now and what wording changed; a missing or short one is refused and listed by `--check`. State any meaning change you could not avoid in that section's `SHRINK` line, so that the reviewer judges it.
- An independent reviewer then judges every textual change against the previous revision, unit by unit, added and reordered lines included, not only lost ones; differences become findings. Labels that are not inventoried (A5, OD15, D10) are covered by that judgement, not by the id map.
- An **input refresh** is the previous plan with only the title's revision and date changed: it loses nothing, so it is not shrink-only. The orchestrator asks for one when a shrink's own review round cannot run.
- Do not cut text in a revision that answers findings: such a revision more than 5% smaller than its predecessor gets a `WARN`, whether the cut is in a section or only in the change log.

Passing `--check` says nothing about meaning; it checks structure only.

## Residual risks

`## Residual risks` holds one line per risk, starting exactly `- RR<n>: ` followed by the text. Every `RR` id in the inventory has exactly one such line. Rewording a risk voids Mike's earlier acceptance of it, so change risk text only on purpose.

## Artifact inventory (`## Artifact inventory`)

The last section. Only two line shapes, nothing else on the line:

- `- section: <heading>` for **every** `##`/`###` heading in the plan, including `## Artifact inventory` itself, written with its `#`s exactly as it appears; never the `# PLAN` title.
- `- id: <ID>` for every OB/INV/RR/AC/EV id the plan uses, and only those. Other labels (OD, FT, T, Q, ...) may appear in the text but are never inventoried.

Correct, verbatim:

```
## Artifact inventory
- section: ## 0. Summary
- section: ## 3. Invariants
- section: ### Q5. Docs
- section: ## Residual risks
- section: ## Change log
- section: ## Artifact inventory
- id: OB1
- id: INV2
- id: RR1
```

**Do not append annotations** to inventory lines: no `(unchanged)`, `(new)`, `(from rev N)`, comments or trailing text. If an orchestrator message showed inventory lines with a suffix, that was description, not format. Carry the inventory over unchanged from the previous revision unless headings or ids changed.

Every inventoried id must be used outside the inventory, and every id used must be inventoried. **A removed ID may appear only on its own `- REMOVED <ID>: ...` line**; any other mention, anywhere including `SHRINK` lines and other `REMOVED` lines ("so RR3 is removed", "merged INV3 into INV2"), counts as a use and is refused as not inventoried.

## Obligations

Obligation text (`OB<n>`) is byte-exact: copy it from the source file, not from a rendering or a wrapped quotation (CLAUDE.md wraps lines). The bundle compares it byte for byte.

## Planner model (escalated track)

The real handback checks the planner's model on an escalated run. Fable must write revision 1, or the first revision after a run was escalated later (`planloop_escalated_revision`), and any revision while a redesign is required or answering an open or reopened finding with `REDESIGN`. Answer lines you carried over for findings that are already closed or awaiting review do not count (`--check` notes them). Opus may write every other revision. A per-run override recorded by Mike lets Opus write any revision. The orchestrator picks the planner; `--check` prints which model this content needs.

## Self-check before handing back

Run the read-only check on your draft; it applies every content rule above against the previous revision and the run's findings, and writes nothing:

```
python3 .claude/skills/planloop/scripts/planloop.py handback --run <run> --check <<'PLANLOOP_DRAFT'
<<<PLANLOOP-HANDBACK run=<run> revision=<N> nonce=<nonce>>>>
# PLAN ...the whole draft...
<<<PLANLOOP-HANDBACK-END run=<run> revision=<N> nonce=<nonce>>>>
PLANLOOP_DRAFT
```

Run it from the repository root. Markers are optional on stdin; `--revision` defaults to the next one. It prints `check passed: ...` (exit 0), or (exit 1) the first structural error (title, headings, inventory, ids, RR lines: these stop the analysis) or else every content refusal (finding answers, `REMOVED`, `SHRINK`, the `PRESERVED` map of a shrink-only revision, short dispositions); exit 2 or 3 means the run's Beads state could not be read or is inconsistent, or the run's published revisions do not verify as a chain from HEAD, which is the orchestrator's problem, not your draft's. It also prints, for each section needing `SHRINK`, the previous revision's lines it could not find, the preamble lines it could not find (for information), the plan's size against the previous revision with the size policy line and a `WARN` over the threshold, the classification (shrink-only or not), and which planner model the policy requires. Invalid UTF-8 or a byte-order mark is refused. Fix and re-run until it passes, then hand back the same text. It does not check markers, the nonce or your model; the real handback does. A draft that passes `--check` passes the real handback's content checks.

**Large drafts.** The Bash tool passes the whole command, heredoc included, as one argument, and the system limit on one argument is 128 KiB (quotes in the text grow it further), so a heredoc of a draft over about 100 KB fails with `Argument list too long` before planloop runs. For such a draft write a scratch file in chunks of under 100 KB, each in its own Bash call, named with the run's nonce, then check it and delete it:

```
F="${TMPDIR:-/tmp}/planloop-draft-<nonce>.md"
cat > "$F" <<'PLANLOOP_DRAFT'          # first chunk (> creates); later chunks use cat >> "$F"
...under 100 KB of the draft...
PLANLOOP_DRAFT
python3 .claude/skills/planloop/scripts/planloop.py handback --run <run> --check < "$F"
rm -f "$F"
```

Split only at line boundaries. That scratch file is the one file a planner may write. Normally it is a self-check aid only, never the handback, which is still the full plan in your final message.

**A plan too large for one message.** If the full plan cannot be emitted in one message (the output limit cuts it off), keep the checked scratch file, with both markers in it, instead of deleting it, and make your final message name its path and its full `sha256sum`. The orchestrator then runs `handback ... --transcript <agent>.jsonl --draft <file>`, which accepts the file only if it is named with the request's nonce and the final message in the transcript names its exact sha256, and records the file and digest in the handback record. Every content rule above applies to the file unchanged. (Mike, 2026-11-05, cgr.pl1 revision 5: 213,547 bytes after three failed attempts.)
