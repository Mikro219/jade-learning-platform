# planloop file formats (planloop/3, from quartz-rs-lur; JADE example paths)

Every JSON file planloop writes is canonical (sorted keys, no spaces, one trailing newline). Host-written inputs, runner artifacts, receipts, decisions, evidence and the HEAD/APPROVAL pointers are parsed strictly: duplicate keys, NaN/Infinity, missing fields, unknown fields and out-of-range enums are errors. Codex's rollout and the agent transcript are third-party formats: they are parsed line by line and any unfamiliar shape makes the input unverifiable rather than accepted. Paths in records are repository-relative unless noted.

The plan text itself (markers, change log, inventory, lost lines) is specified for planners in `handback.md`.

## Layout

```
plans/planloop/<run>/                 (<run> = <bead>.pl<N>)
  run.json                            settings (schema planloop-run/1): reviewer_model, gate_model, model_changes,
                                      reviewer_backend (claude|codex) and backend_changes [{at, from, to, quote,
                                      after_call}]; both are written only for a claude run or one ever switched, so
                                      a Codex run's run.json stays readable by older planloop; absent means codex
  HEAD                                the single revision pointer {revision, revision_sha256}
  .publishing-rev-NNN                 publishing intent {schema: "planloop-publishing/1", revision, revision_sha256},
                                      written before the rename, removed once HEAD names that revision
                                      or once no rev-NNN holds it
  rev-NNN/                            immutable once HEAD names it
    plan.md                           exact planner bytes
    handback.json                     source transcript + sha, completion evidence, answers, dispositions, cut, preserved
    revision.json                     plan, bundle and handback hashes; base revision and its hash
    bundle/manifest.json              the frozen input inventory (its sha is the bundle hash)
    bundle/frozen/                    plan, brief, obligations, bead text, evidence, discovery, findings snapshot,
                                      meaning-r<S>/{before,after,index}.md for each shrink this revision's reviews judge
    bundle/overlay/                   copies of every modified/untracked non-ignored file at bundle time
  reviews/call-CCC-aA/
    input/dispatch.json               frozen per-call inputs: revision, bundle, kind, effort, snapshot, feedback hash,
                                      fix-proposed findings the reviewer must report on, `scope`, the cgroup v2
                                      path of the systemd user scope the review runs in, and `view`, how the
                                      dispatching shell saw cgroups: {host, machine_id (/etc/machine-id, null
                                      unless it reads as 32 lowercase hex digits), boot_id, cgroup_ns (inode of
                                      /proc/self/ns/cgroup), cgroup_dev (device of /sys/fs/cgroup)}. Both are
                                      absent or null only in a record an earlier planloop wrote; a `scope` with
                                      no `view`, or under another planloop-*.scope name, is a record of an
                                      unreleased build (72m rounds 21-22, scratch clones only) or an edit: receipt
                                      says so (CONFLICT) and how to recover by hand. `snapshot`,
                                      `artifacts_root`, `live_repo`
                                      and `scope` must be non-blank strings without NUL or an unpaired surrogate
                                      (exit 1 otherwise). It is written before the private copy and the artifact
                                      directory it names are created; each is made as `.marking-<name>`, gets a
                                      `.planloop-reserve` file holding the reserve directory's name, and is then
                                      renamed into place; a later dispatch removes what a killed one left: a
                                      directory in place only where that marker matches, a leftover
                                      `.marking-<name>` by its name (the record's uuid names make it that
                                      dispatch's); a marked directory is renamed back to `.marking-<name>` before
                                      it is deleted, and a record whose directories are not all removed, or whose
                                      paths cannot be checked (any error but a missing path), is kept; once the
                                      record is a call directory, that call's receipt removes a leftover
                                      `.marking-<name>` of either directory; a marker that
                                      is not a regular file of at most 4096 bytes keeps the record. receipt
                                      takes the scope from here, never
                                      from running.json, whether or not running.json exists: `scope` must be the
                                      path computed from the run id and `artifacts_root` for the current user and
                                      `view` must be whole (CONFLICT otherwise), and nothing is recorded while
                                      the scope is not empty (its cgroup.events lacks `populated 0`, or a control
                                      file cannot be read while the scope's directory is there; only a scope whose
                                      own directory is gone, under a user manager cgroup that is there, is empty,
                                      including one removed after its directory was opened: a control file then
                                      ENOENT or ENODEV and the name gone from app.slice; a control file that is not
                                      a regular file of at most 1 MiB is an error, never read),
                                      while the path to it is not proven the real cgroup tree (/sys/fs/cgroup a
                                      cgroup2 mount of this cgroup namespace's root by /proc/self/mountinfo, every
                                      directory and control file on that same mount by its fdinfo mnt_id, both
                                      read whole from a /proc whose fstatfs type is procfs, on its device: anything
                                      mounted over the path is an error, not an absent scope; no mount id or mount
                                      namespace is recorded, the proof is made where receipt runs)
                                      or while `view` differs from the shell that runs receipt in anything but a
                                      new boot_id on the same host and the same non-null machine_id (after a
                                      reboot nothing of the review runs, so the scope is empty; without a machine
                                      id on both sides another boot cannot be told from another host). Two systems
                                      cloned with one host name and machine id are taken for one. A call whose
                                      host name or machine id changed without a reboot is recovered by hand, as
                                      the CONFLICT says: check nothing runs in the scope, remove the call
                                      directory, dispatch the attempt again
    running.json                      the dispatching process (host, boot_id, pid, pid_ns, start, nonce: pid_ns is
                                      the inode of /proc/self/ns/pid, and a record that names another PID
                                      namespace than the reader's, or none, is never taken as dead except by a new
                                      boot id: receipt says to run where the call was dispatched; pid_ns is null
                                      when /proc/self is not the process's own pid; receipt skips this check once
                                      receipt.json exists), with a copy of
                                      dispatch.json's `scope` and `view` that nothing reads; receipt waits while the
                                      dispatcher lives (an exited, unreaped process does not; a pid that is not an
                                      integer from 1 to 2^31-1 is never taken as dead; remove it by hand only if
                                      that pid is not a planloop dispatch: that gives up the wait for the
                                      dispatcher only, the scope check does not depend on this file, and a
                                      dispatch that finds its nonce gone from here, or a receipt.json, under the
                                      run lock just before it would start its runner, never starts it); it must be
                                      a JSON object in a regular file, never a symbolic link, `null` or a list;
                                      nothing else about the runner or Codex is recorded; dispatch keeps it when
                                      the scope is not empty after it was killed, receipt removes it once the
                                      attempt is recorded. receipt reads it, dispatch.json and the scope under
                                      the run lock, the one that guards the receipt it writes
    input/feedback.md                 the exact feedback given to the runner (claude backend: to the reviewer, also
                                      copied read-only into its private copy as .planloop-call/feedback.md)
    input/prompt.txt                  claude backend only: the reviewer agent's exact prompt (its first user turn)
    call.json                         {schema: "planloop-call/1", runner_exit, artifacts, runner_stdout_sha256} (output):
                                      runner exit and artifact directory; `receipt --artifacts DIR` writes it, with
                                      runner_exit and runner_stdout_sha256 null, when the call has no call.json and no
                                      receipt and DIR is a claudex-* directory directly in the call's artifact root
                                      holding a result.json file; if it is missing, is not a file or does not parse,
                                      the receipt is invalid unless `receipt --artifacts` names the directory;
                                      if it exists but cannot be read at all, `receipt` stops unverifiable and
                                      records nothing; when the runner's artifact directory cannot be listed
                                      after the runner returned, `dispatch` writes no call.json and says to
                                      record it with `receipt --artifacts` once it can be listed; `dispatch` writes
                                      it before it checks that nothing holds the call open, so a plain `receipt`
                                      records a finished review once that clears
    receipt.json                      verification result (output, immutable)
  intents/*.json                      planned Beads changes: planned -> applied -> verified
  decisions/D<n>.json                 Mike's decisions and risk acceptances
  decisions/S<n>.json                 Mike's size decisions (planloop-size-decision/1)
  decisions/A<n>.json                 Mike's sign-off of a claude-backend gate (planloop-signoff/1)
  approvals/approval-rNNN-<sha12>.json   approval records (pending until APPROVAL names one)
  APPROVAL                            the approval pointer {record, sha256}
  ledger.md                           generated projection, never edited
~/.local/state/planloop/<run>/
  snap-rNNN-<nonce>/                  the revision's frozen read-only snapshot (git archive + overlay + .planloop-bundle)
  .lock-bundle/                       held by a running `bundle`, and by `publish` before the run lock (owner.json,
                                      as the run lock: {host, boot_id, pid, pid_ns, start, nonce, acquired_at}; a
                                      lock is broken only when its owner is provably dead, on this host and after a
                                      reboot or in the PID namespace `pid_ns` names, never one that names another
                                      PID namespace or none), so two bundles never build one staging directory and snapshot
                                      at once and a staging directory is never published while a bundle builds it
  calls/call-CCC-aA-r-XXXXXXXX/claudex-*/   runner artifacts (+ rollout.jsonl copy of Codex's session record); the
                                      directory is dispatch.json's `artifacts_root`, named after the call and its
                                      private snapshot copy (`r-XXXXXXXX`), so it is unique to one dispatch even
                                      when checkouts share this state directory and a run id; `dispatch` creates
                                      it when it reserves the call and refuses one that already exists (exit 2,
                                      nothing reserved); calls dispatched before this have `calls/call-CCC-aA`.
                                      A claude call holds no claudex-* directory but transcript.jsonl and
                                      transcript.meta.json (the reviewer agent's, kept by its first `receipt
                                      --transcript`) and transcript-source.json {path, sha256, meta_sha256}
~/.local/state/planloop-isolated/r-*/repo/   a call's private copy of the snapshot, the reviewer's working directory;
                                      (the parent is mode 0300: not listable); removed once the receipt exists,
                                      except for the latest counted gate, which re-verification needs; renamed to
                                      .pruned-r-* before removal, which a NOTE names if removal fails; one left by a
                                      SIGKILL mid-prune is read by nothing and can be removed by hand (`chmod -R u+w`
                                      first)
```

**Claude-backend dispatch record.** `dispatch.json` adds `backend: "claude"` and `prompt_sha256` (both absent on a Codex call, which reads as `backend: "codex"`), has `model: "opus"`, `effort: "high"`, `scope` and `view` null, and no `running.json` is written: nothing runs under planloop's control. A record whose backend, prompt hash and scope disagree fails.

Inputs (frozen before dispatch) and outputs (written by or after the review) are kept apart: nothing in `reviews/*/` other than `input/` is ever an input to the call that produced it.

## inputs.json (host-written, `planloop-inputs/1`)

```json
{"schema": "planloop-inputs/1",
 "brief": "plans/planloop/<run>/brief-r2.md",
 "repo_files": ["src/lib/server/events/ingest.ts", "docs/handoff/EVENTS.md", "docs/handoff/phases/phase-06-event-pipeline.md"],
 "dir_inventories": ["migrations"],
 "beads": [{"id": "jade-zg3", "fields": []}],
 "obligations": [{"id": "OB1", "source": "docs/handoff/EVENTS.md",
                  "section": "Server rules", "text": "<exact normative text>"}],
 "evidence": ["plans/planloop/<run>/evidence/EV1.json"],
 "discovery": "plans/planloop/<run>/discovery.json"}
```

`fields: []` means title, description, acceptance_criteria, design. A bead `id` names the frozen copy `beads/<id>.json`, so one that is not a safe relative path fails the bundle (`inputs.beads.id: ...`); an evidence `output` is copied to `evidence/<output>` beside the records `evidence/<id>.json`, so an output that equals, contains or lies inside a record's path fails it too (`evidence frozen paths collide: ...`); records may share one output. An obligation `source` may be `bead:<id>` for a bundled bead. Obligation ids must equal the plan's `OB` inventory one to one.

## discovery.json (`planloop-discovery/1`)

`searches`: `{command, purpose, hits, match_proof}` (match_proof required when hits is 0); `sources`: `{path, class: binding|candidate|irrelevant, reason}`; `known_omissions`: must be empty.

## Evidence record (`planloop-evidence/1`)

```
id EV<n>; claim; kind sql|grep|log|file|command; source; query; query_sha256;
inputs [{path, sha256}]; observation_window {start, end} | null; collected_at;
snapshot (txid/commit) | null; group | null; status result|empty|unknown|error|timeout;
truncated; claim_needs_complete; match_proof | null; limits {max_rows, max_bytes};
limits_justification | null; row_count | null; bytes; output (path); output_sha256;
attempts [{at, outcome, backoff_s}] (1..3; retries back off >= 5 s, then >= 15 s);
validity {type: historical} | {type: until_input_change} |
         {type: observation, max_age_s, must_remain_current}
```

## Decision (`planloop-decision/1`)

`{id: "D<n>", by: "Mike", quote: <his exact words>, recorded_at, recorded_by, subjects: [{id: "R<k>"|"RR<k>", text_sha256}], outcome: accepted-risk|rejected-finding|deferred|scope-out, follow_up: <bead id> | null}`. For an `RR`, `text_sha256` is the SHA-256 of the risk text after `RR<k>: ` in the plan; a reworded risk needs a new acceptance. A deferral names its follow-up bead.

## Finding map (`findings ingest --map`)

`{"<reviewer finding id>": "new" | "new:R<k>" | "R<k>"}` covering exactly the reviewer's finding ids.

## handback.json (`planloop-handback/1`) size fields

`cut`: `{shrink_only, lost_lines, removed_sections, threshold_bytes, live_answers}`, the classification computed at handback (lost lines include the preamble's), the run's threshold (its first policy revision's, or `SIZE_THRESHOLD_BYTES` for that first revision) and `live_answers`, the sorted ids of the open or reopened findings the change log answered; `shrink_only` is true exactly when the revision is not revision 1, `live_answers` is empty and something was lost. `bundle`, `publish` and a recovery's roll-forward re-check it: exact shape, `threshold_bytes` equal to the run's threshold, every live answer answered in the plan's change log and a finding of this run (at `bundle` and `publish` one whose state is open or reopened; at a roll-forward any existing one), and the counts and flag recomputed from the staged plan and the previous revision; a `cut` that does not hold is refused, or moved aside by a recovery; a Beads read error during that check stops the command unverifiable (exit 2) and neither refuses nor moves anything. A `cut` without `live_answers` fails the shape check (only build-1 test records had that shape; none was published outside tests); `preserved`: the `PRESERVED` change-log entries. A run's policy starts at its lowest published revision with `cut`, and its threshold is that revision's `threshold_bytes`; `run.json` is unchanged. A `handback.json` without `cut` was staged by planloop code that predates the size policy: `bundle` and `publish` refuse such a staging, and a published one inside a run's policy range is classified from its text.

Every policy fact is read only after every published revision from 1 to HEAD verified as a chain from HEAD's pointer (`plan.md`, `handback.json`, manifest and overlay copies against `revision.json`, and every `bundle/frozen/` file a manifest item names against that item's digest: `plan.md`, `brief.md`, `obligations.json`, `discovery.json`, `findings.json`, `beads/<id>.json` by `sha256`, `evidence/<id>.json` by `record_sha256` and its output copy `evidence/<output>` by that record's `output_sha256`, `meaning-r<S>/{before,after,index}.md` by their three digests; a named path that is not a string, is empty, starts with `/`, contains a NUL or a backslash, or has a `.` or `..` component fails as `revision N manifest names an unsafe frozen path`; each `revision.json` against the next one's `base`); a manifest's `{"type": "plan"}` item must equal `plan_sha256`, and a read error during the walk counts as a failure. A malformed manifest (no `items` list, an item that is not an object or has no `type`, an overlay entry or snapshot item without its fields, bytes that are not UTF-8) is a failure too, and so is a missing (or non-file) `revision.json`, `plan.md`, `handback.json`, manifest, overlay copy or predecessor `revision.json`; a permission or other I/O error is not converted and stops the command (above HEAD, recovery reports it as `could not read <path> (<error>); retry once it is no longer held open; if it persists, ` followed by `move <rev-NNN> out of the run directory by hand (it can then be re-staged)` for a file inside a revision or `move it out of the run directory by hand (a revision is then moved aside and can be re-staged)` for an intent, exit 2, and moves nothing). Above HEAD, such a revision is moved aside by recovery, with one exception that holds a publication open instead of destroying it: a non-file (directory, FIFO, socket, device, dangling symbolic link) where a record should be in the revision right after HEAD whose `.publishing-rev-NNN` intent exists, or at that intent path itself, stops every locking command with exit 1, `FAIL  <path> is not a regular file (a directory, FIFO, socket, device or dangling symbolic link), so reading it again cannot help; nothing was moved aside or discarded: repair it by hand, or move <rev-NNN> out of the run directory by hand (it can then be re-staged)` (`, or move it out of the run directory by hand (a revision is then moved aside and can be re-staged)` for the intent), until it is repaired; `publish` stops the same way, moving nothing, when its own check after the rename finds one. A non-file in any other revision above HEAD does not verify and is moved aside. `.publishing-rev-NNN` is the publishing intent `publish` writes after verifying a staging and before renaming it: `{schema: "planloop-publishing/1", revision, revision_sha256}`, the digest of the `revision.json` it verified (which pins the plan, handback and manifest). Recovery rolls `rev-NNN` forward only when it verifies, chains to HEAD and its `revision.json` digest equals that intent's; with no intent, an unparsable one (`its publishing intent cannot be read`) or another digest it moves the directory aside and deletes its intent. `publish` verifies `rev-NNN` in full again after the rename and before writing HEAD, and moves it aside (exit 3), deleting its stale intent, when that fails or its four top files differ from the verified bytes; a non-file already at its intent path stops it before anything is written (exit 1, `remove it by hand`); an I/O error writing the intent stops it unverifiable with nothing published (exit 2), and one writing HEAD stops it unverifiable with the revision and its intent in place for the next recovery to complete (exit 2). Intents for revisions at or below HEAD, and intents with no `rev-NNN` beside them, are deleted by recovery, and `publish` deletes its own after HEAD; both are best effort, a failure printing `NOTE  could not remove ...` and the next recovery retrying (for a directory, `remove it by hand`). There are no tombstones; a `.rejected-rev-NNN-<sha256>` left by earlier code is inert. A failure is an integrity error, never a missing policy: `gate` without `--publish` reports a failed check and NOT APPROVED (exit 1); `gate --publish` and every other command exit 2, because their recovery walks the chain first. After the walk, a failed deep check of HEAD (its frozen snapshot missing or changed) makes `dispatch` exit 1 and `gate` report NOT APPROVED (exit 1). Receipts, dispatch records, decisions and Beads are not part of that chain.

## Meaning obligations

Manifest item `{"type": "meaning_obligation", "revision": S, "before_sha256", "after_sha256", "index_sha256", "units": [...], "revalidate": false}` for each shrink-only revision S not yet judged when the bundle was built (the revision itself when it is shrink-only); the files are `frozen/meaning-r<S>/before.md` (revision S-1's exact `plan.md`), `after.md` (revision S's) and `index.md` (navigation only). Units are the `##`/`###` sections and `(preamble)` whose non-blank lines differ in content or order, or that were added, removed or moved, Change log and Artifact inventory excepted.

`dispatch.json` of a call carrying obligations has `meaning_check: [{revision, previous_revision, before_sha256, after_sha256, index_sha256, units}, ...]`; the receipt then has `meaning_check: [{revision, previous_revision, verdicts: {<unit>: preserved|changed}}, ...]`. Both keys are absent on every other call. A counted receipt with `meaning_check` judges a shrink only when it and its dispatch record name the authenticated revision's hashes and its mandate equals that revision's frozen item; otherwise it is an integrity error.

## Sign-off (`planloop-signoff/1`, claude backend)

`{schema, id: "A<n>", by: "Mike", quote: <his exact words>, recorded_at, recorded_by, revision, plan_sha256, gate_call, gate_attempt, gate_receipt_sha256}` at `decisions/A<n>.json`, parsed strictly like a size decision (a malformed one fails `gate`'s `sign-off A<n>.json well formed` check). `signoff --run R --quote` writes the next one for the latest counted claude gate on HEAD; one may also be written by hand. Only files named exactly `A<positive integer>.json` are read; any other `A*`/`a*` JSON there is a NOTE. It counts only when it names the published revision, its `plan_sha256`, and the gate call and attempt with the sha256 of that gate's `receipt.json` as it is now; the lowest-numbered such file is bound into the approval. A well-formed one that binds another revision or gate receipt is a NOTE and fails nothing, but leaves the sign-off check failing.

## Size decision (`planloop-size-decision/1`)

`{schema, id: "S<n>", by: "Mike", quote: <his exact words>, recorded_at, recorded_by, revision: <S>, plan_sha256: <revision S's>, ceiling_bytes: <int>}` at `decisions/S<n>.json`, parsed strictly: a missing field or a wrong value (an array or object where `"Mike"` or the schema string belongs included) fails `gate`'s `size decision S<n>.json well formed` check and refuses a gate `dispatch` (exit 1). Only files named exactly `S<positive integer>.json` are read; any other `S*.json` or `s*.json` in `decisions/` is ignored with a NOTE. It gives a policy head G a basis when revision S <= G is a judged shrink-only policy revision with that `plan_sha256`, and `ceiling_bytes` is at least the size of both S and G; a well-formed decision that does not is reported as a NOTE. The lowest-numbered covering decision is used, and only when the plan is neither within the threshold nor within the renewal margin after a judged anchor shrink with no policy revision since it past that margin; a lower-numbered covering decision added after approval therefore changes the bound decision and lapses the approval.

## Approval record (`planloop-approval/1`) size fields

For a policy head only: `size: {plan_bytes, threshold_bytes, margin_bytes, basis, size_policy: {threshold_bytes, from_revision}, decision: null | {id, sha256}}` and `meaning_checks: [{revision, call, attempt, receipt_sha256, preserved, changed}, ...]` for every judged shrink-only policy revision. Readiness recomputes them; any difference lapses the approval.

## Approval record, claude backend

Adds `reviewer_backend: "claude"` and `signoff: {id, sha256}` (the bound sign-off file's hash); readiness recomputes both, so a changed sign-off file, a backend switch or a re-derived gate receipt that differs lapses the approval. A Codex approval has neither field.

## Reviewer coverage lines

For every finding in state `fix_proposed`: `finding R<k>: resolved` or `finding R<k>: unresolved`. Any later reviewer may withdraw an open finding with `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, 40+ characters>`. The final gate must answer each withdrawn finding with `finding R<k>: withdrawal confirmed` or re-raise it. Re-raising a known finding uses its `R<k>` as the finding id. A line that starts like a status but matches none of these, or a second line for the same finding, voids the call. On a call carrying meaning obligations: exactly one `meaning revision <S> <unit>: preserved` or `...: changed` per listed unit; a missing, duplicated or malformed line, or `changed` with no finding in the response, voids the call.

## Receipt (`planloop-receipt/1`)

Run, call, attempt, kind, revision and its hash, bundle and plan hashes, requested `{model, effort}`, effective `{model, effort, sandbox, source, rollout_sha256}`, session id, fresh, verdict, findings, coverage, live_reads, revalidation (list of changes), artifact hashes, usage, cli_version, dispatched_at, reasons, infrastructure, status `counted|invalid|triage`, created_at. The gate re-derives it from the artifacts and requires equality with the stored copy. Every command that reads a receipt checks its schema, status, call and attempt; `ledger`, `findings check` (for a finding's resolution receipt) and `findings ingest` also check that the other fields are present with their types (a counted or triage receipt's verdict a string, coverage a list of strings and findings objects with string id, severity and evidence). One that is not fails naming it (`<path> is not a planloop receipt for call C attempt A (<why>); it was edited or damaged: restore it ..., or delete it and run `receipt` for that call again, which re-derives it ...`, exit 1); a receipt re-derived after the call's private snapshot copy was removed is invalid. Intents (`intents/*.json`) and the run and finding beads' planloop counters, finding lists, finding severity (`low|medium|high`) and finding state (one of the finding states) are checked the same way (`intent <name> is not a planloop intent (<why>)`, `run|finding bead <id> holds malformed planloop metadata (<key>=<value>)`, exit 1) and nothing is applied from them. Re-running `receipt` on a recorded call prints the stored copy (with a NOTE) when it differs from the re-derived one but is exactly, `created_at` aside, what the same verification produces from the stored copy's own revalidation outcome: its `revalidation` list (strings) and at most one `live inputs could not be revalidated: ` reason, with the `relevant inputs changed during the review: ` reason, the order of `reasons`, `infrastructure` and `status` all recomputed from that outcome and every other field re-derived from the artifacts. Any other difference is a conflict, and the stored copy is never rewritten. That check shows the stored copy is consistent, not that it is the one first written: the revalidation outcome at the time of the review is recorded nowhere else, so a copy edited consistently in every field (for example an input-change invalidation removed together with its reason, `infrastructure` and `status`) is printed as recorded; hand-editing receipts is out of scope (Mike, 2026-11-11). A receipt recorded under an earlier wording of the reason it re-derives to (such as `runner left no artifact directory` where the call's `claudex-*/result.json` exists, or from a dispatcher that died while its runner continued) is a conflict on every re-run but still stands as recorded: invalid, never counted, and the next attempt dispatches normally.

**Claude-backend receipt.** The same schema and fields, plus `backend: "claude"` and `transcript: {source, sha256, meta_sha256, kept, parser: "claude-subagent/1"}`; `requested` is `{model: "opus", effort: "high"}`, `effective` is `{model, effort, sandbox, source, transcript_sha256}` from the transcript (the Opus model and effort Claude Code recorded), `session_id` is the agent id, `cli_version` the Claude Code version, `artifacts` the kept files' hashes, `usage` null. It is re-derived from the kept copy; a `--transcript` that differs from it, or a kept copy that differs from `transcript-source.json`, invalidates the re-derivation (a conflict for `receipt`, NOT APPROVED for `gate`). `--transcript none` on an unrecorded call records it invalid (infrastructure, `no reviewer transcript is recorded for this call ...`).

## Exit status

0 success or ready; 1 a check failed; 2 usage error or unverifiable input (`UNVERIFIABLE`, or `UNREADABLE` for a record that exists but cannot be read); 3 lock, publication or Beads conflict, or a review scope that is not empty or cannot be checked from where the command runs (`CONFLICT`); an I/O error a command does not name more precisely is still `UNVERIFIABLE` (exit 2), never a traceback, and says what to run next as the SIGINT line does; a runner artifact (`stdout.txt`, `prompt.txt`) that is not UTF-8 records the attempt invalid (infrastructure) like a missing one, and malformed runner JSON (wrong types, numbers too large to convert or not finite, nesting too deep) makes the receipt invalid with a reason naming it, never a traceback; 130 stopped by SIGINT outside the runner phase of `dispatch`, with one line `INTERRUPTED  stopped by SIGINT before the command finished; what it had written stands: ...` saying what to run next (`receipt` once `dispatch` has reserved the call, the same command otherwise). Bad input never produces a traceback: specific checks remain where they give better advice, and a malformed record that reaches no specific check (a `TypeError`, `KeyError`, `AttributeError`, `ValueError` including `UnicodeError`, `IndexError` or `RecursionError`) ends the command with exit 1 and one line `FAIL  <command>: a record it read is malformed (<type>: <message>); it stopped there, and what it had written before stands: ...` followed by what to run next (the same advice the SIGINT line gives where the command has one, otherwise repair or restore that record and run the command again); set `PLANLOOP_DEBUG=1` to also print the traceback (of any failure). Runner `result.json` or a Codex session record line holding an unpaired surrogate escape (`\ud800` to `\udfff` alone) records the attempt invalid, since no receipt could hold it. A `dispatch` that gets a second SIGTERM, SIGINT or SIGHUP after its runner has stopped, while it is still recording, ends by that signal's default action and prints nothing (a shell reports 128+N: 143, 130, 129); `running.json` stays and `receipt` completes the attempt.

## Precedence when records disagree

What was requested comes from the dispatch record, and `command.json` and `result.json` must both agree with it. What ran comes from Codex's rollout. Any disagreement between them makes the call invalid; neither side is preferred. A rollout that is missing, from an unvalidated CLI version or of unfamiliar structure makes the call unverifiable (infrastructure), never counted.
