#!/usr/bin/env python3
"""
Executable tests for planloop.py (quartz-rs-lur). Every case builds its own
throwaway git repository, fake Beads database, fake runner artifacts and fake
Codex session store under a temporary directory; nothing touches the live
repository, live Beads, live plans or the network. Run, from anywhere:
  python3 .claude/skills/planloop/tests/test_planloop.py           (whole suite, one process per test, per CPU)
  python3 .../test_planloop.py -j 16 tests.test_planloop.Gate      (any unittest names)
  python3 .../test_planloop.py --times /tmp/planloop-times.json    (longest first from the last green run)
  python3 .../test_planloop.py --serial tests.test_planloop.Gate   (in one process, plain unittest)
  PLANLOOP_TEST_TMP=/mnt/c/... python3 .../test_planloop.py        (drvfs)
Options, exit codes and what fails a run: run_parallel.py, which runs it.
"""
import atexit
import contextlib
import errno
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "scripts" / "planloop.py"
_spec = importlib.util.spec_from_file_location("fake_reviewer", HERE / "fake_reviewer.py")
FAKE_REVIEWER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FAKE_REVIEWER)
OLD_TOOL = HERE / "fixtures" / "planloop_c391e6b.py"
BEAD = "qz-abc"
RUN = "qz-abc.pl1"
OBLIGATION = "The importer must reject a file whose checksum is already loaded."
BUNDLED = "staging already has a bundle and revision.json is in place: publish it"
T, M = 250000, 25000
PID_NS = os.stat("/proc/self/ns/pid").st_ino
FAR = ("unshare", "--user", "--map-current-user", "--pid", "--fork", "--kill-child", "--mount-proc")
WSL = ("a WSL distribution restarted while its VM runs keeps the boot id but gets a new PID namespace, so what a crash "
       "left before that restart is settled this way)")
FIXTURES = []


def plan_text(rev, answers=(), extra_design=(), removed=(), shrink=(), risks=("RR1: the archive may lag by a day",),
              drop_design=False, extra_ids=()):
    design = ["## Design", "Use INV1 throughout.", "Line two of the design.", "Line three of the design.",
              *extra_design]
    risk_lines = ["## Residual risks", *[f"- {r}" for r in risks]] if risks else []
    log = ["## Change log", *[f"- {a}" for a in answers], *[f"- REMOVED {r}" for r in removed],
           *[f"- SHRINK {s}" for s in shrink]]
    body = [f"# PLAN {BEAD}: importer dedupe (revision {rev}, 2026-10-22)", "", "## Goal", "Meet OB1.", "",
            *([] if drop_design else design), "", *risk_lines, "", *log, "", "## Artifact inventory"]
    heads = ["## Goal"] + ([] if drop_design else ["## Design"]) + (["## Residual risks"] if risks else []) + \
        ["## Change log", "## Artifact inventory"]
    ids = ["OB1"] + ([] if drop_design else ["INV1"]) + (["RR1"] if risks else []) + list(extra_ids)
    body += [f"- section: {h}" for h in heads] + [f"- id: {i}" for i in ids]
    return "\n".join(body) + "\n"


def review(verdict="APPROVED", findings=(), coverage=("plan read in full",)):
    return {"verdict": verdict, "summary": "fake review", "findings": list(findings),
            "coverage": list(coverage), "limitations": ["fake"]}


def finding(fid, severity="high"):
    return {"id": fid, "severity": severity, "path": "plan.md", "evidence": f"concrete failure {fid}",
            "fix": "do the thing"}


A5_OLD = "A5 (no unsignalled live loss goes unhandled) is met by the restoration sweep."
A8_OLD = "A8: a periodic sweep every 300 s while continuity holds bounds the evidence's age."
A7_OLD = ("A7: a published fill whose commission cannot be sent again is a `commission_due` expectation written "
          "ahead of the fill and named `uncommissioned` from that durable record.")
WEAK = {A5_OLD: "A5 (every signalled live loss handled) is met by the restoration sweep.",
        A8_OLD: "A8: a periodic sweep every 300 s bounds the evidence's age.",
        A7_OLD: "A7: a published fill whose commission cannot be sent again is a `commission_due` named "
                "`uncommissioned`."}
FAITHFUL = {A5_OLD: "A5: no unsignalled live loss goes unhandled (restoration sweep).",
            A8_OLD: "A8: while continuity holds, a 300 s periodic sweep bounds evidence age.",
            A7_OLD: "A7: a `commission_due` expectation, written ahead of the fill, names a published fill "
                    "`uncommissioned` from that durable record when its commission cannot be sent again."}
BASE = (("## Goal", ("Meet OB1.",)),
        ("## Design", ("Use INV1 throughout.", "Line two of the design.", "Line three of the design.")),
        ("## 11. Obligations", (A5_OLD, A8_OLD, A7_OLD)))
SHRINK_DESIGN = "SHRINK ## Design: dropped line three, it restated the design; no obligation affected"
SHRINK_OBL = "SHRINK ## 11. Obligations: tightened the wording of the labelled guarantees; no obligation affected"
SHRINK_DETAIL = "SHRINK ## Detail: cut padding lines that restated the design; no obligation affected"
PLAN_IDS = re.compile(r"\b(?:OB|INV|RR|AC|EV)\d+\b")
LOCKING = (("publish", "--run", RUN, "--recover"),
           ("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium"),
           ("findings", "propose", "--run", RUN), ("state", "--run", RUN, "--set", "active", "--reason", "recovering"),
           ("planner", "--run", RUN, "--model", "opus", "--quote", "use Opus to plan"),
           ("reviewers", "--run", RUN, "--model", "gpt-6-astra", "--gate-model", "gpt-6-astra", "--quote", "keep astra"),
           ("gate", "--run", RUN, "--publish"))


def keep(*ids):
    return [f"PRESERVED {i}: stated where it was in the previous revision, wording unchanged"
            for i in (ids or ("OB1", "INV1", "RR1"))]


def make_plan(rev, sections=BASE, log=(), preamble=(), title="importer dedupe",
              risks=("RR1: the archive may lag by a day",)):
    sections = list(sections) + ([("## Residual risks", [f"- {r}" for r in risks])] if risks else [])
    sections.append(("## Change log", [f"- {e}" for e in log]))
    body, used = [f"# PLAN {BEAD}: {title} (revision {rev}, 2026-10-22)", *preamble, ""], set()
    for head, lines in sections:
        body += [head, *lines, ""]
        used |= set(PLAN_IDS.findall("\n".join(l for l in [head, *lines] if not re.match(r"^\s*[-*]?\s*REMOVED\s", l))))
    heads = [h for h, _ in sections] + ["## Artifact inventory"]
    body += ["## Artifact inventory", *[f"- section: {h}" for h in heads], *[f"- id: {i}" for i in sorted(used)]]
    return "\n".join(body) + "\n"


def edit(sections, mapping=None, drop=(), add=None):
    mapping, add = mapping or {}, add or {}
    return tuple((h, tuple(mapping.get(l, l) for l in lines if l not in drop) + tuple(add.get(h, ())))
                 for h, lines in sections)


def pad(start, count):
    return tuple(f"Detail line {i:05d} of the padding that makes this plan large enough to matter."
                 for i in range(start, start + count))


def big(rev, start, count, extra=(), log=()):
    return make_plan(rev, BASE + (("## Detail", pad(start, count) + tuple(extra)),), log=log)


def sized(rev, target, start, count, log=()):
    k = target - len(big(rev, start, count, log=log)) - 1
    assert k > 0, k
    return big(rev, start, count, extra=("z" * k,), log=log)


def growth(new, old):
    d = len(new) - len(old)
    return f"{d:+,} bytes ({d / len(old) * 100:+.2f}%)"


def tree(root, skip=()):
    out = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0].startswith(".lock") or rel.parts[0] in skip:
            continue
        out[str(rel)] = path.read_bytes() if path.is_file() else None
    return out


def observation(f, at):
    out = f.repo / "plans" / "ev1.out"
    out.write_text("")
    query = "SELECT count(*) FROM backfill WHERE active"
    record = {"schema": "planloop-evidence/1", "id": "EV1", "claim": "no backfill is running", "kind": "sql",
              "source": "fixture", "query": query, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
              "inputs": [], "observation_window": None, "collected_at": at, "snapshot": None, "group": None,
              "status": "empty", "truncated": False, "claim_needs_complete": True,
              "match_proof": "matches when a backfill row is active",
              "limits": {"max_rows": 1000, "max_bytes": 1048576}, "limits_justification": None, "row_count": 0,
              "bytes": 0, "output": "plans/ev1.out", "output_sha256": hashlib.sha256(b"").hexdigest(),
              "attempts": [{"at": at, "outcome": "empty", "backoff_s": 0}],
              "validity": {"type": "observation", "max_age_s": 3600, "must_remain_current": False}}
    (f.repo / "plans" / "ev1.json").write_text(json.dumps(record))


def expected_lapse(before, changes):
    """The before/after rule of DC2(b): a saved `gate --run` (stdout, exit code) of a fully approved run, and the
    revalidation list E of its HEAD, give the expected (stdout, exit code) once exactly those inputs changed."""
    stdout, code = before
    lines = stdout.splitlines()
    assert code == 0 and lines and lines[-1].startswith("PLAN APPROVED") and not any(l.startswith("FAIL") for l in lines)
    evidence = [c.split() for c in changes if c.startswith("evidence ")]
    out = []
    for line in lines:
        if line == "PASS  [mechanical] gate receipt re-derived from runner and Codex records matches the stored receipt":
            line = "FAIL" + line[4:]
        elif line == "PASS  [mechanical] gate call verified":
            line = f"FAIL  [mechanical] gate call verified: relevant inputs changed during the review: {changes[:5]}"
        elif line == "PASS  [mechanical] relevant live inputs unchanged since the bundle was frozen":
            line = "FAIL" + line[4:] + ": " + "; ".join(changes)
        elif evidence and line.startswith("PASS  [mechanical] bundled evidence supports its claims"):
            line = "FAIL" + line[4:] + ": " + "; ".join(f"{e[1]}: input {e[3]} changed since collection" for e in evidence)
        out.append(line)
    out[-1] = f"NOT APPROVED: {sum(l.startswith('FAIL  ') for l in out)} check(s) failed"
    return "\n".join(out) + "\n", 1


class Fixture:
    def __init__(self, test):
        base = os.environ.get("PLANLOOP_TEST_TMP")
        self.root = Path(tempfile.mkdtemp(prefix="planloop-test-", dir=base))
        test.addCleanup(self.cleanup)
        FIXTURES.append(self)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.rs").write_text("fn main() {}\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "req.md").write_text(f"# Requirements\n\n{OBLIGATION}\n")
        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "brief.md").write_text("Rubric: contradictions, missing requirements, ...\n")
        (self.repo / ".gitignore").write_text("*.pyc\n")
        (self.repo / "AGENTS.md").write_text("# Agent Instructions\n\nUse bd for tracking.\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.db = self.root / "bd.json"
        self.db.write_text(json.dumps({"issues": {BEAD: {"id": BEAD, "title": "importer", "status": "open",
                                                         "description": "Reject duplicate archives.",
                                                         "notes": "", "acceptance_criteria": "", "design": "",
                                                         "metadata": {}, "parent": None}},
                                       "counters": {}, "faults": [], "faults_loaded": True}))
        self.sessions = self.root / "codex-sessions"
        self.isolated_base = Path(tempfile.mkdtemp(prefix="planloop-iso-"))
        self.state = self.root / "state"
        self.review_file = self.root / "review.json"
        self.env = {**os.environ, "PLANLOOP_BD": f"{sys.executable} {HERE / 'fake_bd.py'}",
                    "FAKE_BD_DB": str(self.db), "PLANLOOP_RUNNER": f"{sys.executable} {HERE / 'fake_runner.py'}",
                    "PLANLOOP_STATE": str(self.state), "PLANLOOP_CODEX_SESSIONS": str(self.sessions),
                    "PLANLOOP_ISOLATED": str(self.isolated_base / "isolated"),
                    "FAKE_REVIEW": str(self.review_file), "FAKE_LIVE_REPO": str(self.repo.resolve()),
                    "PLANLOOP_LOCK_TIMEOUT": "1"}
        self.versions = self.root / "versions.txt"
        shutil.copy(HERE.parent / "scripts" / "codex_rollout_versions.txt", self.versions)
        self.env["PLANLOOP_ROLLOUT_VERSIONS"] = str(self.versions)
        for key in ("PLANLOOP_CRASH_AT", "FAKE_MODE", "PLANLOOP_NOW"):
            self.env.pop(key, None)
        self.transcripts = self.root / "agents"
        self.transcripts.mkdir()
        self.nonces = {}
        self.call = 0
        self.outputs = []
        self.rdir = self.repo / "plans" / "planloop" / RUN

    def cleanup(self):
        for path in self.rdir.glob("reviews/*/input/dispatch.json"):
            with contextlib.suppress(OSError, ValueError, AttributeError):
                scope = Path(json.loads(path.read_text()).get("scope") or "/nowhere")
                if scope.name.startswith("planloop-") and scope.suffix == ".scope":
                    (scope / "cgroup.kill").write_text("1")
                    for _ in range(100):
                        if not scope.exists():
                            break
                        time.sleep(0.05)
        if (self.isolated_base / "isolated").exists():
            os.chmod(self.isolated_base / "isolated", 0o755)
        for base in (self.isolated_base,):
            for dirpath, dirnames, filenames in os.walk(base):
                os.chmod(dirpath, 0o755)
            shutil.rmtree(base, ignore_errors=True)
        for dirpath, dirnames, filenames in os.walk(self.root):
            os.chmod(dirpath, 0o755)
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def tool(self, *args, env=None, expect=0, stdin=None, old=False):
        proc = subprocess.run([sys.executable, str(old if isinstance(old, Path) else OLD_TOOL if old else TOOL), *args],
                              cwd=self.repo,
                              capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=300, input=stdin)
        self.last = proc
        self.outputs.append(proc.stdout + proc.stderr)
        if expect is not None and proc.returncode != expect:
            raise AssertionError(f"planloop {' '.join(args)} exited {proc.returncode}, expected {expect}\n"
                                 f"STDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}")
        return proc

    def bd(self):
        return json.loads(self.db.read_text())

    def set_bd(self, db):
        self.db.write_text(json.dumps(db))

    def fault(self, op, mode):
        db = self.bd()
        db["faults"].append({"op": op, "mode": mode})
        self.set_bd(db)

    def run_bead(self):
        return next(i for i in self.bd()["issues"].values() if i["metadata"].get("planloop_key") == f"run:{RUN}")

    def finding_bead(self, fid):
        return next(i for i in self.bd()["issues"].values()
                    if i["metadata"].get("planloop_key") == f"finding:{RUN}:{fid}")

    def init(self, *extra, old=False, backend="codex"):
        # A new run defaults to the claude backend (Mike, 2026-11-14); the Codex tests ask for codex explicitly.
        # The old tool predates backends, and a run it creates is a Codex run.
        self.tool("init", "--run", RUN, "--bead", BEAD, *(extra or ("--track", "ordinary", "--risk-domains", "none",
                  "--rationale", "test importer change with no persistence or ordering semantics")),
                  *(() if old or backend is None else ("--reviewer-backend", backend)), old=old)

    def claude_review(self, response, kind="working", call=None, attempt=1, expect=0, prompt_edit=None,
                      receipt=True, transcript=None, **opts):
        """dispatch for the claude backend, then a fake background Plan agent's transcript, then receipt."""
        if call is None:
            self.call += 1 if attempt == 1 else 0
            call = self.call
        self.tool("dispatch", "--run", RUN, "--call", str(call), "--attempt", str(attempt), "--kind", kind,
                  "--effort", "high")
        self.launched = self.last.stdout
        record = self.dispatched(call, attempt)
        prompt = (self.rdir / "reviews" / f"call-{call:03d}-a{attempt}" / "input" / "prompt.txt").read_text()
        if prompt_edit:
            prompt = prompt_edit(prompt)
        path = transcript or FAKE_REVIEWER.write(self.transcripts, uuid.uuid4().hex[:17], prompt, response,
                                                 record["snapshot"], str(self.repo), **opts)
        self.transcript_path = path
        if receipt:
            self.tool("receipt", "--run", RUN, "--call", str(call), "--attempt", str(attempt), "--transcript",
                      str(path), expect=expect)
        return call

    def transcript(self, text, finished=True, delivered=True, name=None, agent_type="Plan", model="opus"):
        name = name or uuid.uuid4().hex[:8]
        path = self.transcripts / f"agent-{name}.jsonl"
        rows = [{"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "SubagentHandback", "input": {"message": text}}]}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1",
                     "content": [{"type": "text", "text": '{"success":true,"message":"Report delivered."}'
                                  if delivered else '{"success":false}'}]}]}}]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        (self.transcripts / f"agent-{name}.meta.json").write_text(json.dumps({"finished": finished,
                                                                              "agentType": agent_type,
                                                                              "model": model}))
        return path

    def wrap(self, rev, nonce, plan, end=True):
        out = f"Here is the plan.\n<<<PLANLOOP-HANDBACK run={RUN} revision={rev} nonce={nonce}>>>\n{plan}"
        if end:
            out += f"<<<PLANLOOP-HANDBACK-END run={RUN} revision={rev} nonce={nonce}>>>\n"
        return out

    def inputs(self, discovery=None, evidence=(), obligations=None, repo_files=("docs/req.md", "src/a.rs"),
               dirs=("src",)):
        disc = discovery or {"schema": "planloop-discovery/1",
                             "searches": [{"command": "command grep -rn checksum docs", "purpose": "requirements",
                                           "hits": 1, "match_proof": None}],
                             "sources": [{"path": "docs/req.md", "class": "binding", "reason": "requirement"},
                                         {"path": "src/a.rs", "class": "candidate", "reason": "code touched"}],
                             "known_omissions": []}
        (self.root / "discovery.json").write_text(json.dumps(disc))
        shutil.copy(self.root / "discovery.json", self.repo / "plans" / "discovery.json")
        spec = {"schema": "planloop-inputs/1", "brief": "plans/brief.md", "repo_files": list(repo_files),
                "dir_inventories": list(dirs), "beads": [{"id": BEAD, "fields": []}],
                "obligations": obligations if obligations is not None else
                [{"id": "OB1", "source": "docs/req.md", "section": "Requirements", "text": OBLIGATION}],
                "evidence": list(evidence), "discovery": "plans/discovery.json"}
        path = self.root / f"inputs-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(spec))
        return path

    def hand(self, rev, plan, expect=0, model="opus", old=False):
        nonce = uuid.uuid4().hex[:16]
        self.tool("handback", "--run", RUN, "--revision", str(rev), "--nonce", nonce,
                  "--transcript", str(self.transcript(self.wrap(rev, nonce, plan), model=model)), expect=expect, old=old)
        return nonce

    def stage(self, rev, plan, inputs=None, expect_handback=0, model="opus", old=False):
        nonce = self.hand(rev, plan, expect_handback, model, old)
        if expect_handback:
            return None
        self.tool("bundle", "--run", RUN, "--revision", str(rev), "--nonce", nonce,
                  "--inputs", str(inputs or self.inputs()), old=old)
        return nonce

    def publish(self, rev, plan, inputs=None, model="opus", old=False):
        nonce = self.stage(rev, plan, inputs, model=model, old=old)
        self.published = self.tool("publish", "--run", RUN, "--revision", str(rev), "--nonce", nonce, old=old)
        if rev > 1:
            self.tool("findings", "propose", "--run", RUN, old=old)
        return nonce

    def review(self, response, kind="working", effort="medium", mode="", expect=0, call=None, attempt=1, old=False):
        self.review_file.write_text(json.dumps(response))
        if call is None:
            self.call += 1 if attempt == 1 else 0
            call = self.call
        env = {"FAKE_MODE": mode} if mode else {}
        self.tool("dispatch", "--run", RUN, "--call", str(call), "--attempt", str(attempt), "--kind", kind,
                  "--effort", effort, env=env, expect=expect, old=old)
        return call

    def ingest(self, call, mapping, attempt=1, expect=0, old=False):
        path = self.root / f"map-{call}-{attempt}.json"
        path.write_text(json.dumps(mapping))
        return self.tool("findings", "ingest", "--run", RUN, "--call", str(call), "--attempt", str(attempt),
                         "--map", str(path), expect=expect, old=old)

    def check(self, plan, expect, *extra):
        return self.tool("handback", "--run", RUN, "--check", *extra, stdin=plan, expect=expect)

    def head(self):
        return json.loads((self.rdir / "HEAD").read_text())["revision"]

    def staged(self, rev, nonce):
        return json.loads((self.rdir / f".staging-{rev:03d}-{nonce}" / "handback.json").read_text())

    def manifest(self, rev):
        return json.loads((self.rdir / f"rev-{rev:03d}" / "bundle" / "manifest.json").read_text())

    def meanings(self, rev):
        return [i for i in self.manifest(rev)["items"] if i["type"] == "meaning_obligation"]

    def lines_for(self, rev, verdict="preserved", skip=()):
        return [f"meaning revision {i['revision']} {u}: {verdict}" for i in self.meanings(rev) for u in i["units"]
                if u not in skip]

    def artifacts(self, call=1, attempt=1):
        try:
            return Path(self.dispatched(call, attempt)["artifacts_root"])
        except OSError:
            return self.state / RUN / "calls" / "none"

    def dispatched(self, call, attempt=1):
        return json.loads((self.rdir / "reviews" / f"call-{call:03d}-a{attempt}" / "input" / "dispatch.json").read_text())

    def feedback(self, call, attempt=1):
        return (self.rdir / "reviews" / f"call-{call:03d}-a{attempt}" / "input" / "feedback.md").read_text()

    def size_decision(self, sid, rev, ceiling, **over):
        path = self.rdir / "decisions" / f"{sid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = self.rdir / f"rev-{rev:03d}" / "revision.json"
        plan_sha = json.loads(record.read_text())["plan_sha256"] if record.exists() else "0" * 64
        path.write_text(json.dumps({"schema": "planloop-size-decision/1", "id": sid, "by": "Mike",
                                    "quote": "accept this size for the shrink", "recorded_at": "2026-10-22T23:00:00Z",
                                    "recorded_by": "orchestrator", "revision": rev, "plan_sha256": plan_sha,
                                    "ceiling_bytes": ceiling, **over}))
        return path

    def receipt(self, call, attempt=1):
        return json.loads((self.repo / "plans" / "planloop" / RUN / "reviews" / f"call-{call:03d}-a{attempt}"
                           / "receipt.json").read_text())

    def accept_risk(self, text="the archive may lag by a day", did="D1"):
        import hashlib
        path = self.repo / "plans" / "planloop" / RUN / "decisions" / f"{did}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "planloop-decision/1", "id": did, "by": "Mike",
                                    "quote": "accept RR1", "recorded_at": "2026-10-22T23:00:00Z",
                                    "recorded_by": "orchestrator",
                                    "subjects": [{"id": "RR1", "text_sha256": hashlib.sha256(text.encode()).hexdigest()}],
                                    "outcome": "accepted-risk", "follow_up": None}))

    def to_gate_ready(self):
        self.init()
        self.publish(1, plan_text(1))
        c = self.review(review("REVISE", [finding("F1")]))
        self.ingest(c, {"F1": "new"})
        self.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        c = self.review(review("APPROVED", coverage=["plan read in full", "finding R1: resolved"]))
        self.ingest(c, {})
        self.accept_risk()


class Receipts(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()
        self.f.publish(1, plan_text(1))

    def invalid(self, mode, needle, kind="working", effort="medium"):
        c = self.f.review(review(), kind=kind, effort=effort, mode=mode, expect=1)
        r = self.f.receipt(c)
        self.assertEqual(r["status"], "invalid")
        self.assertTrue(any(needle in x for x in r["reasons"]), r["reasons"])
        return r

    def test_counted_review_records_effective_settings(self):
        c = self.f.review(review())
        r = self.f.receipt(c)
        self.assertEqual(r["status"], "counted")
        self.assertEqual(r["effective"]["effort"], "medium")
        self.assertTrue(r["fresh"])

    def test_claimed_high_but_rollout_medium_is_a_downgrade(self):
        self.invalid("rollout_effort=medium", "downgrade", kind="gate", effort="high")

    def test_gate_that_resumed_a_session_is_not_fresh(self):
        r = self.invalid("resume", "fresh", kind="gate", effort="high")
        self.assertFalse(r["fresh"])

    def test_earlier_user_turn_is_not_fresh(self):
        self.invalid("second_user_turn", "fresh")

    def test_a_separate_context_turn_carrying_the_snapshots_agents_md_is_still_fresh(self):
        c = self.f.review(review(), mode="context_turn=agents")
        r = self.f.receipt(c)
        self.assertEqual(r["status"], "counted", r["reasons"])
        self.assertTrue(r["fresh"])

    def test_a_context_turn_whose_agents_md_differs_from_the_snapshot_is_not_fresh(self):
        self.invalid("context_turn=tampered", "fresh")

    def test_a_context_turn_carrying_anything_else_is_not_fresh(self):
        self.invalid("context_turn=extra", "fresh")

    def test_a_context_turn_naming_another_directory_is_not_fresh(self):
        self.invalid("context_turn=elsewhere", "fresh")

    def test_prompt_with_another_bundle_is_rejected(self):
        self.invalid("wrong_bundle", "bundle marker")

    def test_event_stream_naming_another_session_is_rejected(self):
        self.invalid("wrong_thread", "thread ids")

    def test_malformed_reply_is_rejected(self):
        self.invalid("malformed_reply", "reply.txt")

    def test_duplicate_key_in_result_is_rejected(self):
        self.invalid("dup_key_result", "duplicate JSON key")

    def test_missing_session_is_rejected(self):
        self.invalid("no_session", "session_id")

    def test_missing_rollout_is_unverifiable_infrastructure(self):
        r = self.invalid("no_rollout", "unverifiable")
        self.assertTrue(r["infrastructure"])

    def test_unfamiliar_cli_version_is_unverifiable(self):
        self.invalid("rollout_version=0.200.0", "has not been validated")

    def test_new_codex_version_needs_rollout_check_then_counts(self):
        r = self.invalid("rollout_version=0.160.0", "has not been validated")
        adir = r["artifacts"]["dir"]
        self.f.tool("rollout-check", "--artifacts", adir)
        self.assertNotIn("0.160.0", self.f.versions.read_text())
        self.f.tool("rollout-check", "--artifacts", adir, "--accept")
        self.assertIn("0.160.0", self.f.versions.read_text())
        self.f.review(review(), mode="rollout_version=0.160.0", call=r["call"], attempt=2)

    def test_rollout_check_refuses_a_mismatching_rollout(self):
        r = self.invalid("rollout_version=0.160.0,rollout_effort=low", "has not been validated")
        self.f.tool("rollout-check", "--artifacts", r["artifacts"]["dir"], "--accept", expect=1)
        self.assertNotIn("0.160.0", self.f.versions.read_text())

    def test_live_checkout_read_voids_review(self):
        self.invalid("live_read", "live checkout")

    def test_relevant_file_changed_during_review(self):
        self.invalid("touch=src/a.rs", "src/a.rs")

    def test_new_file_in_inventoried_directory(self):
        self.invalid("add=src/b.rs", "directory src")

    def test_deleted_source_during_review(self):
        self.invalid("delete=docs/req.md", "docs/req.md")

    def test_binding_bead_text_change_invalidates(self):
        self.invalid(f"bead_text={BEAD}", "bead qz-abc")

    def test_unrelated_updates_do_not_invalidate(self):
        (self.f.repo / "unrelated.txt").write_text("x\n")
        self.f.git("add", "-A")
        self.f.git("commit", "-qm", "unrelated")
        c = self.f.review(review(), mode=f"bead_notes={BEAD}")
        self.assertEqual(self.f.receipt(c)["status"], "counted")
        self.f.ingest(c, {})
        self.f.tool("ledger", "--run", RUN)
        c = self.f.review(review())
        self.assertEqual(self.f.receipt(c)["status"], "counted")

    def test_effort_floor_and_unsupported_effort(self):
        self.f.review_file.write_text(json.dumps(review()))
        for kind, effort, needle in (("working", "low", "below this run's floor"), ("gate", "medium", "high effort"),
                                     ("working", "xhigh", "not used by planloop"), ("triage", "medium", "low effort")):
            self.f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", kind,
                        "--effort", effort, expect=1)
            self.assertIn(needle, self.f.last.stderr)
        self.assertFalse((self.f.repo / "plans/planloop" / RUN / "reviews").exists())


class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()
        self.f.publish(1, plan_text(1))

    def raise_and_fix(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"})
        self.f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))

    def test_output_or_reasoning_mentioning_the_live_path_is_not_a_read(self):
        c = self.f.review(review(), mode="output_mentions_live")
        self.assertEqual(self.f.receipt(c)["status"], "counted")

    def test_run_area_never_enters_overlay_or_inventories(self):
        c = self.f.review(review())
        self.f.ingest(c, {})
        self.f.publish(2, plan_text(2), inputs=self.f.inputs(dirs=("src", "plans")))
        manifest = json.loads((self.f.repo / "plans/planloop" / RUN / "rev-002/bundle/manifest.json").read_text())
        paths = [e["path"] for i in manifest["items"] if i["type"] in ("overlay", "dir_inventory") for e in i["entries"]]
        self.assertFalse([p for p in paths if p.startswith("plans/planloop")], paths)
        c = self.f.review(review())
        self.assertEqual(self.f.receipt(c)["status"], "counted")

    def test_commit_during_bundle_is_refused(self):
        (self.f.repo / "src" / "a.rs").write_text("fn main() { wip(); }\n")
        self.f.fault("show", "commit")
        nonce = uuid.uuid4().hex[:16]
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", nonce,
                    "--transcript", str(self.f.transcript(self.f.wrap(2, nonce, plan_text(2)))))
        self.f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(self.f.inputs()),
                    expect=1)
        self.assertIn("changed while the bundle was built", self.f.last.stderr)
        self.f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(self.f.inputs()))

    def test_unparseable_contradictory_or_missing_coverage_voids_the_call(self):
        self.raise_and_fix()
        for coverage, needle in ((["finding R1: resolved (now rejects duplicates)"], "not exactly"),
                                 (["finding R1: resolved", "finding R1: unresolved"], "more than once"),
                                 (["plan read in full"], "did not report")):
            c = self.f.review(review("APPROVED", coverage=coverage), expect=1, call=self.f.call + 1)
            self.f.call = c
            self.assertTrue(any(needle in r for r in self.f.receipt(c)["reasons"]), self.f.receipt(c)["reasons"])
            self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed the reviewer")

    def test_stale_review_cannot_verify_a_newer_fix(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"})
        self.f.review_file.write_text(json.dumps(review("APPROVED", coverage=["finding R1: resolved"])))
        self.f.tool("dispatch", "--run", RUN, "--call", "2", "--attempt", "1", "--kind", "working", "--effort",
                    "medium", env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        self.f.publish(2, plan_text(2, answers=["FIX R1: add the lookup"]))
        self.f.tool("receipt", "--run", RUN, "--call", "2", "--attempt", "1", expect=None)
        r = self.f.receipt(2)
        self.assertEqual((r["status"], r["revision"]), ("counted", 1), r["reasons"])
        self.f.ingest(2, {})
        self.assertEqual(self.f.finding_bead("R1")["metadata"]["planloop_state"], "fix_proposed")

    def test_findings_are_ingested_in_call_order(self):
        c1 = self.f.review(review("REVISE", [finding("F1")]))
        c2 = self.f.review(review("REVISE", [finding("F2")]), expect=1)
        self.assertIn("not ingested", self.f.last.stderr)
        self.f.ingest(c1, {"F1": "new"})

    def test_decided_redesign_finding_unblocks(self):
        self.raise_and_fix()
        for rev in (3,):
            c = self.f.review(review("REVISE", [finding("R1")]))
            self.f.ingest(c, {"R1": "R1"})
            self.f.publish(rev, plan_text(rev, answers=[f"FIX R1: attempt {rev}"]))
        c = self.f.review(review("REVISE", [finding("R1")]))
        self.f.ingest(c, {"R1": "R1"})
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_redesign_required"], "R1")
        path = self.f.repo / "plans/planloop" / RUN / "decisions" / "D2.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "planloop-decision/1", "id": "D2", "by": "Mike", "quote": "out of scope",
                                    "recorded_at": "2026-10-22T23:00:00Z", "recorded_by": "orchestrator",
                                    "subjects": [{"id": "R1", "text_sha256": None}], "outcome": "scope-out",
                                    "follow_up": None}))
        self.f.tool("findings", "decide", "--run", RUN, "--decision", str(path))
        self.f.tool("findings", "check", "--run", RUN)
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_redesign_required"], "")

    def test_init_escalates_an_existing_run(self):
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "escalated", "--risk-domains", "idempotency",
                    "--rationale", "review showed the import retry must be idempotent")
        meta = self.f.run_bead()["metadata"]
        self.assertEqual((meta["planloop_track"], meta["planloop_risk_domains"]), ("escalated", "idempotency"))
        self.assertIn("idempotent", meta["planloop_risk_rationale"])
        self.f.review(review(), effort="medium", expect=1)
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "none",
                    "--rationale", "trying to lower the track again", expect=1)

    def test_dispatch_failure_before_reservation_leaves_no_wedge(self):
        self.f.fault("list", "fail")
        self.f.review_file.write_text(json.dumps(review()))
        self.f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort",
                    "medium", expect=2)
        self.f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort",
                    "medium")

    def test_receipt_refused_while_review_runs(self):
        self.f.review_file.write_text(json.dumps(review()))
        self.f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort",
                    "medium", env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        time.sleep(0.1)
        running = self.f.repo / "plans/planloop" / RUN / "reviews/call-001-a1/running.json"
        owner = json.loads(running.read_text())
        owner.update(pid=sleeper.pid, start=Path(f"/proc/{sleeper.pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
        running.write_text(json.dumps(owner))
        self.f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
        sleeper.kill()
        sleeper.wait()
        self.f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")

    def test_invalid_streak_across_calls_blocks(self):
        for _ in range(3):
            self.f.review(review(), mode="no_rollout", expect=1)
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_state"], "blocked")
        self.f.review(review(), expect=1)

    def test_tampered_receipt_fails_the_gate(self):
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.accept_risk()
        path = self.f.repo / "plans/planloop" / RUN / "reviews" / f"call-{c:03d}-a1" / "receipt.json"
        r = json.loads(path.read_text())
        r["usage"] = {"input_tokens": 1}
        path.write_text(json.dumps(r))
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.assertIn("matches the stored receipt", self.f.last.stdout)

    def test_pinned_reviewer_model_is_checked(self):
        db = json.loads((self.f.repo / "plans/planloop" / RUN / "run.json").read_text())
        db["reviewer_model"] = "gpt-6-astra"
        (self.f.repo / "plans/planloop" / RUN / "run.json").write_text(json.dumps(db))
        self.f.publish(2, plan_text(2))
        c = self.f.review(review())
        r = self.f.receipt(c)
        self.assertEqual((r["status"], r["effective"]["model"]), ("counted", "gpt-6-astra"))

    def test_the_gate_runs_on_its_own_model(self):
        self.f.tool("reviewers", "--run", RUN, "--model", "gpt-6-sol", "--gate-model", "gpt-6-astra",
                    "--quote", "", expect=1)
        self.f.tool("reviewers", "--run", RUN, "--model", "gpt-6-sol", "--gate-model", "gpt-6-astra",
                    "--quote", "keep sol until the final gate then use astra")
        db = json.loads((self.f.repo / "plans/planloop" / RUN / "run.json").read_text())
        self.assertEqual((db["reviewer_model"], db["gate_model"]), ("gpt-6-sol", "gpt-6-astra"))
        self.assertEqual(db["model_changes"][0]["quote"], "keep sol until the final gate then use astra")
        self.f.publish(2, plan_text(2))
        c = self.f.review(review())
        self.assertEqual((self.f.receipt(c)["status"], self.f.receipt(c)["effective"]["model"]), ("counted", "gpt-6-sol"))
        self.f.ingest(c, {})
        g = self.f.review(review(), kind="gate", effort="high")
        r = self.f.receipt(g)
        self.assertEqual((r["status"], r["requested"]["model"], r["effective"]["model"]),
                         ("counted", "gpt-6-astra", "gpt-6-astra"))

    def test_a_run_file_without_a_gate_model_still_loads(self):
        path = self.f.repo / "plans/planloop" / RUN / "run.json"
        db = json.loads(path.read_text())
        db.pop("gate_model", None)
        db.pop("model_changes", None)
        path.write_text(json.dumps(db))
        self.f.tool("ledger", "--run", RUN)

    def test_relative_climb_out_of_the_snapshot_voids_the_review(self):
        for mode in ("sibling_read", "relative_state_read"):
            c = self.f.review(review(), mode=mode, expect=1, call=self.f.call + 1)
            self.f.call = c
            self.assertTrue(any("climbing above" in x for x in self.f.receipt(c)["reasons"]))
        with self.assertRaises(PermissionError):
            os.listdir(self.f.isolated_base / "isolated")
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed")
        c = self.f.review(review(), mode="relative_parent", call=self.f.call + 1)
        self.f.call = c
        self.assertEqual(self.f.receipt(c)["status"], "counted")
        sys.path.insert(0, str(TOOL.parent))
        import planloop
        root = self.f.root / "climb"
        for d in ("backend/src", "src", "a/b"):
            (root / d).mkdir(parents=True)
        cases = [('/bin/bash -lc "cd backend && sed -n 1,80p ../plans/P.md"', False),
                 ("grep -rn 'OB1 .. OB4' plans", False), ("cat backend/../../x", True),
                 ("cd backend && cd ../.. && ls", True), ("ls ..", True),
                 ("cd src && sed -n 1,80p ../docs/req.md && ls ..", False), ('cat "../../../planloop/x"', True),
                 ("/bin/bash -lc 'cat \"../../../planloop/x\"'", True), ("cat '../x'", True),
                 ('/bin/bash -lc "cat \\"../../p\\""', True), ("(cd a/b); cat ../../../planloop/x", True),
                 ("cd zz/yy/xx; cat ../../../planloop/x", True), ("git diff HEAD~1..HEAD", False),
                 ('command grep -rn ".." src', False), ('find . -path "*/../*"', False),
                 ("cat backend/src/../Cargo.toml", False), ("cd backend; cd ..; cat CLAUDE.md", False),
                 ("cd; cat x", True), ("cd ~ && ls", True), ("sed -n '1,80p' src/a.rs", False),
                 ("cd a/b && cat ../../src/x", False), ("cd", True), ("ls src | head; cd backend && ls ../src", False)]
        wrong = [c for c, want in cases if planloop.climbs_out(c, root) != want]
        self.assertEqual(wrong, [])

    def test_absolute_reads_of_state_or_codex_home_void_the_review(self):
        for mode in ("codex_home", "state_read"):
            c = self.f.review(review(), mode=mode, expect=1, call=self.f.call + 1)
            self.f.call = c
            self.assertTrue(any("outside its private snapshot" in x for x in self.f.receipt(c)["reasons"]))
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed")
        c = self.f.review(review(), call=self.f.call + 1)
        self.f.call = c
        self.assertEqual(self.f.receipt(c)["status"], "counted")

    def test_each_review_runs_in_a_private_copy(self):
        c = self.f.review(review())
        d = json.loads((self.f.repo / "plans/planloop" / RUN / "reviews" / f"call-{c:03d}-a1/input/dispatch.json")
                       .read_text())
        self.assertFalse(Path(d["snapshot"]).exists())
        self.f.ingest(c, {})
        self.f.accept_risk()
        g = self.f.review(review(), kind="gate", effort="high")
        d = json.loads((self.f.repo / "plans/planloop" / RUN / "reviews" / f"call-{g:03d}-a1/input/dispatch.json")
                       .read_text())
        private = Path(d["snapshot"]).parent
        self.assertEqual(sorted(p.name for p in private.iterdir()), [".planloop-reserve", "repo"])
        self.assertNotIn(str(self.f.state), d["snapshot"])
        self.f.ingest(g, {})
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_withdrawal_needs_evidence_and_gate_confirmation(self):
        c = self.f.review(review("REVISE", [finding("F1", "medium")]))
        self.f.ingest(c, {"F1": "new"})
        c = self.f.review(review("APPROVED", coverage=["plan read", "finding R1: withdrawn: no"]), expect=1)
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed")
        why = "finding R1: withdrawn: the importer holds the table lock, so two loads of one file cannot interleave"
        c = self.f.review(review("APPROVED", coverage=["plan read", why]), call=c + 1)
        self.f.call = c
        self.f.ingest(c, {})
        self.assertEqual(self.f.finding_bead("R1")["metadata"]["planloop_state"], "withdrawn")
        self.f.accept_risk()
        g = self.f.review(review(), kind="gate", effort="high", expect=1)
        self.assertTrue(any("did not report" in x for x in self.f.receipt(g)["reasons"]))
        g = self.f.review(review(coverage=["plan read", "finding R1: withdrawal confirmed"]), kind="gate",
                          effort="high", call=g, attempt=2)
        self.f.ingest(g, {}, attempt=2)
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_gate_answering_resolved_for_a_withdrawn_finding_cannot_approve(self):
        c = self.f.review(review("REVISE", [finding("F1", "medium")]))
        self.f.ingest(c, {"F1": "new"})
        why = "finding R1: withdrawn: the importer holds the table lock, so two loads of one file cannot interleave"
        c = self.f.review(review("APPROVED", coverage=["plan read", why]))
        self.f.ingest(c, {})
        self.f.accept_risk()
        g = self.f.review(review(coverage=["plan read", "finding R1: resolved"]), kind="gate", effort="high")
        self.f.ingest(g, {})
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.assertIn("confirmed every withdrawn finding", self.f.last.stdout)

    def test_approval_lapses_when_a_must_remain_current_observation_expires(self):
        import hashlib
        out = self.f.repo / "plans" / "ev1.out"
        out.write_text("")
        query = "SELECT count(*) FROM backfill WHERE active"
        record = {"schema": "planloop-evidence/1", "id": "EV1", "claim": "no backfill is running", "kind": "sql",
                  "source": "fixture", "query": query, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                  "inputs": [], "observation_window": None, "collected_at": "2026-10-22T10:00:00Z", "snapshot": None,
                  "group": None, "status": "empty", "truncated": False, "claim_needs_complete": True,
                  "match_proof": "matches when a backfill row is active", "limits": {"max_rows": 1000,
                  "max_bytes": 1048576}, "limits_justification": None, "row_count": 0, "bytes": 0,
                  "output": "plans/ev1.out", "output_sha256": hashlib.sha256(b"").hexdigest(),
                  "attempts": [{"at": "2026-10-22T10:00:00Z", "outcome": "empty", "backoff_s": 0}],
                  "validity": {"type": "observation", "max_age_s": 3600, "must_remain_current": True}}
        (self.f.repo / "plans" / "ev1.json").write_text(json.dumps(record))
        self.f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
        c = self.f.review(review())
        self.f.ingest(c, {})
        self.f.publish(2, plan_text(2), inputs=self.f.inputs(evidence=["plans/ev1.json"]))
        self.f.accept_risk()
        g = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(g, {})
        self.f.tool("gate", "--run", RUN, "--publish")
        self.f.tool("gate", "--run", RUN)
        self.f.env["PLANLOOP_NOW"] = "2026-10-22T12:00:00Z"
        self.f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("must remain current", self.f.last.stdout)

    def test_only_the_latest_counted_gate_copy_is_kept(self):
        self.f.accept_risk()
        g1 = self.f.review(review(), kind="gate", effort="high", mode="no_rollout", expect=1)
        g1b = self.f.review(review(), kind="gate", effort="high", call=g1, attempt=2)
        self.f.ingest(g1, {}, attempt=2)
        g2 = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(g2, {})
        def copy(call, attempt=1):
            d = json.loads((self.f.repo / "plans/planloop" / RUN / "reviews" / f"call-{call:03d}-a{attempt}" /
                            "input/dispatch.json").read_text())
            return Path(d["snapshot"]).exists()
        self.assertEqual((copy(g1), copy(g1, 2), copy(g2)), (False, False, True))
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_any_lapse_of_approval_lets_the_run_reopen(self):
        self.f.accept_risk()
        g = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(g, {})
        self.f.tool("gate", "--run", RUN, "--publish")
        d = json.loads((self.f.repo / "plans/planloop" / RUN / "reviews" / f"call-{g:03d}-a1/input/dispatch.json")
                       .read_text())
        for dirpath, dirnames, filenames in os.walk(Path(d["snapshot"]).parent):
            os.chmod(dirpath, 0o755)
        shutil.rmtree(Path(d["snapshot"]).parent)
        self.f.tool("gate", "--run", RUN, expect=1)
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "gate copy lost; re-gate")
        g = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(g, {})
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_voided_approval_lets_the_run_continue(self):
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.accept_risk()
        self.f.tool("gate", "--run", RUN, "--publish")
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "x", expect=1)
        (self.f.repo / "docs" / "req.md").write_text(f"# Requirements\n\n{OBLIGATION}\nAnd one more.\n")
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "requirements changed")
        self.f.publish(2, plan_text(2))
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish")


class RiskClassification(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_dispatch_refuses_an_isolated_root_that_ignores_permissions(self):
        self.f.init()
        self.f.publish(1, plan_text(1))
        drvfs = Path("/mnt/c/Users/mikep/AppData/Local/Temp")
        if not drvfs.is_dir():
            self.skipTest("no drvfs path on this machine")
        root = Path(tempfile.mkdtemp(prefix="planloop-drvfs-iso-", dir=drvfs))
        self.addCleanup(shutil.rmtree, root, True)
        self.f.review_file.write_text(json.dumps(review()))
        self.f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort",
                    "medium", env={"PLANLOOP_ISOLATED": str(root / "isolated")}, expect=None)
        if self.f.last.returncode == 0:
            self.skipTest("this drvfs mount honours permissions")
        self.assertEqual(self.f.last.returncode, 2)
        self.assertIn("can still be listed", self.f.last.stderr)

    def test_classification_is_required_and_recorded(self):
        self.f.tool("init", "--run", RUN, "--bead", BEAD, expect=2)
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "ordering",
                    "--rationale", "the importer reorders batches", expect=1)
        self.assertIn("require --track escalated", self.f.last.stderr)
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "escalated", "--risk-domains", "vibes",
                    "--rationale", "the importer reorders batches", expect=1)
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "escalated", "--risk-domains",
                    "ordering,persistence", "--rationale", "the importer reorders batches and changes fsync points")
        meta = self.f.run_bead()["metadata"]
        self.assertEqual((meta["planloop_track"], meta["planloop_min_effort"], meta["planloop_risk_domains"]),
                         ("escalated", "high", "ordering,persistence"))

    def test_jade_risk_domains_are_accepted_and_escalate(self):
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "consent-gate",
                    "--rationale", "the ingest endpoint reads logging_enabled", expect=1)
        self.assertIn("require --track escalated", self.f.last.stderr)
        self.f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "escalated", "--risk-domains",
                    "consent-gate,privacy,authorization,secrets,schema-migration",
                    "--rationale", "ingest gate, kit-code HMAC and a forward-only migration")
        meta = self.f.run_bead()["metadata"]
        self.assertEqual((meta["planloop_track"], meta["planloop_risk_domains"]),
                         ("escalated", "authorization,consent-gate,privacy,schema-migration,secrets"))

    def test_escalated_run_needs_a_fable_planner_and_high_reviews(self):
        self.f.init("--track", "escalated", "--risk-domains", "recovery",
                    "--rationale", "changes how a crashed import resumes")
        nonce = "5555555555555555"
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(1, nonce, plan_text(1)))), expect=1)
        self.assertIn("Fable planner", self.f.last.stderr)
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(1, nonce, plan_text(1)), model="fable")))
        self.f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(self.f.inputs()))
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
        self.f.review(review(), effort="medium", expect=1)
        self.assertIn("below this run's floor high", self.f.last.stderr)
        c = self.f.review(review(), effort="high", call=1)
        self.assertEqual(self.f.receipt(c)["status"], "counted")


    def test_escalated_planner_override_needs_a_recorded_decision(self):
        self.f.init("--track", "escalated", "--risk-domains", "recovery",
                    "--rationale", "changes how a crashed import resumes")
        nonce = "6666666666666666"
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(1, nonce, plan_text(1)), model="opus")), expect=1)
        self.assertIn("Fable planner", self.f.last.stderr)
        self.f.tool("planner", "--run", RUN, "--model", "opus", "--quote", "  ", expect=1)
        self.f.tool("planner", "--run", RUN, "--model", "opus", "--quote", "use Opus to plan")
        meta = self.f.run_bead()["metadata"]
        self.assertEqual(meta["planloop_planner_override"], "opus")
        self.assertIn("use Opus to plan", meta["planloop_planner_override_decision"])
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(1, nonce, plan_text(1)), model="sonnet")), expect=1)
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(1, nonce, plan_text(1)), model="opus")))
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_track"], "escalated")


class Handback(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()

    def handback(self, text, expect=1, finished=True, delivered=True, rev=1, nonce="0123456789abcdef"):
        return self.f.tool("handback", "--run", RUN, "--revision", str(rev), "--nonce", nonce, "--transcript",
                           str(self.f.transcript(text, finished, delivered)), expect=expect)

    def test_exact_bytes_staged(self):
        plan = plan_text(1)
        self.handback(self.f.wrap(1, "0123456789abcdef", plan), expect=0)
        staged = self.f.repo / "plans/planloop" / RUN / ".staging-001-0123456789abcdef/plan.md"
        self.assertEqual(staged.read_text(), plan)

    def test_draft_file_bound_by_digest_in_final_message(self):
        nonce = "0123456789abcdef"
        plan = plan_text(1)
        draft = self.f.root / f"planloop-draft-{nonce}.md"
        draft.write_text(self.f.wrap(1, nonce, plan))
        digest = hashlib.sha256(draft.read_bytes()).hexdigest()
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(f"plan left in {draft} sha256 {'0' * 64}")), "--draft", str(draft),
                    expect=1)
        self.assertIn("does not name the draft's sha256", self.f.last.stderr)
        other = self.f.root / "planloop-draft-ffffffffffffffff.md"
        other.write_bytes(draft.read_bytes())
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(f"sha256 {digest}")), "--draft", str(other), expect=1)
        self.assertIn("nonce", self.f.last.stderr)
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
                    str(self.f.transcript(f"plan left in {draft} sha256 {digest}")), "--draft", str(draft))
        staging = self.f.repo / "plans/planloop" / RUN / f".staging-001-{nonce}"
        self.assertEqual((staging / "plan.md").read_text(), plan)
        record = json.loads((staging / "handback.json").read_text())
        self.assertEqual(record["draft"]["sha256"], digest)
        self.assertTrue(record["completion"]["kind"].endswith("+draft-file"))

    def test_truncated_handback(self):
        self.handback(self.f.wrap(1, "0123456789abcdef", plan_text(1), end=False))

    def test_unfinished_agent(self):
        self.handback(self.f.wrap(1, "0123456789abcdef", plan_text(1)), finished=False)

    def test_undelivered_handback(self):
        self.handback(self.f.wrap(1, "0123456789abcdef", plan_text(1)), delivered=False)

    def test_planner_must_be_the_plan_agent(self):
        path = self.f.transcript(self.f.wrap(1, "0123456789abcdef", plan_text(1)), agent_type="general-purpose")
        self.f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", "0123456789abcdef", "--transcript",
                    str(path), expect=1)
        self.assertIn("Plan agent", self.f.last.stderr)

    def test_every_rr_needs_a_stated_risk(self):
        text = plan_text(1).replace("## Residual risks", "## Residual risks and limits")
        self.handback(self.f.wrap(1, "0123456789abcdef", text))
        self.assertIn("RR", self.f.last.stderr)

    def test_removed_id_and_colon_heading_dispositions(self):
        self.f.publish(1, plan_text(1))
        n2 = "4444444444444444"
        text = plan_text(2, risks=(), removed=["RR1: the archive risk no longer applies, the importer is synchronous",
                                               "## Residual risks: the section held only RR1, removed above"],
                         answers=keep("OB1", "INV1"))
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n2, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n2, text))))
        sys.path.insert(0, str(TOOL.parent))
        import planloop
        self.assertEqual(planloop.disposition(["## Step 1: design: cut the duplicate table, no OB affected"],
                                              "## Step 1: design"), "cut the duplicate table, no OB affected")
        self.assertIsNone(planloop.disposition(["## Step 1: other text"], "## Step 1: design"))

    def test_stale_nonce(self):
        self.handback(self.f.wrap(1, "ffffffffffffffff", plan_text(1)))

    def test_dangling_and_unlisted_ids(self):
        self.handback(self.f.wrap(1, "0123456789abcdef", plan_text(1).replace("Meet OB1.", "Meet OB1 and OB2.")))
        self.handback(self.f.wrap(1, "0123456789abcdef", plan_text(1, extra_ids=["AC7"])))

    def test_removed_section_and_shrink_need_dispositions(self):
        self.f.publish(1, plan_text(1))
        n2 = "1111111111111111"
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n2, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n2, plan_text(2, drop_design=True)))), expect=1)
        self.assertIn("REMOVED", self.f.last.stderr)
        shrunk = plan_text(2).replace("Line three of the design.\n", "")
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n2, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n2, shrunk))), expect=1)
        self.assertIn("SHRINK", self.f.last.stderr)
        ok = plan_text(2, shrink=["## Design: dropped line three, it restated INV1; no obligation affected"],
                       answers=keep()).replace("Line three of the design.\n", "")
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n2, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n2, ok))))

    def test_open_finding_must_be_answered(self):
        self.f.publish(1, plan_text(1))
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"})
        n2 = "2222222222222222"
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n2, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n2, plan_text(2)))), expect=1)
        self.assertIn("R1", self.f.last.stderr)


class HandbackCheck(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()
        self.f.publish(1, plan_text(1))

    def state(self):
        files = {}
        for base in (self.f.repo / "plans", self.f.state):
            for dirpath, dirnames, filenames in os.walk(base):
                for name in dirnames + filenames:
                    path = Path(dirpath) / name
                    files[str(path)] = path.read_bytes() if path.is_file() else None
        return files, self.f.bd()["issues"]

    def check(self, plan, expect, *extra):
        return self.f.tool("handback", "--run", RUN, "--check", *extra, stdin=plan, expect=expect).stdout

    def test_check_passes_a_valid_plan_and_writes_nothing(self):
        before = self.state()
        out = self.check(plan_text(2), 0)
        self.assertIn("check passed: handback would accept this plan content", out)
        out = self.check(self.f.wrap(2, "0123456789abcdef", plan_text(2)), 0)
        self.assertIn("check passed", out)
        self.assertEqual(self.state(), before)
        self.assertEqual(list((self.f.repo / "plans" / "planloop" / RUN).glob(".staging-*")), [])

    def test_check_lists_the_lines_a_missing_shrink_lost(self):
        before = self.state()
        out = self.check(plan_text(2).replace("Line three of the design.\n", ""), 1)
        self.assertIn("'## Design' lost 1 line(s) of revision 1", out)
        self.assertIn("no 'SHRINK ## Design:' disposition", out)
        self.assertIn("  - Line three of the design.", out)
        self.assertEqual(self.state(), before)

    def test_a_line_edited_in_place_is_lost(self):
        edited = plan_text(2, extra_design=["A new line."]).replace("Line two of the design.",
                                                                    "Line two of the design, edited.")
        out = self.check(edited, 1)
        self.assertIn("'## Design' lost 1 line(s)", out)
        self.assertIn("  - Line two of the design.\n", out)
        n = "7777777777777777"
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n, edited))), expect=1)
        self.assertIn("SHRINK ## Design", self.f.last.stderr)

    def test_check_and_handback_agree(self):
        c = self.f.review(review("REVISE", [finding("F1", "medium")]))
        self.f.ingest(c, {"F1": "new"})
        self.check(plan_text(2), 1)
        self.assertIn("R1", self.f.last.stdout)
        n = "8888888888888888"
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n, plan_text(2)))), expect=1)
        good = plan_text(2, answers=["FIX R1: add the checksum lookup"],
                         shrink=["## Design: dropped line three, it restated INV1; no obligation affected"]) \
            .replace("Line three of the design.\n", "")
        self.check(self.f.wrap(2, n, good), 0)
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n, good))))

    def test_check_of_a_published_revision_compares_with_its_predecessor(self):
        self.f.publish(2, plan_text(2, extra_design=["Only in revision two."]))
        self.check(plan_text(3), 1)
        self.assertIn("'## Design' lost 1 line(s) of revision 2", self.f.last.stdout)
        out = self.check(plan_text(2), 0, "--revision", "2")
        self.assertIn("revision 2 is already published; comparing with revision 1", out)
        out = self.check(plan_text(2).replace("Line three of the design.\n", ""), 1, "--revision", "2")
        self.assertIn("lost 1 line(s) of revision 1", out)
        self.assertIn("  - Line three of the design.", out)
        self.assertNotIn("Only in revision two.", out)
        self.check(plan_text(2), 1, "--revision", "4")
        self.assertIn("--check --revision must be between 1 and HEAD+1 (3)", self.f.last.stderr)
        self.check(plan_text(1), 0, "--revision", "1")

    def test_check_reports_an_unparseable_plan(self):
        out = self.check("not a plan\n", 1)
        self.assertIn("first line is not", out)
        out = self.check("\ufeff" + self.f.wrap(2, "0123456789abcdef", plan_text(2)), 1)
        self.assertIn("byte-order mark", out)
        proc = subprocess.run([sys.executable, str(TOOL), "handback", "--run", RUN, "--check"], cwd=self.f.repo,
                              capture_output=True, env=self.f.env, input=b"# PLAN \xff\n", timeout=300)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"not valid UTF-8", proc.stderr)
        self.assertNotIn(b"Traceback", proc.stderr)

    def test_check_refuses_handback_only_arguments(self):
        self.f.tool("handback", "--run", RUN, "--check", "--nonce", "0123456789abcdef", stdin=plan_text(2), expect=2)
        self.assertIn("takes no --nonce, --transcript or --draft", self.f.last.stderr)

    def test_disposition_length_is_measured_after_a_colon_heading(self):
        sys.path.insert(0, str(TOOL.parent))
        import planloop
        known = ["## Step 1: design"]
        self.assertEqual(planloop.disposition_text("## Step 1: design: short", known), "short")
        self.assertEqual(planloop.disposition_text("RR1: the risk no longer applies at all", ["RR1"]),
                         "the risk no longer applies at all")
        self.assertIsNone(planloop.disposition_text("no colon here", known))

    def test_unfinished_intent_blocks_the_real_handback(self):
        intents = self.f.repo / "plans" / "planloop" / RUN / "intents"
        intents.mkdir(parents=True, exist_ok=True)
        (intents / "propose-x.json").write_text(json.dumps({"schema": "planloop-intent/1", "name": "propose-x",
                                                            "state": "planned", "ops": []}))
        n = "abababababababab"
        self.f.tool("handback", "--run", RUN, "--revision", "2", "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(2, n, plan_text(2)))), expect=1)
        self.assertIn("unfinished Beads intents ['propose-x.json']", self.f.last.stderr)
        self.assertIn("unfinished Beads intents", self.check(plan_text(2), 0))


class EscalatedPlannerPolicy(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init("--track", "escalated", "--risk-domains", "recovery",
                    "--rationale", "changes how a crashed import resumes")

    def raise_finding(self, severity):
        self.f.publish(1, plan_text(1), model="fable")
        c = self.f.review(review("REVISE", [finding("F1", severity)]), effort="high")
        self.f.ingest(c, {"F1": "new"})

    def hand(self, rev, plan, model, expect):
        n = uuid.uuid4().hex[:16]
        self.f.tool("handback", "--run", RUN, "--revision", str(rev), "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(rev, n, plan), model=model)), expect=expect)
        if expect == 0:
            return json.loads((self.f.repo / "plans/planloop" / RUN / f".staging-{rev:03d}-{n}" /
                               "handback.json").read_text())["completion"]
        return None

    def test_revision_one_needs_fable(self):
        self.hand(1, plan_text(1), "opus", 1)
        self.assertIn("revision 1 is drafted by Fable", self.f.last.stderr)
        self.assertEqual(self.hand(1, plan_text(1), "fable", 0)["planner_basis"], "fable")

    def test_opus_writes_a_fix_revision(self):
        self.raise_finding("medium")
        out = self.f.tool("handback", "--run", RUN, "--check", stdin=plan_text(2, answers=["FIX R1: add it"])).stdout
        self.assertIn("Fable or Opus may hand this content back", out)
        self.assertNotIn("unknown track", out)
        completion = self.hand(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), "opus", 0)
        self.assertEqual(completion["planner_basis"], "opus-fix-revision")
        self.hand(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), "sonnet", 1)

    def set_run_meta(self, **meta):
        db = self.f.bd()
        bead = next(i for i in db["issues"].values() if i["metadata"].get("planloop_key") == f"run:{RUN}")
        bead["metadata"].update(meta)
        self.f.set_bd(db)

    def test_opus_fix_while_a_redesign_is_required_is_refused(self):
        self.raise_finding("medium")
        self.set_run_meta(planloop_redesign_required="R1")
        self.hand(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), "opus", 1)
        self.assertIn("planloop_redesign_required is set (R1)", self.f.last.stderr)
        self.assertIn("not answered with REDESIGN", self.f.last.stderr)

    def test_unknown_track_fails_closed(self):
        self.raise_finding("medium")
        self.set_run_meta(planloop_track="sideways")
        self.hand(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), "fable", 1)
        self.assertIn("unknown track 'sideways'", self.f.last.stderr)

    def test_override_is_named_by_check(self):
        self.f.tool("planner", "--run", RUN, "--model", "opus", "--quote", "use Opus to plan")
        out = self.f.tool("handback", "--run", RUN, "--check", stdin=plan_text(1)).stdout
        self.assertIn("Opus allowed by Mike's recorded override", out)

    def test_late_escalation_has_fable_draft_the_first_escalated_revision(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.publish(2, plan_text(2))
        f.init("--track", "escalated", "--risk-domains", "recovery", "--rationale", "found that resume semantics change")
        self.assertEqual(str(f.run_bead()["metadata"]["planloop_escalated_revision"]), "3")
        f.init("--track", "escalated", "--risk-domains", "recovery,ordering",
               "--rationale", "found that resume semantics and order change")
        self.assertEqual(str(f.run_bead()["metadata"]["planloop_escalated_revision"]), "3")
        n = "cdcdcdcdcdcdcdcd"
        f.tool("handback", "--run", RUN, "--revision", "3", "--nonce", n, "--transcript",
               str(f.transcript(f.wrap(3, n, plan_text(3)), model="opus")), expect=1)
        self.assertIn("revision 3 is the run's first escalated revision", f.last.stderr)
        f.publish(3, plan_text(3), model="fable")
        f.stage(4, plan_text(4), model="opus")

    def test_carried_over_redesign_line_for_a_verified_finding_does_not_need_fable(self):
        self.raise_finding("medium")
        self.f.publish(2, plan_text(2, answers=["REDESIGN R1: replace the lookup with a unique index"]), model="fable")
        c = self.f.review(review("REVISE", [finding("F2", "medium")],
                                 coverage=["plan read in full", "finding R1: resolved"]), effort="high")
        self.f.ingest(c, {"F2": "new"})
        self.assertEqual(self.f.finding_bead("R1")["metadata"]["planloop_state"], "verified")
        plan = plan_text(3, answers=["REDESIGN R1: replace the lookup with a unique index", "FIX R2: tighten it"])
        out = self.f.tool("handback", "--run", RUN, "--check", stdin=plan).stdout
        self.assertIn("Fable or Opus may hand this content back", out)
        self.assertIn("REDESIGN answers to ['R1'] name findings that are not open", out)
        self.assertEqual(self.hand(3, plan, "opus", 0)["planner_basis"], "opus-fix-revision")

    def test_non_numeric_escalated_revision_fails_clearly(self):
        self.raise_finding("medium")
        self.set_run_meta(planloop_escalated_revision="abc")
        self.hand(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), "fable", 1)
        self.assertIn("planloop_escalated_revision is 'abc'", self.f.last.stderr)
        self.assertNotIn("Traceback", self.f.last.stderr)

    def test_opus_revision_staged_before_escalation_cannot_publish_as_the_first_escalated(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2), model="opus")
        f.init("--track", "escalated", "--risk-domains", "recovery", "--rationale", "found that resume semantics change")
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, expect=1)
        self.assertIn("re-plan that revision with Fable", f.last.stderr)
        self.assertIsNone(f.tool("publish", "--run", RUN, "--recover").returncode or None)
        self.assertFalse((f.repo / "plans" / "planloop" / RUN / "rev-002").exists())
        f.publish(2, plan_text(2), model="fable")

    def test_redesign_required_needs_fable(self):
        self.raise_finding("medium")
        self.set_run_meta(planloop_redesign_required="R1")
        plan = plan_text(2, answers=["REDESIGN R1: replace the lookup with a unique index"])
        self.hand(2, plan, "opus", 1)
        self.assertIn("planloop_redesign_required is set (R1)", self.f.last.stderr)
        out = self.f.tool("handback", "--run", RUN, "--check", stdin=plan).stdout
        self.assertIn("needs a Fable planner", out)
        self.assertNotIn("unknown track", out)
        self.hand(2, plan, "fable", 0)

    def test_a_redesign_answer_needs_fable(self):
        self.raise_finding("medium")
        plan = plan_text(2, answers=["REDESIGN R1: replace the lookup with a unique index"])
        self.hand(2, plan, "opus", 1)
        self.assertIn("with REDESIGN", self.f.last.stderr)
        self.hand(2, plan, "fable", 0)

    def test_opus_answers_a_high_finding_with_a_fix(self):
        self.raise_finding("high")
        plan = plan_text(2, answers=["FIX R1: add the checksum lookup"])
        self.assertEqual(self.hand(2, plan, "opus", 0)["planner_basis"], "opus-fix-revision")

    def test_new_runs_pin_astra_for_reviews_and_the_gate(self):
        db = json.loads((self.f.repo / "plans/planloop" / RUN / "run.json").read_text())
        self.assertEqual((db["reviewer_model"], db["gate_model"]), ("gpt-6-astra", "gpt-6-astra"))

    def test_recorded_override_still_allows_opus(self):
        self.raise_finding("high")
        self.f.tool("planner", "--run", RUN, "--model", "opus", "--quote", "use Opus to plan")
        completion = self.hand(2, plan_text(2, answers=["REDESIGN R1: replace the lookup with a unique index"]),
                               "opus", 0)
        self.assertEqual(completion["planner_basis"], "override")
        self.assertIn("use Opus to plan", completion["planner_override_decision"])

    def test_ordinary_track_is_unchanged(self):
        f = Fixture(self)
        f.init()
        n = "9999999999999999"
        f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", n, "--transcript",
               str(f.transcript(f.wrap(1, n, plan_text(1)), model="opus")))
        completion = json.loads((f.repo / "plans/planloop" / RUN / f".staging-001-{n}" /
                                 "handback.json").read_text())["completion"]
        self.assertNotIn("planner_basis", completion)
        out = f.tool("handback", "--run", RUN, "--check", stdin=plan_text(1)).stdout
        self.assertIn("ordinary track, Opus plans", out)


class Publication(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()
        self.dir = self.f.repo / "plans/planloop" / RUN

    def head(self):
        return json.loads((self.dir / "HEAD").read_text())["revision"]

    def test_concurrent_publication_same_base(self):
        a = self.f.stage(1, plan_text(1))
        b = self.f.stage(1, plan_text(1).replace("Line two", "Line 2"))
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", a)
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", b, expect=3)
        self.assertEqual(self.head(), 1)

    def test_stale_base_revision(self):
        self.f.publish(1, plan_text(1))
        n = self.f.stage(2, plan_text(2))
        other = self.f.stage(2, plan_text(2, extra_design=["A competing writer's extra line."]))
        self.f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", other)
        self.f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, expect=3)

    def test_interrupted_publication_rolls_forward(self):
        n = self.f.stage(1, plan_text(1))
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", n,
                    env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
        self.assertFalse((self.dir / "HEAD").exists())
        self.assertTrue((self.dir / ".lock").exists())
        self.f.tool("publish", "--run", RUN, "--recover")
        self.assertEqual(self.head(), 1)

    def test_unchained_orphan_moved_aside(self):
        self.f.publish(1, plan_text(1))
        n = self.f.stage(2, plan_text(2))
        os.rename(self.dir / f".staging-002-{n}", self.dir / "rev-003")
        self.f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse((self.dir / "rev-003").exists())
        self.assertTrue(list(self.dir.glob(".orphan-rev-003-*")))
        self.assertEqual(self.head(), 1)

    def write_lock(self, owner):
        lock = self.dir / ".lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text(json.dumps(owner))

    def ident(self, pid):
        import socket
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19] \
            if Path(f"/proc/{pid}/stat").exists() else "1"
        return {"host": socket.gethostname(), "boot_id": boot, "pid": pid, "pid_ns": PID_NS, "start": start,
                "nonce": "x" * 32,
                "acquired_at": "2026-10-22T00:00:00Z"}

    def test_dead_owner_lock_is_broken(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        self.write_lock(self.ident(proc.pid) | {"start": "999999999"})
        self.f.publish(1, plan_text(1))

    def test_reused_pid_lock_is_broken(self):
        self.write_lock(self.ident(os.getpid()) | {"start": "1"})
        self.f.publish(1, plan_text(1))

    def test_live_owner_lock_blocks(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.kill)
        time.sleep(0.1)
        self.write_lock(self.ident(sleeper.pid))
        n = self.f.stage(1, plan_text(1))
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", n, expect=3)
        self.assertTrue((self.dir / ".lock").exists())

    def test_other_host_lock_never_broken(self):
        self.write_lock(self.ident(1) | {"host": "another-machine", "pid": 999999})
        n = self.f.stage(1, plan_text(1))
        self.f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", n, expect=3)


class FindingState(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()
        self.f.publish(1, plan_text(1))

    def test_beads_create_race_fails_closed(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.fault("create", "race")
        self.f.ingest(c, {"F1": "new"}, expect=3)
        self.assertIn("2 records for logical key", self.f.last.stderr)

    def test_beads_create_stolen_fails_closed(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.fault("create", "steal")
        self.f.ingest(c, {"F1": "new"}, expect=3)

    def test_lost_create_reply_is_adopted_on_replay(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.fault("create", "lost_reply")
        self.f.ingest(c, {"F1": "new"})
        self.assertEqual(self.f.finding_bead("R1")["metadata"]["planloop_state"], "open")
        keys = [i for i in self.f.bd()["issues"].values() if i["metadata"].get("planloop_finding") == "R1"]
        self.assertEqual(len(keys), 1)

    def test_dropped_update_replays_to_convergence(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"})
        nonce = self.f.stage(2, plan_text(2, answers=["FIX R1: add the lookup"]))
        self.f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.f.fault("update", "dropped")
        self.f.tool("findings", "propose", "--run", RUN, expect=2)
        self.f.tool("findings", "check", "--run", RUN, expect=1)
        self.f.tool("findings", "propose", "--run", RUN)
        self.assertEqual(self.f.finding_bead("R1")["metadata"]["planloop_state"], "fix_proposed")
        self.f.tool("findings", "check", "--run", RUN)

    def test_crash_after_apply_replays(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"}, expect=None)
        self.f.tool("findings", "check", "--run", RUN)
        c = self.f.review(review("REVISE", [finding("F9", "medium")]))
        path = self.f.root / "m.json"
        path.write_text(json.dumps({"F9": "R1"}))
        self.f.tool("findings", "ingest", "--run", RUN, "--call", str(c), "--attempt", "1", "--map", str(path),
                    env={"PLANLOOP_CRASH_AT": "intent_applied"}, expect=99)
        self.f.tool("findings", "check", "--run", RUN, expect=1)
        self.f.tool("findings", "check", "--run", RUN, expect=1)
        self.f.tool("ledger", "--run", RUN)
        self.f.tool("findings", "propose", "--run", RUN)
        self.f.tool("findings", "check", "--run", RUN)

    def test_map_must_cover_every_reviewer_finding(self):
        c = self.f.review(review("REVISE", [finding("F1"), finding("F2")]))
        self.f.ingest(c, {"F1": "new"}, expect=1)
        self.assertIn("must be exactly the reviewer's finding ids", self.f.last.stderr)

    def test_repeated_finding_forces_redesign_then_escalation(self):
        c = self.f.review(review("REVISE", [finding("F1")]))
        self.f.ingest(c, {"F1": "new"})
        for rev in (2, 3):
            self.f.publish(rev, plan_text(rev, answers=[f"FIX R1: attempt {rev}"]))
            c = self.f.review(review("REVISE", [finding("R1")]))
            self.f.ingest(c, {"R1": "R1"})
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_redesign_required"], "R1")
        n = "3333333333333333"
        self.f.tool("handback", "--run", RUN, "--revision", "4", "--nonce", n, "--transcript",
                    str(self.f.transcript(self.f.wrap(4, n, plan_text(4, answers=["FIX R1: again"])))), expect=1)
        self.assertIn("REDESIGN", self.f.last.stderr)
        self.f.publish(4, plan_text(4, answers=["REDESIGN R1: replace the lookup with a unique index"]))
        self.f.review(review(), effort="medium", expect=1)
        self.f.call -= 1
        c = self.f.review(review("REVISE", [finding("R1")]), effort="high")
        self.f.ingest(c, {"R1": "R1"})
        self.f.publish(5, plan_text(5, answers=["FIX R1: attempt 5"]))
        c = self.f.review(review("REVISE", [finding("R1")]), effort="high")
        self.f.ingest(c, {"R1": "R1"})
        meta = self.f.run_bead()["metadata"]
        self.assertEqual(meta["planloop_track"], "escalated")
        self.assertEqual(meta["planloop_redesign_required"], "R1")
        self.assertEqual(meta["planloop_state"], "active")
        self.assertEqual(str(meta["planloop_escalated_revision"]), "6")


class Evidence(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()

    def record(self, **kw):
        import hashlib
        out = self.f.repo / "plans" / "ev1.out"
        out.write_text(kw.pop("output_text", ""))
        query = "SELECT 1 WHERE false"
        rec = {"schema": "planloop-evidence/1", "id": "EV1", "claim": "no duplicate archive rows", "kind": "sql",
               "source": "fixture db", "query": query, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
               "inputs": [], "observation_window": {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
               "collected_at": "2026-10-22T10:00:00Z", "snapshot": "txid 42", "group": None, "status": "empty",
               "truncated": False, "claim_needs_complete": True, "match_proof": "same query matches row 7 in fixture",
               "limits": {"max_rows": 1000, "max_bytes": 1048576}, "limits_justification": None, "row_count": 0,
               "bytes": out.stat().st_size, "output": "plans/ev1.out",
               "output_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
               "attempts": [{"at": "2026-10-22T10:00:00Z", "outcome": "empty", "backoff_s": 0}],
               "validity": {"type": "historical"}}
        for k, v in kw.items():
            rec[k] = v
        path = self.f.root / f"ev-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(rec))
        return path, rec

    def check(self, expect, env=None, **kw):
        path, _ = self.record(**kw)
        self.f.tool("evidence", "--run", RUN, str(path), expect=expect, env=env)

    def test_successful_empty_result_with_match_proof(self):
        self.check(0)

    def test_empty_without_match_proof(self):
        self.check(1, match_proof=None)

    def test_timeout_is_unknown(self):
        self.check(1, status="timeout", attempts=[{"at": "2026-10-22T10:00:00Z", "outcome": "timeout", "backoff_s": 0}])

    def test_truncated_result_for_a_completeness_claim(self):
        self.check(1, status="result", row_count=1000, truncated=True, output_text="x")

    def test_retries_need_backoff_and_are_bounded(self):
        a = {"at": "2026-10-22T10:00:00Z", "outcome": "timeout", "backoff_s": 0}
        self.check(1, attempts=[a, a | {"backoff_s": 1}, a | {"outcome": "empty", "backoff_s": 15}])
        self.check(1, attempts=[a, a, a, a | {"outcome": "empty"}])
        self.check(0, attempts=[a, a | {"backoff_s": 5}, a | {"outcome": "empty", "backoff_s": 15}])

    def test_observation_expires_by_age(self):
        validity = {"type": "observation", "max_age_s": 3600, "must_remain_current": False}
        self.check(0, validity=validity, env={"PLANLOOP_NOW": "2026-10-22T10:30:00Z"})
        self.check(1, validity=validity, env={"PLANLOOP_NOW": "2026-10-22T12:00:00Z"})

    def test_limit_override_needs_justification_and_cap(self):
        self.check(1, limits={"max_rows": 5000, "max_bytes": 1048576})
        self.check(0, limits={"max_rows": 5000, "max_bytes": 1048576}, limits_justification="full month of rows")
        self.check(1, limits={"max_rows": 200000, "max_bytes": 1048576}, limits_justification="too big")

    def test_failed_group_member_fails_whole_group(self):
        p1, _ = self.record(group="G1")
        p2, _ = self.record(group="G1", id="EV2", status="error",
                            attempts=[{"at": "2026-10-22T10:00:00Z", "outcome": "error", "backoff_s": 0}])
        self.f.tool("evidence", "--run", RUN, str(p1), str(p2), expect=1)
        self.assertIn("whole group", self.f.last.stdout)


class Gate(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_happy_path_publishes_approval(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish")
        self.f.tool("gate", "--run", RUN)
        meta = self.f.run_bead()["metadata"]
        self.assertEqual(meta["planloop_state"], "approved")
        self.assertEqual(self.f.bd()["issues"][BEAD]["status"], "open")

    def test_open_finding_despite_approved_verdict(self):
        self.f.init()
        self.f.publish(1, plan_text(1))
        c = self.f.review(review("REVISE", [finding("F1", "medium")]))
        self.f.ingest(c, {"F1": "new"})
        self.f.accept_risk()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.assertIn("no unresolved finding", self.f.last.stdout)

    def test_missing_or_stale_risk_acceptance(self):
        self.f.to_gate_ready()
        (self.f.repo / "plans/planloop" / RUN / "decisions/D1.json").unlink()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.f.accept_risk(text="a different wording")
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.f.accept_risk()
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_gate_must_be_the_latest_call(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        c = self.f.review(review())
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)

    def test_more_rounds_than_the_old_cap_continue(self):
        self.f.to_gate_ready()
        for _ in range(13):
            c = self.f.review(review())
            self.f.ingest(c, {})
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.assertGreater(c, 12)
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_unchanged_infrastructure_blocker_stops_without_approval(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high", mode="no_rollout", expect=1)
        for attempt in (2, 3):
            self.f.review(review(), kind="gate", effort="high", mode="no_rollout", expect=1, call=c, attempt=attempt)
        self.assertEqual(self.f.run_bead()["metadata"]["planloop_state"], "blocked")
        self.f.review(review(), kind="gate", effort="high", expect=1, call=c, attempt=4)
        self.f.review(review(), kind="gate", effort="high", expect=1, call=c + 1)
        self.f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.f.tool("state", "--run", RUN, "--set", "active", "--reason", "Codex session store restored")
        self.f.review(review(), kind="gate", effort="high", call=c + 1)
        self.f.ingest(c + 1, {})
        self.f.tool("gate", "--run", RUN, "--publish")

    def test_approval_interrupted_before_pointer(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        for point in ("approval_pending", "beads_candidate"):
            self.f.tool("gate", "--run", RUN, "--publish", env={"PLANLOOP_CRASH_AT": point}, expect=99)
            self.assertFalse((self.f.repo / "plans/planloop" / RUN / "APPROVAL").exists())
            self.assertNotEqual(self.f.run_bead()["metadata"]["planloop_state"], "approved")
            self.f.tool("gate", "--run", RUN, expect=1)
        self.f.tool("gate", "--run", RUN, "--publish")
        self.f.tool("gate", "--run", RUN)

    def test_approval_interrupted_after_pointer(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish", env={"PLANLOOP_CRASH_AT": "approval_pointer"}, expect=99)
        self.f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("Beads records this approval", self.f.last.stdout)
        self.f.tool("gate", "--run", RUN, "--publish")
        self.f.tool("gate", "--run", RUN)

    def test_input_change_after_approval_voids_it(self):
        self.f.to_gate_ready()
        c = self.f.review(review(), kind="gate", effort="high")
        self.f.ingest(c, {})
        self.f.tool("gate", "--run", RUN, "--publish")
        (self.f.repo / "docs" / "req.md").write_text("changed\n")
        self.f.tool("gate", "--run", RUN, expect=1)


@unittest.skipUnless(shutil.which("bd"), "real bd not installed")
class RealBeads(unittest.TestCase):
    def test_full_run_against_real_bd_in_a_throwaway_database(self):
        f = Fixture(self)
        f.env.pop("PLANLOOP_BD")
        env = {k: v for k, v in f.env.items() if not k.startswith("BEADS")}
        f.env = env
        subprocess.run(["bd", "init", "--prefix", "qz", "--quiet"], cwd=f.repo, env=env, check=True,
                       capture_output=True, timeout=120)
        subprocess.run(["bd", "create", "--id", BEAD, "--title", "importer", "--description",
                        "Reject duplicate archives.", "--silent"], cwd=f.repo, env=env, check=True,
                       capture_output=True, timeout=60)
        f.to_gate_ready()
        c = f.review(review(), kind="gate", effort="high")
        f.ingest(c, {})
        f.tool("gate", "--run", RUN, "--publish")
        f.tool("gate", "--run", RUN)
        shown = json.loads(subprocess.run(["bd", "list", "--all", "--metadata-field", f"planloop_key=finding:{RUN}:R1",
                                           "-n", "0", "--json"], cwd=f.repo, env=env, capture_output=True,
                                          timeout=60).stdout)
        self.assertEqual([s["status"] for s in shown], ["closed"])
        bead = json.loads(subprocess.run(["bd", "show", BEAD, "--json"], cwd=f.repo, env=env, capture_output=True,
                                         timeout=60).stdout)[0]
        self.assertEqual(bead["status"], "open")


class Bundle(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.f.init()

    def handback(self, rev=1):
        nonce = uuid.uuid4().hex[:16]
        self.f.tool("handback", "--run", RUN, "--revision", str(rev), "--nonce", nonce, "--transcript",
                    str(self.f.transcript(self.f.wrap(rev, nonce, plan_text(rev)))))
        return nonce

    def bundle(self, inputs, expect):
        nonce = self.handback()
        self.f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(inputs), expect=expect)

    def test_binding_source_without_obligation(self):
        disc = {"schema": "planloop-discovery/1", "searches": [{"command": "grep", "purpose": "p", "hits": 1,
                                                                 "match_proof": None}],
                "sources": [{"path": "src/a.rs", "class": "binding", "reason": "r"}], "known_omissions": []}
        self.bundle(self.f.inputs(discovery=disc), 1)

    def test_known_omission(self):
        disc = {"schema": "planloop-discovery/1", "searches": [{"command": "grep", "purpose": "p", "hits": 1,
                                                                 "match_proof": None}],
                "sources": [], "known_omissions": ["plans/PLAN_5g9.md section 8 not read"]}
        self.bundle(self.f.inputs(discovery=disc), 1)

    def test_candidate_not_supplied(self):
        self.bundle(self.f.inputs(repo_files=["docs/req.md"]), 1)

    def test_obligation_text_must_be_verbatim(self):
        self.bundle(self.f.inputs(obligations=[{"id": "OB1", "source": "docs/req.md", "section": "x",
                                                "text": "The importer should reject duplicates."}]), 1)

    def test_snapshot_is_frozen_and_read_only(self):
        (self.f.repo / "src" / "wip.rs").write_text("untracked work\n")
        nonce = self.handback()
        self.f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(self.f.inputs()))
        snap = self.f.state / RUN / f"snap-r001-{nonce}"
        self.assertEqual((snap / "src" / "wip.rs").read_text(), "untracked work\n")
        self.assertTrue((snap / ".planloop-bundle" / "beads" / f"{BEAD}.json").exists())
        with self.assertRaises(PermissionError):
            (snap / "src" / "a.rs").write_text("x")

    def test_an_unsafe_bead_id_fails_before_anything_is_written(self):
        evil = "../../../../evil"
        db = self.f.bd()
        db["issues"][evil] = {**db["issues"][BEAD], "id": evil}
        self.f.set_bd(db)
        spec = json.loads(self.f.inputs().read_text())
        spec["beads"].append({"id": evil, "fields": []})
        inputs = self.f.root / "inputs-evil.json"
        inputs.write_text(json.dumps(spec))
        nonce = self.handback()
        self.f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(inputs), expect=None)
        self.assertEqual(self.f.last.returncode, 1, self.f.last.stdout + self.f.last.stderr)
        self.assertNotIn("Traceback", self.f.last.stderr)
        self.assertIn(f"inputs.beads.id: {evil!r} must not contain . or ..", self.f.last.stderr)
        self.assertFalse(list(self.f.root.rglob("evil.json")))
        staging = self.f.rdir / f".staging-001-{nonce}"
        self.assertFalse((staging / "bundle").exists())
        self.assertFalse(list(staging.glob(".bundle-tmp-*")))

    def test_an_evidence_output_colliding_with_a_record_fails_cleanly(self):
        for output in ("EV1.json", "EV1.json/x"):
            with self.subTest(output=output):
                f = Fixture(self)
                f.init()
                observation(f, "2026-10-22T10:00:00Z")
                f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
                (f.repo / output).parent.mkdir(parents=True, exist_ok=True)
                (f.repo / output).write_text("")
                path = f.repo / "plans" / "ev1.json"
                path.write_text(json.dumps({**json.loads(path.read_text()), "output": output}))
                nonce = f.hand(1, plan_text(1))
                f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs",
                       str(f.inputs(evidence=["plans/ev1.json"])), expect=None)
                self.assertEqual(f.last.returncode, 1, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"evidence frozen paths collide: EV1's record EV1.json and EV1's output {output}",
                              f.last.stderr)
                staging = f.rdir / f".staging-001-{nonce}"
                self.assertFalse((staging / "bundle").exists())
                self.assertFalse(list(staging.glob(".bundle-tmp-*")))


    def test_two_evidence_records_sharing_one_output_bundle_and_publish(self):
        f = Fixture(self)
        f.init()
        observation(f, "2026-10-22T10:00:00Z")
        f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
        record = json.loads((f.repo / "plans" / "ev1.json").read_text())
        (f.repo / "plans" / "ev2.json").write_text(json.dumps({**record, "id": "EV2"}))
        nonce = f.stage(1, plan_text(1), inputs=f.inputs(evidence=["plans/ev1.json", "plans/ev2.json"]))
        self.assertNotIn("Traceback", f.last.stderr)
        f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
        self.assertEqual(f.head(), 1)
        frozen = f.rdir / "rev-001" / "bundle" / "frozen" / "evidence"
        self.assertTrue((frozen / "EV1.json").is_file() and (frozen / "EV2.json").is_file())
        self.assertTrue((frozen / "plans" / "ev1.out").is_file())


def shrink_setup(f):
    f.init()
    f.publish(1, make_plan(1))
    c = f.review(review("REVISE", [finding("F1", "low")]))
    f.ingest(c, {"F1": "new"})
    grown = edit(BASE, add={"## Design": ("Line four of the design.",)})
    f.publish(2, make_plan(2, grown, log=["FIX R1: add line four"]))
    c2 = f.review(review(coverage=["plan read in full", "finding R1: resolved"]))
    f.ingest(c2, {})
    f.publish(3, make_plan(3, edit(grown, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()]))
    return c2


def decision_approval(f, start=0, count=3300):
    p2 = big(2, start + 1, count - 1, log=[SHRINK_DETAIL, *keep()])
    f.publish(2, p2)
    c = f.review(review(coverage=["plan read in full", *f.lines_for(2)]))
    f.ingest(c, {})
    f.size_decision("S1", 2, len(p2) + 10000)
    f.accept_risk()
    g = f.review(review(), kind="gate", effort="high")
    f.ingest(g, {})
    f.tool("gate", "--run", RUN, "--publish")
    return p2


class SizeReport(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_publish_reports_size_and_growth(self):
        f = self.f
        f.init()
        p1 = make_plan(1)
        f.publish(1, p1)
        self.assertIn(f"size: revision 1 is {len(p1):,} bytes (1 kB = 1,000 bytes); (first revision)\n",
                      f.published.stdout)
        self.assertIn("size policy: threshold 250,000 bytes, renewal margin 25,000 bytes; within the threshold; "
                      "gate: eligible (under-threshold); meaning: no shrink awaits judgement", f.published.stdout)
        p2 = make_plan(2, BASE + (("## Extra", tuple(f"Extra line {i} for revision two." for i in range(30))),))
        f.publish(2, p2)
        self.assertIn(f"size: revision 2 is {len(p2):,} bytes (1 kB = 1,000 bytes); {growth(p2, p1)} vs revision 1\n",
                      f.published.stdout)
        p3 = make_plan(3, log=["REMOVED ## Extra: the extra lines restated the goal; no obligation affected", *keep()])
        f.publish(3, p3)
        self.assertLess(len(p3), len(p2))
        self.assertIn(f"size: revision 3 is {len(p3):,} bytes (1 kB = 1,000 bytes); {growth(p3, p2)} vs revision 2; "
                      f"{growth(p3, p1)} vs revision 1\n", f.published.stdout)
        self.assertIn("meaning: revision 3 awaits judgement", f.published.stdout)
        p4 = make_plan(4, edit(BASE, add={"## Design": ("Line four of the design.",)}))
        f.publish(4, p4)
        self.assertIn(f"{growth(p4, p3)} vs revision 3, the latest shrink-only revision; {growth(p4, p1)} vs "
                      "revision 1\n", f.published.stdout)
        self.assertIn("NOTE  revision 3 has no meaning judgement yet; its comparison is carried into the reviews of "
                      "revision 4", f.published.stdout)

    def test_check_and_handback_report_size_and_classification(self):
        f = self.f
        f.init()
        p1 = make_plan(1)
        f.publish(1, p1)
        c = f.review(review("REVISE", [finding("F1", "low")]))
        f.ingest(c, {"F1": "new"})
        fix = make_plan(2, edit(BASE, add={"## Design": ("Line four of the design.",)}), log=["FIX R1: add line four"])
        out = f.check(fix, 0).stdout
        self.assertIn(f"size: revision 2 is {len(fix):,} bytes (1 kB = 1,000 bytes); {growth(fix, p1)} vs revision 1\n",
                      out)
        self.assertIn("classification: not shrink-only", out)
        self.assertNotIn("this is a shrink-only revision", out)
        shrink = make_plan(2, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()])
        out = f.check(shrink, 0).stdout
        self.assertIn("classification: shrink-only", out)
        self.assertIn("size policy: threshold 250,000 bytes, renewal margin 25,000 bytes; within the threshold; "
                      "meaning: revision 2 awaits judgement", out)
        self.assertIn("nothing this check does judges meaning", out)
        f.hand(2, shrink)
        self.assertIn("classification: shrink-only", f.last.stdout)
        self.assertIn("nothing this check does judges meaning", f.last.stdout)

    def test_oversize_plan_warns_at_check_handback_publish_and_working_dispatch(self):
        f = self.f
        f.init()
        p1 = big(1, 0, 3340)
        self.assertGreater(len(p1), 260000)
        warn = f"WARN  revision 1 is {len(p1):,} bytes, over the size threshold"
        self.assertIn(warn, f.check(p1, 0).stdout)
        nonce = f.hand(1, p1)
        self.assertIn(warn, f.last.stdout)
        f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
        self.assertIn(warn, f.last.stdout)
        c = f.review(review())
        self.assertIn(warn, f.last.stdout)
        self.assertEqual(f.receipt(c)["status"], "counted")

    def test_shrink_only_classification_uses_live_answers(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        c = f.review(review("REVISE", [finding("F1", "low")]))
        f.ingest(c, {"F1": "new"})
        cut = edit(BASE, drop=("Line three of the design.",))
        n = f.hand(2, make_plan(2, cut, log=[SHRINK_DESIGN, *keep()]))
        self.assertEqual(f.staged(2, n).get("cut"), {"shrink_only": True, "lost_lines": 1, "removed_sections": 0,
                                                     "threshold_bytes": 250000, "live_answers": []})
        n = f.hand(2, make_plan(2, cut, log=["FIX R1: dropped the restating line", SHRINK_DESIGN]))
        self.assertEqual(f.staged(2, n)["cut"]["shrink_only"], False)
        grown = edit(BASE, add={"## Design": ("Line four of the design.",)})
        f.publish(2, make_plan(2, grown, log=["REDESIGN R1: replace the lookup with a unique index"]))
        self.assertEqual(f.finding_bead("R1")["metadata"]["planloop_state"], "fix_proposed")
        carried = make_plan(3, edit(grown, drop=("Line three of the design.",)),
                            log=["REDESIGN R1: replace the lookup with a unique index", SHRINK_DESIGN, *keep()])
        self.assertIn("classification: shrink-only", f.check(carried, 0).stdout)
        n = f.hand(3, carried)
        self.assertEqual(f.staged(3, n)["cut"]["shrink_only"], True)
        n = f.hand(3, make_plan(3, edit(grown, add={"## Goal": ("And meet it quickly.",)})))
        self.assertEqual(f.staged(3, n)["cut"], {"shrink_only": False, "lost_lines": 0, "removed_sections": 0,
                                                 "threshold_bytes": 250000, "live_answers": []})

    def test_fix_revision_that_cuts_more_than_five_percent_warns(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1, BASE + (("## Detail", pad(0, 40)),)))
        c = f.review(review("REVISE", [finding("F1", "medium")]))
        f.ingest(c, {"F1": "new"})
        fix = make_plan(2, BASE + (("## Detail", pad(0, 5)),), log=["FIX R1: cut the padding it named", SHRINK_DETAIL])
        warn = "% smaller than revision 1; a size cut belongs in its own shrink-only revision, which gets a meaning check"
        out = f.check(fix, 0).stdout
        self.assertIn("WARN  this revision answers findings and is ", out)
        self.assertIn(warn, out)
        f.publish(2, fix)
        self.assertIn(warn, f.published.stdout)
        c = f.review(review(coverage=["plan read in full", "finding R1: resolved"]))
        self.assertIn("check that every cut is explained by the finding it answers or by its disposition", f.feedback(c))

    def test_shrink_only_draft_needs_a_preserved_line_for_every_kept_id(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        cut = edit(BASE, drop=("Line three of the design.",))
        out = f.check(make_plan(2, cut, log=[SHRINK_DESIGN]), 1).stdout
        self.assertIn("PRESERVED", out)
        self.assertIn("missing ['INV1', 'OB1', 'RR1']", out)
        out = f.check(make_plan(2, cut, log=[SHRINK_DESIGN, "PRESERVED OB1: same", *keep("INV1", "RR1")]), 1).stdout
        self.assertIn("too short ['OB1']", out)
        f.hand(2, make_plan(2, cut, log=[SHRINK_DESIGN]), expect=1)
        self.assertIn("PRESERVED", f.last.stderr)
        self.assertIn("'OB1'", f.last.stderr)
        f.check(make_plan(2, cut, log=[SHRINK_DESIGN, *keep()]), 0)
        c = f.review(review("REVISE", [finding("F1", "low")]))
        f.ingest(c, {"F1": "new"})
        f.check(make_plan(2, cut, log=["FIX R1: dropped the line", SHRINK_DESIGN, "PRESERVED OB1: same"]), 0)


class MeaningCheck(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_bundle_freezes_the_comparison_for_a_shrink_only_revision(self):
        f = self.f
        shrink_setup(f)
        self.assertEqual(f.meanings(2), [])
        self.assertEqual(len(f.meanings(3)), 1)
        [item] = f.meanings(3)
        snapshot = next(i for i in f.manifest(3)["items"] if i["type"] == "snapshot")["path"]
        frozen = Path(snapshot) / ".planloop-bundle" / "meaning-r3"
        before, after = (f.rdir / "rev-002/plan.md").read_bytes(), (f.rdir / "rev-003/plan.md").read_bytes()
        self.assertEqual((frozen / "before.md").read_bytes(), before)
        self.assertEqual((frozen / "after.md").read_bytes(), after)
        index = (frozen / "index.md").read_bytes()
        self.assertEqual((item["before_sha256"], item["after_sha256"], item["index_sha256"]),
                         tuple(hashlib.sha256(b).hexdigest() for b in (before, after, index)))
        index = index.decode()
        self.assertTrue(index.startswith("Mechanical index: where the text of revision 3 differs from revision 2. It "
                                         "never shows that meaning survived; unchanged lines can change meaning in a "
                                         "changed context.\n"), index)
        lost = before.decode().split("\n").index("Line three of the design.") + 1
        self.assertIn(f"=== ## Design\n", index)
        self.assertIn(f"\nchanged: lost: before.md lines {lost}\n", index)
        self.assertRegex(index, r"=== ## Goal\nbefore\.md lines \d+-\d+; after\.md lines \d+-\d+\nunchanged\n")
        self.assertEqual(item["units"], ["## Design"])

    def test_dispatch_on_a_shrink_only_revision_carries_the_meaning_mandate(self):
        f = self.f
        c2 = shrink_setup(f)
        self.assertNotIn("meaning_check", f.dispatched(c2))
        self.assertNotIn("MEANING CHECK", f.feedback(c2))
        self.assertEqual([i["units"] for i in f.meanings(3)], [["## Design"]])
        c = f.review(review(coverage=["plan read in full", *f.lines_for(3)]))
        self.assertEqual([(e["revision"], e["previous_revision"], e["units"]) for e in f.dispatched(c)["meaning_check"]],
                         [(3, 2, ["## Design"])])
        feedback = f.feedback(c)
        for needle in ("--- MEANING CHECK (shrink-only revision 3 against revision 2) ---",
                       ".planloop-bundle/meaning-r3/before.md", "meaning revision 3 ## Design: ",
                       "no unsignalled live loss goes unhandled", "PRESERVED OB1: "):
            self.assertIn(needle, feedback)
        r = f.receipt(c)
        self.assertEqual(r["status"], "counted", r["reasons"])
        self.assertEqual(r["meaning_check"], [{"revision": 3, "previous_revision": 2,
                                               "verdicts": {"## Design": "preserved"}}])

    def test_meaning_lines_are_checked_exactly(self):
        f = self.f
        shrink_setup(f)
        good = "meaning revision 3 ## Design: preserved"
        blocked = {"verdict": "BLOCKED", "summary": "blocked", "findings": [], "limitations": ["no access"],
                   "coverage": ["meaning revision 3 ## Design: changed"]}
        cases = [(review(coverage=["plan read in full"]), "no meaning verdict"),
                 (review(coverage=[good, good]), "more than once"),
                 (review(coverage=[good, "meaning revision 3 ## Goal: preserved"]), "meaning line"),
                 (review(coverage=["meaning revision 2 ## Design: preserved"]), "meaning line"),
                 (review(coverage=["meaning revision 3 ## Design: kept"]), "meaning line"),
                 (review(coverage=["meaning revision 3 ## Design: changed"]), "raises no finding"),
                 (blocked, "raises no finding")]
        for response, needle in cases:
            c = f.review(response, expect=1, call=f.call + 1)
            f.call = c
            reasons = f.receipt(c)["reasons"]
            self.assertTrue(any(needle in r for r in reasons), (response, reasons))
            f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed the reviewer")
        c = f.review(review(coverage=["plan read in full", good]), call=f.call + 1)
        r = f.receipt(c)
        self.assertEqual((r["status"], r["meaning_check"][0]["verdicts"]), ("counted", {"## Design": "preserved"}))

    def test_an_unjudged_shrink_is_carried_until_judged(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        shrink = make_plan(2, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()])
        observation(f, "2026-10-22T10:00:00Z")
        f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
        f.publish(2, shrink, inputs=f.inputs(evidence=["plans/ev1.json"]))
        f.env["PLANLOOP_NOW"] = "2026-10-22T12:00:00Z"
        f.review(review(coverage=f.lines_for(2)), expect=1)
        self.assertIn("recollect and republish", f.last.stderr)
        f.call -= 1
        observation(f, "2026-10-22T12:00:00Z")
        f.env["PLANLOOP_NOW"] = "2026-10-22T12:05:00Z"
        f.publish(3, shrink.replace("(revision 2,", "(revision 3,"), inputs=f.inputs(evidence=["plans/ev1.json"]))
        self.assertIn("NOTE  revision 2 has no meaning judgement yet; its comparison is carried into the reviews of "
                      "revision 3", f.published.stdout)
        for name in ("before.md", "after.md", "index.md"):
            self.assertEqual((f.rdir / "rev-003/bundle/frozen/meaning-r2" / name).read_bytes(),
                             (f.rdir / "rev-002/bundle/frozen/meaning-r2" / name).read_bytes())
        self.assertEqual([i["revision"] for i in f.meanings(3)], [2])
        f.accept_risk()
        f.size_decision("S1", 2, 10 ** 6)
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [judgement, recorded] every shrink-only revision", f.last.stdout)
        c = f.review(review(coverage=["plan read in full"]), expect=1)
        self.assertEqual(f.dispatched(c)["meaning_check"][0]["revision"], 2)
        self.assertIn("Revision 2 was not judged in its own round", f.feedback(c))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [judgement, recorded] every shrink-only revision", f.last.stdout)
        c = f.review(review(coverage=f.lines_for(3)), call=c, attempt=2)
        self.assertEqual(f.receipt(c, 2)["status"], "counted")
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("PASS  [judgement, recorded] every shrink-only revision since the size policy applied has a "
                      "counted reviewer's meaning judgement (revision 2: call 1 on revision 3, 1 units preserved",
                      f.last.stdout)

        g = Fixture(self)
        g.init()
        g.publish(1, make_plan(1))
        g.publish(2, shrink)
        c = g.review(review(coverage=g.lines_for(2)), mode="touch=src/a.rs", expect=1)
        self.assertTrue(any("src/a.rs" in r for r in g.receipt(c)["reasons"]))
        g.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [judgement, recorded]", g.last.stdout)
        g.publish(3, make_plan(3, edit(BASE, drop=("Line three of the design.",),
                                       add={"## Goal": ("And reject it before staging.",)}), log=[SHRINK_DESIGN]))
        c = g.review(review(coverage=g.lines_for(3)))
        self.assertEqual(g.dispatched(c)["meaning_check"][0]["revision"], 2)
        self.assertEqual(g.receipt(c)["status"], "counted")
        g.tool("gate", "--run", RUN, expect=1)
        self.assertIn("PASS  [judgement, recorded]", g.last.stdout)

    def test_cgr_weakenings_pass_structure_and_reach_the_reviewer(self):
        before = make_plan(1).split("\n")
        for lines in ([A5_OLD], [A8_OLD], [A7_OLD], [A5_OLD, A8_OLD, A7_OLD]):
            f = Fixture(self)
            f.init()
            f.publish(1, make_plan(1))
            draft = make_plan(2, edit(BASE, {l: WEAK[l] for l in lines}), log=[SHRINK_OBL, *keep()])
            f.check(draft, 0)
            f.publish(2, draft)
            self.assertEqual([i["units"] for i in f.meanings(2)], [["## 11. Obligations"]])
            index = (f.rdir / "rev-002/bundle/frozen/meaning-r2/index.md").read_text()
            numbers = [before.index(l) + 1 for l in lines]
            span = str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}-{numbers[-1]}"
            self.assertIn(f"=== ## 11. Obligations\n", index)
            self.assertIn(f"changed: lost: before.md lines {span}; added: after.md lines {span}\n", index)
            c = f.review(review(coverage=f.lines_for(2)))
            self.assertEqual(f.dispatched(c)["meaning_check"][0]["units"], ["## 11. Obligations"])
            self.assertEqual(f.receipt(c)["status"], "counted")
            self.assertFalse([o for o in f.outputs if "preserved" in o], f.outputs)

    def test_structure_cannot_tell_a_weakened_shrink_from_a_faithful_one(self):
        runs = {}
        for name, table in (("weak", WEAK), ("faithful", FAITHFUL)):
            f = Fixture(self)
            f.init()
            f.publish(1, make_plan(1))
            draft = make_plan(2, edit(BASE, table), log=[SHRINK_OBL, *keep()])
            out = f.check(draft, 0).stdout
            f.publish(2, draft)
            runs[name] = (f, [l for l in out.splitlines() if l.startswith(("classification:", "check ", "this is a"))])
        (wf, wout), (ff, fout) = runs["weak"], runs["faithful"]
        self.assertEqual(wout, fout)
        self.assertEqual(len(wout), 3)
        self.assertEqual(wf.meanings(2)[0]["units"], ff.meanings(2)[0]["units"])
        wc = wf.review(review("REVISE", [finding("F1", "medium")], coverage=wf.lines_for(2, "changed")))
        fc = ff.review(review(coverage=ff.lines_for(2)))
        self.assertEqual(wf.dispatched(wc)["meaning_check"][0]["units"], ff.dispatched(fc)["meaning_check"][0]["units"])
        self.assertEqual((wf.receipt(wc)["status"], ff.receipt(fc)["status"]), ("counted", "counted"))
        self.assertEqual(wf.receipt(wc)["meaning_check"][0]["verdicts"], {"## 11. Obligations": "changed"})
        self.assertEqual(ff.receipt(fc)["meaning_check"][0]["verdicts"], {"## 11. Obligations": "preserved"})

    def test_meaning_finding_blocks_approval_until_restored_or_decided(self):
        for path in ("restore", "decide"):
            f = Fixture(self)
            f.init()
            f.publish(1, make_plan(1))
            f.publish(2, make_plan(2, edit(BASE, {A5_OLD: WEAK[A5_OLD]}), log=[SHRINK_OBL, *keep()]))
            c = f.review(review("REVISE", [finding("F1", "medium")],
                                coverage=["plan read in full", *f.lines_for(2, "changed")]))
            self.assertEqual(f.receipt(c).get("meaning_check"), [{"revision": 2, "previous_revision": 1,
                                                                  "verdicts": {"## 11. Obligations": "changed"}}])
            f.ingest(c, {"F1": "new"})
            f.accept_risk()
            g = f.review(review(), kind="gate", effort="high")
            f.ingest(g, {})
            f.tool("gate", "--run", RUN, "--publish", expect=1)
            self.assertIn("FAIL  [mechanical] no unresolved finding", f.last.stdout)
            if path == "restore":
                f.publish(3, make_plan(3, log=["FIX R1: restored 'no unsignalled live loss goes unhandled' in A5",
                                               SHRINK_OBL]))
                c = f.review(review(coverage=["plan read in full", "finding R1: resolved"]))
                f.ingest(c, {})
            else:
                d = f.rdir / "decisions" / "D2.json"
                d.write_text(json.dumps({"schema": "planloop-decision/1", "id": "D2", "by": "Mike",
                                         "quote": "the reworded A5 is acceptable", "recorded_at": "2026-10-22T23:00:00Z",
                                         "recorded_by": "orchestrator", "subjects": [{"id": "R1", "text_sha256": None}],
                                         "outcome": "rejected-finding", "follow_up": None}))
                f.tool("findings", "decide", "--run", RUN, "--decision", str(d))
            g = f.review(review(), kind="gate", effort="high")
            f.ingest(g, {})
            f.tool("gate", "--run", RUN, "--publish")
            [record] = (f.rdir / "approvals").glob("*.json")
            self.assertEqual([(m["revision"], m["call"], m["preserved"], m["changed"])
                              for m in json.loads(record.read_text())["meaning_checks"]], [(2, 1, 0, 1)])

    def test_meaning_units_cover_every_textual_change(self):
        f = self.f
        f.init()
        secs = (("## Goal", ("Meet OB1.",)), ("## A", ("Use INV1 throughout.", "A line that the shrink cuts.")),
                ("## B", ("A8 holds while continuity holds.",)),
                ("## C", ("1. write the `commission_due` expectation.", "2. publish the fill.")),
                ("## E", ("Section E text.",)), ("## F", ("Section F text.",)), ("## G", ("Section G text.",)))
        before = make_plan(1, secs)
        f.publish(1, before)
        new = (secs[0], ("## A", ("Use INV1 throughout.",)),
               ("## B", ("A8 holds while continuity holds.", "A8 holds except during a reconnect.")),
               ("## C", ("2. publish the fill.", "1. write the `commission_due` expectation.")),
               secs[5], secs[6], secs[4], ("## D", ("Section D is new.",)))
        out = f.check(make_plan(2, new, log=keep()), 1).stdout
        self.assertIn("'## A' lost 1 line(s)", out)
        for head in ("## B", "## C", "## D", "## E"):
            self.assertNotIn(f"'{head}' lost", out)
        draft = make_plan(2, new, log=["SHRINK ## A: cut the restating line; no obligation affected", *keep()])
        f.check(draft, 0)
        f.publish(2, draft)
        self.assertEqual([i["units"] for i in f.meanings(2)], [["## A", "## B", "## C", "## E", "## D"]])
        index = (f.rdir / "rev-002/bundle/frozen/meaning-r2/index.md").read_text()
        blocks = {b.split("\n")[0][4:]: b.split("\n")[-1] for b in index.strip().split("\n\n") if b.startswith("=== ")}
        old_lines, new_lines = before.split("\n"), draft.split("\n")
        self.assertEqual(blocks["## A"], f"changed: lost: before.md lines {old_lines.index('A line that the shrink cuts.') + 1}")
        self.assertEqual(blocks["## B"],
                         f"changed: added: after.md lines {new_lines.index('A8 holds except during a reconnect.') + 1}")
        self.assertEqual(blocks["## C"], "changed: order changed")
        self.assertEqual(blocks["## D"], "changed: added in revision 2")
        self.assertEqual(blocks["## E"], "changed: moved")
        for head in ("(preamble)", "## Goal", "## F", "## G", "## Residual risks"):
            self.assertEqual(blocks[head], "unchanged")
        for skip in ("## B", "## C", "## D", "## E"):
            c = f.review(review(coverage=f.lines_for(2, skip=(skip,))), expect=1, call=f.call + 1)
            f.call = c
            self.assertTrue(any("no meaning verdict" in r and skip in r for r in f.receipt(c)["reasons"]))
            f.tool("state", "--run", RUN, "--set", "active", "--reason", "re-briefed the reviewer")
        c = f.review(review(coverage=f.lines_for(2)), call=f.call + 1)
        self.assertEqual(f.receipt(c)["status"], "counted")

    def test_preamble_and_title_count_for_classification(self):
        pre = "No unsignalled live loss goes unhandled while continuity holds."
        secs = (("## Goal", ("Meet OB1.",)),
                ("## Design", ("Use INV1 throughout.", "```", "## not a heading inside a fence", "fenced line one", "```",
                               "#### A minor heading", "Line after the minor heading.")))
        p1 = make_plan(1, secs, preamble=(pre,))

        def staged_units(g, rev, nonce):
            g.tool("bundle", "--run", RUN, "--revision", str(rev), "--nonce", nonce, "--inputs", str(g.inputs()))
            manifest = json.loads((g.rdir / f".staging-{rev:03d}-{nonce}/bundle/manifest.json").read_text())
            return [i["units"] for i in manifest["items"] if i["type"] == "meaning_obligation"]

        f = self.f
        f.init()
        f.publish(1, p1)
        out = f.check(make_plan(2, secs), 1).stdout
        self.assertIn("classification: shrink-only", out)
        self.assertIn("PRESERVED", out)
        self.assertNotIn("SHRINK", out)
        self.assertIn(f"'(preamble)'", out)
        self.assertIn(f"  - {pre}", out)
        deleted = make_plan(2, secs, log=keep())
        self.assertIn(f"  - {pre}", f.check(deleted, 0).stdout)
        n = f.hand(2, deleted)
        self.assertEqual((f.staged(2, n)["cut"]["shrink_only"], f.staged(2, n)["cut"]["lost_lines"]), (True, 1))
        self.assertEqual(staged_units(f, 2, n), [["(preamble)"]])
        index = (f.rdir / f".staging-002-{n}/bundle/frozen/meaning-r2/index.md").read_text()
        self.assertIn("=== (preamble)\nbefore.md lines 1-3; after.md lines 1-2\nchanged: lost: before.md lines 2\n", index)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n)
        f.tool("findings", "propose", "--run", RUN)
        c = f.review(review(coverage=["plan read in full"]), expect=1)
        self.assertEqual(f.dispatched(c)["meaning_check"][0]["units"], ["(preamble)"])
        self.assertTrue(any("no meaning verdict" in r for r in f.receipt(c)["reasons"]))

        g = Fixture(self)
        g.init()
        g.publish(1, p1)
        edited = make_plan(2, secs, preamble=("Every signalled live loss is handled.",))
        self.assertIn("PRESERVED", g.check(edited, 1).stdout)
        n = g.hand(2, make_plan(2, secs, preamble=("Every signalled live loss is handled.",), log=keep()))
        self.assertEqual((g.staged(2, n)["cut"]["shrink_only"], g.staged(2, n)["cut"]["lost_lines"]), (True, 1))
        self.assertEqual(staged_units(g, 2, n), [["(preamble)"]])
        index = (g.rdir / f".staging-002-{n}/bundle/frozen/meaning-r2/index.md").read_text()
        self.assertIn("=== (preamble)\nbefore.md lines 1-3; after.md lines 1-3\n"
                      "changed: lost: before.md lines 2; added: after.md lines 2\n", index)
        n = g.hand(2, make_plan(2, secs, preamble=(pre,), title="importer dedupe, renamed", log=keep()))
        self.assertTrue(g.staged(2, n)["cut"]["shrink_only"])
        self.assertEqual(staged_units(g, 2, n), [["(preamble)"]])
        refresh = make_plan(2, secs, preamble=(pre,))
        n = g.hand(2, refresh)
        self.assertEqual((g.staged(2, n)["cut"]["shrink_only"], g.staged(2, n)["cut"]["lost_lines"]), (False, 0))
        self.assertEqual(staged_units(g, 2, n), [])
        g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n)
        g.tool("findings", "propose", "--run", RUN)
        c = g.review(review())
        self.assertNotIn("meaning_check", g.dispatched(c))
        g.ingest(c, {})
        for old, new in (("fenced line one", "fenced line one, edited"),
                         ("#### A minor heading", "#### A minor heading, renamed")):
            draft = make_plan(3, edit(secs, {old: new}), preamble=(pre,),
                              log=["SHRINK ## Design: reworded one line of the section; no obligation affected", *keep()])
            n = g.hand(3, draft)
            self.assertTrue(g.staged(3, n)["cut"]["shrink_only"])
            self.assertEqual(staged_units(g, 3, n), [["## Design"]])

        for text, shrink_only in ((make_plan(3, secs), True), (make_plan(3, secs, preamble=(pre,)), False)):
            h = Fixture(self)
            h.init()
            h.publish(1, p1)
            h.publish(2, make_plan(2, secs, preamble=(pre,)))
            h.publish(3, text, old=True)
            h.review(review(), expect=1 if shrink_only else 0)
            self.assertIn("classified from its text: " + ("shrink-only" if shrink_only else "not shrink-only"),
                          h.last.stdout)
            if shrink_only:
                self.assertIn("revision 3's meaning obligation is not frozen in revision 3", h.last.stderr)


class SizeEligibility(unittest.TestCase):
    def test_oversize_gate_refused_without_basis(self):
        f = Fixture(self)
        f.init()
        f.publish(1, big(1, 0, 3300))
        f.accept_risk()
        f.review(review(), kind="gate", effort="high", expect=1)
        self.assertIn("not gate-eligible under the size policy", f.last.stderr)
        self.assertIn("needed:", f.last.stderr)
        f.call -= 1
        decision_approval(f)
        f.tool("gate", "--run", RUN)
        (f.rdir / "decisions" / "S1.json").unlink()
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] revision 2 is gate-eligible under the size policy", f.last.stdout)
        self.assertIn("FAIL  [mechanical] the published approval matches the current state", f.last.stdout)

    def test_renewal_after_a_judged_shrink(self):
        f = Fixture(self)
        f.init()
        f.publish(1, big(1, 0, 3200))
        p2 = big(2, 200, 3000, log=[SHRINK_DETAIL, *keep()])
        self.assertLess(len(p2), T)
        f.publish(2, p2)
        c = f.review(review("REVISE", [finding("F1", "low")], coverage=["plan read in full", *f.lines_for(2)]))
        f.ingest(c, {"F1": "new"})
        p3 = sized(3, T + M, 200, 3000, log=["FIX R1: grew within the renewal allowance"])
        f.publish(3, p3)
        self.assertEqual(len(p3), T + M)
        self.assertIn("gate: eligible (renewal after shrink r2)", f.published.stdout)
        p4 = p3.replace("(revision 3,", "(revision 4,").replace("\n## Residual risks", "\n\n## Residual risks")
        self.assertEqual(len(p4), T + M + 1)
        f.publish(4, p4)
        self.assertIn("gate: NOT eligible", f.published.stdout)
        p5 = big(5, 1200, 2000, log=[SHRINK_DETAIL, *keep()])
        f.publish(5, p5)
        c = f.review(review(coverage=["finding R1: resolved", *f.lines_for(5)]))
        f.ingest(c, {})
        f.publish(6, sized(6, T + 10000, 1200, 2000))
        self.assertIn("gate: eligible (renewal after shrink r5)", f.published.stdout)

        g = Fixture(self)
        g.init()
        g.publish(1, big(1, 0, 3600))
        p2 = big(2, 100, 3500, log=[SHRINK_DETAIL, *keep()])
        self.assertGreater(len(p2), T)
        g.publish(2, p2)
        c = g.review(review(coverage=g.lines_for(2)))
        g.ingest(c, {})
        g.tool("gate", "--run", RUN, expect=1)
        self.assertIn("gate: NOT eligible", g.last.stdout)

        h = Fixture(self)
        h.init()
        h.publish(1, big(1, 0, 3200))
        h.publish(2, big(2, 200, 3000, log=[SHRINK_DETAIL, *keep()]))
        c = h.review(review("REVISE", [finding("F1", "low")], coverage=["plan read in full", *h.lines_for(2)]))
        h.ingest(c, {"F1": "new"})
        h.publish(3, sized(3, 280000, 200, 3000, log=["FIX R1: grew past the renewal allowance"]))
        self.assertIn("gate: NOT eligible", h.published.stdout)
        c = h.review(review("REVISE", [finding("F2", "low")], coverage=["plan read in full", "finding R1: resolved"]))
        h.ingest(c, {"F2": "new"})
        p4 = sized(4, 270000, 200, 3000, log=["FIX R2: cut back under the allowance", SHRINK_DETAIL])
        h.publish(4, p4)
        self.assertEqual(len(p4), 270000)
        self.assertIn("gate: NOT eligible", h.published.stdout)
        self.assertIn("the renewal after shrink r2 lapsed when revision 3 reached 280,000 bytes", h.published.stdout)
        self.assertNotIn("eligible (renewal after shrink r2)", h.published.stdout)
        h.publish(5, big(5, 1200, 2000, log=[SHRINK_DETAIL, *keep()]))
        c = h.review(review(coverage=["finding R2: resolved", *h.lines_for(5)]))
        h.ingest(c, {})
        h.publish(6, sized(6, T + 10000, 1200, 2000))
        self.assertIn("gate: eligible (renewal after shrink r5)", h.published.stdout)

    def test_size_decision_binds_a_judged_shrink_and_its_ceiling(self):
        f = Fixture(self)
        f.init()
        p1 = big(1, 0, 3300)
        f.publish(1, p1)
        p2 = big(2, 1, 3299, log=[SHRINK_DETAIL, *keep()])
        self.assertGreater(len(p2), len(p1))
        f.publish(2, p2)

        def gate():
            return f.tool("gate", "--run", RUN, expect=None).stdout

        ceiling = len(p2) + 5000
        f.size_decision("S1", 2, ceiling)
        out = gate()
        self.assertIn("NOTE  size decision S1 gives revision 2 no basis: revision 2 has no meaning judgement yet", out)
        self.assertIn("gate: NOT eligible", out)
        c = f.review(review(coverage=f.lines_for(2)))
        f.ingest(c, {})
        self.assertIn("gate: eligible (size decision S1)", gate())
        for over, why in (({"plan_sha256": "0" * 64}, "plan_sha256 is not revision 2's"),
                          ({"revision": 1}, "revision 1 is not a shrink-only policy revision"),
                          ({"ceiling_bytes": len(p2) - 1}, "is below revision 2's")):
            f.size_decision("S1", 2, ceiling, **over)
            out = gate()
            self.assertIn("NOTE  size decision S1 gives revision 2 no basis: ", out)
            self.assertIn(why, out)
            self.assertIn("gate: NOT eligible", out)
            self.assertNotIn("FAIL  [mechanical] size decision", out)
        for over in ({"by": "Bob"}, {"id": "S2"}):
            f.size_decision("S1", 2, ceiling, **over)
            self.assertIn("FAIL  [mechanical] size decision S1.json well formed", gate())
        f.size_decision("S1", 2, ceiling)
        later = f.size_decision("S5", 9, ceiling)
        out = gate()
        self.assertIn("NOTE  size decision S5 gives revision 2 no basis", out)
        self.assertNotIn("FAIL  [mechanical] size decision", out)
        later.unlink()
        f.size_decision("S3", 2, ceiling)
        f.accept_risk()
        g = f.review(review(), kind="gate", effort="high")
        f.ingest(g, {})
        f.tool("gate", "--run", RUN, "--publish")
        [record] = (f.rdir / "approvals").glob("*.json")
        self.assertEqual(json.loads(record.read_text())["size"]["decision"]["id"], "S1")
        f.size_decision("S4", 2, ceiling)
        f.tool("gate", "--run", RUN)
        f.publish(3, big(3, 1, 3299, extra=("y" * 6000,)))
        self.assertIn("gate: NOT eligible", f.published.stdout)
        self.assertIn("NOTE  size decision S1 gives revision 3 no basis", gate())

    def test_approval_binds_the_size_decision_and_policy(self):
        f = Fixture(self)
        f.init()
        f.publish(1, big(1, 0, 3300))
        p2 = decision_approval(f)
        path = f.rdir / "decisions" / "S1.json"
        original = path.read_bytes()
        for change in ({"quote": "another wording"}, {"recorded_by": "someone else"},
                       {"ceiling_bytes": len(p2) + 10001}, None):
            if change is None:
                path.unlink()
            else:
                path.write_text(json.dumps({**json.loads(original), **change}))
            f.tool("gate", "--run", RUN, expect=1)
            self.assertIn("FAIL  [mechanical] the published approval matches the current state", f.last.stdout)
            path.write_bytes(original)
            f.tool("gate", "--run", RUN)
        f.size_decision("S2", 2, len(p2) + 10000)
        f.tool("gate", "--run", RUN)
        f.size_decision("S3", 7, len(p2) + 10000)
        f.tool("gate", "--run", RUN)
        self.assertIn("NOTE  size decision S3 gives revision 2 no basis", f.last.stdout)
        source = TOOL.read_text()
        self.assertIn("SIZE_THRESHOLD_BYTES = 250000", source)
        copy = f.root / "changed" / "planloop.py"
        copy.parent.mkdir()
        copy.write_text(source.replace("SIZE_THRESHOLD_BYTES = 250000", "SIZE_THRESHOLD_BYTES = 100000"))
        proc = subprocess.run([sys.executable, str(copy), "gate", "--run", RUN], cwd=f.repo, capture_output=True,
                              text=True, env=f.env, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        x = Fixture(self)
        x.init(old=True)
        x.publish(1, make_plan(1), old=True)
        x.publish(2, big(2, 0, 3200))
        x.publish(3, make_plan(3, BASE + (("## Detail", pad(0, 100)),), log=[SHRINK_DETAIL, *keep()]))
        c = x.review(review(coverage=x.lines_for(3)))
        x.ingest(c, {})
        x.accept_risk()
        g = x.review(review(), kind="gate", effort="high")
        x.ingest(g, {})
        x.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PASS  [mechanical] revision 3 is gate-eligible under the size policy (under-threshold)",
                      x.last.stdout)
        draft = make_plan(4, BASE + (("## Detail", pad(0, 100)),))
        n4 = x.hand(4, draft)
        work = x.rdir / "reviews" / f"call-{c:03d}-a1"

        def broken(name, label="revisions 1 to 3 verify as a chain from HEAD: "):
            phrase = "do not verify from HEAD"
            if name.startswith("receipt"):
                label, phrase = "every stored meaning receipt is bound to revisions 1 to 3: ", "inspect that receipt"
            x.tool("gate", "--run", RUN, expect=1)
            self.assertIn(f"FAIL  [mechanical] {label}{name}", x.last.stdout)
            outs = [x.last.stdout]
            for args, stdin in ((("dispatch", "--run", RUN, "--call", str(g + 1), "--attempt", "1", "--kind", "working",
                                  "--effort", "medium"), None),
                                (("bundle", "--run", RUN, "--revision", "4", "--nonce", n4, "--inputs", str(x.inputs())),
                                 None),
                                (("handback", "--run", RUN, "--check"), draft), (("publish", "--run", RUN, "--recover"), None)):
                x.tool(*args, stdin=stdin, expect=2)
                self.assertIn(name, x.last.stderr)
                self.assertIn(phrase, x.last.stderr)
                outs.append(x.last.stdout + x.last.stderr)
            self.assertFalse([o for o in outs if "size policy" in o or "size: " in o], outs)

        for target, change, name in (
                ("rev-002/handback.json", lambda d: {k: v for k, v in d.items() if k != "cut"}, "revision 2: "),
                ("rev-001/handback.json", lambda d: {**d, "cut": {"shrink_only": False, "lost_lines": 0,
                                                                  "removed_sections": 0, "threshold_bytes": 1,
                                                                  "live_answers": []}},
                 "revision 1: "),
                ("rev-001/plan.md", None, "revision 1: "), ("rev-002/plan.md", None, "revision 2: "),
                ("HEAD", lambda d: {**d, "revision_sha256": "0" * 64}, "HEAD points at a revision whose record differs"),
                (f"reviews/call-{c:03d}-a1/receipt.json", lambda d: {**d, "revision_sha256": "0" * 64},
                 f"receipt of call {c} attempt 1: "),
                (f"reviews/call-{c:03d}-a1/input/dispatch.json",
                 lambda d: {**d, "meaning_check": [{**d["meaning_check"][0], "units": ["## Goal"]}]},
                 f"receipt of call {c} attempt 1: ")):
            path = x.rdir / target
            original = path.read_bytes()
            if change is None:
                path.write_bytes(original.replace(b"Meet OB1.", b"Meet OB2."))
            else:
                path.write_text(json.dumps(change(json.loads(original))))
            broken(name)
            path.write_bytes(original)
            x.tool("gate", "--run", RUN)
        hb, rv = x.rdir / "rev-002/handback.json", x.rdir / "rev-002/revision.json"
        originals = hb.read_bytes(), rv.read_bytes()
        hb.write_text(json.dumps({k: v for k, v in json.loads(originals[0]).items() if k != "cut"}))
        rv.write_text(json.dumps({**json.loads(originals[1]),
                                  "handback_sha256": hashlib.sha256(hb.read_bytes()).hexdigest()}))
        x.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] revision integrity: revision 3 does not chain to revision 2", x.last.stdout)
        broken("revision 3", label="revision integrity: ")
        hb.write_bytes(originals[0])
        rv.write_bytes(originals[1])
        x.tool("gate", "--run", RUN)

        y = Fixture(self)
        y.init(old=True)
        y.publish(1, make_plan(1), old=True)
        y.publish(2, make_plan(2))
        y.publish(3, make_plan(3, edit(BASE, add={"## Goal": ("And meet it quickly.",)})), old=True)
        y.accept_risk()
        g = y.review(review(), kind="gate", effort="high", old=True)
        y.ingest(g, {}, old=True)
        y.tool("gate", "--run", RUN, "--publish", old=True)
        y.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] the published approval matches the current state", y.last.stdout)
        hb = y.rdir / "rev-002/handback.json"
        hb.write_text(json.dumps({k: v for k, v in json.loads(hb.read_text()).items() if k != "cut"}))
        y.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] revisions 1 to 3 verify as a chain from HEAD: revision 2: ", y.last.stdout)
        self.assertNotIn("the published approval matches", y.last.stdout)


class Compatibility(unittest.TestCase):
    def old_run(self, f, approve=True):
        f.init(old=True)
        f.publish(1, plan_text(1), old=True)
        c = f.review(review("REVISE", [finding("F1")]), old=True)
        f.ingest(c, {"F1": "new"}, old=True)
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]), old=True)
        c = f.review(review(coverage=["plan read in full", "finding R1: resolved"]), old=True)
        f.ingest(c, {}, old=True)
        shrunk = plan_text(3, shrink=["## Design: dropped line three, it restated INV1; no obligation affected"])
        f.publish(3, shrunk.replace("Line three of the design.\n", ""), old=True)
        f.accept_risk()
        if approve:
            g = f.review(review(), kind="gate", effort="high", old=True)
            f.ingest(g, {}, old=True)
            f.tool("gate", "--run", RUN, "--publish", old=True)

    def test_runs_approved_before_the_change_still_verify(self):
        f = Fixture(self)
        self.old_run(f)
        run_json = (f.rdir / "run.json").read_bytes()
        old = f.tool("gate", "--run", RUN, old=True)
        new = f.tool("gate", "--run", RUN)
        self.assertEqual((new.stdout, new.returncode), (old.stdout, old.returncode))
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "nothing changed", expect=1)
        self.assertIn("approval still verifies", f.last.stderr)
        private = Path(f.dispatched(f.call)["snapshot"]).parent
        for dirpath, dirnames, filenames in os.walk(private):
            os.chmod(dirpath, 0o755)
        shutil.rmtree(private)
        f.tool("gate", "--run", RUN, expect=1)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "gate copy lost; re-gate")
        g = f.review(review(), kind="gate", effort="high")
        self.assertNotIn("meaning_check", f.dispatched(g))
        self.assertNotIn("size", f.last.stdout)
        f.ingest(g, {})
        f.tool("gate", "--run", RUN, "--publish")
        out = f.tool("gate", "--run", RUN).stdout
        self.assertNotIn("size", out)
        self.assertEqual((f.rdir / "run.json").read_bytes(), run_json)
        f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "escalated", "--risk-domains", "recovery",
               "--rationale", "found that resume semantics change")

    def test_policy_range_starts_at_first_new_publication(self):
        f = Fixture(self)
        self.old_run(f, approve=False)
        run_json = (f.rdir / "run.json").read_bytes()
        f.publish(4, plan_text(4, extra_design=["A line added by revision four."]))
        self.assertIn("size: revision 4 is", f.published.stdout)
        self.assertIn("meaning: no shrink awaits judgement", f.published.stdout)
        self.assertEqual((f.rdir / "run.json").read_bytes(), run_json)
        f.init()
        g = f.review(review(), kind="gate", effort="high")
        f.ingest(g, {})
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PASS  [judgement, recorded]", f.last.stdout)
        self.assertEqual((f.rdir / "run.json").read_bytes(), run_json)
        f.tool("reviewers", "--run", RUN, "--model", "gpt-6-astra", "--gate-model", "gpt-6-astra",
               "--quote", "keep astra for both")

    def test_revision_staged_by_the_old_tool_is_refused(self):
        f = Fixture(self)
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.hand(2, make_plan(2), old=True)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()), expect=1)
        self.assertIn("revision 2 was staged by planloop before the size policy; re-run handback for it", f.last.stderr)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()), old=True)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, expect=1)
        self.assertIn("revision 2 was staged by planloop before the size policy", f.last.stderr)
        shutil.rmtree(f.rdir / f".staging-002-{nonce}")
        f.publish(2, make_plan(2))
        self.assertIn("size: revision 2 is", f.published.stdout)

    def test_older_processes_after_the_policy_applies_grant_nothing(self):
        f = Fixture(self)
        f.init()
        f.publish(1, make_plan(1))
        f.publish(2, make_plan(2))
        new_nonce = f.stage(3, make_plan(3))
        old_nonce = f.stage(3, make_plan(3, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN]),
                            old=True)
        flag = f.root / "release"
        f.fault("list", f"pause:{flag}")
        new = subprocess.Popen([sys.executable, str(TOOL), "publish", "--run", RUN, "--revision", "3", "--nonce",
                                new_nonce], cwd=f.repo, env={**f.env, "PLANLOOP_CRASH_AT": "before_rename"},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 60
        while not Path(f"{flag}.waiting").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        old = subprocess.Popen([sys.executable, str(OLD_TOOL), "publish", "--run", RUN, "--revision", "3", "--nonce",
                                old_nonce], cwd=f.repo, env={**f.env, "PLANLOOP_LOCK_TIMEOUT": "60"},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        self.assertIsNone(old.poll())
        flag.touch()
        self.assertEqual(new.wait(timeout=120), 99)
        out, err = old.communicate(timeout=120)
        self.assertEqual(old.returncode, 0, err)
        self.assertEqual(f.head(), 3)
        self.assertNotIn("cut", json.loads((f.rdir / "rev-003/handback.json").read_text()))
        self.assertTrue((f.rdir / f".staging-003-{new_nonce}").exists())
        f.tool("findings", "propose", "--run", RUN)
        note = ("NOTE  revision 3 was published by planloop code that predates the size policy (no cut); classified "
                "from its text: shrink-only")
        f.review(review(), expect=1)
        f.call -= 1
        self.assertIn(note, f.last.stdout)
        self.assertIn("revision 3's meaning obligation is not frozen in revision 3; stage, bundle and publish a "
                      "successor with the current tool", f.last.stderr)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn(note, f.last.stdout)
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn(note, f.last.stdout)
        self.assertIn("FAIL  [judgement, recorded]", f.last.stdout)
        f.publish(4, (f.rdir / "rev-003/plan.md").read_text().replace("(revision 3,", "(revision 4,"))
        self.assertEqual([i["revision"] for i in f.meanings(4)], [3])
        c = f.review(review(coverage=["plan read in full"]), expect=1)
        self.assertEqual(f.dispatched(c)["meaning_check"][0]["revision"], 3)
        self.assertIn("predates the size policy", f.feedback(c))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [judgement, recorded]", f.last.stdout)
        c = f.review(review(coverage=f.lines_for(4)), call=c, attempt=2)
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("PASS  [judgement, recorded]", f.last.stdout)

        b = Fixture(self)
        b.init()
        b.publish(1, make_plan(1))
        b.publish(2, make_plan(2))
        b.publish(3, make_plan(3, edit(BASE, add={"## Goal": ("And meet it quickly.",)})), old=True)
        c = b.review(review())
        self.assertIn("classified from its text: not shrink-only", b.last.stdout)
        self.assertNotIn("meaning_check", b.dispatched(c))

        e = Fixture(self)
        e.init()
        e.publish(1, make_plan(1))
        e.publish(2, make_plan(2, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()]))
        c = e.review(review(), old=True)
        self.assertEqual(e.receipt(c)["status"], "counted")
        self.assertNotIn("meaning_check", e.dispatched(c))
        e.ingest(c, {})
        e.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [judgement, recorded]", e.last.stdout)
        e.review_file.write_text(json.dumps(review(coverage=e.lines_for(2))))
        e.tool("dispatch", "--run", RUN, "--call", "2", "--attempt", "1", "--kind", "working", "--effort", "medium",
               env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        self.assertEqual(e.dispatched(2)["meaning_check"][0]["revision"], 2)
        e.tool("receipt", "--run", RUN, "--call", "2", "--attempt", "1", old=True, expect=1)
        self.assertIn("meaning_check", e.last.stderr)
        self.assertFalse((e.rdir / "reviews/call-002-a1/receipt.json").exists())
        e.tool("receipt", "--run", RUN, "--call", "2", "--attempt", "1")
        self.assertEqual(e.receipt(2)["status"], "counted")
        e.tool("gate", "--run", RUN, expect=1)
        self.assertIn("PASS  [judgement, recorded]", e.last.stdout)

        d = Fixture(self)
        d.init()
        d.publish(1, big(1, 0, 3300))
        d.accept_risk()
        g = d.review(review(), kind="gate", effort="high", old=True)
        d.ingest(g, {}, old=True)
        d.tool("gate", "--run", RUN, "--publish", old=True)
        d.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] revision 1 is gate-eligible under the size policy", d.last.stdout)
        self.assertIn("FAIL  [mechanical] the published approval matches the current state", d.last.stdout)
        d.tool("state", "--run", RUN, "--set", "active", "--reason", "older approval lacks the size facts")

    def test_an_input_change_lapses_exactly_the_input_lines(self):
        f = Fixture(self)
        files = ["docs/req.md", "src/a.rs"] + [f"docs/f{i}.md" for i in range(1, 5)]
        for rel in files[2:] + ["docs/undeclared.md"]:
            (f.repo / rel).write_text(f"{rel}\n")
        f.git("add", "-A")
        f.git("commit", "-qm", "inputs")
        f.init(old=True)
        f.publish(1, plan_text(1), inputs=f.inputs(repo_files=files, dirs=()), old=True)
        f.accept_risk()
        g = f.review(review(), kind="gate", effort="high", old=True)
        f.ingest(g, {}, old=True)
        f.tool("gate", "--run", RUN, "--publish", old=True)
        saved = f.tool("gate", "--run", RUN, old=True)
        saved = (saved.stdout, saved.returncode)
        receipt = (f.rdir / f"reviews/call-{g:03d}-a1/receipt.json").read_bytes()
        approvals = tree(f.rdir / "approvals")
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "nothing changed", expect=1)
        with open(f.repo / "docs" / "undeclared.md", "a") as handle:
            handle.write("edited\n")
        for tool in (True, False):
            proc = f.tool("gate", "--run", RUN, old=tool)
            self.assertEqual((proc.stdout, proc.returncode), saved)
        for rel in files:
            with open(f.repo / rel, "a") as handle:
                handle.write("changed\n")
        changes = [f"file {rel} changed or was deleted" for rel in files]
        old = f.tool("gate", "--run", RUN, old=True, expect=1)
        new = f.tool("gate", "--run", RUN, expect=1)
        self.assertEqual((old.stdout, old.returncode), (new.stdout, new.returncode))
        self.assertEqual((new.stdout, new.returncode), expected_lapse(saved, changes))
        self.assertIn(f"relevant inputs changed during the review: {changes[:5]}", new.stdout)
        self.assertNotIn(changes[5], new.stdout.split("gate call verified")[1].split("\n")[0])
        self.assertEqual((f.rdir / f"reviews/call-{g:03d}-a1/receipt.json").read_bytes(), receipt)
        self.assertEqual(tree(f.rdir / "approvals"), approvals)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "inputs changed")

    def old_crash(self, f, new_staging=False, point="after_rename"):
        f.init(old=True)
        f.publish(1, plan_text(1), old=True)
        nonce = f.stage(2, plan_text(2), old=not new_staging)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": point},
               expect=99, old=True)
        if probe_any(f.rdir / ".lock"):
            f.tool("publish", "--run", RUN, "--recover", expect=3)
            self.assertIn("its record names no PID namespace (a planloop that did not yet record one wrote it)",
                          f.last.stderr)
            shutil.rmtree(f.rdir / ".lock")
        return nonce

    def test_old_tool_crash_then_recovery_by_every_locking_command(self):
        for command in LOCKING:
            f = Fixture(self)
            nonce = self.old_crash(f)
            keys = sorted(json.loads((f.rdir / "run.json").read_text()))
            f.review_file.write_text(json.dumps(review()))
            f.tool(*command, expect=None)
            out = f.last.stdout + f.last.stderr
            self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", out)
            self.assertIn(f"--nonce {nonce} --transcript ", out)
            self.assertEqual(f.head(), 1)
            self.assertEqual(sorted(json.loads((f.rdir / "run.json").read_text())), keys)
            self.assertFalse(re.search(r"^(size:|size policy:)", out, re.M), out)
            restage = re.search(r"re-stage it: (handback .*?), then bundle and publish", out).group(1)
            f.tool(*shlex.split(restage))
            f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
            self.assertIn("size: revision 2 is", f.last.stdout)
            self.assertEqual(f.head(), 2)
        f = Fixture(self)
        nonce = self.old_crash(f, new_staging=True)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("no publishing intent names it", f.last.stderr)
        self.assertIn(f"--nonce {nonce} --transcript ", f.last.stderr)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertEqual(f.head(), 1)
        f = Fixture(self)
        self.old_crash(f, point="after_head")
        self.assertEqual(f.head(), 2)
        before = tree(f.rdir)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse(re.search(r"^(size:|size policy:)", f.last.stdout + f.last.stderr, re.M))
        self.assertEqual(tree(f.rdir), before)
        f.publish(3, plan_text(3))
        self.assertIn("size: revision 3 is", f.published.stdout)

    def test_new_tool_crash_points_converge_and_report(self):
        f = Fixture(self)
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.stage(2, make_plan(2))
        before = tree(f.rdir, skip=(f".staging-002-{nonce}",))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "before_rename"},
               expect=99)
        self.assertEqual(tree(f.rdir, skip=(f".staging-002-{nonce}",)), before)
        self.assertEqual(f.head(), 1)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertIn("size: revision 2 is", f.last.stdout)
        self.assertIn("size policy: ", f.last.stdout)
        for command in LOCKING:
            g = Fixture(self)
            g.init()
            g.publish(1, make_plan(1))
            n = g.stage(2, make_plan(2))
            g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
                   expect=99)
            g.review_file.write_text(json.dumps(review()))
            g.tool(*command, expect=None)
            self.assertEqual(g.head(), 2, command)
            self.assertIn("size: revision 2 is", g.last.stderr)
            self.assertIn("size policy: ", g.last.stderr)
        h = Fixture(self)
        h.init()
        h.publish(1, make_plan(1))
        n = h.stage(2, make_plan(2))
        h.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_head"},
               expect=99)
        before = tree(h.rdir, skip=(".publishing-rev-002",))
        for _ in range(2):
            h.tool("publish", "--run", RUN, "--recover")
            self.assertIn("size: revision 2 is", h.last.stdout)
            self.assertIn("size policy: ", h.last.stdout)
        self.assertEqual(tree(h.rdir), before)
        h.tool("findings", "propose", "--run", RUN)
        h.review(review())
        out = h.last.stdout
        self.assertLess(out.index("size: revision 2 is"), out.index("call 1 attempt 1:"))
        self.assertIn("size policy: ", out)
        h.tool("gate", "--run", RUN, expect=1)
        self.assertIn("size: revision 2 is", h.last.stdout)
        self.assertIn("size policy: ", h.last.stdout)


COUNT_WALKS = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
walked, real = [], tool.verify_revision
def counted(run, n, rev_dir=None, deep=True, **kw):
    if not deep:
        walked.append(n)
    return real(run, n, rev_dir, deep, **kw)
tool.verify_revision = counted
code = tool.main(sys.argv[2:])
print(json.dumps({"code": code, "walked": walked}))
"""


SWAP_AT_DEEP = """
import importlib.util, json, sys, hashlib
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
mode, real, done = sys.argv[2], tool.verify_revision, []
def swapped(run, n, rev_dir=None, deep=True, **kw):
    if deep and rev_dir is None and not done and run.head() and n == run.head()[0]:
        done.append(1)
        d = run.rev_dir(n)
        plan, rv, mf, fp = d / "plan.md", d / "revision.json", d / "bundle" / "manifest.json", \\
            d / "bundle" / "frozen" / "plan.md"
        saved = plan.read_bytes(), rv.read_bytes(), mf.read_bytes()
        plan.write_bytes(saved[0] + b"Injected line after the walk.\\n")
        fp.write_bytes(plan.read_bytes())
        digest = hashlib.sha256(plan.read_bytes()).hexdigest()
        m = json.loads(saved[2])
        next(i for i in m["items"] if i["type"] == "plan")["sha256"] = digest
        mf.write_text(json.dumps(m))
        r = json.loads(saved[1])
        r["plan_sha256"], r["bundle_sha256"] = digest, hashlib.sha256(mf.read_bytes()).hexdigest()
        rv.write_text(json.dumps(r))
        try:
            return real(run, n, rev_dir, deep, **kw)
        finally:
            if mode == "restore":
                plan.write_bytes(saved[0])
                fp.write_bytes(saved[0])
                rv.write_bytes(saved[1])
                mf.write_bytes(saved[2])
    return real(run, n, rev_dir, deep, **kw)
tool.verify_revision = swapped
print(json.dumps({"code": tool.main(sys.argv[3:])}))
"""

FAIL_WALK = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
at, real = int(sys.argv[2]), tool.verify_revision
def failing(run, n, rev_dir=None, deep=True, **kw):
    if not deep and n == at:
        raise tool.Fail(f"injected: revision {n} changed after its publication")
    return real(run, n, rev_dir, deep, **kw)
tool.verify_revision = failing
print(json.dumps({"code": tool.main(sys.argv[3:])}))
"""


BD_GLITCH = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
mode = sys.argv[2]
def glitch(self):
    if mode == "decode":
        b"\\xff".decode("utf-8")
    raise tool.Fail("bd list --parent: malformed JSON (Expecting value)")
tool.Run.findings = glitch
print(json.dumps({"code": tool.main(sys.argv[3:])}))
"""

BROKEN_REPORT = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
def broken(*args, **kw):
    raise TypeError("injected")
tool.policy_report = broken
print(json.dumps({"code": tool.main(sys.argv[2:])}))
"""

RACE_PUBLISH = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
real, calls = tool.policy_now, []
def racing(run):
    calls.append(run)
    if len(calls) == int(sys.argv[4]):
        tool.main(["publish", "--run", run.id, "--revision", sys.argv[2], "--nonce", sys.argv[3]])
    return real(run)
tool.policy_now = racing
print(json.dumps({"code": tool.main(sys.argv[5:])}))
"""

SWAP_AT_RENAME = """
import importlib.util, json, sys, hashlib
from pathlib import Path
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
real = tool.rename
def swapped(src, dst, **kw):
    src = Path(src)
    if src.name.startswith(".staging-") and Path(dst).name.startswith("rev-"):
        plan = src / "plan.md"
        lines = plan.read_text().splitlines(True)
        del lines[next(i for i, line in enumerate(lines) if line.startswith("- ") and i > 2)]
        plan.write_text("".join(lines))
        rv = src / "revision.json"
        r = json.loads(rv.read_text())
        r["plan_sha256"] = hashlib.sha256(plan.read_bytes()).hexdigest()
        rv.write_text(json.dumps(r))
    return real(src, dst, **kw)
tool.rename = swapped
print(json.dumps({"code": tool.main(sys.argv[2:])}))
"""

SWAP_STAGING_AT_RENAME = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
mode, real = sys.argv[2], tool.rename
def swapped(src, dst, **kw):
    src = Path(src)
    if src.name.startswith(".staging-") and Path(dst).name.startswith("rev-"):
        if mode == "manifest":
            mf = src / "bundle" / "manifest.json"
            mf.write_text(json.dumps(json.loads(mf.read_text()), indent=1))
        elif mode == "unlink":
            (src / "plan.md").unlink()
        elif mode == "directory":
            (src / "handback.json").unlink()
            (src / "handback.json").mkdir()
        elif mode == "overlay":
            m = json.loads((src / "bundle" / "manifest.json").read_text())
            e = next(e for i in m["items"] if i["type"] == "overlay" for e in i["entries"] if e["sha256"])
            with open(src / "bundle" / "overlay" / e["path"], "a") as handle:
                handle.write("edited after verification\\n")
        else:
            src = src.parent / mode
    elif src.name.startswith("rev-") and Path(dst).name.startswith(".orphan-") and len(sys.argv) > 3 and \
            sys.argv[3] == "stuck":
        raise tool.Conflict(f"could not rename {src} -> {dst}: a file inside is held open (drvfs EACCES)")
    return real(src, dst, **kw)
tool.rename = swapped
print(json.dumps({"code": tool.main(sys.argv[4 if sys.argv[3] == "stuck" else 3:])}))
"""

READ_ERROR_ONCE = SWAP_STAGING_AT_RENAME.replace("tool.rename = swapped", """tool.rename = swapped
seen, plain = [], tool.present
def present(path, what, link=False):
    if Path(path).parent.name == "rev-002" and Path(path).name == "plan.md" and not seen:
        seen.append(path)
        raise PermissionError(13, "Permission denied", str(path))
    return plain(path, what, link)
tool.present = present""")

INTENT_READ_ERROR_ONCE = READ_ERROR_ONCE.replace(
    'Path(path).parent.name == "rev-002" and Path(path).name == "plan.md"',
    'Path(path).name == ".publishing-rev-002"')

PRED_READ_ERROR_ONCE = READ_ERROR_ONCE.replace(
    'Path(path).parent.name == "rev-002" and Path(path).name == "plan.md"', 'what == "revision 1 revision.json"')

SNAP_READ_ERROR_ONCE = SWAP_STAGING_AT_RENAME.replace("tool.rename = swapped", """tool.rename = swapped
seen, plain = [], tool.sha_file
def sha_file(path):
    if "snap-r002-" in str(path) and not seen:
        seen.append(path)
        raise PermissionError(13, "Permission denied", str(path))
    return plain(path)
tool.sha_file = sha_file""")

EXISTS_DENIED_ONCE = SWAP_STAGING_AT_RENAME.replace("tool.rename = swapped", """tool.rename = swapped
seen, plain = [], Path.exists
def exists(self, *a, **kw):
    if self.name == "rev-002" and not seen:
        seen.append(self)
        raise PermissionError(13, "Permission denied", str(self))
    return plain(self, *a, **kw)
Path.exists = exists""")

EIO_AT_RENAME = """
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
mode, real = sys.argv[2], os.rename
def rename(src, dst):
    if Path(src).name.startswith(mode) and Path(dst).name.startswith(".orphan-" if mode == "rev-" else "rev-"):
        raise OSError(5, "Input/output error", str(src))
    return real(src, dst)
os.rename = rename
print(json.dumps({"code": tool.main(sys.argv[3:])}))
"""

UNLINK_DENIED = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
real = Path.unlink
def unlink(self, missing_ok=False):
    if self.name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(self))
    return real(self, missing_ok)
Path.unlink = unlink
print(json.dumps({"code": tool.main(sys.argv[2:])}))
"""

REPLACE_DENIED = UNLINK_DENIED.replace("""real = Path.unlink
def unlink(self, missing_ok=False):
    if self.name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(self))
    return real(self, missing_ok)
Path.unlink = unlink""", """import os
real = os.replace
def replace(src, dst):
    if Path(dst).name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(dst))
    return real(src, dst)
os.replace = replace""")

HEAD_NO_SPACE = REPLACE_DENIED.replace('''Path(dst).name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(dst))''', '''Path(dst).name == "HEAD":
        raise OSError(28, "No space left on device", str(dst))''')

OPEN_NO_SPACE = UNLINK_DENIED.replace("""real = Path.unlink
def unlink(self, missing_ok=False):
    if self.name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(self))
    return real(self, missing_ok)
Path.unlink = unlink""", """import builtins
def opened(file, *args, **kw):
    if Path(file).name.startswith("..publishing-rev-"):
        raise OSError(28, "No space left on device", str(file))
    return builtins.open(file, *args, **kw)
tool.open = opened""")

SWAP_THEN_UNLINK_DENIED = SWAP_STAGING_AT_RENAME.replace("tool.rename = swapped", """tool.rename = swapped
plain_unlink = Path.unlink
def unlink(self, missing_ok=False):
    if self.name.startswith(".publishing-rev-"):
        raise PermissionError(13, "Permission denied", str(self))
    return plain_unlink(self, missing_ok)
Path.unlink = unlink""")


PATCHED = """
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("planloop", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
arg, real, seen = sys.argv[2], os.rename, []
PATCH
print(json.dumps({"code": tool.main(sys.argv[3:])}))
"""

RELEASE_EIO = PATCHED.replace("PATCH", """def rename(src, dst):
    if Path(dst).name.startswith(".lock-released-"):
        seen.append(dst)
        if len(seen) == int(arg):
            raise OSError(5, "Input/output error", str(src))
    return real(src, dst)
os.rename = rename""")

EIO_FROM = PATCHED.replace("PATCH", """def rename(src, dst):
    if Path(src).name.startswith(arg):
        raise OSError(5, "Input/output error", str(src))
    return real(src, dst)
os.rename = rename""")

EIO_ONTO = EIO_FROM.replace("Path(src).name.startswith(arg)", "Path(dst).name == arg")

WRITE_FAILS = PATCHED.replace("PATCH", """import errno, re
where, code = arg.split("|")
number = getattr(errno, code)
write, replace, mkdir = Path.write_bytes, os.replace, Path.mkdir
def failing(self, data):
    if re.search(where, str(self)):
        write(self, data[:1])
        raise OSError(number, os.strerror(number), str(self))
    return write(self, data)
def replacing(src, dst):
    if re.search(where, str(dst)):
        raise OSError(number, os.strerror(number), str(src), None, str(dst))
    return replace(src, dst)
def making(self, *a, **kw):
    if re.search(where, str(self)):
        raise OSError(number, os.strerror(number), str(self))
    return mkdir(self, *a, **kw)
Path.write_bytes, os.replace, Path.mkdir = failing, replacing, making""")

OWNER_LOST = PATCHED.replace("PATCH", "tool.Lock.read_owner = lambda self, path=None: None")

LANDED_EIO = PATCHED.replace("PATCH", """def rename(src, dst):
    real(src, dst)
    if Path(dst).name.startswith(arg):
        raise OSError(5, "Input/output error", str(src))
os.rename = rename""")

LANDED_EIO_ONTO = LANDED_EIO.replace("Path(dst).name.startswith(arg)", "Path(dst).name == arg")

OWNER_GARBLED = PATCHED.replace("PATCH", """prepare = tool.prepare
def prepared(run):
    (run.dir / ".lock" / "owner.json").write_bytes(b"\\xff\\xfe")
    prepare(run)
tool.prepare = prepared""")

SNAPSHOT_TOUCHED = PATCHED.replace("PATCH", """import subprocess
launch = subprocess.Popen
def run(argv, *a, **kw):
    if "review" in argv:
        repo = Path(argv[argv.index("--repo") + 1])
        os.chmod(repo, 0o755)
        (repo / "extra.txt").write_text("x")
    return launch(argv, *a, **kw)
subprocess.Popen = run""")

READ_FAILS = PATCHED.replace("PATCH", """import errno, re, shutil
kind, where, code = arg.split("|")
number = getattr(errno, code)
read, copyfile = Path.read_bytes, shutil.copyfile
def reading(self):
    if kind == "read" and re.search(where, str(self)):
        raise OSError(number, os.strerror(number), str(self))
    return read(self)
def copying(src, dst, *a, **kw):
    if kind == "copy" and re.search(where, str(src)):
        raise OSError(number, os.strerror(number), str(src))
    return copyfile(src, dst, *a, **kw)
Path.read_bytes, shutil.copyfile = reading, copying""")

OPEN_FAILS = PATCHED.replace("PATCH", """import builtins, errno, re
where, code = arg.split("|")
number = getattr(errno, code)
plain = builtins.open
def opened(file, mode="r", *a, **kw):
    if "w" in str(mode) and re.search(where, str(file)):
        with plain(file, mode, *a, **kw) as handle:
            handle.write(b"x" if "b" in mode else "x")
        raise OSError(number, os.strerror(number), str(file))
    return plain(file, mode, *a, **kw)
builtins.open = opened""")

BUNDLE_STUCK = WRITE_FAILS.replace("Path.write_bytes, os.replace, Path.mkdir = failing, replacing, making", """\
Path.write_bytes, os.replace, Path.mkdir = failing, replacing, making
import shutil
remove = shutil.rmtree
def removing(path, ignore_errors=False, *a, **kw):
    if Path(path).name == "bundle":
        if ignore_errors:
            return None
        raise OSError(errno.EBUSY, os.strerror(errno.EBUSY), str(path))
    return remove(path, ignore_errors, *a, **kw)
shutil.rmtree = removing""")

STRAY_OSERROR = PATCHED.replace("PATCH", """import errno
def broken(args):
    raise OSError(errno.EIO, os.strerror(errno.EIO), "/nowhere/ledger.md")
tool.cmd_ledger = broken""")

STRAY_PIPE = PATCHED.replace("PATCH", """import errno
def broken(args):
    raise BrokenPipeError(errno.EPIPE, os.strerror(errno.EPIPE))
tool.cmd_ledger = broken""")

STRAY_AFTER_RESERVE = PATCHED.replace("PATCH", """import errno, signal
moved, plain, block = [], tool.rename, signal.pthread_sigmask
def renaming(src, dst, *a, **kw):
    plain(src, dst, *a, **kw)
    moved.append(Path(dst).name.startswith("call-"))
def masking(how, mask):
    if any(moved) and how == signal.SIG_BLOCK:
        raise BrokenPipeError(errno.EPIPE, os.strerror(errno.EPIPE))
    return block(how, mask)
tool.rename, signal.pthread_sigmask = renaming, masking""")

STOPPED_AT = PATCHED.replace("PATCH", """import re
where, landed = arg.split("|")
write, replace = Path.write_bytes, os.replace
def writing(self, data):
    if re.search(where, str(self)):
        write(self, data[:1])
        raise KeyboardInterrupt
    return write(self, data)
def replacing(src, dst):
    if re.search(where, str(dst)):
        if landed:
            replace(src, dst)
        raise KeyboardInterrupt
    return replace(src, dst)
Path.write_bytes, os.replace = writing, replacing""")

CONCURRENT_BUNDLE = PATCHED.replace("PATCH", """import subprocess
fill = tool.fill_snapshot
def filling(*a, **kw):
    if not seen:
        seen.append(subprocess.run([sys.executable, sys.argv[1], *sys.argv[3:]], capture_output=True, text=True))
        print(json.dumps({"other": seen[0].returncode, "said": seen[0].stderr}), file=sys.stderr)
    return fill(*a, **kw)
tool.fill_snapshot = filling""")

PAUSED = """import time
def pause():
    Path(arg + ".at").write_text("x")
    while not Path(arg + ".go").exists():
        time.sleep(0.05)
"""

PAUSED_AT_BUNDLE_LOCK = PATCHED.replace("PATCH", PAUSED + """enter = tool.Lock.__enter__
def entering(self):
    if self.path.name == ".lock-bundle":
        pause()
    return enter(self)
tool.Lock.__enter__ = entering""")

STOPPED_AFTER_REVISION = PATCHED.replace("PATCH", PAUSED + """replace = os.replace
def replacing(src, dst):
    replace(src, dst)
    if Path(dst).name == "revision.json":
        pause()
        raise KeyboardInterrupt
os.replace = replacing""")

PAUSED_HOLDING_LOCK = PATCHED.replace("PATCH", PAUSED + """enter = tool.Lock.__enter__
def entering(self):
    out = enter(self)
    if not seen:
        seen.append(self)
        pause()
    return out
tool.Lock.__enter__ = entering""")

PAUSED_AT_SNAPSHOT = PATCHED.replace("PATCH", PAUSED + """fill = tool.fill_snapshot
def filling(*a):
    pause()
    return fill(*a)
tool.fill_snapshot = filling""")

OWN_PID_ELSEWHERE = PATCHED.replace("PATCH", """record = json.loads(Path(arg).read_text())
Path(arg).write_text(json.dumps({**record, "pid": os.getpid(), "pid_ns": tool.pid_ns() + 1, "start": None}))""")

SURROGATE_RUNNER = r"""import subprocess, sys
from pathlib import Path
code = subprocess.run([sys.executable, sys.argv[1], *sys.argv[2:]]).returncode
for out in Path(sys.argv[sys.argv.index("--artifacts") + 1]).glob("claudex-*/stdout.txt"):
    out.write_text(out.read_text().replace('"command": "', '"command": "ls ~/.codex/sessions \\ud800; ', 1))
sys.exit(code)
"""

PAUSED_AT_STAGING_VERIFY = PATCHED.replace("PATCH", PAUSED + """verify = tool.verify_revision
def verifying(run, n, rev_dir=None, **kw):
    if rev_dir is not None and rev_dir.name.startswith(".staging-") and not seen:
        seen.append(rev_dir)
        pause()
    return verify(run, n, rev_dir, **kw)
tool.verify_revision = verifying""")

REPLACE_LANDED_EIO = PATCHED.replace("PATCH", """replace = os.replace
def replacing(src, dst):
    replace(src, dst)
    if Path(dst).name == arg:
        raise OSError(5, "Input/output error", str(src), None, str(dst))
os.replace = replacing""")

STAGED_MEANWHILE = PATCHED.replace("PATCH", """plain = Path.mkdir
def mkdir(self, *a, **kw):
    if self.name.startswith(".staging-"):
        plain(self, *a, **kw)
        (self / "plan.md").write_text("theirs")
    return plain(self, *a, **kw)
Path.mkdir = mkdir""")

CORRUPTING_RUNNER = """
import json, os, subprocess, sys
from pathlib import Path
proc = subprocess.run([sys.executable, *sys.argv[1:]], capture_output=True, text=True)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
adir = Path(json.loads(proc.stdout.strip().splitlines()[-1])["artifacts"])
exec(os.environ["CORRUPT"])
sys.exit(proc.returncode)
"""

MKDIR_EIO = PATCHED.replace("PATCH", """plain = Path.mkdir
def mkdir(self, *a, **kw):
    if self.name.startswith(arg):
        raise OSError(5, "Input/output error", str(self))
    return plain(self, *a, **kw)
Path.mkdir = mkdir""")

RMDIR_EIO = PATCHED.replace("PATCH", """plain = Path.rmdir
def rmdir(self):
    if self.name == arg:
        raise OSError(5, "Input/output error", str(self))
    return plain(self)
Path.rmdir = rmdir""")

EXISTS_EIO = PATCHED.replace("PATCH", """plain = Path.exists
def exists(self, *a, **kw):
    if self.name.startswith(arg):
        raise PermissionError(13, "Permission denied", str(self))
    return plain(self, *a, **kw)
Path.exists = exists""")

PUBLISHED_HANDBACK_DENIED = PATCHED.replace("PATCH", """plain, prepare, on = Path.read_bytes, tool.prepare, []
def prepared(run):
    prepare(run)
    on.append(run)
def read_bytes(self):
    if on and self.name == "handback.json" and self.parent.name == arg:
        raise PermissionError(13, "Permission denied", str(self))
    return plain(self)
tool.prepare = prepared
Path.read_bytes = read_bytes""")

RELEASE_EIO_AFTER_SWAP = SWAP_STAGING_AT_RENAME.replace("tool.rename = swapped", """tool.rename = swapped
import os
plain_rename = os.rename
def released(src, dst):
    if Path(dst).name.startswith(".lock-released-"):
        raise OSError(5, "Input/output error", str(src))
    return plain_rename(src, dst)
os.rename = released""")

ASIDE_EIO_AFTER_SWAP = RELEASE_EIO_AFTER_SWAP.replace('Path(dst).name.startswith(".lock-released-")',
                                                      'Path(src).name == "rev-002" and Path(dst).name.startswith(".orphan-")')

NO_NAME_READ_ERROR_ONCE = READ_ERROR_ONCE.replace('raise PermissionError(13, "Permission denied", str(path))',
                                                  'raise PermissionError(13, "Permission denied")')

RESERVE_EIO_COPY_STUCK = EIO_FROM.replace("os.rename = rename", """os.rename = rename
def stuck(root):
    raise OSError(16, "Device or resource busy", str(root))
tool.remove_tree = stuck""")

INPUT_TOUCHED = PATCHED.replace("PATCH", """import subprocess
launch = subprocess.Popen
def run(argv, *a, **kw):
    if "review" in argv:
        Path(arg).write_text("fn main() { changed(); }\\n")
    return launch(argv, *a, **kw)
subprocess.Popen = run""")

REVALIDATION_DOWN = PATCHED.replace("PATCH", """def down(run, n, bundle_sha):
    raise tool.Unverifiable(arg)
tool.revalidate = down""")

MARKED = """prepare = tool.prepare
def prepared(run):
    prepare(run)
    print("MARKER printed before the NOTE")
tool.prepare = prepared"""

RELEASED_AT_DEADLINE = PATCHED.replace("PATCH", """import shutil
Path(arg).mkdir()
(Path(arg) / "owner.json").write_bytes(tool.canon({**tool.identity(), "nonce": "f" * 32, "acquired_at": "x"}))
plain = tool.Lock.read_owner
def read_owner(self, path=None):
    seen.extend([path] if path is None and self.path == Path(arg) else [])
    if len(seen) == 2 and path is None and self.path == Path(arg):
        shutil.rmtree(self.path)
        return None
    return plain(self, path)
tool.Lock.read_owner = read_owner""")


PRUNE_STUCK = PATCHED.replace("PATCH", """import shutil
plain = os.rename
def rename(src, dst):
    if arg == "rename" and Path(dst).name.startswith(".pruned-"):
        raise OSError(5, "Input/output error", str(src))
    return plain(src, dst)
def partial(root):
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
    next(p for p in Path(root).rglob("*") if p.is_file()).unlink()
    raise OSError(16, "Device or resource busy", str(root))
os.rename = rename
tool.remove_tree = partial""")

CALL_JSON_EIO = PATCHED.replace("PATCH", """plain_write, plain_unlink = tool.write_new, Path.unlink
def write_new(path, data):
    if path.name == "call.json":
        if arg != "open":
            path.write_bytes(data[:len(data) // 2])
        raise OSError(5, "Input/output error", str(path))
    return plain_write(path, data)
def unlink(self, missing_ok=False):
    if arg == "stuck" and self.name == "call.json":
        raise OSError(5, "Input/output error", str(self))
    return plain_unlink(self, missing_ok)
tool.write_new = write_new
Path.unlink = unlink""")


CHMOD_BEFORE_RECEIPT = PATCHED.replace("PATCH", """plain = tool.finish_receipt
def finish(run, *a, **kw):
    Path(arg).chmod(0)
    return plain(run, *a, **kw)
tool.finish_receipt = finish""")

CHMOD_AT_PRUNE = PATCHED.replace("PATCH", """plain = tool.prune_copies
def prune(run, *a):
    Path(arg).chmod(0)
    return plain(run, *a)
tool.prune_copies = prune""")

UNLISTABLE_RUNNER = """
import os, subprocess, sys
code = subprocess.call([sys.executable, *sys.argv[1:]])
os.chmod(sys.argv[sys.argv.index("--artifacts") + 1], 0o300)
sys.exit(code)
"""

LINGERING_RUNNER = """
import os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen(["sleep", "300"])
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {child.pid}")
time.sleep(300)
"""

SIGNAL_IN_POPEN = PATCHED.replace("PATCH", """import signal, subprocess
launch = subprocess.Popen
def run(argv, *a, **kw):
    proc = launch(argv, *a, **kw)
    if "review" in argv:
        Path(arg).write_text(str(proc.pid))
        os.kill(os.getpid(), signal.SIGTERM)
    return proc
subprocess.Popen = run""")

SHORT_RUNNER_WAIT = PATCHED.replace("PATCH", "tool.RUNNER_WAIT = float(arg)")

DECISIONS_DENIED_AFTER_RECONCILE = PATCHED.replace("PATCH", """reconcile, on, listdir = tool.reconcile, [], os.listdir
def reconciled(run):
    out = reconcile(run)
    on.append(run)
    return out
def denied(path):
    if on and Path(path).name == "decisions":
        raise PermissionError(13, "Permission denied", str(path))
    return listdir(path)
tool.reconcile = reconciled
os.listdir = denied""")

ESCAPING_RUNNER = """
import os, subprocess, sys, time
from pathlib import Path
held = subprocess.Popen(["sleep", "60"], start_new_session=True)
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {held.pid}")
if os.environ.get("STALL"):
    time.sleep(300)
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

IGNORING_RUNNER = """
import os, signal, subprocess, time
from pathlib import Path
for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(sig, signal.SIG_IGN)
Path(os.environ["RUNNER_PIDS"]).write_text(str(os.getpid()))
time.sleep(300)
"""


CODEX_LIKE_RUNNER = """
import os, signal, subprocess, sys
from pathlib import Path
codex = subprocess.Popen(["sleep", "300"], start_new_session=True, cwd=sys.argv[sys.argv.index("--repo") + 1])
try:
    Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {codex.pid}")
    codex.communicate(timeout=300)
except (subprocess.TimeoutExpired, KeyboardInterrupt):
    os.killpg(codex.pid, signal.SIGKILL)
    codex.wait()
    sys.exit(1)
"""

STRAGGLING_RUNNER = """
import os, subprocess, sys
from pathlib import Path
quiet = {} if os.environ.get("HOLD") else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
left = subprocess.Popen(["sleep", "300"], **quiet)
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {left.pid}")
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

SETTLED = """
import signal
main = tool.main
def settled(argv):
    before = [signal.getsignal(s) for s in tool.FORWARDED]
    code = main(argv)
    Path(arg).write_text(json.dumps({"mask": sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, [])),
                                     "handlers": [signal.getsignal(s) == h for s, h in zip(tool.FORWARDED, before)]}))
    return code
tool.main = settled
"""

PREEXEC_FAILS = PATCHED.replace("PATCH", SETTLED + """import subprocess
launch = subprocess.Popen
def run(argv, *a, **kw):
    if "review" in argv:
        kw["preexec_fn"] = lambda: 1 / 0
    return launch(argv, *a, **kw)
subprocess.Popen = run""")

RUNNER_WAIT_RAISES = PATCHED.replace("PATCH", SETTLED + """def failing(proc, scope, stopped):
    import time
    for _ in range(1200):
        if os.path.exists(os.environ["RUNNER_PIDS"]) and len(Path(os.environ["RUNNER_PIDS"]).read_text().split()) == 2:
            break
        time.sleep(0.05)
    raise RuntimeError("injected")
tool.await_runner = failing""")

INTENT_FSYNC_FAILS = PATCHED.replace("PATCH", """import errno
sync = os.fsync
def failing(fd):
    if "/intents/." in os.readlink(f"/proc/self/fd/{fd}"):
        raise OSError(errno.EIO, "Input/output error")
    return sync(fd)
os.fsync = failing""")


ESCAPED_RUNNER = """
import os, signal, subprocess, sys, time
from pathlib import Path
codex = subprocess.Popen(["sleep", "300"], start_new_session=True, cwd=sys.argv[sys.argv.index("--repo") + 1])
signal.signal(signal.SIGINT, signal.SIG_IGN)
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {codex.pid}")
time.sleep(300)
"""

SPECIAL_RUNNER = """
import os, sys
repo = sys.argv[sys.argv.index("--repo") + 1]
os.chmod(os.path.join(repo, "src"), 0o755)
os.mkfifo(os.path.join(repo, "src", "pipe"))
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

RESULT_DIR_RUNNER = """
import os, sys
os.makedirs(os.path.join(sys.argv[sys.argv.index("--artifacts") + 1], "claudex-extra", "result.json"))
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

DEAF_STRAGGLER_RUNNER = """
import os, subprocess, sys
from pathlib import Path
left = subprocess.Popen([sys.executable, "-c", "import signal, time\\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\\n"
                         "time.sleep(300)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {left.pid}")
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

GRACE = PATCHED.replace("PATCH", "tool.STOP_GRACE, tool.PIPE_GRACE = int(arg), 1")

UNSTOPPABLE = PATCHED.replace("PATCH", "tool.STOP_GRACE = 1\ntool.kill_scope = lambda scope: None")

KILLED_WHILE_STOPPING = PATCHED.replace("PATCH", """import signal
tool.STOP_GRACE = 1
def killed(scope):
    os.kill(os.getpid(), signal.SIGKILL)
tool.kill_scope = killed""")

SCOPE_UNREADABLE = PATCHED.replace("PATCH", """plain = tool.scope_left
tool.scope_left = lambda scope: plain(scope) if "/planloop-probe-" in scope else (
    f"whether a process still runs in it cannot be checked ([Errno 13] Permission denied: '{scope}/cgroup.events')")
tool.STOP_GRACE = 1""")

UNSHARED = """import ctypes
uid, gid = os.getuid(), os.getgid()
os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)
Path("/proc/self/setgroups").write_text("deny")
Path("/proc/self/uid_map").write_text(f"{uid} {uid} 1")
Path("/proc/self/gid_map").write_text(f"{gid} {gid} 1")
def mounted():
    libc = ctypes.CDLL(None, use_errno=True)
    for source, target, kind, flags in json.loads(arg):
        if libc.mount(source.encode(), target.encode(), kind.encode(), flags, None):
            raise OSError(ctypes.get_errno(), "mount", target)
    if libc.capset((ctypes.c_uint32 * 2)(0x20080522, 0), (ctypes.c_uint32 * 6)()):
        raise OSError(ctypes.get_errno(), "capset")
"""
MOUNTED_OVER = PATCHED.replace("PATCH", UNSHARED + "mounted()")
MOUNTED_OVER_ONCE_PROBED = PATCHED.replace("PATCH", UNSHARED + """plain = getattr(tool, "scope_ready", dict)
def ready():
    out = plain()
    mounted()
    return out
tool.scope_ready = ready
tool.STOP_GRACE = 1""")

TAKEN_BEFORE_THE_RUNNER = PATCHED.replace("PATCH", """import signal, stat, subprocess, time
plain, plain_write, mode = tool.start_scoped, os.write, arg
def write(fd, data):
    if data == b"1" and stat.S_ISFIFO(os.fstat(fd).st_mode) and os.environ.get("GO_WRITTEN"):
        Path(os.environ["GO_WRITTEN"]).write_text("x")
    return plain_write(fd, data)
os.write = write
def start(argv, *a, **kw):
    if "review" in argv:
        running = Path(argv[argv.index("--feedback") + 1]).parent.parent / "running.json"
        if mode in ("replaced", "replaced_stuck"):
            running.write_text(json.dumps({**json.loads(running.read_text()), "nonce": "0" * 32, "pid": 2 ** 22 + 7}))
        if mode == "replaced_stuck":
            tool.GATE = "import signal, time\\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\\ntime.sleep(60)"
            tool.kill_scope = lambda scope: None
        elif mode == "receipt_written":
            (running.parent / "receipt.json").write_text("{}")
        elif mode == "locked":
            lock = running.parent.parent.parent / ".lock"
            lock.mkdir()
            (lock / "owner.json").write_bytes(tool.canon({**tool.identity(), "nonce": "f" * 32}))
        elif mode == "unreadable":
            running.chmod(0)
        elif mode == "malformed":
            running.write_text("{")
        elif mode == "lock_eio":
            plain_mkdir = Path.mkdir
            def mkdir(self, *a, **kw):
                if self.name.startswith(".lock-tmp-"):
                    raise OSError(5, "Input/output error", str(self))
                return plain_mkdir(self, *a, **kw)
            Path.mkdir = mkdir
        elif mode == "held":
            held = running.parent / "held"
            subprocess.Popen([sys.executable, "-c", "import importlib.util, sys, time\\nfrom pathlib import Path\\n"
                              "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\\n"
                              "t = importlib.util.module_from_spec(spec)\\nspec.loader.exec_module(t)\\n"
                              "with t.Lock(Path(sys.argv[2])):\\n    Path(sys.argv[3]).write_text('x')\\n"
                              "    time.sleep(3)", sys.argv[1], str(running.parent.parent.parent), str(held)])
            while not held.exists():
                time.sleep(0.02)
        elif mode == "signalled":
            os.kill(os.getpid(), signal.SIGTERM)
        elif mode in ("receipted", "removed"):
            running.unlink()
        if mode == "receipted":
            subprocess.run([sys.executable, sys.argv[1], "receipt", *sys.argv[4:10]], capture_output=True)
        if mode == "replaced_stuck":
            out = plain(argv, *a, **kw)
            time.sleep(1)
            return out
    return plain(argv, *a, **kw)
tool.start_scoped = start
tool.STOP_GRACE = 1""")

KILLED_AT_MARKER = PATCHED.replace("PATCH", """import signal
plain, marks = Path.write_text, []
def write_text(self, data, *a, **kw):
    if self.name == tool.MARKER:
        marks.append(self)
        if len(marks) == int(arg):
            os.kill(os.getpid(), signal.SIGKILL)
    return plain(self, data, *a, **kw)
Path.write_text = write_text""")

PROBE_BOUNDS = PATCHED.replace("PATCH", "tool.STOP_GRACE = tool.PIPE_GRACE = tool.PROBE_WAIT = 1\ntool.RUNNER_WAIT = 3\n"
                               "if arg != 'x':\n    tool.GATE = arg")

SYSTEMD_RUN_PROBE = """#!/bin/sh
case " $* " in *"--unit=planloop-probe-"*) ;; *) exec @REAL@ "$@" ;; esac
PROBE
exec @REAL@ "$@"
"""

COPY_STUCK = PATCHED.replace("PATCH", """plain = tool.remove_tree
def stuck(root):
    if str(root) == arg:
        raise OSError(5, "Input/output error", str(root))
    return plain(root)
tool.remove_tree = stuck""")

KILL_FAILS = PATCHED.replace("PATCH", """tool.STOP_GRACE = 1
tool.kill_scope = lambda scope: PermissionError(13, "Permission denied", f"{scope}/cgroup.kill")""")

SYSTEMD_RUN_FAILS = """#!/bin/sh
case " $* " in *" review --host "*) ;; *) exec @REAL@ "$@" ;; esac
echo "Failed to connect to bus: No medium found" >&2
exit 1
"""

SYSTEMD_RUN_UNSCOPED = """#!/bin/sh
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
"""

RUNNER_LIKE = """
import os, signal, subprocess, sys
from pathlib import Path
repo = sys.argv[sys.argv.index("--repo") + 1]
out = Path(sys.argv[sys.argv.index("--artifacts") + 1]) / "claudex-like"
out.mkdir()
codex = subprocess.Popen([sys.executable, "-c", os.environ["CODEX"], "exec", "-o", str(out / "reply.txt")], cwd=repo,
                         start_new_session=True)
try:
    Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {codex.pid}")
    codex.communicate(timeout=300)
except (subprocess.TimeoutExpired, KeyboardInterrupt):
    os.killpg(codex.pid, signal.SIGKILL)
    codex.wait()
    sys.exit(1)
"""

READY = """
with open(os.environ["READY"], "w") as handle:
    handle.write("ready")
time.sleep(300)"""
CODEX_PLAIN = "import os, time" + READY
CODEX_DEAF = "import os, signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)" + READY
CODEX_FAMILY = """import os, signal, subprocess, sys, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time\\ntime.sleep(300)"], cwd="/")
with open(os.environ["GRANDCHILD"], "w") as handle:
    handle.write(str(child.pid))""" + READY

BLOCKED_RECORDING = PATCHED.replace("PATCH", """import time
write = tool.write_new
def blocked(path, data):
    if Path(path).name == "call.json":
        Path(arg).write_text("blocked")
        time.sleep(300)
    return write(path, data)
tool.write_new = blocked""")

SIGINT_BEFORE_RUNNER = PATCHED.replace("PATCH", """import signal, time
def interrupted():
    os.kill(os.getpid(), signal.SIGINT)
    time.sleep(5)
tool.runner_path = interrupted""")

BRIEF_SWAPPED_AFTER_VERIFY = PATCHED.replace("PATCH", """plain = tool.runner_path
def swapped():
    brief = Path(arg)
    brief.parent.chmod(0o755)
    brief.unlink()
    brief.mkdir()
    return plain()
tool.runner_path = swapped""")

SIGNAL_BEFORE_CALL_RECORD = PATCHED.replace("PATCH", """import signal
write = tool.write_new
def signalled(path, data):
    if Path(path).name == "call.json":
        os.kill(os.getpid(), signal.SIGTERM)
    return write(path, data)
tool.write_new = signalled""")

CODEX_ORPHANING = """import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import signal, time\\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\\n"
                          "time.sleep(300)"], cwd="/")
with open(os.environ["GRANDCHILD"], "w") as handle:
    handle.write(str(child.pid))""" + READY

FIXED_PRIVATE = PATCHED.replace("PATCH", """import types, uuid
fixed = types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex="fixed"))
ready = tool.scope_ready
def scope_ready():
    tool.uuid = uuid
    try:
        return ready()
    finally:
        tool.uuid = fixed
tool.scope_ready = scope_ready
tool.uuid = fixed""")

KILLED_AT_PRIVATE = FIXED_PRIVATE.replace('hex="fixed"))', """hex="fixed"))
import signal
plain = Path.mkdir
def mkdir(self, *a, **kw):
    if self.name in ("r-fixed", ".marking-r-fixed"):
        os.kill(os.getpid(), signal.SIGKILL)
    return plain(self, *a, **kw)
Path.mkdir = mkdir""")

SIGINT_AFTER_RESERVE = PATCHED.replace("PATCH", """import signal, time
plain = tool.rename
def renamed(src, dst, *a, **kw):
    plain(src, dst, *a, **kw)
    if Path(dst).name == "call-001-a1":
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(5)
tool.rename = renamed""")

CALL_JSON_EIO_AFTER_STOP = CALL_JSON_EIO.replace("tool.write_new = write_new", "tool.write_new = write_new\ntool.STOP_GRACE = 1")


LEAVING_RUNNER = """
import os, subprocess, sys, time
from pathlib import Path
root, repo = (sys.argv[sys.argv.index(name) + 1] for name in ("--artifacts", "--repo"))
argv, cwd = (["sleep", "300"], "/") if os.environ["LEAVE"] == "plain" else \\
    ([sys.executable, "-c", "import time\\ntime.sleep(300)", "python3", os.environ["PLANLOOP"], "--artifacts", root], repo)
left = subprocess.Popen(argv, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
Path(os.environ["RUNNER_PIDS"]).write_text(f"{os.getpid()} {left.pid}")
time.sleep(300)
"""

DOUBLE_FORKING_RUNNER = """
import os, sys
from pathlib import Path
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        os.chdir("/")
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        Path(os.environ["RUNNER_PIDS"]).write_text(str(os.getpid()))
        os.execvp("sleep", ["sleep", "300"])
    os._exit(0)
os.wait()
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""

MARKING_RUNNER = """
import os
from pathlib import Path
Path(os.environ["RUNNER_PIDS"]).write_text(str(os.getpid()))
"""

WAITING_RUNNER = """
import os, sys, time
from pathlib import Path
Path(os.environ["RUNNER_PIDS"]).write_text(str(os.getpid()))
while not os.path.exists(os.environ["GO"]):
    time.sleep(0.05)
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
"""


RECEIPT_WAITS_FOR_LOCK = PATCHED.replace("PATCH", """import time
plain = tool.Lock.__enter__
def waited(self):
    Path(arg + ".waiting").write_text("waiting")
    while not os.path.exists(arg):
        time.sleep(0.05)
    return plain(self)
tool.Lock.__enter__ = waited""")

VIEWED = PATCHED.replace("PATCH", """plain = getattr(tool, "view", dict)
tool.view = lambda: {**plain(), **json.loads(arg)}""")

NO_MANAGER = PATCHED.replace("PATCH", 'tool.scope_base = lambda: "/sys/fs/cgroup/planloop-no-such-manager"')

SLOW_KILL = PATCHED.replace("PATCH", """import threading
plain = tool.kill_scope
tool.kill_scope = lambda scope: threading.Timer(float(arg), plain, [scope]).start()""")

KILLED_AT_COPY = PATCHED.replace("PATCH", """import shutil, signal
def copying(*a, **kw):
    os.kill(os.getpid(), signal.SIGKILL)
shutil.copytree = copying""")

SYSTEMD_RUN_LOGGED = """#!/bin/sh
line=
for a; do
    [ "$a" = -- ] && break
    line="$line $a"
done
printf '%s\\n' "$line" >> "$SYSTEMD_RUN_LOG"
if [ -n "$SYSTEMD_RUN_OLD" ]; then
    for a; do
        if [ "$a" = --expand-environment=no ]; then
            echo "systemd-run: unrecognized option '--expand-environment=no'" >&2
            exit 1
        fi
    done
fi
exec @REAL@ "$@"
"""

SYSTEMD_RUN_HOLDS_PIPES = """#!/bin/sh
case " $* " in *" review --host "*) ;; *) exec @REAL@ "$@" ;; esac
sleep 30 &
echo $! > "$RUNNER_PIDS"
exit 1
"""

INTERRUPTED_RUN = """
import importlib.util, sys, unittest
spec = importlib.util.spec_from_file_location("planloop_tests", sys.argv[1])
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)
class Interrupted(tests.PolicyReviewFixes):
    def test_interrupted(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, tests.LINGERING_RUNNER)
        proc = self.launch(f, env)
        started = self.started(pids, 2)
        proc.kill()
        proc.communicate()
        print(f.dispatched(1)["scope"], f.root, *started, flush=True)
        raise KeyboardInterrupt
unittest.main(argv=["interrupted", "Interrupted.test_interrupted"])
"""


UNDO_FAILS = PATCHED.replace("PATCH", """import shutil
prefix, landed = arg.split(":")
plain_rmtree, failed = shutil.rmtree, []
def rename(src, dst):
    if Path(src).name.startswith(".marking-" + prefix):
        if landed == "landed":
            real(src, dst)
        failed.append(src)
        raise OSError(5, "Input/output error", str(src))
    return real(src, dst)
def rmtree(path, *a, **kw):
    if failed and Path(path).name.startswith((prefix, ".marking-" + prefix)):
        raise OSError(16, "Device or resource busy", str(path))
    return plain_rmtree(path, *a, **kw)
os.rename, shutil.rmtree = rename, rmtree""")

KILLED_REMOVING = PATCHED.replace("PATCH", """import signal
plain_unlink, failed = os.unlink, []
def rename(src, dst):
    if Path(src).name.startswith(".marking-" + arg):
        real(src, dst)
        failed.append(src)
        raise OSError(5, "Input/output error", str(src))
    return real(src, dst)
def unlink(path, *a, **kw):
    plain_unlink(path, *a, **kw)
    if os.path.basename(path) == tool.MARKER and (failed or arg == "leftover"):
        os.kill(os.getpid(), signal.SIGKILL)
os.rename, os.unlink = rename, unlink""")

NO_CTYPES = PATCHED.replace("import importlib.util, json, os, sys\n",
                            "import importlib.util, json, os, sys\nsys.modules['ctypes'] = None\n", 1).replace("PATCH", "")

ADMISSION_SIGNALLED = PATCHED.replace("PATCH", """import signal, subprocess, time
plain_start, plain_enter = tool.start_scoped, tool.Lock.__enter__
def start(argv, *a, **kw):
    if "review" in argv:
        call_dir = Path(argv[argv.index("--feedback") + 1]).parent.parent
        running = call_dir / "running.json"
        if arg == "held":
            held = call_dir.parent.parent / "held"
            subprocess.Popen([sys.executable, "-c", "import importlib.util, sys, time\\nfrom pathlib import Path\\n"
                              "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\\n"
                              "t = importlib.util.module_from_spec(spec)\\nspec.loader.exec_module(t)\\n"
                              "with t.Lock(Path(sys.argv[2])):\\n    Path(sys.argv[3]).write_text('x')\\n"
                              "    end = time.monotonic() + 8\\n"
                              "    while time.monotonic() < end and not Path(sys.argv[4]).exists():\\n"
                              "        time.sleep(0.02)", sys.argv[1], str(call_dir.parent.parent), str(held),
                              os.environ.get("FREE", os.environ["RELEASED"])])
            while not held.exists():
                time.sleep(0.02)
        elif arg == "lost":
            os.kill(os.getpid(), signal.SIGTERM)
            tool.Lock.read_owner = lambda self, path=None: None
        else:
            running.write_text(json.dumps({**json.loads(running.read_text()), "nonce": "0" * 32, "pid": 2 ** 22 + 7}))
    return plain_start(argv, *a, **kw)
def enter(self):
    if self.timeout <= float(os.environ.get("PLANLOOP_LOCK_TIMEOUT", "30")) or arg == "lost":
        return plain_enter(self)
    if arg == "held":
        os.kill(os.getpid(), signal.SIGTERM)
        began = time.monotonic()
        try:
            return plain_enter(self)
        finally:
            Path(os.environ["RELEASED"]).write_text(str(time.monotonic() - began))
    got = plain_enter(self)
    os.kill(os.getpid(), getattr(signal, arg))
    return got
plain_signal, handled = signal.signal, []
def install(sig, handler):
    if getattr(handler, "__name__", "") != "forward":
        return plain_signal(sig, handler)
    def counted(signum, frame):
        handler(signum, frame)
        handled.append(signum)
        with open(os.environ["HANDLED"], "a") if "HANDLED" in os.environ else open(os.devnull, "w") as out:
            out.write(f"{signum}\\n")
        if len(handled) == 1 and arg in ("SIGINT", "SIGTERM"):
            os.kill(os.getpid(), signum)
    return plain_signal(sig, counted)
tool.start_scoped, tool.Lock.__enter__, signal.signal = start, enter, install
tool.STOP_GRACE = 1""")

RECEIPT_LOCKED = PATCHED.replace("PATCH", """import subprocess, time
plain_finish = tool.finish_receipt
def finish(run, call, attempt, artifacts=None):
    if arg == "readonly":
        mode = run.dir.stat().st_mode & 0o777
        run.dir.chmod(0o500)
        try:
            return plain_finish(run, call, attempt, artifacts)
        finally:
            run.dir.chmod(mode)
    held = Path(os.environ["HELD"])
    subprocess.Popen([sys.executable, "-c", "import importlib.util, sys, time\\nfrom pathlib import Path\\n"
                      "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\\n"
                      "t = importlib.util.module_from_spec(spec)\\nspec.loader.exec_module(t)\\n"
                      "with t.Lock(Path(sys.argv[2])):\\n    Path(sys.argv[3]).write_text('x')\\n"
                      "    end = time.monotonic() + 20\\n"
                      "    while time.monotonic() < end and not Path(sys.argv[4]).exists():\\n"
                      "        time.sleep(0.02)", sys.argv[1], str(run.dir), str(held), os.environ["FREE"]])
    while not held.exists():
        time.sleep(0.02)
    return plain_finish(run, call, attempt, artifacts)
tool.finish_receipt = finish""")

PUBLISHED_THEN = PATCHED.replace("PATCH", """import shutil, signal
plain_rename, plain_rmtree, plain_unlink, hit, markers = tool.rename, shutil.rmtree, os.unlink, [], []
def rename(src, dst, *a, **kw):
    plain_rename(src, dst, *a, **kw)
    if Path(dst).name.startswith("call-"):
        hit.append(dst)
        if arg.startswith("error"):
            raise tool.Unverifiable(f"could not rename {src} -> {dst} (injected after it landed)")
        raise KeyboardInterrupt
def rmtree(path, *a, **kw):
    if hit and arg.endswith("busy") and Path(path).name.startswith(".marking-"):
        raise OSError(16, "Device or resource busy", str(path))
    return plain_rmtree(path, *a, **kw)
def unlink(path, *a, **kw):
    plain_unlink(path, *a, **kw)
    if hit and os.path.basename(path) == tool.MARKER:
        markers.append(path)
        if arg.endswith(f"kill{len(markers)}"):
            os.kill(os.getpid(), signal.SIGKILL)
tool.rename, shutil.rmtree, os.unlink = rename, rmtree, unlink""")

LSTAT_EIO = PATCHED.replace("PATCH", """plain_lstat, failed = os.lstat, []
def rename(src, dst):
    real(src, dst)
    if arg == "fail" and Path(dst).name.startswith("call-001-a1-r-") and not failed:
        failed.append(dst)
        raise OSError(5, "Input/output error", str(src))
def lstat(path, *a, **kw):
    if (failed or arg == "always") and os.path.basename(path).startswith(".marking-"):
        raise OSError(5, "Input/output error", str(path))
    return plain_lstat(path, *a, **kw)
os.rename, os.lstat = rename, lstat""")


def load_tool():
    spec = importlib.util.spec_from_file_location("planloop_under_test", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def group_gone(pgid, wait=10):
    for _ in range(int(wait / 0.05)):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def readable_as_000(test, path):
    mode = path.stat().st_mode & 0o777
    path.chmod(0)
    try:
        path.read_bytes() if path.is_file() else os.listdir(path)
    except PermissionError:
        return
    finally:
        path.chmod(mode)
    test.skipTest("chmod 000 does not stop this user reading")


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


def intend(f, n):
    record = (f.rdir / f"rev-{n:03d}" / "revision.json").read_bytes()
    (f.rdir / f".publishing-rev-{n:03d}").write_text(json.dumps({"schema": "planloop-publishing/1", "revision": n,
                                                                  "revision_sha256": hashlib.sha256(record).hexdigest()}))


class PolicyReviewFixes(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def shrink_staged(self, f):
        f.init()
        f.publish(1, make_plan(1))
        return f.hand(2, make_plan(2, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()]))

    def set_cut(self, staging, **change):
        hb, rv = staging / "handback.json", staging / "revision.json"
        record = json.loads(hb.read_text())
        record["cut"] = {**record["cut"], **change}
        hb.write_text(json.dumps(record))
        if rv.exists():
            rv.write_text(json.dumps({**json.loads(rv.read_text()),
                                      "handback_sha256": hashlib.sha256(hb.read_bytes()).hexdigest()}))

    def bogus_receipt(self, f, rev):
        path = f.rdir / "reviews" / "call-099-a1"
        (path / "input").mkdir(parents=True)
        (path / "receipt.json").write_text(json.dumps({"schema": "planloop-receipt/1", "status": "counted", "call": 99,
                                                       "attempt": 1, "revision": rev, "meaning_check": []}))

    def test_bundle_publish_and_recover_recheck_the_staged_cut(self):
        f = self.f
        nonce = self.shrink_staged(f)
        staging = f.rdir / f".staging-002-{nonce}"
        bundle = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        original = (staging / "handback.json").read_bytes()
        for change, needle in (({"shrink_only": False}, "shrink_only"), ({"threshold_bytes": 300000}, "threshold_bytes"),
                               ({"lost_lines": 0}, "lost_lines"),
                               ({"shrink_only": False, "live_answers": ["R1"]}, "live_answers"),
                               ({"shrink_only": "yes"}, "shrink_only")):
            self.set_cut(staging, **change)
            f.tool(*bundle, expect=1)
            self.assertIn("handback.json cut", f.last.stderr)
            self.assertIn(needle, f.last.stderr)
            self.assertFalse((staging / "bundle").exists())
            (staging / "handback.json").write_bytes(original)
        f.tool(*bundle)
        for change in ({"shrink_only": False}, {"shrink_only": "yes"}):
            self.set_cut(staging, **change)
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, expect=1)
            self.assertIn("handback.json cut", f.last.stderr)
            self.assertEqual(f.head(), 1)
            self.assertFalse((f.rdir / "rev-002").exists())
        for change in ({"shrink_only": False}, {"shrink_only": "yes"}, {"threshold_bytes": 1}):
            g = Fixture(self)
            n = self.shrink_staged(g)
            g.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", n, "--inputs", str(g.inputs()))
            self.set_cut(g.rdir / f".staging-002-{n}", **change)
            os.rename(g.rdir / f".staging-002-{n}", g.rdir / "rev-002")
            intend(g, 2)
            g.tool("publish", "--run", RUN, "--recover")
            self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", g.last.stderr)
            self.assertIn("handback.json cut", g.last.stderr)
            self.assertEqual(g.head(), 1)
            g.tool("gate", "--run", RUN, expect=1)
            self.assertNotIn("do not verify from HEAD", g.last.stdout + g.last.stderr)

    def test_handback_records_the_runs_threshold(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        copy = f.root / "changed" / "planloop.py"
        copy.parent.mkdir()
        copy.write_text(TOOL.read_text().replace("SIZE_THRESHOLD_BYTES = 250000", "SIZE_THRESHOLD_BYTES = 100000"))
        nonce = uuid.uuid4().hex[:16]
        proc = subprocess.run([sys.executable, str(copy), "handback", "--run", RUN, "--revision", "2", "--nonce", nonce,
                               "--transcript", str(f.transcript(f.wrap(2, nonce, make_plan(2))))], cwd=f.repo,
                              capture_output=True, text=True, env=f.env, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(f.staged(2, nonce)["cut"]["threshold_bytes"], T)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)

    def test_a_fix_that_shrinks_only_its_change_log_warns(self):
        f = self.f
        f.init()
        notes = [f"note {i}: a long change-log entry describing what revision one did, padded out to matter." for i in
                 range(20)]
        f.publish(1, make_plan(1, log=notes))
        c = f.review(review("REVISE", [finding("F1", "low")]))
        f.ingest(c, {"F1": "new"})
        fix = make_plan(2, log=["FIX R1: confirmed the lookup as written"])
        warn = "WARN  this revision answers findings and is "
        self.assertIn(warn, f.check(fix, 0).stdout)
        nonce = f.hand(2, fix)
        self.assertIn(warn, f.last.stdout)
        self.assertEqual(f.staged(2, nonce)["cut"]["live_answers"], ["R1"])
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertIn(warn, f.last.stdout)
        f.tool("findings", "propose", "--run", RUN)
        c = f.review(review(coverage=["plan read in full", "finding R1: resolved"]))
        self.assertIn("check that every cut is explained by the finding it answers or by its disposition", f.feedback(c))
        f.ingest(c, {})
        shrink = make_plan(3, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()])
        self.assertNotIn(warn, f.check(shrink, 0).stdout)

    def test_order_changed_only_for_a_real_reordering(self):
        sys.path.insert(0, str(TOOL.parent))
        import planloop

        def labels(before, after):
            old = make_plan(1, (("## Goal", ("Meet OB1.",)), ("## A", before)))
            new = make_plan(2, (("## Goal", ("Meet OB1.",)), ("## A", after)))
            return next(u["labels"] for u in planloop.meaning_units(old, new) if u["unit"] == "## A")

        self.assertEqual(labels(("x", "y", "x"), ("y", "x")), ["lost"])
        self.assertEqual(labels(("x", "y", "x"), ("x", "y")), ["lost"])
        self.assertEqual(labels(("x", "y", "x"), ("x", "y", "x", "x")), ["added"])
        self.assertEqual(labels(("x", "y"), ("y", "x")), ["order changed"])
        self.assertEqual(labels(("x", "y", "x", "z"), ("z", "y", "x")), ["lost", "order changed"])
        self.assertEqual(labels(("x", "", "y"), ("x", "y", "")), [])

    def test_the_chain_is_walked_once_per_command(self):
        f = self.f
        f.init()
        for rev in (1, 2, 3):
            f.publish(rev, make_plan(rev))
        f.accept_risk()
        driver = f.root / "count_walks.py"
        driver.write_text(COUNT_WALKS)

        def walks(*args):
            proc = subprocess.run([sys.executable, str(driver), str(TOOL), *args], cwd=f.repo, capture_output=True,
                                  text=True, env=f.env, timeout=300)
            return json.loads(proc.stdout.strip().splitlines()[-1])

        f.review_file.write_text(json.dumps(review()))
        self.assertEqual(walks("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "gate",
                               "--effort", "high"), {"code": 0, "walked": [3, 2, 1]})
        f.ingest(1, {})
        self.assertEqual(walks("gate", "--run", RUN), {"code": 1, "walked": [3, 2, 1]})
        self.assertEqual(walks("gate", "--run", RUN, "--publish"), {"code": 0, "walked": [3, 2, 1]})
        self.assertEqual(walks("ledger", "--run", RUN), {"code": 0, "walked": [3, 2, 1]})
        nonce = f.stage(4, make_plan(4))
        self.assertEqual(walks("publish", "--run", RUN, "--revision", "4", "--nonce", nonce),
                         {"code": 0, "walked": [3, 2, 1, 4, 3, 2, 1]})

    def test_a_failed_size_report_after_head_moves_is_a_warning(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.stage(2, make_plan(2))
        self.bogus_receipt(f, 1)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertIn("WARN  size report unavailable: Unbound: receipt of call 99 attempt 1: ", f.last.stdout)
        self.assertIn("a stored receipt's binding to the authenticated revisions fails; inspect that receipt",
                      f.last.stdout)
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] every stored meaning receipt is bound to revisions 1 to 2: receipt of call 99",
                      f.last.stdout)
        self.assertNotIn("do not verify from HEAD", f.last.stdout)

        g = Fixture(self)
        g.init()
        g.publish(1, make_plan(1))
        n = g.stage(2, make_plan(2))
        g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        shutil.copytree(g.rdir / "rev-002", g.rdir / "rev-003")
        self.bogus_receipt(g, 1)
        g.tool("findings", "propose", "--run", RUN)
        self.assertEqual(g.head(), 2)
        self.assertIn("NOTE  recovered interrupted publication of revision 2", g.last.stderr)
        self.assertIn("WARN  size report unavailable: Unbound: receipt of call 99 attempt 1: ", g.last.stderr)
        self.assertIn("NOTE  moved unreferenced rev-003 aside to .orphan-rev-003-", g.last.stderr)
        self.assertFalse((g.rdir / "rev-003").exists())

        h = Fixture(self)
        h.init()
        h.publish(1, make_plan(1))
        n = h.stage(2, make_plan(2))
        (h.rdir / "reviews" / "call-099-a1").mkdir(parents=True)
        (h.rdir / "reviews" / "call-099-a1" / "receipt.json").write_text(json.dumps({"schema": "other"}))
        h.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n)
        self.assertEqual(h.head(), 2)
        self.assertIn("WARN  size report unavailable: Fail: ", h.last.stdout)
        self.assertIn("is not a planloop receipt for call 99 attempt 1", h.last.stdout)

    def driver(self, f, text, *args, env=None):
        path = f.root / f"driver-{uuid.uuid4().hex[:6]}.py"
        path.write_text(text)
        proc = subprocess.run([sys.executable, str(path), str(TOOL), *args], cwd=f.repo, capture_output=True, text=True,
                              env={**f.env, **(env or {})}, timeout=300)
        f.last = proc
        return proc.returncode or json.loads(proc.stdout.strip().splitlines()[-1])["code"]

    def test_a_record_rewritten_between_the_walk_and_the_deep_verify_is_refused(self):
        differs = "HEAD points at a revision whose record differs"
        dispatch = ("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium")
        for mode in ("keep", "restore"):
            f = Fixture(self)
            f.init()
            f.publish(1, make_plan(1))
            f.publish(2, make_plan(2))
            f.review_file.write_text(json.dumps(review()))
            self.assertEqual(self.driver(f, SWAP_AT_DEEP, mode, *dispatch), 2, f.last.stdout + f.last.stderr)
            self.assertIn(differs, f.last.stderr)
            self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
            g = Fixture(self)
            g.to_gate_ready()
            gc = g.review(review(), kind="gate", effort="high")
            g.ingest(gc, {})
            for args in (("gate", "--run", RUN), ("gate", "--run", RUN, "--publish")):
                self.assertEqual(self.driver(g, SWAP_AT_DEEP, mode, *args), 1, g.last.stdout + g.last.stderr)
                self.assertIn(f"FAIL  [mechanical] revisions 1 to 2 verify as a chain from HEAD: {differs}",
                              g.last.stdout)
                self.assertFalse((g.rdir / "APPROVAL").exists())
                if mode == "keep":
                    break

    def live_staged(self, f):
        f.init()
        f.publish(1, make_plan(1))
        c = f.review(review("REVISE", [finding("F1", "low")]))
        f.ingest(c, {"F1": "new"})
        nonce = f.hand(2, make_plan(2, log=["FIX R1: confirmed the lookup as written"]))
        self.assertEqual(f.staged(2, nonce)["cut"]["live_answers"], ["R1"])
        return nonce

    def set_finding(self, f, fid, state=None):
        db = f.bd()
        bead = f.finding_bead(fid)["id"]
        if state is None:
            del db["issues"][bead]
        else:
            db["issues"][bead]["metadata"]["planloop_state"] = state
        f.set_bd(db)

    def test_a_live_answer_must_be_a_finding_of_the_run(self):
        f = self.f
        nonce = self.live_staged(f)
        bundle = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        publish = ("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        for state in ("verified", "withdrawn"):
            self.set_finding(f, "R1", state)
            f.tool(*bundle, expect=1)
            self.assertIn("cut.live_answers names R1, which is not an open or reopened finding of this run",
                          f.last.stderr)
            self.assertFalse((f.rdir / f".staging-002-{nonce}" / "bundle").exists())
        self.set_finding(f, "R1", "open")
        f.tool(*bundle)
        for state in ("verified", "withdrawn"):
            self.set_finding(f, "R1", state)
            f.tool(*publish, expect=1)
            self.assertIn("cut.live_answers names R1, which is not an open or reopened finding of this run",
                          f.last.stderr)
            self.assertEqual(f.head(), 1)
        self.set_finding(f, "R1", "reopened")
        f.tool(*publish)
        self.assertEqual(f.head(), 2)
        for state in ("verified", None):
            g = Fixture(self)
            n = self.live_staged(g)
            g.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", n, "--inputs", str(g.inputs()))
            g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
                   expect=99)
            self.set_finding(g, "R1", state)
            g.tool("publish", "--run", RUN, "--recover")
            if state:
                self.assertIn("NOTE  recovered interrupted publication of revision 2", g.last.stderr)
                self.assertEqual(g.head(), 2)
            else:
                self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", g.last.stderr)
                self.assertIn("cut.live_answers names R1, which is not a finding of this run", g.last.stderr)
                self.assertEqual(g.head(), 1)

    def test_an_integrity_failure_after_head_moves_is_not_a_warning(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.stage(2, make_plan(2))
        code = self.driver(f, FAIL_WALK, "2", "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertEqual(f.head(), 2)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertIn("the publication of revision 2 is complete", f.last.stdout)
        self.assertIn("UNVERIFIABLE  revision 2: injected: revision 2 changed after its publication", f.last.stderr)
        self.assertNotIn("size report unavailable", f.last.stdout + f.last.stderr)

        g = Fixture(self)
        g.init()
        g.publish(1, make_plan(1))
        n = g.stage(2, make_plan(2))
        g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        shutil.copytree(g.rdir / "rev-002", g.rdir / "rev-003")
        self.assertEqual(self.driver(g, FAIL_WALK, "2", "publish", "--run", RUN, "--recover"), 2,
                         g.last.stdout + g.last.stderr)
        self.assertEqual(g.head(), 2)
        self.assertIn("NOTE  recovered interrupted publication of revision 2", g.last.stderr)
        self.assertIn("the publication of revision 2 is complete", g.last.stderr)
        self.assertIn("UNVERIFIABLE  revision 2: injected", g.last.stderr)
        self.assertTrue((g.rdir / "rev-003").exists())
        g.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  moved unreferenced rev-003 aside to .orphan-rev-003-", g.last.stderr)

    def test_only_s_number_files_are_size_decisions(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        f.accept_risk()
        for name, text in (("S1-draft.json", "{}"), ("S0.json", "{}"), ("Snotes.json", "not json"), ("S01.json", "{}"),
                           ("s1.json", "{}")):
            path = f.rdir / "decisions" / name
            path.write_text(text)
        g = f.review(review(), kind="gate", effort="high")
        f.ingest(g, {})
        f.tool("gate", "--run", RUN, "--publish")
        for name in ("S1-draft.json", "S0.json", "Snotes.json", "S01.json", "s1.json"):
            self.assertIn(f"NOTE  decisions/{name} is not named S<positive integer>.json, so it is not a size "
                          "decision; ignored", f.last.stdout)
        self.assertNotIn("FAIL", f.last.stdout)
        f.size_decision("S2", 1, 10 ** 6, by="Bob")
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] size decision S2.json well formed", f.last.stdout)

    def test_check_names_a_shrink_only_revision_in_the_planner_policy(self):
        f = self.f
        f.init("--track", "escalated", "--risk-domains", "recovery", "--rationale",
               "test importer change that alters how a resume recovers")
        f.publish(1, make_plan(1), model="fable")
        out = f.check(make_plan(2, edit(BASE, drop=("Line three of the design.",)), log=[SHRINK_DESIGN, *keep()]),
                      0).stdout
        self.assertIn("classification: shrink-only", out)
        self.assertIn("planner policy: Fable or Opus may hand this content back (a shrink-only revision)", out)
        f.publish(2, make_plan(2, edit(BASE, add={"## Design": ("Line four of the design.",)})))
        c = f.review(review("REVISE", [finding("F1", "low")]), effort="high")
        f.ingest(c, {"F1": "new"})
        out = f.check(make_plan(3, edit(BASE, add={"## Design": ("Line four of the design.", "Line five.")}),
                                log=["FIX R1: add line five"]), 0).stdout
        self.assertIn("planner policy: Fable or Opus may hand this content back (a FIX revision)", out)


    def test_a_beads_read_error_in_the_cut_check_is_unverifiable(self):
        for mode in ("fail", "decode"):
            g = Fixture(self)
            n = self.live_staged(g)
            g.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", n, "--inputs", str(g.inputs()))
            g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
                   expect=99)
            self.assertEqual(self.driver(g, BD_GLITCH, mode, "publish", "--run", RUN, "--recover"), 2,
                             g.last.stdout + g.last.stderr)
            self.assertIn("UNVERIFIABLE  Beads could not be read to check revision 2's cut", g.last.stderr)
            self.assertNotIn("moved", g.last.stderr)
            self.assertTrue((g.rdir / "rev-002").exists())
            self.assertEqual(g.head(), 1)
            g.tool("publish", "--run", RUN, "--recover")
            self.assertIn("NOTE  recovered interrupted publication of revision 2", g.last.stderr)
            self.assertEqual(g.head(), 2)
        f = self.f
        nonce = self.live_staged(f)
        staging = f.rdir / f".staging-002-{nonce}"
        bundle = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        publish = ("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(self.driver(f, BD_GLITCH, "fail", *bundle), 2, f.last.stdout + f.last.stderr)
        self.assertIn("UNVERIFIABLE  Beads could not be read", f.last.stderr)
        self.assertNotIn("delete", f.last.stderr)
        self.assertFalse((staging / "bundle").exists())
        f.tool(*bundle)
        self.assertEqual(self.driver(f, BD_GLITCH, "decode", *publish), 2, f.last.stdout + f.last.stderr)
        self.assertIn("UNVERIFIABLE  Beads could not be read", f.last.stderr)
        self.assertNotIn("delete", f.last.stderr)
        self.assertTrue(staging.exists())
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertEqual(f.head(), 1)
        f.tool(*publish)
        self.assertEqual(f.head(), 2)

    def test_an_unexpected_size_report_error_after_head_moves_is_a_warning(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.stage(2, make_plan(2))
        self.assertEqual(self.driver(f, BROKEN_REPORT, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce),
                         0, f.last.stdout + f.last.stderr)
        self.assertEqual(f.head(), 2)
        self.assertIn("WARN  size report unavailable: TypeError: injected", f.last.stdout)
        g = Fixture(self)
        g.init()
        g.publish(1, make_plan(1))
        n = g.stage(2, make_plan(2))
        g.tool("publish", "--run", RUN, "--revision", "2", "--nonce", n, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        shutil.copytree(g.rdir / "rev-002", g.rdir / "rev-003")
        self.assertEqual(self.driver(g, BROKEN_REPORT, "findings", "propose", "--run", RUN), 0,
                         g.last.stdout + g.last.stderr)
        self.assertEqual(g.head(), 2)
        self.assertIn("NOTE  recovered interrupted publication of revision 2", g.last.stderr)
        self.assertIn("WARN  size report unavailable: TypeError: injected", g.last.stderr)
        self.assertIn("NOTE  moved unreferenced rev-003 aside to .orphan-rev-003-", g.last.stderr)

    def test_a_policy_walk_of_a_later_head_is_refused(self):
        f = Fixture(self)
        f.to_gate_ready()
        gc = f.review(review(), kind="gate", effort="high")
        f.ingest(gc, {})
        nonce = f.stage(3, plan_text(3, answers=["FIX R1: add the checksum lookup"]))
        self.assertEqual(self.driver(f, RACE_PUBLISH, "3", nonce, "2", "gate", "--run", RUN), 1,
                         f.last.stdout + f.last.stderr)
        self.assertEqual(f.head(), 3)
        self.assertIn("FAIL  [mechanical] revisions 1 to 2 verify as a chain from HEAD: HEAD points at a revision "
                      "whose record differs", f.last.stdout)
        self.assertIn("NOT APPROVED", f.last.stdout)

    def test_publish_uses_the_bytes_it_verified(self):
        f = self.f
        f.init()
        f.publish(1, make_plan(1))
        nonce = f.stage(2, make_plan(2))
        code = self.driver(f, SWAP_AT_RENAME, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("CONFLICT  ", f.last.stderr)
        self.assertEqual(f.head(), 1)
        g = Fixture(self)
        g.init()
        g.publish(1, make_plan(1))
        manifest = g.rdir / "rev-001" / "bundle" / "manifest.json"
        record = json.loads(manifest.read_text())
        next(i for i in record["items"] if i["type"] == "plan")["sha256"] = "0" * 64
        manifest.write_text(json.dumps(record))
        rv = g.rdir / "rev-001" / "revision.json"
        rv.write_text(json.dumps({**json.loads(rv.read_text()),
                                  "bundle_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
        (g.rdir / "HEAD").write_text(json.dumps({**json.loads((g.rdir / "HEAD").read_text()),
                                                 "revision_sha256": hashlib.sha256(rv.read_bytes()).hexdigest()}))
        g.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] revision integrity: revision 1 bundle manifest names another plan",
                      g.last.stdout)

    def test_a_rejected_publication_is_moved_aside_not_rolled_forward(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        other = f.stage(2, plan_text(2, extra_design=["A competing writer's extra line."]))
        code = self.driver(f, SWAP_STAGING_AT_RENAME, f".staging-002-{other}", "publish", "--run", RUN, "--revision",
                           "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("CONFLICT  ", f.last.stderr)
        self.assertFalse((f.rdir / "rev-002").exists())
        aside = list(f.rdir.glob(".orphan-rev-002-*"))
        self.assertEqual(len(aside), 1)
        self.assertIn(aside[0].name, f.last.stderr)
        self.assertEqual(f.head(), 1)
        again = re.search(r"still verifies; publish it again: (publish .*)$", f.last.stderr.strip()).group(1)
        self.assertEqual(again, f"publish --run {RUN} --revision 2 --nonce {nonce}")
        for args in LOCKING[:1] + LOCKING[2:3]:
            f.tool(*args, expect=None)
            self.assertNotIn("recovered interrupted publication", f.last.stderr)
            self.assertEqual(f.head(), 1)
        f.tool(*shlex.split(again))
        self.assertEqual(f.head(), 2)

    def test_publish_rehashes_the_manifest_it_verified(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, SWAP_STAGING_AT_RENAME, "manifest", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertTrue(list(f.rdir.glob(".orphan-rev-002-*")))

    def test_a_file_vanishing_at_the_rename_is_a_conflict(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, SWAP_STAGING_AT_RENAME, "unlink", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("changed between its verification and HEAD (revision 2 plan.md: missing or not a file)",
                      f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertTrue(list(f.rdir.glob(".orphan-rev-002-*")))
        self.assertIn(f"re-stage it: handback --run {RUN} --revision 2 --nonce {nonce} ", f.last.stderr)

    def rejected(self, f):
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        other = f.stage(2, plan_text(2, extra_design=["A competing writer's extra line."]))
        return nonce, other

    def test_a_rejected_revision_that_could_not_be_moved_aside_is_never_rolled_forward(self):
        f = self.f
        nonce, other = self.rejected(f)
        code = self.driver(f, SWAP_STAGING_AT_RENAME, f".staging-002-{other}", "stuck", "publish", "--run", RUN,
                           "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("changed between its verification and HEAD (revision.json, plan.md, handback.json, "
                      "bundle/manifest.json)", f.last.stderr)
        self.assertIn("drvfs EACCES", f.last.stderr)
        self.assertIn("so it is still present and the next recovery moves it aside", f.last.stderr)
        self.assertIn(f"publish it again: publish --run {RUN} --revision 2 --nonce {nonce}", f.last.stderr)
        self.assertTrue((f.rdir / "rev-002").is_dir())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn("it is not the revision publish verified", f.last.stderr)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_crash_after_a_swapped_rename_is_never_rolled_forward(self):
        for args in LOCKING:
            f = Fixture(self)
            nonce, other = self.rejected(f)
            code = self.driver(f, SWAP_STAGING_AT_RENAME, f".staging-002-{other}", "publish", "--run", RUN,
                               "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"})
            self.assertEqual(code, 99, f.last.stdout + f.last.stderr)
            self.assertTrue((f.rdir / "rev-002").is_dir())
            f.tool(*args, expect=None)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertNotIn("recovered interrupted publication", f.last.stderr)
            self.assertEqual(f.head(), 1)
            self.assertFalse((f.rdir / "rev-002").exists())
            self.assertIn("it is not the revision publish verified", f.last.stderr)

    def test_a_read_error_after_the_rename_never_publishes_swapped_content(self):
        f = self.f
        nonce, other = self.rejected(f)
        code = self.driver(f, READ_ERROR_ONCE, f".staging-002-{other}", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        failed = f.last
        self.assertEqual(f.head(), 1)
        f.tool("publish", "--run", RUN, "--recover", expect=None)
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertIn("it is not the revision publish verified", f.last.stderr)
        self.assertEqual(code, 2, failed.stdout + failed.stderr)
        self.assertIn("could not be re-read after the rename", failed.stderr)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_crash_after_an_honest_rename_rolls_forward_and_clears_its_intent(self):
        for args in LOCKING:
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            nonce = f.stage(2, plan_text(2))
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
                   env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
            self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
            f.review_file.write_text(json.dumps(review()))
            f.tool(*args, expect=None)
            self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr, args)
            self.assertEqual(f.head(), 2)
            self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def test_a_crash_after_the_intent_leaves_the_staging_to_publish_again(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_intent"},
               expect=99)
        self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertTrue((f.rdir / f".staging-002-{nonce}").is_dir())
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertEqual(f.head(), 1)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def test_a_revision_above_head_without_an_intent_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn("no publishing intent names it", f.last.stderr)
        restage = re.search(r"re-stage it: (handback .*?), then bundle and publish", f.last.stderr).group(1)
        self.assertIn(f"--nonce {nonce} ", restage)

    def test_a_stale_intent_never_blocks_a_later_publication(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_head"},
               expect=99)
        self.assertEqual(f.head(), 2)
        self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        first = f.stage(3, plan_text(3))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", first, env={"PLANLOOP_CRASH_AT": "after_intent"},
               expect=99)
        stale = (f.rdir / ".publishing-rev-003").read_bytes()
        second = f.stage(3, plan_text(3, extra_design=["A later honest line."]))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", second, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        self.assertNotEqual((f.rdir / ".publishing-rev-003").read_bytes(), stale)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  recovered interrupted publication of revision 3", f.last.stderr)
        self.assertEqual(f.head(), 3)
        self.assertIn("A later honest line.", (f.rdir / "rev-003" / "plan.md").read_text())
        self.assertFalse((f.rdir / ".publishing-rev-003").exists())

    def test_an_identical_restage_after_a_rejection_is_not_blocked(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
        nonce = f.stage(2, plan_text(2))
        honest = (f.rdir / f".staging-002-{nonce}" / "revision.json").read_bytes()
        code = self.driver(f, SWAP_STAGING_AT_RENAME, "unlink", "stuck", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse((f.rdir / "rev-002").exists())
        restage = re.search(r"re-stage it: (handback .*?), then bundle and publish", f.last.stderr).group(1)
        f.tool(*shlex.split(restage))
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        self.assertEqual((f.rdir / f".staging-002-{nonce}" / "revision.json").read_bytes(), honest)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_a_lone_revision_above_a_missing_predecessor_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        d = f.rdir / f".staging-002-{nonce}"
        rv = d / "revision.json"
        rv.write_text(json.dumps({**json.loads(rv.read_text()), "revision": 3,
                                  "base": {"revision": 2, "revision_sha256": "0" * 64}}))
        os.rename(d, f.rdir / "rev-003")
        intend(f, 3)
        f.tool("publish", "--run", RUN, "--recover", expect=None)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("rev-003 aside to .orphan-rev-003-", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def test_an_overlay_copy_missing_above_head_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        d = f.rdir / f".staging-002-{nonce}"
        manifest = json.loads((d / "bundle" / "manifest.json").read_text())
        entries = [e for i in manifest["items"] if i["type"] == "overlay" for e in i["entries"] if e["sha256"]]
        self.assertTrue(entries, manifest)
        (d / "bundle" / "overlay" / entries[0]["path"]).unlink()
        os.rename(d, f.rdir / "rev-002")
        intend(f, 2)
        f.tool("publish", "--run", RUN, "--recover", expect=None)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn("it does not verify as the revision after HEAD", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def test_a_revision_above_head_that_cannot_be_read_is_moved_aside(self):
        def plain(f):
            (f.rdir / "rev-002").write_text("not a revision\n")

        def staged(change):
            def make(f):
                nonce = f.stage(2, plan_text(2))
                d = f.rdir / f".staging-002-{nonce}"
                change(d)
                os.rename(d, f.rdir / "rev-002")
            return make

        def undecodable(d):
            mf, rv = d / "bundle" / "manifest.json", d / "revision.json"
            mf.write_bytes(b"\xff\xfe not UTF-8\n")
            rv.write_text(json.dumps({**json.loads(rv.read_text()),
                                      "bundle_sha256": hashlib.sha256(mf.read_bytes()).hexdigest()}))

        breaks = (plain, staged(lambda d: (d / "plan.md").unlink()), staged(lambda d: (d / "handback.json").unlink()),
                  staged(lambda d: (d / "bundle" / "manifest.json").unlink()), staged(undecodable))
        for args in LOCKING:
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            for make in breaks:
                make(f)
                f.tool(*args, expect=None)
                self.assertNotIn("Traceback", f.last.stderr, (args, make))
                self.assertIn("rev-002 aside to .orphan-rev-002-", f.last.stderr)
                self.assertFalse((f.rdir / "rev-002").exists())
                self.assertEqual(f.head(), 1)

    def test_gate_reports_a_missing_head_plan_as_not_approved(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        (f.rdir / "rev-001" / "plan.md").unlink()
        f.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  [mechanical] revision integrity: revision 1 plan.md: missing", f.last.stdout)
        self.assertIn("NOT APPROVED", f.last.stdout)
        for args in LOCKING:
            f.tool(*args, expect=2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("revision 1 plan.md: missing", f.last.stderr)

    def test_a_restage_command_never_names_a_missing_nonce(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        for change in (lambda d: {k: v for k, v in d.items() if k != "nonce"}, lambda d: {**d, "nonce": "x; rm -rf ~"}):
            nonce = f.stage(2, plan_text(2))
            hb = f.rdir / f".staging-002-{nonce}" / "handback.json"
            hb.write_text(json.dumps(change(json.loads(hb.read_text()))))
            os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
            f.tool("publish", "--run", RUN, "--recover")
            self.assertIn(f"re-stage it: handback --run {RUN} --revision 2 --nonce <a new nonce> --transcript ",
                          f.last.stderr)
            self.assertNotIn("None", f.last.stderr)
            self.assertNotIn("rm -rf", f.last.stderr)

    def test_an_unverifiable_orphan_still_gets_its_restage_command(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
        with open(f.rdir / "rev-002" / "plan.md", "a") as handle:
            handle.write("An edit after staging.\n")
        f.tool("publish", "--run", RUN, "--recover")
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        restage = re.search(r"re-stage it: (handback .*?), then bundle and publish", f.last.stderr).group(1)
        self.assertIn(f"--revision 2 --nonce {nonce} ", restage)

    def malform(self, d, change):
        mf, rv = d / "bundle" / "manifest.json", d / "revision.json"
        mf.write_text(json.dumps(change(json.loads(mf.read_text()))))
        rv.write_text(json.dumps({**json.loads(rv.read_text()),
                                  "bundle_sha256": hashlib.sha256(mf.read_bytes()).hexdigest()}))
        return hashlib.sha256(rv.read_bytes()).hexdigest()

    def test_a_malformed_manifest_above_head_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        for change in (lambda m: {**m, "items": ["junk"]}, lambda m: {k: v for k, v in m.items() if k != "items"},
                       lambda m: {**m, "items": [{**i, "entries": [7]} if i["type"] == "overlay" else i
                                                 for i in m["items"]]},
                       lambda m: {**m, "items": [{"type": "snapshot"} if i["type"] == "snapshot" else i
                                                 for i in m["items"]]},
                       lambda m: {**m, "items": [*m["items"], {"path": "x"}]}):
            nonce = f.stage(2, plan_text(2))
            self.malform(f.rdir / f".staging-002-{nonce}", change)
            os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
            f.tool("publish", "--run", RUN, "--recover")
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertFalse((f.rdir / "rev-002").exists())
            self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
            self.assertEqual(f.head(), 1)

    def test_a_malformed_published_manifest_is_an_integrity_failure(self):
        g = self.f
        g.init()
        g.publish(1, plan_text(1))
        digest = self.malform(g.rdir / "rev-001", lambda m: {**m, "items": ["junk"]})
        (g.rdir / "HEAD").write_text(json.dumps({**json.loads((g.rdir / "HEAD").read_text()),
                                                 "revision_sha256": digest}))
        g.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", g.last.stderr)
        self.assertIn("revision 1 bundle manifest", g.last.stdout)
        self.assertIn("NOT APPROVED", g.last.stdout)
        for args in LOCKING:
            g.tool(*args, expect=2)
            self.assertNotIn("Traceback", g.last.stderr)
            self.assertIn("revision 1 bundle manifest", g.last.stderr)

    def test_an_overlay_copy_changed_at_the_rename_never_reaches_head(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, SWAP_STAGING_AT_RENAME, "overlay", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("changed between its verification and HEAD", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertEqual(len(list(f.rdir.glob(".orphan-rev-002-*"))), 1)
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def test_a_frozen_copy_edited_in_a_published_revision_is_an_integrity_failure(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        with open(f.rdir / "rev-001" / "bundle" / "frozen" / "obligations.json", "a") as handle:
            handle.write("[]\n")
        f.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  [mechanical] revision integrity: revision 1 frozen obligations.json changed",
                      f.last.stdout)
        self.assertIn("NOT APPROVED", f.last.stdout)
        for args in LOCKING:
            f.tool(*args, expect=2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("revision 1 frozen obligations.json changed", f.last.stderr)

    def test_a_frozen_copy_edited_above_head_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
        (f.rdir / "rev-002" / "bundle" / "frozen" / "discovery.json").write_text("{}\n")
        intend(f, 2)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn("it does not verify as the revision after HEAD", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def test_an_undeletable_intent_never_fails_a_completed_publication(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, UNLINK_DENIED, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertIn("NOTE  could not remove .publishing-rev-002", f.last.stderr)
        self.assertEqual(f.head(), 2)
        self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
        code = self.driver(f, UNLINK_DENIED, "findings", "propose", "--run", RUN)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("NOTE  could not remove .publishing-rev-002", f.last.stderr)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        nonce = f.stage(3, plan_text(3))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        code = self.driver(f, UNLINK_DENIED, "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("NOTE  recovered interrupted publication of revision 3", f.last.stderr)
        self.assertIn("NOTE  could not remove .publishing-rev-003", f.last.stderr)
        self.assertEqual(f.head(), 3)

    def test_a_directory_named_like_an_intent_never_wedges_a_command(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        (f.rdir / ".publishing-rev-001").mkdir()
        (f.rdir / ".publishing-rev-001" / "x").write_text("x\n")
        for args in LOCKING[:1] + LOCKING[2:3]:
            f.tool(*args)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("NOTE  could not remove .publishing-rev-001", f.last.stderr)
            self.assertIn("remove it by hand", f.last.stderr)
            self.assertNotIn("the next recovery removes it", f.last.stderr)
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_read_error_during_recovery_moves_nothing_aside(self):
        for driver in (READ_ERROR_ONCE, INTENT_READ_ERROR_ONCE):
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            nonce = f.stage(2, plan_text(2))
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
                   env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
            before = tree(f.rdir / "rev-002")
            code = self.driver(f, driver, "none", "publish", "--run", RUN, "--recover")
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            held = Path(re.search(r"could not read (\S+) \(", f.last.stderr).group(1))
            self.assertEqual(held.name, "plan.md" if driver is READ_ERROR_ONCE else ".publishing-rev-002")
            way_out = f"move {held.parent} out of the run directory by hand (it can then be re-staged)" \
                if held.parent.name == "rev-002" else \
                "move it out of the run directory by hand (a revision is then moved aside and can be re-staged)"
            self.assertIn(f"retry once it is no longer held open; if it persists, {way_out}", f.last.stderr)
            self.assertEqual(tree(f.rdir / "rev-002"), before)
            self.assertFalse(list(f.rdir.glob(".orphan-rev-002-*")))
            self.assertEqual(f.head(), 1)
            f.tool("publish", "--run", RUN, "--recover")
            self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
            self.assertEqual(f.head(), 2)

    def test_an_unreadable_intent_is_named_as_the_cause(self):
        for text in ("not json\n", json.dumps({"schema": "x", "revision": 2, "revision_sha256": "a"})):
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            nonce = f.stage(2, plan_text(2))
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
                   env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
            (f.rdir / ".publishing-rev-002").write_text(text)
            f.tool("publish", "--run", RUN, "--recover")
            self.assertEqual(f.head(), 1)
            self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
            self.assertIn("its publishing intent cannot be read", f.last.stderr, text)
            self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def evidence_staged(self, f, rev):
        observation(f, "2026-10-22T10:00:00Z")
        f.env["PLANLOOP_NOW"] = "2026-10-22T10:10:00Z"
        return f.stage(rev, plan_text(rev), inputs=f.inputs(evidence=["plans/ev1.json"]))

    def test_an_evidence_output_copy_edited_in_a_published_revision_is_an_integrity_failure(self):
        f = self.f
        f.init()
        nonce = self.evidence_staged(f, 1)
        f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
        out = f.rdir / "rev-001" / "bundle" / "frozen" / "evidence" / "plans" / "ev1.out"
        self.assertTrue(out.is_file())
        out.write_text("1\n")
        f.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  [mechanical] revision integrity: revision 1 frozen evidence/plans/ev1.out changed",
                      f.last.stdout)
        for args in LOCKING:
            f.tool(*args, expect=2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("revision 1 frozen evidence/plans/ev1.out changed", f.last.stderr)

    def test_an_evidence_output_copy_edited_above_head_is_moved_aside(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = self.evidence_staged(f, 2)
        os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
        (f.rdir / "rev-002" / "bundle" / "frozen" / "evidence" / "plans" / "ev1.out").write_text("1\n")
        intend(f, 2)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("recovered interrupted publication", f.last.stderr)
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn("it does not verify as the revision after HEAD", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def forge_bead(self, rev, bead_id):
        mf, rv = rev / "bundle" / "manifest.json", rev / "revision.json"
        manifest = json.loads(mf.read_text())
        digest = hashlib.sha256((rev / "handback.json").read_bytes()).hexdigest()
        manifest["items"].append({"type": "bead", "id": bead_id, "fields": [], "sha256": digest})
        mf.write_text(json.dumps(manifest))
        record = json.loads(rv.read_text())
        record["bundle_sha256"] = hashlib.sha256(mf.read_bytes()).hexdigest()
        rv.write_text(json.dumps(record))
        return hashlib.sha256(rv.read_bytes()).hexdigest()

    def test_an_unsafe_frozen_path_above_head_is_moved_aside(self):
        for bead_id in ("../../../handback", "a\u0000b"):
            with self.subTest(bead_id=bead_id):
                f = Fixture(self)
                f.init()
                f.publish(1, plan_text(1))
                nonce = f.stage(2, plan_text(2))
                os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
                self.forge_bead(f.rdir / "rev-002", bead_id)
                intend(f, 2)
                f.tool("publish", "--run", RUN, "--recover", expect=None)
                self.assertEqual(f.last.returncode, 0, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertNotIn("recovered interrupted publication", f.last.stderr)
                self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
                self.assertIn("it does not verify as the revision after HEAD", f.last.stderr)
                self.assertEqual(f.head(), 1)

    def test_an_unsafe_frozen_path_in_a_published_revision_is_an_integrity_failure(self):
        for bead_id in ("../../../handback", "a\u0000b"):
            with self.subTest(bead_id=bead_id):
                f = Fixture(self)
                f.init()
                f.publish(1, plan_text(1))
                digest = self.forge_bead(f.rdir / "rev-001", bead_id)
                (f.rdir / "HEAD").write_text(json.dumps({"schema": "planloop-head/1", "revision": 1,
                                                         "revision_sha256": digest}))
                f.tool("gate", "--run", RUN, expect=None)
                self.assertEqual(f.last.returncode, 1, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("revision integrity: revision 1 manifest names an unsafe frozen path", f.last.stdout)
                for args in LOCKING:
                    f.tool(*args, expect=None)
                    self.assertEqual(f.last.returncode, 2, f.last.stdout + f.last.stderr)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertIn("revision 1 manifest names an unsafe frozen path", f.last.stderr)

    def test_a_directory_at_the_intent_path_stops_publish_cleanly(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        staging = f.rdir / f".staging-002-{nonce}"
        before = tree(staging)
        (f.rdir / ".publishing-rev-002").mkdir()
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, expect=None)
        self.assertEqual(f.last.returncode, 1, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(".publishing-rev-002", f.last.stderr)
        self.assertIn("remove it by hand", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertEqual(tree(staging), before)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertFalse(list(f.rdir.glob("..publishing-rev-002.tmp-*")))
        (f.rdir / ".publishing-rev-002").rmdir()
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_failed_intent_write_leaves_no_temporary_file(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, REPLACE_DENIED, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertFalse(list(f.rdir.glob("..publishing-rev-002.tmp-*")))
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        self.assertTrue((f.rdir / f".staging-002-{nonce}").is_dir())

    def test_an_intent_write_error_stops_publish_cleanly(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        staging = f.rdir / f".staging-002-{nonce}"
        before = tree(staging)
        code = self.driver(f, OPEN_NO_SPACE, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not write {f.rdir / '.publishing-rev-002'} (", f.last.stderr)
        self.assertIn("No space left on device", f.last.stderr)
        self.assertIn("nothing was published, HEAD is unchanged; publish again once it can be written", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertEqual(tree(staging), before)
        self.assertFalse((f.rdir / "rev-002").exists())
        self.assertFalse(list(f.rdir.glob("..publishing-rev-002.tmp-*")))
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_head_write_error_is_completed_by_the_next_locking_command(self):
        for args in LOCKING[:1] + LOCKING[2:3]:
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            nonce = f.stage(2, plan_text(2))
            code = self.driver(f, HEAD_NO_SPACE, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("could not write HEAD (", f.last.stderr)
            self.assertIn("revision 2 is in place with its publishing intent, the next locking command (or "
                          "`publish --recover`) completes it, or moves it aside with a NOTE to re-stage it if it no "
                          "longer verifies", f.last.stderr)
            self.assertEqual(f.head(), 1)
            self.assertTrue((f.rdir / "rev-002").is_dir())
            self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
            self.assertFalse(list(f.rdir.glob(".HEAD.tmp-*")))
            code = self.driver(f, HEAD_NO_SPACE, "publish", "--run", RUN, "--recover")
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("could not write HEAD (", f.last.stderr)
            self.assertIn("revision 2 stays in place with its publishing intent, the next locking command (or "
                          "`publish --recover`) completes it once HEAD can be written, or moves it aside with a NOTE "
                          "to re-stage it if it no longer verifies", f.last.stderr)
            self.assertEqual(f.head(), 1)
            self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
            f.tool(*args)
            self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr, args)
            self.assertEqual(f.head(), 2)
            self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def test_an_intent_left_after_a_rejected_rename_is_removed_by_the_next_recovery(self):
        f = self.f
        nonce, other = self.rejected(f)
        code = self.driver(f, SWAP_THEN_UNLINK_DENIED, f".staging-002-{other}", "publish", "--run", RUN,
                           "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("NOTE  could not remove .publishing-rev-002 (", f.last.stderr)
        self.assertIn("the next recovery removes it", f.last.stderr)
        self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
        self.assertFalse((f.rdir / "rev-002").exists())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())
        self.assertEqual(f.head(), 1)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)


    def test_a_read_error_outside_the_recovered_revision_advises_only_a_retry(self):
        for driver, name in ((PRED_READ_ERROR_ONCE, "revision.json"), (SNAP_READ_ERROR_ONCE, None)):
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            nonce = f.stage(2, plan_text(2))
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
                   env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
            before = tree(f.rdir, skip=("reviews",))
            code = self.driver(f, driver, "none", "publish", "--run", RUN, "--recover")
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            held = Path(re.search(r"could not read (\S+) \(", f.last.stderr).group(1))
            self.assertIn("rev-001/revision.json" if name else "snap-r002-", held.as_posix())
            self.assertIn("retry once it is no longer held open", f.last.stderr)
            self.assertNotIn("if it persists", f.last.stderr)
            self.assertNotIn("move ", f.last.stderr)
            self.assertEqual(tree(f.rdir, skip=("reviews",)), before)
            self.assertEqual(f.head(), 1)
            f.tool("publish", "--run", RUN, "--recover")
            self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
            self.assertEqual(f.head(), 2)

    def test_a_denied_existence_check_during_recovery_is_unverifiable(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
               env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
        before = tree(f.rdir, skip=("reviews",))
        code = self.driver(f, EXISTS_DENIED_ONCE, "none", "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not read {f.rdir / 'rev-002'} (", f.last.stderr)
        self.assertIn("retry once it is no longer held open", f.last.stderr)
        self.assertEqual(tree(f.rdir, skip=("reviews",)), before)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_an_io_error_renaming_the_staging_stops_publish_cleanly(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        staging = f.rdir / f".staging-002-{nonce}"
        before = tree(staging)
        code = self.driver(f, EIO_AT_RENAME, ".staging-", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not rename {staging} -> {f.rdir / 'rev-002'} (", f.last.stderr)
        self.assertIn("Input/output error", f.last.stderr)
        self.assertIn("the rename did not report success, so it may or may not have taken effect; run the command "
                      "again, it re-checks what is on disk", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertEqual(tree(staging), before)
        self.assertFalse((f.rdir / "rev-002").exists())
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)
        self.assertFalse((f.rdir / ".publishing-rev-002").exists())

    def test_an_io_error_moving_a_revision_aside_leaves_it_for_the_next_recovery(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
        before = tree(f.rdir / "rev-002")
        code = self.driver(f, EIO_AT_RENAME, "rev-", "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not rename {f.rdir / 'rev-002'} -> ", f.last.stderr)
        self.assertIn("the rename did not report success, so it may or may not have taken effect; run the command "
                      "again, it re-checks what is on disk; if rev-002 is gone it is .orphan-rev-002-", f.last.stderr)
        self.assertIn(f", re-stage it: handback --run {RUN} --revision 2 --nonce {nonce} ", f.last.stderr)
        self.assertEqual(tree(f.rdir / "rev-002"), before)
        self.assertFalse(list(f.rdir.glob(".orphan-rev-002-*")))
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def test_publishing_again_after_a_head_write_error_reports_the_revision_published(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, HEAD_NO_SPACE, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertIn(f"revision 2 (nonce {nonce}) is already published (HEAD is revision 2); nothing to do",
                      f.last.stdout)
        self.assertNotIn("FAIL", f.last.stdout + f.last.stderr)
        self.assertEqual(f.head(), 2)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", "0123abcd", expect=1)
        self.assertIn("revision 2 is already published from another staging (HEAD is revision 2)", f.last.stderr)
        nonce = f.stage(3, plan_text(3))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        (f.rdir / ".publishing-rev-003").write_text("not json\n")
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", nonce, expect=1)
        self.assertIn("NOTE  moved rev-003 aside to .orphan-rev-003-", f.last.stderr)
        self.assertIn(f".staging-003-{nonce} does not exist; revision 3 is not published (HEAD is revision 2); "
                      "re-stage it", f.last.stderr)
        self.assertEqual(f.head(), 2)


    def dispatch_args(self, attempt=1):
        return ("dispatch", "--run", RUN, "--call", "1", "--attempt", str(attempt), "--kind", "working", "--effort",
                "medium")

    def ready_to_dispatch(self, f):
        f.init()
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review("REVISE", [finding("F1")])))

    def test_a_lock_release_error_after_publishing_says_the_work_completed(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, RELEASE_EIO, "1", "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertFalse(probe_any(f.state / RUN / ".lock-bundle"))
        self.assertIn(f"the command's work completed (see the output above); the lock {f.rdir / '.lock'} could not "
                      "be released (", f.last.stderr)
        self.assertIn("if it is still there, a planloop command run after this process has exited breaks it",
                      f.last.stderr)
        self.assertNotIn("nothing was moved", f.last.stderr)
        self.assertEqual(f.head(), 2)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)

    def test_a_lock_release_error_never_masks_the_commands_own_error(self):
        f = self.f
        nonce, other = self.rejected(f)
        code = self.driver(f, RELEASE_EIO_AFTER_SWAP, f".staging-002-{other}", "publish", "--run", RUN,
                           "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertNotIn("UNVERIFIABLE", f.last.stderr)
        self.assertIn("changed between its verification and HEAD", f.last.stderr)
        self.assertIn("it was moved aside to .orphan-rev-002-", f.last.stderr)
        self.assertIn(f"publish it again: publish --run {RUN} --revision 2 --nonce {nonce}", f.last.stderr)
        self.assertIn(f"NOTE  could not release lock {f.rdir / '.lock'} (", f.last.stderr)
        self.assertIn("if it is still there, a planloop command run after this process has exited breaks it",
                      f.last.stderr)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_lost_lock_never_masks_the_commands_own_error(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        code = self.driver(f, OWNER_LOST, "none", "publish", "--run", RUN, "--revision", "2", "--nonce", "0123abcd")
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertIn("FAIL  .staging-002-0123abcd does not exist", f.last.stderr)
        self.assertIn(f"NOTE  lock {f.rdir / '.lock'} is no longer ours (its owner.json now reads None): another "
                      "writer broke it, or it was removed or cannot be read; it was not released here", f.last.stderr)

    def test_a_lost_lock_after_publishing_says_the_work_completed(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, OWNER_LOST, "none", "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertIn("CONFLICT  the command's work completed (see the output above), but lock "
                      f"{f.rdir / '.lock'} is no longer ours (its owner.json now reads None)", f.last.stderr)
        self.assertIn(f"NOTE  lock {f.state / RUN / '.lock-bundle'} is no longer ours (its owner.json now reads None)",
                      f.last.stderr)
        self.assertEqual(f.head(), 2)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)

    def test_an_unreadable_lock_owner_never_masks_the_commands_own_error(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        code = self.driver(f, OWNER_GARBLED, "none", "publish", "--run", RUN, "--revision", "2", "--nonce",
                           "0123abcd")
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  .staging-002-0123abcd does not exist", f.last.stderr)
        self.assertIn(f"NOTE  lock {f.rdir / '.lock'} is no longer ours (its owner.json now reads None)",
                      f.last.stderr)

    def test_a_lock_release_error_follows_each_commands_closing_line(self):
        f = self.f
        init = ("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "none", "--rationale",
                "test importer change with no persistence or ordering semantics", "--reviewer-backend", "codex")
        self.assertEqual(self.driver(f, RELEASE_EIO, "1", *init), 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"run {RUN}: bead ", f.last.stdout)
        f.to_gate_ready()
        c = f.review(review(), kind="gate", effort="high")
        f.ingest(c, {})
        for args, line in ((("state", "--run", RUN, "--set", "active", "--reason", "carrying on"),
                            f"run {RUN}: active (carrying on)"),
                           (("planner", "--run", RUN, "--model", "opus", "--quote", "use Opus to plan"),
                            f"run {RUN}: escalated-track planner override 'opus' recorded"),
                           (("reviewers", "--run", RUN, "--model", "gpt-6-astra", "--gate-model", "gpt-6-astra",
                             "--quote", "keep astra"), f"run {RUN}: Codex reviews on 'gpt-6-astra'"),
                           (("gate", "--run", RUN, "--publish"), "PLAN APPROVED: revision 2")):
            self.assertEqual(self.driver(f, RELEASE_EIO, "1", *args), 2, f.last.stdout + f.last.stderr)
            self.assertIn(line, f.last.stdout)
            self.assertIn("the command's work completed (see the output above); the lock ", f.last.stderr)
        f.tool("gate", "--run", RUN)

    def test_a_lock_release_that_took_effect_despite_its_error_is_a_release(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        code = self.driver(f, LANDED_EIO, ".lock-released-", "publish", "--run", RUN, "--revision", "2", "--nonce",
                           nonce)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("published revision 2", f.last.stdout)
        self.assertNotIn("could not be released", f.last.stderr)
        self.assertNotIn("could not release", f.last.stderr)
        self.assertFalse(list(f.rdir.glob(".lock*")))
        self.assertEqual(f.head(), 2)

    def test_a_lock_release_error_is_printed_below_the_output_it_points_at(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        path = f.root / "driver-merged.py"
        path.write_text(RELEASE_EIO)
        proc = subprocess.run([sys.executable, str(path), str(TOOL), "1", "publish", "--run", RUN, "--revision", "2",
                               "--nonce", nonce], cwd=f.repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=f.env, timeout=300)
        self.assertIn("published revision 2", proc.stdout)
        self.assertIn("see the output above", proc.stdout)
        self.assertLess(proc.stdout.index("published revision 2"), proc.stdout.index("see the output above"),
                        proc.stdout)

    def test_a_lock_without_a_readable_owner_says_how_to_clear_it(self):
        f = self.f
        f.init()
        (f.rdir / ".lock").mkdir()
        (f.rdir / ".lock" / "owner.json").write_bytes(b"\xff\xfe")
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertNotIn("held by None", f.last.stderr)
        self.assertIn(f"could not take the lock {f.rdir / '.lock'} and its owner.json does not read", f.last.stderr)
        self.assertIn(f"if this persists while no planloop process runs, remove {f.rdir / '.lock'} by hand",
                      f.last.stderr)
        shutil.rmtree(f.rdir / ".lock")
        f.tool("publish", "--run", RUN, "--recover")

    def test_a_reservation_that_landed_despite_its_error_is_recorded_invalid_and_retried(self):
        f = self.f
        self.ready_to_dispatch(f)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, LANDED_EIO_ONTO, "call-001-a1", *self.dispatch_args())
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"if {call_dir} exists now, record it with `receipt --run {RUN} --call 1 --attempt 1`",
                      f.last.stderr)
        self.assertTrue(call_dir.is_dir())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_review_whose_snapshot_changed_is_invalid_and_reprints(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, SNAPSHOT_TOUCHED, "none", *self.dispatch_args())
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertIn("FAIL  frozen snapshot changed during the review", f.last.stdout)
        stored = (f.rdir / "reviews" / "call-001-a1" / "receipt.json").read_bytes()
        self.assertEqual(json.loads(stored)["status"], "invalid")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("FAIL  frozen snapshot changed during the review", f.last.stdout)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertEqual((f.rdir / "reviews" / "call-001-a1" / "receipt.json").read_bytes(), stored)

    def test_a_first_receipt_never_skips_a_missing_snapshot(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        self.assertFalse((call_dir / "receipt.json").exists())
        private = Path(json.loads((call_dir / "input" / "dispatch.json").read_text())["snapshot"]).parent
        for dirpath, dirnames, filenames in os.walk(private):
            os.chmod(dirpath, 0o755)
        shutil.rmtree(private)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("FAIL  frozen snapshot changed during the review", f.last.stdout)
        self.assertEqual(json.loads((call_dir / "receipt.json").read_text())["status"], "invalid")

    def test_a_reservation_lock_release_error_names_the_receipt_and_the_next_attempt(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, RELEASE_EIO, "1", *self.dispatch_args())
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"call 1 attempt 1 is reserved and Codex has not run; record it with `receipt --run {RUN} "
                      "--call 1 --attempt 1` (Codex did not run, so it is recorded invalid), then dispatch call 1 "
                      "attempt 2", f.last.stderr)
        self.assertIn(f"the lock {f.rdir / '.lock'} could not be released (", f.last.stderr)
        self.assertNotIn("run the command again", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_run_lock_that_is_not_released_once_the_runner_was_started_stops_the_runner_again(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        started = []
        try:
            code = self.driver(f, RELEASE_EIO, "2", *self.dispatch_args(), env=env)
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("UNVERIFIABLE  the review runner was started for call 1 attempt 1 and is stopped again, since "
                          "the run lock it was started under was not released; record it with `receipt --run "
                          f"{RUN} --call 1 --attempt 1` (its call.json is missing, so it is recorded invalid), then "
                          "dispatch call 1 attempt 2 (after `state --set active` if that receipt blocks the run); the "
                          f"lock {f.rdir / '.lock'} could not be released (", f.last.stderr)
            self.assertTrue(self.emptied(f))
            self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "call.json").exists())
        finally:
            if pids.exists():
                started = [int(p) for p in pids.read_text().split()]
            self.stop_all(started)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_receipt_lock_release_error_says_the_review_is_recorded(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, RELEASE_EIO, "3", *self.dispatch_args())
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertIn("the review is recorded (call 1 attempt 1: counted, see the output above), carry on from it "
                      f"(a counted review goes to `findings ingest`); `receipt --run {RUN} --call 1 --attempt 1` "
                      "prints it again", f.last.stderr)
        self.assertNotIn("run the command again", f.last.stderr)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        f.ingest(1, {"F1": "new"})

    def test_running_receipt_again_reprints_a_recorded_review(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args())
        stored = (f.rdir / "reviews" / "call-001-a1" / "receipt.json").read_bytes()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted, verdict REVISE", f.last.stdout)
        self.assertEqual((f.rdir / "reviews" / "call-001-a1" / "receipt.json").read_bytes(), stored)

    def test_an_io_error_reserving_a_call_names_the_receipt_for_a_reservation_that_landed(self):
        f = self.f
        self.ready_to_dispatch(f)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, EIO_FROM, ".reserve-", *self.dispatch_args())
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"if {call_dir} exists now, record it with `receipt --run {RUN} --call 1 --attempt 1`",
                      f.last.stderr)
        self.assertIn("otherwise run the command again", f.last.stderr)
        self.assertFalse(call_dir.exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_an_io_error_installing_a_bundle_says_what_to_remove(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.hand(2, plan_text(2))
        staging = f.rdir / f".staging-002-{nonce}"
        code = self.driver(f, EIO_FROM, ".bundle-tmp-", "bundle", "--run", RUN, "--revision", "2", "--nonce", nonce,
                           "--inputs", str(f.inputs()))
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"if {staging / 'bundle'} exists now, remove it (no revision.json was written for it); then run "
                      "the command again", f.last.stderr)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_an_io_error_moving_a_rejected_revision_aside_hedges_whether_it_moved(self):
        f = self.f
        nonce, other = self.rejected(f)
        code = self.driver(f, ASIDE_EIO_AFTER_SWAP, f".staging-002-{other}", "publish", "--run", RUN,
                           "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("the rename did not report success, so it may or may not have taken effect; if it is still "
                      "present the next recovery moves it aside", f.last.stderr)
        self.assertNotIn("so it is still present", f.last.stderr)
        self.assertTrue((f.rdir / "rev-002").is_dir())
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  moved rev-002 aside to .orphan-rev-002-", f.last.stderr)
        self.assertEqual(f.head(), 1)

    def test_a_read_error_naming_no_file_during_recovery_advises_only_a_retry(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        before = tree(f.rdir / "rev-002")
        code = self.driver(f, NO_NAME_READ_ERROR_ONCE, "none", "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not read {f.rdir / 'rev-002'} (", f.last.stderr)
        self.assertIn("retry once it is no longer held open", f.last.stderr)
        self.assertNotIn("if it persists", f.last.stderr)
        self.assertEqual(tree(f.rdir / "rev-002"), before)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_a_read_error_checking_an_earlier_publication_advises_only_a_retry(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        for driver, arg, held in ((EXISTS_EIO, f".staging-002-{nonce}", f.rdir / f".staging-002-{nonce}"),
                                  (PUBLISHED_HANDBACK_DENIED, "rev-002", f.rdir / "rev-002" / "handback.json")):
            code = self.driver(f, driver, arg, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn(f"could not read {held} (", f.last.stderr)
            self.assertIn("retry once it is no longer held open", f.last.stderr)
            self.assertNotIn("if it persists", f.last.stderr)
            self.assertNotIn("move ", f.last.stderr)
            self.assertEqual(f.head(), 2)
            self.assertTrue((f.rdir / "rev-002").is_dir())

    def test_a_lock_that_cannot_be_prepared_is_unverifiable(self):
        f = self.f
        f.init()
        code = self.driver(f, MKDIR_EIO, ".lock-tmp-", "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("could not prepare the lock in ", f.last.stderr)
        self.assertIn("the lock was not taken", f.last.stderr)
        self.assertFalse(list(f.rdir.glob(".lock*")))

    def test_a_lock_rename_that_keeps_failing_reports_its_error(self):
        f = self.f
        f.init()
        code = self.driver(f, EIO_ONTO, ".lock", "publish", "--run", RUN, "--recover",
                           env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not take the lock {f.rdir / '.lock'}: renaming .lock-tmp-", f.last.stderr)
        self.assertIn("Input/output error", f.last.stderr)
        self.assertNotIn("held by None", f.last.stderr)
        self.assertFalse(list(f.rdir.glob(".lock*")))

    def test_a_lock_breaker_that_cannot_remove_its_marker_says_so(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "lock_acquired"},
               expect=99)
        code = self.driver(f, RMDIR_EIO, ".lock-break", "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertIn(f"NOTE  could not remove {f.state / RUN / '.lock-break'} (", f.last.stderr)
        self.assertIn("remove it by hand once no planloop process runs", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_a_lock_directory_that_cannot_be_made_is_unverifiable(self):
        f = self.f
        f.init()
        code = self.driver(f, MKDIR_EIO, RUN, "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not prepare the lock in {f.rdir} (", f.last.stderr)
        self.assertIn("the lock was not taken", f.last.stderr)
        self.assertFalse(list(f.rdir.glob(".lock*")))

    def test_a_lock_breaker_that_cannot_make_its_marker_takes_nothing(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "lock_acquired"},
               expect=99)
        owner = (f.state / RUN / ".lock-bundle" / "owner.json").read_bytes()
        code = self.driver(f, MKDIR_EIO, ".lock-break", "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not create {f.state / RUN / '.lock-break'} to break the stale lock of dead owner ",
                      f.last.stderr)
        self.assertIn("the lock was not taken", f.last.stderr)
        self.assertEqual((f.state / RUN / ".lock-bundle" / "owner.json").read_bytes(), owner)
        self.assertEqual(f.head(), 1)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_a_snapshot_copy_that_cannot_be_removed_never_masks_the_reservation_advice(self):
        f = self.f
        self.ready_to_dispatch(f)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, RESERVE_EIO_COPY_STUCK, ".reserve-", *self.dispatch_args())
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"if {call_dir} exists now, record it with `receipt --run {RUN} --call 1 --attempt 1`",
                      f.last.stderr)
        self.assertIn("NOTE  could not remove the private snapshot copy ", f.last.stderr)
        self.assertIn("Device or resource busy", f.last.stderr)
        self.assertFalse(call_dir.exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_runner_that_cannot_start_is_recorded_invalid_and_retried(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": str(f.root / "no-such-runner")}, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"NOTE  the review runner could not be started in its scope {self.unit(f)} ([Errno 2] No such "
                      f"file or directory: '{f.root / 'no-such-runner'}'); Codex did not run", f.last.stderr)
        self.assertIn("FAIL  runner left no artifact directory", f.last.stdout)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertEqual(f.receipt(1)["status"], "invalid")
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_missing_runner_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        (f.root / "home").mkdir()
        f.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": "", "HOME": str(f.root / "home")}, expect=2)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("claudex-loop runner.py not found", f.last.stderr)
        self.assertIn("no call was reserved", f.last.stderr)
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_running_receipt_again_after_an_input_changed_prints_the_recorded_receipt(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args())
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = path.read_bytes()
        (f.repo / "src" / "a.rs").write_text("fn main() { later(); }\n")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted, verdict REVISE", f.last.stdout)
        self.assertIn("NOTE  this is the receipt as recorded; the live inputs revalidate differently now (file "
                      "src/a.rs changed or was deleted; ", f.last.stderr)
        self.assertIn("receipt.json was not rewritten", f.last.stderr)
        self.assertNotIn("CONFLICT", f.last.stderr)
        self.assertEqual(path.read_bytes(), stored)
        f.ingest(1, {"F1": "new"})

    def test_running_receipt_again_never_turns_an_invalid_receipt_counted(self):
        f = self.f
        self.ready_to_dispatch(f)
        source = f.repo / "src" / "a.rs"
        original = source.read_text()
        code = self.driver(f, INPUT_TOUCHED, str(source), *self.dispatch_args())
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = path.read_bytes()
        self.assertEqual(json.loads(stored)["status"], "invalid")
        source.write_text(original)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("FAIL  relevant inputs changed during the review", f.last.stdout)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertIn("no declared input differs from the frozen bundle", f.last.stderr)
        self.assertEqual(path.read_bytes(), stored)
        forged = json.loads(stored)
        forged["status"] = "counted"
        path.write_text(json.dumps(forged))
        forged = path.read_bytes()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
        self.assertIn("exists and differs from a fresh verification in more than the live-input revalidation; it "
                      "was left unchanged", f.last.stderr)
        self.assertEqual(path.read_bytes(), forged)

    def receipt_conflicts(self, f, path, record):
        edited = json.dumps(record, sort_keys=True).encode()
        path.write_bytes(edited)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
        self.assertIn("exists and differs from a fresh verification in more than the live-input revalidation; it "
                      "was left unchanged and is not printed", f.last.stderr)
        self.assertNotIn("call 1 attempt 1", f.last.stdout)
        self.assertNotIn("NOTE  this is the receipt as recorded", f.last.stderr)
        self.assertEqual(path.read_bytes(), edited)

    def test_a_receipt_invalid_for_a_changed_input_edited_to_counted_is_a_conflict(self):
        f = self.f
        self.ready_to_dispatch(f)
        source = f.repo / "src" / "a.rs"
        original = source.read_text()
        code = self.driver(f, INPUT_TOUCHED, str(source), *self.dispatch_args())
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = json.loads(path.read_bytes())
        self.assertEqual((stored["status"], stored["infrastructure"], len(stored["reasons"])), ("invalid", False, 1))
        self.assertTrue(stored["revalidation"])
        forged = {**stored, "status": "counted", "reasons": [], "infrastructure": False}
        self.receipt_conflicts(f, path, forged)
        self.receipt_conflicts(f, path, {**stored, "status": "counted"})
        self.receipt_conflicts(f, path, {**stored, "revalidation": []})
        self.receipt_conflicts(f, path, {**stored, "revalidation": stored["revalidation"][:1]})
        self.receipt_conflicts(f, path, {**stored, "reasons": stored["reasons"] * 2})
        changed = "relevant inputs changed during the review: "
        self.receipt_conflicts(f, path, {**stored, "revalidation": "abc", "reasons": [changed + "abc"]})
        self.receipt_conflicts(f, path, {**stored, "revalidation": [["x"]], "reasons": [changed + "[['x']]"]})
        source.write_text(original)
        self.receipt_conflicts(f, path, forged)
        self.receipt_conflicts(f, path, {**stored, "infrastructure": True})
        self.receipt_conflicts(f, path, {**stored, "reasons": stored["reasons"] + [
            "live inputs could not be revalidated: one", "live inputs could not be revalidated: two"]})

    def test_a_counted_receipt_whose_revalidation_or_infrastructure_was_edited_is_a_conflict(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args())
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = json.loads(path.read_bytes())
        self.assertEqual((stored["status"], stored["infrastructure"], stored["revalidation"]), ("counted", False, []))
        fake = ["file src/a.rs changed or was deleted"]
        without = lambda key: {k: v for k, v in stored.items() if k != key}
        edits = {"infrastructure flipped": {**stored, "infrastructure": True},
                 "infrastructure deleted": without("infrastructure"),
                 "infrastructure null": {**stored, "infrastructure": None},
                 "revalidation faked": {**stored, "revalidation": fake},
                 "revalidation deleted": without("revalidation"),
                 "revalidation not a list": {**stored, "revalidation": "none"},
                 "revalidation of non-strings": {**stored, "revalidation": [[]]},
                 "reasons deleted": without("reasons")}
        for live in ("unchanged", "changed"):
            for name, record in edits.items():
                with self.subTest(live=live, edit=name):
                    self.receipt_conflicts(f, path, record)
            if live == "changed":
                for name, record in (("infrastructure 0", {**stored, "infrastructure": 0}),
                                     ("fresh 1", {**stored, "fresh": 1})):
                    with self.subTest(live=live, edit=name):
                        self.receipt_conflicts(f, path, record)
            (f.repo / "src" / "a.rs").write_text("fn main() { later(); }\n")
        path.write_bytes(json.dumps(stored).encode())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted, verdict REVISE", f.last.stdout)

    def test_the_note_on_a_recorded_receipt_states_what_was_recorded_and_what_holds_now(self):
        f = self.f
        self.ready_to_dispatch(f)
        source = f.repo / "src" / "a.rs"
        original = source.read_text()
        self.assertEqual(self.driver(f, INPUT_TOUCHED, str(source), *self.dispatch_args()), 1)
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = path.read_bytes()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertNotIn("NOTE  this is the receipt as recorded", f.last.stderr)
        source.write_text("fn main() { changed_again(); }\n")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertNotIn("NOTE  this is the receipt as recorded", f.last.stderr)
        source.write_text(original)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertIn("NOTE  this is the receipt as recorded; the live inputs revalidate differently now (no declared "
                      "input differs from the frozen bundle) than the receipt records (file src/a.rs changed or was "
                      "deleted; ", f.last.stderr)
        self.assertEqual(path.read_bytes(), stored)
        f.tool(*self.dispatch_args(2))
        path = f.rdir / "reviews" / "call-001-a2" / "receipt.json"
        stored = path.read_bytes()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        self.assertNotIn("NOTE  this is the receipt as recorded", f.last.stderr)
        source.write_text("fn main() { later(); }\n")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)
        self.assertIn("NOTE  this is the receipt as recorded; the live inputs revalidate differently now (file "
                      "src/a.rs changed or was deleted; ", f.last.stderr)
        self.assertIn(") than the receipt records (no declared input differed from the frozen bundle); the recorded "
                      "receipt stands and receipt.json was not rewritten", f.last.stderr)
        self.assertEqual(path.read_bytes(), stored)

    def test_a_receipt_recorded_while_the_inputs_could_not_be_revalidated_stays_invalid(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, REVALIDATION_DOWN, "bd did not answer", *self.dispatch_args())
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        path = f.rdir / "reviews" / "call-001-a1" / "receipt.json"
        stored = json.loads(path.read_bytes())
        self.assertEqual((stored["status"], stored["infrastructure"], stored["revalidation"], stored["reasons"]),
                         ("invalid", True, [], ["live inputs could not be revalidated: bd did not answer"]))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("FAIL  live inputs could not be revalidated: bd did not answer", f.last.stdout)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertIn("NOTE  this is the receipt as recorded; the live inputs revalidate differently now (no declared "
                      "input differs from the frozen bundle) than the receipt records (live inputs could not be "
                      "revalidated: bd did not answer); ", f.last.stderr)
        self.assertEqual(json.loads(path.read_bytes()), stored)
        self.receipt_conflicts(f, path, {**stored, "infrastructure": False})
        self.receipt_conflicts(f, path, {**stored, "status": "counted"})
        self.receipt_conflicts(f, path, {**stored, "reasons": []})

    def test_lock_notes_follow_the_output_printed_before_them(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        for text, note in ((OWNER_LOST.replace("None\n", "None\n" + MARKED + "\n", 1), "NOTE  lock "),
                           (RELEASE_EIO.replace("os.rename = rename", "os.rename = rename\n" + MARKED),
                            "NOTE  could not release lock")):
            path = f.root / f"driver-{uuid.uuid4().hex[:6]}.py"
            path.write_text(text)
            proc = subprocess.run([sys.executable, str(path), str(TOOL), "1", "publish", "--run", RUN, "--revision",
                                   "2", "--nonce", "0123abcd"], cwd=f.repo, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, env=f.env, timeout=300)
            self.assertIn("MARKER printed before the NOTE", proc.stdout)
            self.assertIn(note, proc.stdout)
            self.assertLess(proc.stdout.index("MARKER printed before the NOTE"), proc.stdout.index(note), proc.stdout)

    def test_a_lock_released_just_as_the_timeout_ran_out_is_taken(self):
        f = self.f
        f.init()
        code = self.driver(f, RELEASED_AT_DEADLINE, str(f.rdir / ".lock"), "publish", "--run", RUN, "--recover",
                           env={"PLANLOOP_LOCK_TIMEOUT": "0"})
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertNotIn("does not read", f.last.stderr)
        self.assertFalse(list(f.rdir.glob(".lock")))

    def test_a_gate_that_is_not_approved_says_so_when_the_lock_cannot_be_released(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        code = self.driver(f, RELEASE_EIO, "1", "gate", "--run", RUN, "--publish")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn("NOT APPROVED", f.last.stdout)
        self.assertIn("the gate found the plan NOT APPROVED (see the output above); the lock ", f.last.stderr)
        self.assertNotIn("the command's work completed", f.last.stderr)

    def test_a_revision_left_by_a_failed_move_aside_is_published_if_it_holds_the_verified_bytes(self):
        for driver, extra in ((ASIDE_EIO_AFTER_SWAP, ()), (SWAP_STAGING_AT_RENAME, ("stuck",))):
            f = Fixture(self)
            nonce, other = self.rejected(f)
            code = self.driver(f, driver, f".staging-002-{other}", *extra, "publish", "--run", RUN, "--revision", "2",
                               "--nonce", nonce)
            self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
            self.assertIn("the next recovery moves it aside, or publishes it if it then holds exactly the revision "
                          "publish verified and that revision's cut still holds", f.last.stderr)
            shutil.rmtree(f.rdir / "rev-002")
            os.rename(f.rdir / f".staging-002-{nonce}", f.rdir / "rev-002")
            f.tool("publish", "--run", RUN, "--recover")
            self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
            self.assertEqual(f.head(), 2)

    def test_a_live_owner_whose_start_time_was_not_recorded_is_never_broken(self):
        f = self.f
        f.init()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        lock = f.rdir / ".lock"
        lock.mkdir()
        owner = {"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(), "pid_ns": PID_NS, "start": None,
                 "nonce": "e" * 32, "acquired_at": "2026-11-11T00:00:00Z"}
        (lock / "owner.json").write_text(json.dumps(owner))
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertNotIn("broke stale lock", f.last.stderr)
        self.assertIn("is held by", f.last.stderr)
        self.assertEqual(json.loads((lock / "owner.json").read_text()), owner)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (lock / "owner.json").write_text(json.dumps({**owner, "pid": dead.pid}))
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertFalse(lock.exists())

    def test_a_snapshot_copy_that_cannot_be_pruned_never_fails_a_recorded_receipt(self):
        for mode in ("partial", "rename"):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                code = self.driver(f, PRUNE_STUCK, mode, *self.dispatch_args())
                self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                private = Path(json.loads((call_dir / "input" / "dispatch.json").read_text())["snapshot"]).parent
                left = private if mode == "rename" else private.with_name(f".pruned-{private.name}")
                self.assertIn(f"NOTE  could not remove the private snapshot copy {left} (", f.last.stderr)
                self.assertIn("the receipt is recorded and stands and no review needs that copy: remove it by hand "
                              "(`chmod -R u+w` first) once no planloop process runs", f.last.stderr)
                self.assertTrue(left.exists())
                self.assertEqual(f.receipt(1)["status"], "counted")
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                self.assertNotIn("CONFLICT", f.last.stderr)
                self.assertNotIn("could not remove", f.last.stderr)
                self.assertFalse(private.exists())
                if left.exists():
                    subprocess.run(["chmod", "-R", "u+w", str(left)], check=True)
                    shutil.rmtree(left)
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                f.ingest(1, {"F1": "new"})

    def test_a_held_lock_on_this_host_names_the_way_out(self):
        f = self.f
        f.init()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        lock = f.rdir / ".lock"
        lock.mkdir()
        owner = {"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(), "pid_ns": PID_NS, "start": None,
                 "nonce": "e" * 32, "acquired_at": "2026-11-11T00:00:00Z"}
        hint = f"; if process {os.getpid()} on this host is not a running planloop command, remove {lock} by hand"
        (lock / "owner.json").write_text(json.dumps({**owner, "host": "elsewhere"}))
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertIn("is held by", f.last.stderr)
        self.assertNotIn("on this host is not a running planloop command", f.last.stderr)
        self.assertIn(f"in this PID namespace; it was taken on host 'elsewhere': check on that host that process "
                      f"{os.getpid()} is not a running planloop command, then remove {lock} by hand\n", f.last.stderr)
        (lock / "owner.json").write_text(json.dumps(owner))
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertIn(hint, f.last.stderr)
        shutil.rmtree(lock)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertFalse(lock.exists())

    def test_a_running_marker_held_by_a_reused_pid_names_the_way_out(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        running = f.rdir / "reviews" / "call-001-a1" / "running.json"
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        running.write_text(json.dumps({"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(),
                                       "pid_ns": PID_NS, "start": None, "nonce": "d" * 32}))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
        self.assertIn(f"call 1 attempt 1 is still being reviewed by process {os.getpid()}; wait for it; if process "
                      f"{os.getpid()} on this host is not a planloop dispatch, remove {running} by hand and run "
                      f"`receipt --run {RUN} --call 1 --attempt 1` again: that gives up only the wait for the "
                      "dispatching process (a dispatch that has not started its review runner by then never starts "
                      "it), and the call is still not recorded while a process runs in the scope of its review\n",
                      f.last.stderr)
        running.unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_runner_command_line_that_does_not_parse_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": f"{sys.executable} 'unterminated"}, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  PLANLOOP_RUNNER does not parse (", f.last.stderr)
        self.assertIn("no call was reserved and Codex did not run", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_call_record_that_cannot_be_written_is_recorded_invalid(self):
        for mode in ("open", "partial", "stuck"):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                path = f.rdir / "reviews" / "call-001-a1" / "call.json"
                code = self.driver(f, CALL_JSON_EIO, mode, *self.dispatch_args())
                self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"UNVERIFIABLE  could not write {path} (", f.last.stderr)
                self.assertIn("Input/output error", f.last.stderr)
                self.assertIn("so the review runner's result is not recorded; record it with `receipt --run "
                              f"{RUN} --call 1 --attempt 1` (", f.last.stderr)
                if mode == "stuck":
                    self.assertIn(f"(it is recorded invalid unless {path} reads in full, and nothing is recorded while "
                                  "it cannot be read at all), then dispatch call 1 attempt 2 if it is invalid, or carry "
                                  "on from it if it counted", f.last.stderr)
                    self.assertTrue(path.exists())
                    reason = "FAIL  call.json does not read ("
                else:
                    self.assertIn("(its call.json is missing (never written, or removed after the failed write), so it "
                                  "is recorded invalid), then dispatch call 1 attempt 2 (after", f.last.stderr)
                    self.assertFalse(path.exists())
                    reason = "FAIL  call.json is missing (never written, or removed after a failed write: the " \
                        "dispatching process failed or stopped before it recorded the runner's result), so"
                self.assertTrue(list(f.artifacts().glob("claudex-*/result.json")))
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
                self.assertIn(reason, f.last.stdout)
                self.assertNotIn("runner left no artifact directory", f.last.stdout)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertEqual(f.receipt(1)["status"], "invalid")
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_lock_directory_that_cannot_be_made_says_only_empty_directories_were_made(self):
        f = self.f
        f.init()
        code = self.driver(f, MKDIR_EIO, RUN, "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn("nothing else was changed (at most empty directories on its path were created), run the "
                      "command again", f.last.stderr)

    def test_rerunning_an_older_gate_receipt_keeps_the_latest_gate_copy(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        g1 = f.review(review("REVISE", [finding("F1")]), kind="gate", effort="high")
        f.ingest(g1, {"F1": "new"})
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        g2 = f.review(review("APPROVED", coverage=["plan read in full", "finding R1: resolved"]), kind="gate",
                      effort="high")
        f.ingest(g2, {})
        f.accept_risk()
        f.tool("gate", "--run", RUN, "--publish")
        copy = Path(f.dispatched(g2)["snapshot"])
        f.tool("receipt", "--run", RUN, "--call", str(g1), "--attempt", "1")
        self.assertIn(f"call {g1} attempt 1: counted", f.last.stdout)
        self.assertTrue(copy.exists())
        f.tool("gate", "--run", RUN)
        f.tool("receipt", "--run", RUN, "--call", str(g2), "--attempt", "1")
        self.assertTrue(copy.exists())
        f.tool("gate", "--run", RUN)

    def test_a_record_that_exists_but_cannot_be_read_records_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for name in ("running.json", "call.json", "receipt.json"):
            if name == "receipt.json":
                f.tool(*receipt)
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
            path = call_dir / name
            path.chmod(0)
            try:
                try:
                    path.read_bytes()
                    self.skipTest("chmod 000 does not stop this user reading a file")
                except PermissionError:
                    pass
                f.tool(*receipt, expect=2)
            finally:
                path.chmod(0o644)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn(f"could not be read ([Errno 13] Permission denied: '{path}'); nothing was recorded from it, "
                          "run the command again once it can be read", f.last.stderr)
            self.assertEqual((call_dir / "receipt.json").exists(), name == "receipt.json")
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        f.ingest(1, {"F1": "new"})
        nonce = f.stage(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        (call_dir / "receipt.json").chmod(0)
        try:
            f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        finally:
            (call_dir / "receipt.json").chmod(0o644)
        self.assertIn(f"WARN  size report unavailable: PermissionError: [Errno 13] Permission denied: "
                      f"'{call_dir / 'receipt.json'}'", f.last.stdout)
        self.assertEqual(f.head(), 2)

    def test_a_lock_holder_proven_alive_is_never_offered_for_removal_by_hand(self):
        f = self.f
        f.init()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
        lock = f.rdir / ".lock"
        lock.mkdir()
        owner = {"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(), "pid_ns": PID_NS, "start": start,
                 "nonce": "e" * 32, "acquired_at": "2026-11-11T00:00:00Z"}
        (lock / "owner.json").write_text(json.dumps(owner))
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertIn(f"; process {os.getpid()} on this host took it and is alive: wait for it to finish, or stop it, "
                      "then run the command again", f.last.stderr)
        self.assertNotIn("by hand", f.last.stderr)
        (lock / "owner.json").write_text(json.dumps({**owner, "start": None}))
        f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
        self.assertIn(f"; if process {os.getpid()} on this host is not a running planloop command, remove {lock} by "
                      "hand", f.last.stderr)
        shutil.rmtree(lock)
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review("REVISE", [finding("F1")])))
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        running = f.rdir / "reviews" / "call-001-a1" / "running.json"
        running.write_text(json.dumps({**owner, "nonce": "d" * 32}))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
        self.assertIn(f"call 1 attempt 1 is still being reviewed by process {os.getpid()}; wait for it (it took the "
                      f"call on this host and is alive), or stop it (`kill {os.getpid()}`, which also stops the review "
                      f"runner it started, killing every process in the review's scope if it is not empty 10 seconds later), "
                      f"then run `receipt --run {RUN} --call 1 --attempt 1` again", f.last.stderr)
        self.assertNotIn("by hand", f.last.stderr)
        running.unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_runner_command_line_of_only_whitespace_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": "  \t "}, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  PLANLOOP_RUNNER holds no command; no call was reserved and Codex did not run",
                      f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def approved(self, f):
        f.to_gate_ready()
        c = f.review(review(), kind="gate", effort="high")
        f.ingest(c, {})
        f.tool("gate", "--run", RUN, "--publish")
        self.assertEqual(f.run_bead()["metadata"]["planloop_state"], "approved")
        return c

    def unreadable(self, f, path, *args, code=2):
        readable_as_000(self, path)
        mode = path.stat().st_mode & 0o777
        path.chmod(0)
        try:
            f.tool(*args, expect=None)
        finally:
            path.chmod(mode)
        self.assertEqual(f.last.returncode, code, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNREADABLE  ", f.last.stderr)
        self.assertIn(f"could not be read ([Errno 13] Permission denied: '", f.last.stderr)
        return f.last

    def test_an_approved_run_whose_records_cannot_be_read_is_never_reopened(self):
        f = self.f
        c = self.approved(f)
        state = ("state", "--run", RUN, "--set", "active", "--reason", "reopen it")
        pointer = json.loads((f.rdir / "APPROVAL").read_text())
        for path in (f.rdir / "reviews", f.rdir / "decisions", f.rdir / "reviews" / f"call-{c:03d}-a1" / "receipt.json",
                     f.rdir / "APPROVAL", f.rdir / "approvals" / pointer["record"]):
            with self.subTest(path=path.name):
                self.unreadable(f, path, *state)
                self.assertIn("nothing was recorded from it, run the command again once it can be read", f.last.stderr)
                self.assertEqual(f.run_bead()["metadata"]["planloop_state"], "approved")
                if path.name in ("reviews", "decisions"):
                    for gate in (("gate", "--run", RUN), ("gate", "--run", RUN, "--publish")):
                        self.unreadable(f, path, *gate)
                        self.assertNotIn("APPROVED", f.last.stdout.splitlines()[-1] if f.last.stdout else "")
        f.tool(*state, expect=1)
        self.assertIn("the run is approved and its approval still verifies", f.last.stderr)
        f.tool("gate", "--run", RUN)

    def test_a_run_directory_or_intents_that_cannot_be_listed_stop_the_command(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args())
        f.ingest(1, {"F1": "new"})
        recover = ("publish", "--run", RUN, "--recover")
        self.unreadable(f, f.rdir / "intents", *recover)
        self.unreadable(f, f.rdir / "intents", "findings", "check", "--run", RUN)
        readable_as_000(self, f.rdir)
        f.rdir.chmod(0o300)
        try:
            f.tool(*recover, expect=None)
        finally:
            f.rdir.chmod(0o755)
        self.assertEqual(f.last.returncode, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNREADABLE  {f.rdir} could not be read ([Errno 13] Permission denied: '{f.rdir}')",
                      f.last.stderr)
        f.tool(*recover)
        f.tool("findings", "check", "--run", RUN, expect=None)
        self.assertNotIn("UNREADABLE", f.last.stderr)

    def test_an_artifact_directory_that_cannot_be_listed_after_the_runner_burns_no_attempt(self):
        f = self.f
        self.ready_to_dispatch(f)
        wrapper = f.root / "unlistable_runner.py"
        wrapper.write_text(UNLISTABLE_RUNNER)
        readable_as_000(self, f.rdir)
        try:
            f.tool(*self.dispatch_args(), expect=None,
                   env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}"})
        finally:
            artifacts = f.artifacts()
            if artifacts.exists():
                artifacts.chmod(0o755)
        self.assertEqual(f.last.returncode, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"UNREADABLE  {artifacts} could not be read ([Errno 13] Permission denied: '{artifacts}'); the "
                      "review runner ran for call 1 attempt 1 (exit 0), but call.json was not written, so its result "
                      "is not recorded; do not dispatch call 1 attempt 1 again: once it can be read, record it with "
                      f"`receipt --run {RUN} --call 1 --attempt 1 --artifacts {artifacts}/<the claudex-* directory in "
                      "it holding a result.json file>`, or without `--artifacts` if no directory there holds a "
                      "result.json file (it is then recorded invalid)", f.last.stderr)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        self.assertFalse((call_dir / "receipt.json").exists())
        self.assertFalse((call_dir / "call.json").exists())
        runner_dir = next(artifacts.glob("claudex-*"))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--artifacts", str(runner_dir))
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        f.ingest(1, {"F1": "new"})

    def test_an_unrelated_record_unreadable_after_the_runner_says_codex_ran_and_how_to_record_it(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"FAKE_MODE": "failed"}, expect=1)
        first = f.rdir / "reviews" / "call-001-a1"
        readable_as_000(self, first / "receipt.json")
        code = self.driver(f, CHMOD_BEFORE_RECEIPT, str(first / "receipt.json"), *self.dispatch_args(2))
        (first / "receipt.json").chmod(0o644)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not be read ([Errno 13] Permission denied: '{first / 'receipt.json'}'); the review "
                      "runner ran for call 1 attempt 2 (exit 0); its call.json is written but its receipt is not: do not "
                      "dispatch call 1 attempt 2 again; once it can be read, record it with `receipt --run "
                      f"{RUN} --call 1 --attempt 2`", f.last.stderr)
        self.assertNotIn("nothing was recorded", f.last.stderr)
        second = f.rdir / "reviews" / "call-001-a2"
        self.assertFalse((second / "receipt.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)
        f.ingest(1, {"F1": "new"}, attempt=2)

    def test_a_record_unreadable_once_the_receipt_is_written_says_the_receipt_stands(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"FAKE_MODE": "failed"}, expect=1)
        first = f.rdir / "reviews" / "call-001-a1"
        second = f.rdir / "reviews" / "call-001-a2"
        readable_as_000(self, first / "receipt.json")
        code = self.driver(f, CHMOD_AT_PRUNE, str(first / "receipt.json"), *self.dispatch_args(2))
        (first / "receipt.json").chmod(0o644)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"could not be read ([Errno 13] Permission denied: '{first / 'receipt.json'}'); call 1 attempt 2 "
                      f"is recorded counted in {second / 'receipt.json'} and stands, but this command stopped before "
                      "printing it and before checking whether that blocks the run; do not dispatch that attempt "
                      "again: once it can be read, run `receipt --run "
                      f"{RUN} --call 1 --attempt 2` again, which prints it and makes that check", f.last.stderr)
        self.assertEqual(f.receipt(1, 2)["status"], "counted")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)
        dispatch = first / "input" / "dispatch.json"
        readable_as_000(self, dispatch)
        dispatch.chmod(0)
        try:
            f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        finally:
            dispatch.chmod(0o644)
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)
        self.assertIn(f"NOTE  {dispatch} could not be read ([Errno 13] Permission denied: '{dispatch}'), so the "
                      "private snapshot copy or artifact directory of call 1 attempt 1 was not checked or removed; the receipt is recorded "
                      "and stands and no review needs that copy: once it can be read, running `receipt --run "
                      f"{RUN} --call 1 --attempt 2` again removes the copy", f.last.stderr)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        self.assertNotIn("NOTE", f.last.stderr)

    def test_a_runner_artifact_or_revision_record_that_cannot_be_read_records_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        adir = Path(json.loads((call_dir / "call.json").read_text())["artifacts"])
        rollout = next(f.sessions.rglob("rollout-*.jsonl"))
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for path in (call_dir / "input" / "feedback.md", adir / "command.json", adir / "stdout.txt",
                     adir / "prompt.txt", f.rdir / "rev-001" / "plan.md",
                     f.rdir / "rev-001" / "bundle" / "manifest.json", rollout, rollout.parent):
            with self.subTest(path=path.name):
                self.unreadable(f, path, *receipt)
                self.assertIn("nothing was recorded from it", f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").exists())
        for path in (f.rdir / "rev-001" / "revision.json", f.rdir / "rev-001" / "handback.json"):
            with self.subTest(path=path.name):
                self.unreadable(f, path, "ledger", "--run", RUN)
                self.assertNotIn("HEAD points at a revision whose record differs", f.last.stderr)
                self.assertNotIn("inspect by hand", f.last.stderr)
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_zombie_owner_is_dead(self):
        f = self.f
        f.init()
        zombie = subprocess.Popen(["true"])
        try:
            stat = Path(f"/proc/{zombie.pid}/stat")
            for _ in range(200):
                if stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                    break
                time.sleep(0.05)
            fields = stat.read_text().rsplit(")", 1)[1].split()
            self.assertEqual(fields[0], "Z")
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            owner = {"host": socket.gethostname(), "boot_id": boot, "pid": zombie.pid, "pid_ns": PID_NS,
                     "start": fields[19], "nonce": "e" * 32, "acquired_at": "2026-11-11T00:00:00Z"}
            lock = f.rdir / ".lock"
            lock.mkdir()
            (lock / "owner.json").write_text(json.dumps(owner))
            f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
            self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
            f.publish(1, plan_text(1))
            f.review_file.write_text(json.dumps(review("REVISE", [finding("F1")])))
            f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
            running = f.rdir / "reviews" / "call-001-a1" / "running.json"
            running.write_text(json.dumps({**owner, "nonce": "d" * 32, "scope": f.dispatched(1)["scope"]}))
            f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
            self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        finally:
            zombie.wait()

    def test_stopping_a_dispatch_stops_the_review_runner_it_started(self):
        f = self.f
        self.ready_to_dispatch(f)
        runner = f.root / "lingering_runner.py"
        runner.write_text(LINGERING_RUNNER)
        pids = f.root / "runner.pids"
        env = {**f.env, "PLANLOOP_RUNNER": f"{sys.executable} {runner}", "RUNNER_PIDS": str(pids)}
        proc = subprocess.Popen([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = []
        try:
            for _ in range(1200):
                if pids.exists() and len(pids.read_text().split()) == 2:
                    break
                time.sleep(0.05)
            started = [int(p) for p in pids.read_text().split()]
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=120)
            for _ in range(200):
                if all(gone(p) for p in started):
                    break
                time.sleep(0.05)
            self.assertTrue(all(gone(p) for p in started), f"runner processes {started} outlived the dispatch")
            self.assertEqual(proc.returncode, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
            self.assertIn("FAIL  runner left no artifact directory", out)
        finally:
            for p in started:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(p, signal.SIGKILL)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_an_owner_pid_planloop_cannot_check_names_the_way_out(self):
        f = self.f
        f.init()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        lock = f.rdir / ".lock"
        lock.mkdir()
        owner = {"host": socket.gethostname(), "boot_id": boot, "pid_ns": PID_NS, "start": "1", "nonce": "e" * 32,
                 "acquired_at": "2026-11-11T00:00:00Z"}
        for pid in (2 ** 40, True, 0, -1, "12"):
            with self.subTest(pid=pid):
                (lock / "owner.json").write_text(json.dumps({**owner, "pid": pid}))
                f.tool("publish", "--run", RUN, "--recover", env={"PLANLOOP_LOCK_TIMEOUT": "0.5"}, expect=3)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"; if the process its record names ({pid!r}, which cannot be checked) on this host is "
                              f"not a running planloop command, remove {lock} by hand", f.last.stderr)
                self.assertNotIn("process True", f.last.stderr)
                self.assertTrue(lock.exists())
        shutil.rmtree(lock)
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review("REVISE", [finding("F1")])))
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        running = f.rdir / "reviews" / "call-001-a1" / "running.json"
        for pid in (2 ** 40, True):
            with self.subTest(running=pid):
                running.write_text(json.dumps({**owner, "pid": pid, "nonce": "d" * 32}))
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=3)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"call 1 attempt 1 is still being reviewed by the process its record names ({pid!r}, "
                              f"which cannot be checked); wait for it; if the process its record names ({pid!r}, "
                              f"which cannot be checked) on this host is not a planloop dispatch, remove "
                              f"{running} by hand and run `receipt --run {RUN} --call 1 --attempt 1` again: that "
                              "gives up only the wait for the dispatching process", f.last.stderr)
        running.unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_later_invalid_gate_reports_its_own_reasons_and_keeps_the_counted_gate_copy(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        g1 = f.review(review(), kind="gate", effort="high")
        f.ingest(g1, {})
        g2 = f.review(review(), kind="gate", effort="high", mode="rollout_effort=medium", expect=1)
        self.assertEqual(f.receipt(g2)["status"], "invalid")
        self.assertTrue(Path(f.dispatched(g1)["snapshot"]).exists())
        self.assertFalse(Path(f.dispatched(g2)["snapshot"]).parent.exists())
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("PASS  [mechanical] gate receipt re-derived from runner and Codex records matches the stored "
                      "receipt", f.last.stdout)
        self.assertIn("FAIL  [mechanical] gate call verified: effective effort medium differs from requested high "
                      "(downgrade)", f.last.stdout)
        self.assertNotIn("frozen snapshot changed during the review", f.last.stdout)
        self.assertEqual(f.receipt(g2)["reasons"], ["effective effort medium differs from requested high (downgrade)"])

    def runner_env(self, f, text, *args):
        runner = f.root / f"runner-{uuid.uuid4().hex[:6]}.py"
        runner.write_text(text)
        pids = f.root / f"pids-{uuid.uuid4().hex[:6]}"
        return {"PLANLOOP_RUNNER": shlex.join([sys.executable, str(runner), *args]), "RUNNER_PIDS": str(pids)}, pids

    def started(self, pids, count):
        for _ in range(1200):
            if pids.exists() and len(pids.read_text().split()) == count:
                return [int(p) for p in pids.read_text().split()]
            time.sleep(0.05)
        self.fail("the runner never recorded its pids")

    def unit(self, f):
        return Path(f.dispatched(1)["scope"]).name

    def emptied(self, f, wait=10):
        for _ in range(int(wait / 0.05)):
            try:
                if "populated 0" in (Path(f.dispatched(1)["scope"]) / "cgroup.events").read_text():
                    return True
            except OSError:
                return True
            time.sleep(0.05)
        return False

    def systemctl(self, f, sig):
        subprocess.run(["systemctl", "--user", "kill", f"--signal={sig}", self.unit(f)], check=True,
                       capture_output=True)

    def stop_all(self, pids):
        for p in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(p, signal.SIGKILL)
            with contextlib.suppress(ProcessLookupError):
                os.kill(p, signal.SIGKILL)

    def test_artifacts_named_by_hand_are_bound_so_every_later_verification_agrees(self):
        f = self.f
        f.to_gate_ready()
        f.review_file.write_text(json.dumps(review()))
        f.call = c = f.call + 1
        wrapper = f.root / "unlistable_runner.py"
        wrapper.write_text(UNLISTABLE_RUNNER)
        call_dir = f.rdir / "reviews" / f"call-{c:03d}-a1"
        readable_as_000(self, f.rdir)
        try:
            f.tool("dispatch", "--run", RUN, "--call", str(c), "--attempt", "1", "--kind", "gate", "--effort", "high",
                   env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}"}, expect=2)
        finally:
            artifacts = f.artifacts(c)
            if artifacts.exists():
                artifacts.chmod(0o755)
        self.assertFalse((call_dir / "call.json").exists())
        runner_dir = next(artifacts.glob("claudex-*"))
        receipt = ("receipt", "--run", RUN, "--call", str(c), "--attempt", "1")
        f.tool(*receipt, "--artifacts", str(runner_dir))
        self.assertIn(f"call {c} attempt 1: counted", f.last.stdout)
        self.assertEqual(json.loads((call_dir / "call.json").read_text()),
                         {"schema": "planloop-call/1", "runner_exit": None, "artifacts": str(runner_dir),
                          "runner_stdout_sha256": None})
        f.tool(*receipt)
        self.assertIn(f"call {c} attempt 1: counted", f.last.stdout)
        f.ingest(c, {})
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PLAN APPROVED: revision 2", f.last.stdout)
        f.tool("gate", "--run", RUN)
        g = Fixture(self)
        self.ready_to_dispatch(g)
        try:
            g.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}"},
                   expect=2)
        finally:
            artifacts = g.artifacts()
            if artifacts.exists():
                artifacts.chmod(0o755)
        elsewhere = g.root / "claudex-elsewhere"
        shutil.copytree(next(artifacts.glob("claudex-*")), elsewhere)
        g.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--artifacts", str(elsewhere), expect=1)
        self.assertIn(f"FAIL  --artifacts {elsewhere} is not the one runner directory dispatch would have recorded",
                      g.last.stderr)
        self.assertFalse((g.rdir / "reviews" / "call-001-a1" / "call.json").exists())
        self.assertFalse((g.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())

    def test_a_directory_that_cannot_be_searched_while_hashing_records_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        src = Path(f.dispatched(1)["snapshot"]) / "src"
        readable_as_000(self, f.rdir)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for target, args in ((src, receipt),
                             (next(p for p in (f.rdir / "rev-001" / "bundle" / "overlay").rglob("*")
                                   if p.is_file()).parent, ("ledger", "--run", RUN))):
            with self.subTest(target=target):
                mode = target.stat().st_mode & 0o777
                target.chmod(0o444)
                try:
                    f.tool(*args, expect=None)
                finally:
                    target.chmod(mode)
                self.assertEqual(f.last.returncode, 2, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"UNREADABLE  {target}/", f.last.stderr)
                self.assertIn("could not be read ([Errno 13] Permission denied", f.last.stderr)
                self.assertNotIn("inspect by hand", f.last.stderr)
                self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_record_or_runner_artifact_that_is_a_directory_never_tracebacks(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        feedback = call_dir / "input" / "feedback.md"
        data = feedback.read_bytes()
        feedback.unlink()
        feedback.mkdir()
        f.tool(*receipt, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  feedback.md: missing or not a file", f.last.stderr)
        self.assertFalse((call_dir / "receipt.json").exists())
        feedback.rmdir()
        feedback.write_bytes(data)
        (call_dir / "call.json").unlink()
        (call_dir / "call.json").mkdir()
        f.tool(*receipt, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  call.json does not read (not a file), so the runner's result is not recorded", f.last.stdout)
        self.assertTrue(f.receipt(1)["infrastructure"])
        for name in ("stdout.txt", "rollout.jsonl"):
            with self.subTest(name=name):
                g = Fixture(self)
                self.ready_to_dispatch(g)
                g.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
                adir = Path(json.loads((g.rdir / "reviews" / "call-001-a1" / "call.json").read_text())["artifacts"])
                if (adir / name).exists():
                    (adir / name).unlink()
                (adir / name).mkdir()
                g.tool(*receipt, expect=1)
                self.assertNotIn("Traceback", g.last.stderr)
                self.assertIn(f"FAIL  runner artifact {name}", g.last.stdout)
                self.assertIn("is not a file", g.last.stdout)
                self.assertEqual(g.receipt(1)["status"], "invalid")
                self.assertTrue(g.receipt(1)["infrastructure"])
                g.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", g.last.stdout)

    def test_a_signal_while_the_runner_starts_still_stops_the_runner_and_records_the_attempt(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        pgid_file = f.root / "pgid"
        pgid = None
        try:
            code = self.driver(f, SIGNAL_IN_POPEN, str(pgid_file), *self.dispatch_args(), env=env)
            pgid = int(pgid_file.read_text())
            self.assertTrue(group_gone(pgid), f"runner group {pgid} outlived the dispatch")
            self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
            self.assertIn("NOTE  this dispatch was interrupted by SIGTERM before it let the review runner start, so "
                          "the runner never started and Codex did not run\n", f.last.stderr)
            self.assertEqual(f.receipt(1)["status"], "invalid")
        finally:
            if pgid:
                self.stop_all([pgid])
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_stopping_a_dispatch_says_it_was_interrupted(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        proc = subprocess.Popen([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo, env={**f.env, **env},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = []
        try:
            started = self.started(pids, 2)
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=60)
            self.assertTrue(group_gone(started[0]))
            self.assertEqual(proc.returncode, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
            self.assertIn("NOTE  this dispatch was interrupted by SIGINT: it asked the review runner to stop with SIGINT "
                          "(the signal on which the runner stops Codex)\n", err)
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, which kills "
                          "every process in it), after the review runner had exited\n", err)
            self.assertNotIn("Traceback", err)
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_a_runner_that_leaves_a_process_holding_its_output_is_not_waited_for(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, ESCAPING_RUNNER, str(HERE / "fake_runner.py"))
        started = []
        try:
            begun = time.monotonic()
            f.tool(*self.dispatch_args(), env=env)
            self.assertLess(time.monotonic() - begun, 30)
            self.assertIn("call 1 attempt 1: counted", f.last.stdout)
            started = self.started(pids, 2)
            g = Fixture(self)
            self.ready_to_dispatch(g)
            env, pids = self.runner_env(g, ESCAPING_RUNNER, str(HERE / "fake_runner.py"))
            path = g.root / "driver-wait.py"
            path.write_text(SHORT_RUNNER_WAIT)
            begun = time.monotonic()
            try:
                proc = subprocess.run([sys.executable, str(path), str(TOOL), "2", *self.dispatch_args()], cwd=g.repo,
                                      capture_output=True, text=True, env={**g.env, **env, "STALL": "1"}, timeout=45)
            except subprocess.TimeoutExpired:
                self.fail("a dispatch whose runner timed out still waited for the process holding its output")
            finally:
                started += self.started(pids, 2)
            self.assertLess(time.monotonic() - begun, 30)
            self.assertIn("call 1 attempt 1: invalid", proc.stdout, proc.stdout + proc.stderr)
            self.assertTrue(group_gone(started[2]))
        finally:
            self.stop_all(started)

    def test_a_runner_that_ignores_the_forwarded_signal_is_killed(self):
        for signals in (2, 1):
            with self.subTest(signals=signals):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, IGNORING_RUNNER)
                proc = subprocess.Popen([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo,
                                        env={**f.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                started = []
                try:
                    started = self.started(pids, 1)
                    proc.send_signal(signal.SIGTERM)
                    if signals == 2:
                        time.sleep(1)
                        proc.send_signal(signal.SIGTERM)
                    begun = time.monotonic()
                    try:
                        out, err = proc.communicate(timeout=40)
                    except subprocess.TimeoutExpired:
                        self.fail("dispatch kept waiting for a runner that ignores the forwarded signal")
                    self.assertLess(time.monotonic() - begun, 8 if signals == 2 else 30)
                    self.assertTrue(group_gone(started[0]))
                    self.assertEqual(proc.returncode, 1, out + err)
                    self.assertIn("NOTE  this dispatch was interrupted by SIGTERM: it asked the review runner to "
                                  "stop with SIGINT (the signal on which the runner stops Codex)\n", err)
                    self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, which "
                                  "kills every process in it), the review runner included unless something else had "
                                  "killed it\n", err)
                    self.assertIn("call 1 attempt 1: invalid", out)
                finally:
                    self.stop_all(started)
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()

    def test_a_runner_left_running_by_a_killed_dispatch_is_never_recorded_while_it_runs(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        proc = subprocess.Popen([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo, env={**f.env, **env},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = []
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        running = f.rdir / "reviews" / "call-001-a1" / "running.json"
        try:
            started = self.started(pids, 2)
            self.assertNotIn("runner", json.loads(running.read_text()))
            proc.kill()
            proc.communicate()
            f.tool(*receipt, expect=3)
            unit = self.unit(f)
            self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its "
                          "review, and 2 processes still run in it (", f.last.stderr)
            self.assertIn(f"{started[0]} is `{sys.executable} ", f.last.stderr)
            self.assertIn(f"{started[1]} is `sleep 300`", f.last.stderr)
            self.assertIn(f"); nothing was recorded: wait for it to end, or stop it (`systemctl --user kill --signal=INT "
                          f"{unit}`, then `systemctl --user kill --signal=KILL {unit}` if that is ignored; "
                          f"`systemd-cgls --user-unit {unit}` shows it), then run `receipt --run {RUN} --call 1 "
                          "--attempt 1` again\n", f.last.stderr)
            self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
            self.systemctl(f, "INT")
            self.assertTrue(group_gone(started[0]))
            self.assertTrue(self.emptied(f))
        finally:
            self.stop_all(started)
        f.tool(*receipt, expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertFalse(running.exists())
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_record_that_cannot_be_written_publishes_and_records_nothing(self):
        f = self.f
        f.to_gate_ready()
        c = f.review(review(), kind="gate", effort="high")
        f.ingest(c, {})
        approvals = f.rdir / "approvals"
        approvals.mkdir()
        approvals.chmod(0o555)
        try:
            with self.assertRaises(PermissionError):
                (approvals / "probe").write_text("x")
        except AssertionError:
            approvals.chmod(0o755)
            self.skipTest("a read-only directory does not stop this user writing")
        try:
            f.tool("gate", "--run", RUN, "--publish", expect=2)
        finally:
            approvals.chmod(0o755)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not write {approvals}/approval-r002-", f.last.stderr)
        self.assertIn("this approval was not published: no approval record was written, APPROVAL is unchanged and "
                      f"Beads records no approval candidate for it; once {approvals} can be written, run `gate --run "
                      f"{RUN} --publish` again", f.last.stderr)
        self.assertEqual(os.listdir(approvals), [])
        self.assertFalse((f.rdir / "APPROVAL").exists())
        self.assertEqual(f.run_bead()["metadata"].get("planloop_approval_candidate", ""), "")
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PLAN APPROVED: revision 2", f.last.stdout)
        g = Fixture(self)
        self.ready_to_dispatch(g)
        g.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = g.rdir / "reviews" / "call-001-a1"
        call_dir.chmod(0o555)
        try:
            g.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=2)
        finally:
            call_dir.chmod(0o755)
        self.assertNotIn("Traceback", g.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not write {call_dir / 'receipt.json'} ([Errno 13] Permission denied: "
                      f"'{call_dir / 'receipt.json'}'), so call 1 attempt 1 is not recorded; do not dispatch that "
                      f"attempt again: run `receipt --run {RUN} --call 1 --attempt 1` again once it can be written",
                      g.last.stderr)
        g.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", g.last.stdout)

    def test_a_declared_live_file_that_cannot_be_read_while_revalidating_records_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.unreadable(f, f.repo / "src" / "a.rs", *receipt)
        self.assertIn(f"UNREADABLE  {f.repo / 'src' / 'a.rs'} could not be read", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        self.unreadable(f, f.versions, *receipt)
        self.assertIn(f"UNREADABLE  {f.versions} could not be read", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        readable_as_000(self, f.sessions)
        f.sessions.chmod(0)
        try:
            f.tool(*receipt)
        finally:
            f.sessions.chmod(0o755)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_decisions_that_cannot_be_listed_for_risk_acceptance_stop_the_gate(self):
        f = self.f
        self.approved(f)
        code = self.driver(f, DECISIONS_DENIED_AFTER_RECONCILE, "x", "gate", "--run", RUN)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNREADABLE  {f.rdir / 'decisions'} could not be read", f.last.stderr)
        self.assertNotIn("PLAN APPROVED", f.last.stdout)
        f.tool("gate", "--run", RUN)

    def test_stopping_a_dispatch_with_any_signal_lets_the_runner_stop_codex(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, CODEX_LIKE_RUNNER)
                proc = subprocess.Popen([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo,
                                        env={**f.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                started = []
                try:
                    started = self.started(pids, 2)
                    proc.send_signal(sig)
                    out, err = proc.communicate(timeout=60)
                    for _ in range(100):
                        if all(gone(p) for p in started):
                            break
                        time.sleep(0.05)
                    self.assertTrue(gone(started[1]), f"the runner's Codex stand-in {started[1]} outlived the dispatch")
                    self.assertTrue(gone(started[0]))
                    self.assertEqual(proc.returncode, 1, out + err)
                    self.assertIn("call 1 attempt 1: invalid", out)
                    self.assertIn(f"NOTE  this dispatch was interrupted by {sig.name}: it asked the review runner to "
                                  "stop with SIGINT (the signal on which the runner stops Codex)\n", err)
                    self.assertNotIn("cgroup.kill", err)
                    self.assertNotIn("Traceback", err)
                finally:
                    self.stop_all(started)
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()

    def test_a_runner_group_member_left_behind_is_stopped_before_the_attempt_is_recorded(self):
        for hold in ("", "1"):
            with self.subTest(holds_output=bool(hold)):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, STRAGGLING_RUNNER, str(HERE / "fake_runner.py"))
                started = []
                try:
                    f.tool(*self.dispatch_args(), env={**env, "HOLD": hold}, expect=None)
                    started = self.started(pids, 2)
                    self.assertTrue(gone(started[1]), "a process of the runner's group outlived the dispatch that "
                                    "recorded the attempt")
                    self.assertEqual(f.last.returncode, 0, f.last.stdout + f.last.stderr)
                    self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                    self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
                    f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                    self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                finally:
                    self.stop_all(started)

    def test_the_scope_of_a_review_is_read_from_dispatch_json_whatever_running_json_records(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("older_running", "junk", "elsewhere", "another_call", "scope_edited", "view_edited", "legacy",
                     "unreleased", "another_user"):
            with self.subTest(case=case):
                f = Fixture(self)
                started = self.orphaned_codex(f)
                codex = started[1]
                call_dir, unit = f.rdir / "reviews" / "call-001-a1", self.unit(f)
                running, path = call_dir / "running.json", call_dir / "input" / "dispatch.json"
                record, written = json.loads(running.read_text()), path.read_text()
                scope = record.pop("scope")
                path.chmod(0o644)
                if case == "older_running":
                    del record["view"]
                    record.update({"runner": {"pid": started[0], "start": "1"}, "escaped": [{"pid": codex}]})
                elif case == "junk":
                    record.update(scope=7, view=7)
                elif case == "elsewhere":
                    record["scope"] = "/sys/fs/cgroup/nowhere/planloop-x.scope"
                elif case == "another_call":
                    record["scope"] = scope.replace("call-001-a1", "call-009-a1")
                elif case == "scope_edited":
                    record["scope"] = scope.replace("call-001-a1", "call-009-a1")
                    path.write_text(json.dumps({**json.loads(written), "scope": record["scope"]}))
                elif case == "view_edited":
                    record["scope"] = scope
                    path.write_text(json.dumps({**json.loads(written), "view": {"host": socket.gethostname()}}))
                elif case == "unreleased":
                    del record["view"]
                    path.write_text(json.dumps({k: v for k, v in json.loads(written).items() if k != "view"}))
                elif case == "another_user":
                    record["scope"] = scope.replace(f"user-{os.getuid()}.slice", "user-0.slice")
                    path.write_text(json.dumps({**json.loads(written), "scope": record["scope"]}))
                else:
                    del record["view"]
                    path.write_text(json.dumps({k: v for k, v in json.loads(written).items()
                                                if k not in ("scope", "view")}))
                running.write_text(json.dumps(record))
                populated = (f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its "
                             f"review, and 1 process still runs in it ({codex} is `")
                again = f"run `receipt --run {RUN} --call 1 --attempt 1` again"
                refused = {"another_user": "dispatch.json.scope: not the scope of this run and artifacts_root for this "
                           "user", "view_edited": "dispatch.json.view: missing machine_id, boot_id, cgroup_ns, "
                           "cgroup_dev"}.get(case)
                other = unit.replace("call-001-a1", "call-009-a1")
                unreleased = {"unreleased": f"{unit} without how its dispatch saw cgroups", "scope_edited":
                              f"{other} under a name this planloop does not give the scope of this run and "
                              "artifacts_root"}.get(case)
                f.tool(*receipt, expect=3)
                self.assertNotIn("Traceback", f.last.stderr)
                if case == "legacy":
                    self.assertIn("CONFLICT  call 1 attempt 1 cannot be recorded yet: its dispatch.json records no "
                                  "systemd scope (a planloop older than the scope dispatched it), so whether a process "
                                  "still runs for it cannot be checked here; nothing was recorded: check by hand that "
                                  "the review runner and the Codex it started are gone (`ps -eo pid,lstart,args`), and "
                                  f"only then remove {running} and {again}\n", f.last.stderr)
                elif unreleased:
                    self.assertIn("CONFLICT  call 1 attempt 1 cannot be recorded yet: its dispatch.json records the "
                                  f"systemd scope {unreleased}: an unreleased planloop build (rounds 21 and 22 of "
                                  "quartz-rs-72m, which never left its scratch clones) wrote that record, or it was "
                                  "edited, and this planloop cannot check that scope; nothing was recorded: check by "
                                  "hand that nothing runs in that scope (`systemd-cgls --user-unit "
                                  f"{other if case == 'scope_edited' else unit}` lists no process, or says the unit is "
                                  f"not found), then remove {call_dir} (what it records of the attempt is discarded) "
                                  "and dispatch call 1 attempt 1 again\n", f.last.stderr)
                    self.assertNotIn("dispatch.json was edited, or another user", f.last.stderr)
                    running.unlink()
                    f.tool(*receipt, expect=3)
                    self.assertIn("an unreleased planloop build", f.last.stderr)
                    path.write_text(written)
                    f.tool(*receipt, expect=3)
                    self.assertIn(populated, f.last.stderr)
                elif refused:
                    self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {refused}, so whether a process "
                                  "still runs in its review's scope cannot be checked; nothing was recorded: "
                                  "dispatch.json was edited, or another user runs this command: restore it as dispatch "
                                  f"wrote it, or {again} as the user who dispatched it\n", f.last.stderr)
                    running.unlink()
                    f.tool(*receipt, expect=3)
                    self.assertIn(f"cannot be recorded yet: {refused}, ", f.last.stderr)
                    path.write_text(written)
                    f.tool(*receipt, expect=3)
                    self.assertIn(populated, f.last.stderr)
                else:
                    self.assertIn(populated, f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").exists())
                self.assertFalse(gone(codex))
                f.tool(*self.dispatch_args(2), expect=1)
                self.assertIn("FAIL  retry out of order or an earlier attempt has no receipt", f.last.stderr)
                os.kill(codex, signal.SIGINT)
                self.assertTrue(self.wait_gone(codex))
                if case == "legacy":
                    f.tool(*receipt, expect=3)
                    running.unlink()
                else:
                    self.assertTrue(self.emptied(f))
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertFalse(running.exists())
                if case in ("older_running", "junk", "elsewhere", "another_call"):
                    f.tool(*self.dispatch_args(2))
                    self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_runner_whose_start_fails_in_the_child_is_recorded_invalid_and_restores_signals(self):
        f = self.f
        self.ready_to_dispatch(f)
        state = f.root / "settled.json"
        code = self.driver(f, PREEXEC_FAILS, str(state), *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertIn(f"NOTE  the review runner could not be started in its scope {self.unit(f)} (Exception occurred "
                      "in preexec_fn.); Codex did not run", f.last.stderr)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertEqual(json.loads(state.read_text()), {"mask": [], "handlers": [True, True, True]})
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_an_unexpected_error_while_the_runner_runs_stops_it_and_ends_cleanly(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        state = f.root / "settled.json"
        started = []
        try:
            code = self.driver(f, RUNNER_WAIT_RAISES, str(state), *self.dispatch_args(), env=env)
            started = self.started(pids, 2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertTrue(group_gone(started[0], wait=1), f"runner group {started[0]} outlived the dispatch")
            self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
            self.assertIn("UNVERIFIABLE  dispatch stopped on an unexpected error while the review runner ran "
                          "(RuntimeError: injected)", f.last.stderr)
            self.assertIn(f"record it with `receipt --run {RUN} --call 1 --attempt 1`", f.last.stderr)
            self.assertEqual(json.loads(state.read_text()), {"mask": [], "handlers": [True, True, True]})
        finally:
            self.stop_all(started)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_an_intent_that_cannot_be_written_stops_the_command_cleanly(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args())
        mapping = f.root / "map.json"
        mapping.write_text(json.dumps({"F1": "new"}))
        ingest = ("findings", "ingest", "--run", RUN, "--call", "1", "--attempt", "1", "--map", str(mapping))
        code = self.driver(f, INTENT_FSYNC_FAILS, "x", *ingest)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not write intent ingest-call-001-a1 ([Errno 5] Input/output error); no "
                      "Beads change was made from it", f.last.stderr)
        self.assertFalse(list((f.rdir / "intents").glob("ingest-call-001-a1*")))
        self.assertFalse(list((f.rdir / "intents").glob(".ingest-call-001-a1*")))
        f.tool(*ingest)
        self.assertIn("applied ingest-call-001-a1.json", f.last.stdout)

    def test_a_call_record_that_is_a_directory_stops_receipt_cleanly(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for name in ("input/dispatch.json", "running.json", "receipt.json"):
            with self.subTest(name=name):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                if name == "receipt.json":
                    f.tool(*receipt)
                path = call_dir / name
                data = path.read_bytes()
                path.unlink()
                path.mkdir()
                f.tool(*receipt, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertNotIn("UNREADABLE", f.last.stderr)
                self.assertNotIn("run the command again once it can be read", f.last.stderr)
                self.assertIn(f"FAIL  ", f.last.stderr)
                self.assertIn(": not a file (repair it by hand; reading it again cannot help)", f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").is_file())
                path.rmdir()
                path.write_bytes(data)
                f.tool(*receipt)
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_fifo_in_place_of_an_overlay_copy_never_blocks_a_command(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        overlay = f.rdir / "rev-001" / "bundle" / "overlay"
        copy = next(p for p in sorted(overlay.rglob("*")) if p.is_file())
        rel = copy.relative_to(overlay).as_posix()
        data = copy.read_bytes()
        copy.unlink()
        os.mkfifo(copy)
        try:
            proc = subprocess.run([sys.executable, str(TOOL), "ledger", "--run", RUN], cwd=f.repo, env=f.env,
                                  capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.fail("a FIFO in place of an overlay copy blocked the command")
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"revision 1 overlay copy of {rel}: missing or not a file", proc.stdout + proc.stderr)
        copy.unlink()
        copy.write_bytes(data)
        f.tool("ledger", "--run", RUN)

    def test_a_special_file_in_a_snapshot_names_what_to_do_about_it(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        src = Path(f.dispatched(1)["snapshot"]) / "src"
        mode = src.stat().st_mode & 0o777
        src.chmod(0o755)
        os.mkfifo(src / "pipe")
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f.tool(*receipt, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"UNREADABLE  {src / 'pipe'} could not be read ([Errno 22] not a regular file or symbolic link "
                      "when hashed); nothing was recorded from it: a FIFO, socket or device never reads as a file, so "
                      "running the command again cannot help: remove it, or find what put it there, then run the "
                      "command again", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        (src / "pipe").unlink()
        src.chmod(mode)
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_directory_symlink_added_to_a_snapshot_changes_its_hash(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        src = Path(f.dispatched(1)["snapshot"]) / "src"
        src.chmod(0o755)
        (src / "elsewhere").symlink_to(f.repo / "docs", target_is_directory=True)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("FAIL  frozen snapshot changed during the review", f.last.stdout)

    def bound_by_hand(self, f):
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        adir = Path(json.loads((call_dir / "call.json").read_text())["artifacts"])
        (call_dir / "call.json").unlink()
        return call_dir, adir

    def test_receipt_artifacts_binds_only_the_one_runner_directory_dispatch_would_have_bound(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("second", "named", "result_dir", "relative"):
            with self.subTest(case=case):
                f = Fixture(self)
                call_dir, adir = self.bound_by_hand(f)
                named = adir
                if case == "second":
                    shutil.copytree(adir, adir.with_name("claudex-second"))
                elif case == "named":
                    named = adir.with_name("runner-x")
                    adir.rename(named)
                elif case == "result_dir":
                    result = adir / "result.json"
                    result.unlink()
                    result.mkdir()
                else:
                    named = Path(adir.name)
                f.tool(*receipt, "--artifacts", str(named), expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"FAIL  --artifacts {named} is not the one runner directory dispatch would have "
                              "recorded", f.last.stderr)
                self.assertIn("nothing was recorded", f.last.stderr)
                self.assertFalse((call_dir / "call.json").exists())
                self.assertFalse((call_dir / "receipt.json").exists())
        f = Fixture(self)
        call_dir, adir = self.bound_by_hand(f)
        f.tool(*receipt, expect=1)
        self.assertIn("call.json is missing", f.last.stdout)
        f.tool(*receipt, "--artifacts", str(adir), expect=3)
        self.assertFalse((call_dir / "call.json").exists())

    def test_a_mistyped_artifacts_path_burns_no_attempt(self):
        f = self.f
        call_dir, adir = self.bound_by_hand(f)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f.tool(*receipt, "--artifacts", str(adir) + "-typo", expect=1)
        self.assertFalse((call_dir / "receipt.json").exists())
        self.assertFalse((call_dir / "call.json").exists())
        f.tool(*receipt, "--artifacts", str(adir))
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertEqual(json.loads((call_dir / "call.json").read_text())["artifacts"], str(adir))


    def launch(self, f, env, *args, preexec=None, driver=None, arg="x"):
        cmd = [sys.executable, str(TOOL)] if driver is None else [sys.executable, str(self.write_driver(f, driver)),
                                                                  str(TOOL), arg]
        return subprocess.Popen(cmd + list(args or self.dispatch_args()), cwd=f.repo, env={**f.env, **env},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preexec)

    def write_driver(self, f, text):
        path = f.root / f"driver-{uuid.uuid4().hex[:6]}.py"
        path.write_text(text)
        return path

    def finish(self, proc, timeout=90):
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            self.fail("dispatch did not finish")
        lines = out.strip().splitlines()
        return proc.returncode or (json.loads(lines[-1])["code"] if lines and lines[-1].startswith('{"code"')
                                   else 0), out, err

    def wait_gone(self, pid, wait=10):
        for _ in range(int(wait / 0.05)):
            if gone(pid):
                return True
            time.sleep(0.05)
        return False

    def wait_for(self, path, wait=60):
        for _ in range(int(wait / 0.05)):
            if path.exists() and path.read_text():
                return
            time.sleep(0.05)
        self.fail(f"{path} was never written")

    def orphaned_runner(self, f):
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        proc = self.launch(f, env)
        started = self.started(pids, 2)
        self.addCleanup(self.stop_all, started)
        proc.kill()
        proc.communicate()
        return started, proc.pid

    def codex_env(self, f, code):
        env, pids = self.runner_env(f, RUNNER_LIKE)
        return {**env, "CODEX": code, "READY": str(f.root / "ready"), "GRANDCHILD": str(f.root / "grandchild")}, pids

    def orphaned_codex(self, f):
        self.ready_to_dispatch(f)
        env, pids = self.codex_env(f, CODEX_PLAIN)
        proc = self.launch(f, env)
        started = self.started(pids, 2)
        self.addCleanup(self.stop_all, started)
        self.wait_for(f.root / "ready")
        proc.kill()
        proc.communicate()
        os.kill(started[0], signal.SIGKILL)
        self.assertTrue(group_gone(started[0]))
        self.assertFalse(gone(started[1]))
        return started

    def test_a_runner_left_by_a_killed_dispatch_is_never_recorded_while_its_scope_holds_it_or_cannot_be_read(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("unreadable", "state", "stands"):
            with self.subTest(case=case):
                f = Fixture(self)
                started, dispatcher = self.orphaned_runner(f)
                call_dir, unit = f.rdir / "reviews" / "call-001-a1", self.unit(f)
                if case == "unreadable":
                    code = self.driver(f, SCOPE_UNREADABLE, "x", *receipt)
                else:
                    if case == "stands":
                        (call_dir / "receipt.json").write_text("{}\n")
                    code = f.tool(*receipt, env={"PLANLOOP_STATE": str(f.root / "elsewhere")} if case == "state"
                                  else None, expect=None).returncode
                self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                if case == "unreadable":
                    self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of "
                                  "its review, and whether a process still runs in it cannot be checked ([Errno 13] "
                                  f"Permission denied: '{f.dispatched(1)['scope']}/cgroup.events'); nothing was "
                                  "recorded: wait for it to end, or stop it (`systemctl --user kill --signal=INT "
                                  f"{unit}`, ", f.last.stderr)
                else:
                    self.assertIn(f"{unit} is the systemd scope of its review, and 2 processes still run in it (",
                                  f.last.stderr)
                if case == "stands":
                    self.assertIn("its receipt.json is written and stands, and is printed once nothing runs",
                                  f.last.stderr)
                    (call_dir / "receipt.json").unlink()
                self.assertFalse((call_dir / "receipt.json").exists())
                os.killpg(started[0], signal.SIGINT)
                self.assertTrue(group_gone(started[0]))
                self.assertTrue(self.emptied(f))
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_a_scope_that_cannot_be_read_after_the_runner_keeps_the_finished_review_for_receipt(self):
        f = self.f
        self.ready_to_dispatch(f)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, SCOPE_UNREADABLE, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        unit = self.unit(f)
        self.assertIn(f"CONFLICT  the review runner ran for call 1 attempt 1 (exit 0), but its systemd scope {unit} was "
                      "killed and whether a process still runs in it cannot be checked ([Errno 13] Permission denied: "
                      f"'{f.dispatched(1)['scope']}/cgroup.events'); call.json is written and nothing else was "
                      "recorded: do not dispatch call 1 attempt 1 again; wait for it to end, or stop it (`systemctl "
                      f"--user kill --signal=INT {unit}`, then `systemctl --user kill --signal=KILL {unit}` if that is "
                      f"ignored; `systemd-cgls --user-unit {unit}` shows it), then run `receipt --run {RUN} --call 1 "
                      "--attempt 1`, which records the attempt\n", f.last.stderr)
        self.assertTrue((call_dir / "running.json").exists())
        self.assertTrue((call_dir / "call.json").exists())
        self.assertFalse((call_dir / "receipt.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertFalse((call_dir / "running.json").exists())

    def test_a_non_file_at_a_publication_record_never_moves_a_valid_revision_aside(self):
        for case in ("socket", "directory", "plan_directory", "dangling", "plan_dangling"):
            with self.subTest(case=case):
                f = Fixture(self)
                f.init()
                f.publish(1, plan_text(1))
                nonce = f.stage(2, plan_text(2))
                f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce,
                       env={"PLANLOOP_CRASH_AT": "after_rename"}, expect=99)
                intent = f.rdir / ".publishing-rev-002"
                target = f.rdir / "rev-002" / "plan.md" if case.startswith("plan") else intent
                data = target.read_bytes()
                target.unlink()
                sock = None
                if case == "socket":
                    sock = socket.socket(socket.AF_UNIX)
                    sock.bind(str(target))
                elif case.endswith("dangling"):
                    target.symlink_to(f.root / "nowhere")
                else:
                    target.mkdir()
                try:
                    f.tool("publish", "--run", RUN, "--recover", expect=1)
                finally:
                    if sock:
                        sock.close()
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"FAIL  {target} is not a regular file", f.last.stderr)
                self.assertIn("nothing was moved aside or discarded: repair it by hand", f.last.stderr)
                self.assertTrue((f.rdir / "rev-002").is_dir())
                self.assertFalse(list(f.rdir.glob(".orphan-rev-002-*")))
                self.assertTrue(os.path.lexists(intent))
                self.assertEqual(f.head(), 1)
                target.rmdir() if case.endswith("directory") else target.unlink()
                target.write_bytes(data)
                f.tool("publish", "--run", RUN, "--recover")
                self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
                self.assertEqual(f.head(), 2)

    def test_a_dispatch_started_with_sigint_ignored_still_lets_the_runner_stop_codex(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, CODEX_LIKE_RUNNER)
        proc = self.launch(f, env, preexec=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))
        started = []
        try:
            started = self.started(pids, 2)
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertTrue(self.wait_gone(started[1]), f"the runner's Codex stand-in {started[1]} outlived the dispatch")
            self.assertEqual(code, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
            self.assertNotIn("cgroup.kill", err)
            self.assertNotIn("Traceback", err)
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_codex_left_by_a_killed_runner_is_stopped_before_the_attempt_is_recorded(self):
        for case in ("second_signal", "stop_grace"):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, CODEX_LIKE_RUNNER if case == "second_signal" else ESCAPED_RUNNER)
                proc = self.launch(f, env)
                started = []
                try:
                    started = self.started(pids, 2)
                    proc.send_signal(signal.SIGTERM)
                    if case == "second_signal":
                        proc.send_signal(signal.SIGHUP)
                    code, out, err = self.finish(proc)
                    self.assertTrue(gone(started[1]), f"Codex stand-in {started[1]} outlived the dispatch")
                    self.assertEqual(code, 1, out + err)
                    self.assertIn("call 1 attempt 1: invalid", out)
                    self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
                    self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, which "
                                  "kills every process in it), ", err)
                    self.assertNotIn("Traceback", err)
                finally:
                    self.stop_all(started)
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_scope_that_does_not_empty_keeps_the_attempt_open_until_it_is_stopped_as_advised(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, ESCAPED_RUNNER)
        proc = self.launch(f, env, driver=UNSTOPPABLE)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        call_dir = f.rdir / "reviews" / "call-001-a1"
        started = []
        try:
            started = self.started(pids, 2)
            unit = self.unit(f)
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 3, out + err)
            self.assertIn(f"CONFLICT  the review runner ran for call 1 attempt 1 (exit None), but its systemd scope "
                          f"{unit} was killed and 2 processes still run in it (", err)
            self.assertIn(f"{started[1]} is `sleep 300`", err)
            self.assertIn("); call.json is written and nothing else was recorded: do not dispatch call 1 attempt 1 "
                          f"again; wait for it to end, or stop it (`systemctl --user kill --signal=INT {unit}`, then "
                          f"`systemctl --user kill --signal=KILL {unit}` if that is ignored; `systemd-cgls --user-unit "
                          f"{unit}` shows it), then run `receipt --run {RUN} --call 1 --attempt 1`, which records the "
                          "attempt\n", err)
            self.assertTrue((call_dir / "running.json").exists())
            self.assertTrue((call_dir / "call.json").exists())
            f.tool(*receipt, expect=3)
            self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its "
                          "review, and 2 processes still run in it (", f.last.stderr)
            self.assertFalse((call_dir / "receipt.json").exists())
            f.tool(*self.dispatch_args(2), expect=1)
            self.assertIn("FAIL  retry out of order or an earlier attempt has no receipt", f.last.stderr)
            self.systemctl(f, "INT")
            self.assertTrue(self.wait_gone(started[1]))
            self.assertFalse(gone(started[0]))
            f.tool(*receipt, expect=3)
            self.assertIn(f"and 1 process still runs in it ({started[0]} is `{sys.executable} ", f.last.stderr)
            self.systemctl(f, "KILL")
            self.assertTrue(self.emptied(f))
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        f.tool(*receipt, expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertFalse((call_dir / "running.json").exists())
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_an_error_exit_after_the_runner_stopped_still_prints_its_notes(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, ESCAPED_RUNNER)
        proc = self.launch(f, env, driver=CALL_JSON_EIO_AFTER_STOP, arg="open")
        started = []
        try:
            started = self.started(pids, 2)
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 2, out + err)
            self.assertIn("UNVERIFIABLE  could not write", err)
            self.assertIn("NOTE  this dispatch was interrupted by SIGTERM", err)
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill", err)
            self.assertTrue(gone(started[1]))
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_a_signal_after_the_runner_stopped_lets_the_attempt_be_recorded(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, SIGNAL_BEFORE_CALL_RECORD, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertIn("NOTE  this dispatch received SIGTERM after the review runner had stopped, and held it until it "
                      "had finished", f.last.stderr)
        self.assertNotIn("interrupted by", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())

    def test_a_record_that_is_a_directory_in_an_earlier_attempt_leaves_the_receipt_standing(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"FAKE_MODE": "failed"}, expect=1)
        f.tool(*self.dispatch_args(2), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        earlier = f.rdir / "reviews" / "call-001-a1" / "input" / "dispatch.json"
        data = earlier.read_bytes()
        earlier.unlink()
        earlier.mkdir()
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "2")
        f.tool(*receipt, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  {earlier}: not a file (repair it by hand; reading it again cannot help); call 1 attempt 2 "
                      f"is recorded counted in {f.rdir / 'reviews' / 'call-001-a2' / 'receipt.json'} and stands",
                      f.last.stderr)
        self.assertEqual(f.receipt(1, 2)["status"], "counted")
        earlier.rmdir()
        earlier.write_bytes(data)
        f.tool(*receipt)
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_receipt_artifacts_writes_call_json_only_after_the_call_verifies(self):
        f = self.f
        call_dir, adir = self.bound_by_hand(f)
        plan = f.rdir / "rev-001" / "plan.md"
        data = plan.read_bytes()
        plan.unlink()
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--artifacts", str(adir))
        f.tool(*receipt, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  revision 1 plan.md: missing or not a file", f.last.stderr)
        self.assertFalse(os.path.lexists(call_dir / "call.json"))
        self.assertFalse(os.path.lexists(call_dir / "receipt.json"))
        plan.write_bytes(data)
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertEqual(json.loads((call_dir / "call.json").read_text())["artifacts"], str(adir))

    def test_a_special_file_found_after_the_runner_says_to_record_it_once_removed(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, SPECIAL_RUNNER, str(HERE / "fake_runner.py"))
        f.tool(*self.dispatch_args(), env=env, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("; its call.json is written but its receipt is not: do not dispatch call 1 attempt 1 again; once "
                      f"it is removed, record it with `receipt --run {RUN} --call 1 --attempt 1`", f.last.stderr)
        (Path(f.dispatched(1)["snapshot"]) / "src" / "pipe").unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_fifo_where_codex_or_planloop_keeps_a_record_never_blocks_receipt(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("rollout", "versions"):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
                target = f.versions if case == "versions" else next(f.sessions.rglob("rollout-*.jsonl"))
                data = target.read_bytes()
                target.unlink()
                os.mkfifo(target)
                try:
                    proc = subprocess.run([sys.executable, str(TOOL), *receipt], cwd=f.repo, env=f.env,
                                          capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    self.fail(f"a FIFO in place of the {case} file blocked receipt")
                self.assertNotIn("Traceback", proc.stderr)
                if case == "rollout":
                    self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                    self.assertIn(f"Codex's session record {target} is not a file", proc.stdout)
                    self.assertEqual(f.receipt(1)["status"], "invalid")
                else:
                    self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                    self.assertIn(f"FAIL  {target}: not a file (repair it by hand", proc.stderr)
                    self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
                    target.unlink()
                    target.write_bytes(data)
                    f.tool(*receipt)
                    self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        f = Fixture(self)
        self.ready_to_dispatch(f)
        brief = f.rdir / "rev-001" / "bundle" / "frozen" / "brief.md"
        brief.parent.chmod(0o755)
        brief.unlink()
        os.mkfifo(brief)
        try:
            proc = subprocess.run([sys.executable, str(TOOL), *self.dispatch_args()], cwd=f.repo, env=f.env,
                                  capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.fail("a FIFO in place of the frozen brief blocked dispatch")
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("revision 1 frozen brief.md: missing or not a file", proc.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())

    def test_dispatch_binds_only_a_runner_directory_holding_a_result_json_file(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, RESULT_DIR_RUNNER, str(HERE / "fake_runner.py"))
        f.tool(*self.dispatch_args(), env=env)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_straggler_killed_after_the_runner_exited_is_not_blamed_on_the_runner(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, DEAF_STRAGGLER_RUNNER, str(HERE / "fake_runner.py"))
        started = []
        try:
            code = self.driver(f, GRACE, "2", *self.dispatch_args(), env=env)
            started = self.started(pids, 2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
            self.assertTrue(gone(started[1]))
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, which kills "
                          "every process in it), after the review runner had exited\n", f.last.stderr)
        finally:
            self.stop_all(started)


    def test_codex_left_by_a_runner_killed_from_outside_is_stopped_before_the_attempt_is_recorded(self):
        for case, standin in (("plain", CODEX_PLAIN), ("deaf", CODEX_DEAF), ("family", CODEX_FAMILY)):
            for sig in (signal.SIGKILL, signal.SIGTERM) if case == "plain" else (signal.SIGKILL,):
                with self.subTest(case=case, sig=sig.name):
                    f = Fixture(self)
                    self.ready_to_dispatch(f)
                    env, pids = self.codex_env(f, standin)
                    proc = self.launch(f, env, driver=GRACE, arg="1")
                    started = []
                    try:
                        started = self.started(pids, 2)
                        self.wait_for(f.root / "ready")
                        if case == "family":
                            started.append(int((f.root / "grandchild").read_text()))
                        os.kill(started[0], sig)
                        code, out, err = self.finish(proc)
                        for pid in started[1:]:
                            self.assertTrue(gone(pid), f"process {pid} of the review outlived the dispatch that "
                                            "recorded the attempt")
                        self.assertNotIn("Traceback", err)
                        self.assertEqual(code, 1, out + err)
                        self.assertIn("call 1 attempt 1: invalid", out)
                        self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, "
                                      "which kills every process in it), ", err)
                        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
                    finally:
                        self.stop_all(started)
                        if proc.poll() is None:
                            proc.kill()
                            proc.communicate()
                    f.tool(*self.dispatch_args(2))
                    self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_dispatch_killed_while_it_stops_the_review_or_once_call_json_is_written_keeps_the_attempt_open(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("while_stopping", "call_json_written"):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, ESCAPED_RUNNER)
                if case == "call_json_written":
                    env["PLANLOOP_CRASH_AT"] = "after_runner"
                proc = self.launch(f, env, driver=KILLED_WHILE_STOPPING if case == "while_stopping" else UNSTOPPABLE)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                started = []
                try:
                    started = self.started(pids, 2)
                    proc.send_signal(signal.SIGTERM)
                    proc.communicate(timeout=60)
                    self.assertEqual(proc.returncode, -signal.SIGKILL if case == "while_stopping" else 99)
                    self.assertEqual((call_dir / "call.json").exists(), case == "call_json_written")
                    self.assertFalse(gone(started[0]) or gone(started[1]))
                    f.tool(*receipt, expect=3)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {self.unit(f)} is the systemd "
                                  "scope of its review, and 2 processes still run in it (", f.last.stderr)
                    self.assertIn(f"{started[1]} is `sleep 300`", f.last.stderr)
                    self.assertFalse((call_dir / "receipt.json").exists())
                    f.tool(*self.dispatch_args(2), expect=1)
                    self.assertIn("FAIL  retry out of order or an earlier attempt has no receipt", f.last.stderr)
                    self.systemctl(f, "KILL")
                    self.assertTrue(self.emptied(f))
                finally:
                    self.stop_all(started)
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertFalse((call_dir / "running.json").exists())
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_record_that_becomes_a_non_file_as_publish_renames_it_holds_the_revision_in_place(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        data = (f.rdir / f".staging-002-{nonce}" / "handback.json").read_bytes()
        code = self.driver(f, SWAP_STAGING_AT_RENAME, "directory", "publish", "--run", RUN, "--revision", "2",
                           "--nonce", nonce)
        record = f.rdir / "rev-002" / "handback.json"
        held = (f"FAIL  {record} is not a regular file (a directory, FIFO, socket, device or dangling symbolic link), "
                "so reading it again cannot help; nothing was moved aside or discarded: repair it by hand, or move "
                f"{f.rdir / 'rev-002'} out of the run directory by hand (it can then be re-staged)")
        for step in ("publish", "recover"):
            with self.subTest(step=step):
                if step == "recover":
                    code = f.tool("publish", "--run", RUN, "--recover", expect=None).returncode
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
                self.assertIn(held, f.last.stderr)
                self.assertTrue(record.is_dir())
                self.assertFalse(list(f.rdir.glob(".orphan-rev-002-*")))
                self.assertTrue((f.rdir / ".publishing-rev-002").is_file())
                self.assertEqual(f.head(), 1)
        record.rmdir()
        record.write_bytes(data)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertEqual(f.head(), 2)

    def test_an_unreferenced_revision_holding_a_non_file_is_moved_aside_like_any_other(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        for n in (2, 5):
            (f.rdir / f"rev-{n:03d}" / "revision.json").mkdir(parents=True)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("Traceback", f.last.stderr)
        for n in (2, 5):
            self.assertIn(f"NOTE  moved unreferenced rev-{n:03d} aside to .orphan-rev-{n:03d}-", f.last.stderr)
            self.assertFalse((f.rdir / f"rev-{n:03d}").exists())
            self.assertEqual(len(list(f.rdir.glob(f".orphan-rev-{n:03d}-*"))), 1)
        self.assertEqual(f.head(), 1)
        f.review(review("REVISE", [finding("F1")]))
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_second_signal_after_the_runner_stopped_ends_a_dispatch_that_cannot_finish(self):
        for first, second in ((signal.SIGTERM, signal.SIGTERM), (signal.SIGHUP, signal.SIGINT)):
            with self.subTest(first=first.name, second=second.name):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                marker = f.root / "blocked"
                call_dir = f.rdir / "reviews" / "call-001-a1"
                proc = self.launch(f, {}, driver=BLOCKED_RECORDING, arg=str(marker))
                try:
                    self.wait_for(marker)
                    proc.send_signal(first)
                    time.sleep(1)
                    self.assertIsNone(proc.poll(), "one signal after the runner stopped is held until it is recorded")
                    proc.send_signal(second)
                    try:
                        proc.communicate(timeout=20)
                    except subprocess.TimeoutExpired:
                        self.fail("a second signal did not end a dispatch that could not finish recording")
                    self.assertEqual(proc.returncode, -second)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()
                self.assertFalse((call_dir / "call.json").exists())
                self.assertTrue((call_dir / "running.json").exists())
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertFalse((call_dir / "running.json").exists())
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_sigint_before_the_runner_starts_ends_with_one_line_and_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, SIGINT_BEFORE_RUNNER, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 130, f.last.stdout + f.last.stderr)
        self.assertEqual(f.last.stderr, "INTERRUPTED  stopped by SIGINT before the command finished; what it had "
                         "written stands: run it again, it re-checks what is on disk\n")
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse((f.rdir / ".lock").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_frozen_brief_that_becomes_a_non_file_after_it_verified_stops_dispatch_cleanly(self):
        f = self.f
        self.ready_to_dispatch(f)
        brief = f.rdir / "rev-001" / "bundle" / "frozen" / "brief.md"
        code = self.driver(f, BRIEF_SWAPPED_AFTER_VERIFY, str(brief), *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertIn("FAIL  revision 1 frozen brief.md: missing or not a file", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())

    def bystanders(self, f):
        record = f.dispatched(1)
        note = Path(record["artifacts_root"]) / "notes.txt"
        note.write_text("x\n")
        procs = [subprocess.Popen(argv, cwd=cwd, start_new_session=True, stdout=subprocess.DEVNULL)
                 for argv, cwd in ((["tail", "-f", str(note)], "/"),
                                   ([sys.executable, "-c", "import signal, time\nsignal.signal(signal.SIGINT, "
                                     "signal.SIG_IGN)\ntime.sleep(300)", str(note)], "/"),
                                   (["sleep", "300"], record["artifacts_root"]),
                                   (["sleep", "300"], record["snapshot"]))]
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in procs])
        time.sleep(0.5)
        return procs, note

    def test_what_merely_reads_a_calls_files_is_never_signalled_and_never_holds_the_call_open(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.codex_env(f, CODEX_DEAF)
        proc = self.launch(f, env, driver=GRACE, arg="1")
        started = []
        try:
            started = self.started(pids, 2)
            self.wait_for(f.root / "ready")
            around, note = self.bystanders(f)
            os.kill(started[0], signal.SIGKILL)
            code, out, err = self.finish(proc)
            self.assertTrue(gone(started[1]), "the Codex stand-in outlived the dispatch")
            self.assertEqual([p.poll() for p in around], [None] * 4, "a process that only read the call's files was "
                             "signalled")
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill", err)
            self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)
        self.assertEqual([p.poll() for p in around], [None] * 4)

    def test_a_grandchild_is_pursued_after_the_group_leader_it_belonged_through_has_died(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.codex_env(f, CODEX_ORPHANING)
        proc = self.launch(f, env, driver=GRACE, arg="1")
        started = []
        try:
            started = self.started(pids, 2)
            self.wait_for(f.root / "ready")
            started.append(int((f.root / "grandchild").read_text()))
            time.sleep(0.5)
            os.kill(started[0], signal.SIGKILL)
            code, out, err = self.finish(proc)
            for pid in started[1:]:
                self.assertTrue(gone(pid), f"process {pid} of the review outlived the dispatch that recorded it")
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill", err)
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_two_checkouts_sharing_a_state_directory_and_a_run_id_never_touch_each_others_calls(self):
        a = self.f
        self.ready_to_dispatch(a)
        b = Fixture(self)
        self.ready_to_dispatch(b)
        env, pids = self.codex_env(a, CODEX_PLAIN)
        proc = self.launch(a, env)
        started = []
        try:
            started = self.started(pids, 2)
            self.wait_for(a.root / "ready")
            b.tool(*self.dispatch_args(), env={"PLANLOOP_STATE": a.env["PLANLOOP_STATE"]}, expect=None)
            self.assertEqual(b.last.returncode, 0, b.last.stdout + b.last.stderr)
            self.assertIn("call 1 attempt 1: counted", b.last.stdout)
            self.assertNotIn("cgroup.kill", b.last.stderr)
            self.assertFalse(gone(started[0]) or gone(started[1]), "another checkout's dispatch stopped this review")
            self.assertNotEqual(a.dispatched(1)["scope"], b.dispatched(1)["scope"])
            roots = [Path(x.dispatched(1)["artifacts_root"]) for x in (a, b)]
            self.assertEqual(roots[0].parent, roots[1].parent)
            self.assertNotEqual(roots[0], roots[1])
            self.assertEqual([r.name for r in roots],
                             ["call-001-a1-" + Path(x.dispatched(1)["snapshot"]).parent.name for x in (a, b)])
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertEqual(code, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_an_artifact_directory_that_already_exists_is_refused_not_reused(self):
        f = self.f
        self.ready_to_dispatch(f)
        taken = f.state / RUN / "calls" / "call-001-a1-r-fixed"
        (taken / "claudex-old").mkdir(parents=True)
        (taken / "claudex-old" / "result.json").write_text("{}\n")
        code = self.driver(f, FIXED_PRIVATE, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not prepare call 1 attempt 1 ([Errno 17] File exists: '{taken}'); nothing "
                      "was reserved and Codex did not run", f.last.stderr)
        self.assertEqual((taken / "claudex-old" / "result.json").read_text(), "{}\n")
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertEqual(sorted(p.name for p in taken.iterdir()), ["claudex-old"])

    def test_the_shell_that_runs_receipt_and_its_pipeline_never_hold_the_call_open(self):
        f = self.f
        started, dispatcher = self.orphaned_runner(f)
        self.stop_all(started)
        self.assertTrue(group_gone(started[0]))
        record = f.dispatched(1)
        script = ('cd "$1" && (cd "$2" && "$3" "$4" receipt --run "$5" --call 1 --attempt 1 2>&1 | tee "$6/log"; '
                  'echo "rc=${PIPESTATUS[0]}")')
        proc = subprocess.run(["bash", "-c", script, "sh", record["snapshot"], str(f.repo), sys.executable, str(TOOL),
                               RUN, record["artifacts_root"]], env=f.env, capture_output=True, text=True, timeout=120)
        self.assertIn("call 1 attempt 1: invalid", proc.stdout, proc.stdout + proc.stderr)
        self.assertIn("rc=1\n", proc.stdout)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())

    def test_a_running_record_that_is_not_a_json_object_in_a_regular_file_records_nothing(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for case in ("directory", "symlink", "dangling", "list", "number", "null"):
            with self.subTest(case=case):
                f = Fixture(self)
                started = self.orphaned_codex(f)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                running = call_dir / "running.json"
                text = running.read_text()
                running.unlink()
                if case == "directory":
                    running.mkdir()
                elif case == "symlink":
                    (f.root / "elsewhere.json").write_text(text)
                    running.symlink_to(f.root / "elsewhere.json")
                elif case == "dangling":
                    running.symlink_to(f.root / "nowhere.json")
                else:
                    running.write_text({"list": "[]", "number": "7", "null": "null"}[case] + "\n")
                f.tool(*receipt, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("FAIL  running.json: not a ", f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").exists())
                self.assertTrue(os.path.lexists(running))
                self.assertFalse(gone(started[1]))
                running.rmdir() if case == "directory" else running.unlink()
                running.write_text(text)
                f.tool(*receipt, expect=3)
                os.kill(started[1], signal.SIGKILL)
                self.assertTrue(self.wait_gone(started[1]))
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_sigint_once_the_call_is_reserved_says_to_record_it_not_to_dispatch_it_again(self):
        f = self.f
        self.ready_to_dispatch(f)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, SIGINT_AFTER_RESERVE, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 130, f.last.stdout + f.last.stderr)
        self.assertEqual(f.last.stderr, "INTERRUPTED  stopped by SIGINT before the command finished; what it had "
                         f"written stands: if {call_dir} exists now, do not dispatch call 1 attempt 1 again: run "
                         f"`receipt --run {RUN} --call 1 --attempt 1`, which records it or prints its receipt; "
                         "otherwise run the command again\n")
        self.assertTrue((call_dir / "running.json").exists())
        self.assertFalse((f.rdir / ".lock").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_concurrent_receipts_naming_the_artifacts_bind_them_once(self):
        f = self.f
        self.ready_to_dispatch(f)
        wrapper = f.root / "unlistable_runner.py"
        wrapper.write_text(UNLISTABLE_RUNNER)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        try:
            f.tool(*self.dispatch_args(), env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}"},
                   expect=2)
        finally:
            artifacts = f.artifacts()
            if artifacts.exists():
                artifacts.chmod(0o755)
        runner_dir = next(artifacts.glob("claudex-*"))
        self.assertTrue((call_dir / "running.json").exists())
        procs = [subprocess.Popen([*how, str(TOOL), "receipt", "--run", RUN, "--call", "1", "--attempt", "1",
                                   "--artifacts", str(runner_dir)], cwd=f.repo, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env={**f.env, "PLANLOOP_LOCK_TIMEOUT": "240"})
                 for how in ([sys.executable], [sys.executable, "-u"], [sys.executable, "-X", "dev", "-W", "default"],
                             ["timeout", "600", sys.executable], ["timeout", "600", sys.executable, "-u"],
                             ["env", "PLANLOOP_UNUSED=1", sys.executable])]
        for proc in procs:
            out, err = proc.communicate(timeout=280)
            self.assertEqual(proc.returncode, 0, out + err)
            self.assertIn("call 1 attempt 1: counted", out)
            self.assertNotIn("Traceback", err)
        self.assertEqual(json.loads((call_dir / "call.json").read_text())["artifacts"], str(runner_dir))
        self.assertFalse((call_dir / "running.json").exists())


    def test_dispatch_without_systemd_run_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        (f.root / "bin").mkdir()
        (f.root / "bin" / "git").symlink_to(shutil.which("git"))
        f.tool(*self.dispatch_args(), env={"PATH": str(f.root / "bin")}, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user, which needs systemd-run "
                      "254 or later on PATH, cgroup v2 mounted at /sys/fs/cgroup and this user's systemd manager "
                      "reachable from this shell and running in the cgroup /sys/fs/cgroup/user.slice/user-"
                      f"{os.getuid()}.slice/user@{os.getuid()}.service as this shell sees it (`systemctl --user status` "
                      "shows it): systemd-run is not on PATH; no call was reserved and Codex did not run\n",
                      f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_runner_that_is_not_confirmed_in_its_scope_never_runs(self):
        for case, script in (("fails", SYSTEMD_RUN_FAILS), ("unscoped", SYSTEMD_RUN_FAILS.replace(
                'echo "Failed to connect to bus: No medium found" >&2\nexit 1\n',
                'while [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n'))):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                code = self.driver(f, GRACE, "1", *self.dispatch_args(),
                                   env={**env, **self.fake_systemd_run(f, script)})
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
                self.assertFalse(pids.exists(), "the runner ran although it was never confirmed in its scope")
                unit = self.unit(f)
                self.assertIn(f"NOTE  the review runner could not be started in its scope {unit} ("
                              + ("Failed to connect to bus: No medium found" if case == "fails" else
                                 f"systemd-run did not move it into {f.dispatched(1)['scope']} within 1 seconds")
                              + "); Codex did not run\n", f.last.stderr)
                self.assertIn("FAIL  runner left no artifact directory", f.last.stdout)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertFalse(Path(f.dispatched(1)["scope"]).exists())
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_scope_name_that_is_taken_runs_nothing_and_never_touches_the_scope_that_holds_it(self):
        f = self.f
        self.ready_to_dispatch(f)
        scope = Path(load_tool().scope_of(RUN, str(f.state.resolve() / RUN / "calls" / "call-001-a1-r-fixed")))
        holder = subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect",
                                   f"--unit={scope.name}", "--", "sleep", "300"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        for _ in range(200):
            if scope.exists():
                break
            time.sleep(0.05)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        code = self.driver(f, FIXED_PRIVATE, "x", *self.dispatch_args(), env=env)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertEqual(f.dispatched(1)["scope"], str(scope))
        self.assertFalse(pids.exists(), "the runner ran although its scope name was taken")
        self.assertIsNone(holder.poll(), "the process holding the scope name was signalled")
        self.assertIn(f"NOTE  the review runner could not be started in its scope {scope.name} (Failed to start "
                      f"transient scope unit: Unit {scope.name} was already loaded or has a fragment file.); Codex did "
                      "not run\n", f.last.stderr)
        self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {scope.name} is the systemd scope of its "
                      f"review, and 1 process still runs in it ({holder.pid} is `{shutil.which('sleep')} 300`); nothing "
                      "was recorded: ",
                      f.last.stderr)
        holder.kill()
        holder.wait()
        self.assertTrue(self.emptied(f))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_what_a_dispatch_killed_before_it_reserved_its_call_left_is_removed_by_the_next_dispatch(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "before_reserve"}, expect=99)
        reserve, = (f.rdir / "reviews").glob(".reserve-*")
        record = json.loads((reserve / "input" / "dispatch.json").read_text())
        private, made = Path(record["snapshot"]).parent, Path(record["artifacts_root"])
        self.assertTrue(made.is_dir())
        self.assertTrue(os.path.lexists(private))
        f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))
        self.assertFalse(os.path.lexists(private))
        self.assertFalse(made.exists())
        self.assertNotEqual(f.dispatched(1)["artifacts_root"], str(made))

    def test_what_a_review_left_running_keeps_the_call_open_whatever_it_names(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for leave in ("plain", "disguised"):
            with self.subTest(leave=leave):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, LEAVING_RUNNER)
                proc = self.launch(f, {**env, "LEAVE": leave, "PLANLOOP": str(TOOL)})
                started = self.started(pids, 2)
                self.addCleanup(self.stop_all, started)
                proc.kill()
                proc.communicate()
                os.kill(started[0], signal.SIGKILL)
                self.assertTrue(self.wait_gone(started[0]))
                call_dir = f.rdir / "reviews" / "call-001-a1"
                for _ in range(2):
                    f.tool(*receipt, expect=3)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertIn("CONFLICT  call 1 attempt 1 cannot be recorded yet: ", f.last.stderr)
                    self.assertIn(f"{started[1]} is `", f.last.stderr)
                    self.assertFalse((call_dir / "receipt.json").exists())
                    self.assertFalse(gone(started[1]))
                os.kill(started[1], signal.SIGKILL)
                self.assertTrue(self.wait_gone(started[1]))
                self.assertTrue(self.emptied(f))
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertFalse((call_dir / "running.json").exists())

    def test_a_process_double_forked_into_a_session_of_its_own_at_once_is_stopped_before_the_attempt_is_recorded(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, DOUBLE_FORKING_RUNNER, str(HERE / "fake_runner.py"))
        started = []
        try:
            f.tool(*self.dispatch_args(), env=env, expect=None)
            started = self.started(pids, 1)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertTrue(self.wait_gone(started[0], wait=1), "a process the review double-forked into a session of "
                            "its own outlived the dispatch that recorded the attempt")
            self.assertEqual(f.last.returncode, 0, f.last.stdout + f.last.stderr)
            self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        finally:
            self.stop_all(started)

    def test_a_bystander_in_the_snapshot_that_names_the_artifacts_is_never_signalled_and_holds_nothing_open(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, WAITING_RUNNER, str(HERE / "fake_runner.py"))
        go = f.root / "go"
        proc = self.launch(f, {**env, "GO": str(go)})
        started, around = [], []
        try:
            started = self.started(pids, 1)
            record = f.dispatched(1)
            note = Path(record["artifacts_root"]) / "notes.txt"
            note.write_text("x\n")
            around = [subprocess.Popen(argv, cwd=record["snapshot"], start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                      for argv in (["tail", "-f", str(note)], ["sh", "-c", "sleep 300; :", "sh", str(note)])]
            time.sleep(2.5)
            go.write_text("go")
            code, out, err = self.finish(proc)
            self.assertNotIn("Traceback", err)
            self.assertEqual([p.poll() for p in around], [None, None], "a process the review did not start was "
                             "signalled" + out + err)
            self.assertEqual(code, 0, out + err)
            self.assertIn("call 1 attempt 1: counted", out)
            self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
        finally:
            self.stop_all(started)
            for p in around:
                p.kill()
                p.wait()
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    def fake_systemd_run(self, f, text):
        (f.root / "bin").mkdir()
        path = f.root / "bin" / "systemd-run"
        path.write_text(text.replace("@REAL@", shutil.which("systemd-run")))
        path.chmod(0o755)
        return {"PATH": f"{f.root / 'bin'}:{os.environ['PATH']}"}

    def test_a_receipt_that_waited_for_the_lock_checks_the_call_as_it_is_once_it_holds_the_lock(self):
        f = self.f
        self.ready_to_dispatch(f)
        go, call_dir = f.root / "go", f.rdir / "reviews" / "call-001-a1"
        waiting = self.launch(f, {}, "receipt", "--run", RUN, "--call", "1", "--attempt", "1",
                              driver=RECEIPT_WAITS_FOR_LOCK, arg=str(go))
        env, pids = self.runner_env(f, LINGERING_RUNNER)
        started, proc = [], None
        try:
            self.wait_for(f.root / "go.waiting")
            proc = self.launch(f, env)
            started = self.started(pids, 2)
            go.write_text("go")
            code, out, err = self.finish(waiting)
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 3, out + err)
            self.assertIn(f"CONFLICT  call 1 attempt 1 is still being reviewed by process {proc.pid}; wait for it", err)
            self.assertTrue((call_dir / "running.json").exists(), "a receipt that had waited for the lock removed the "
                            "running.json of the attempt dispatched meanwhile")
            self.assertFalse((call_dir / "receipt.json").exists())
            self.assertFalse(gone(started[0]) or gone(started[1]))
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertEqual(code, 1, out + err)
            self.assertIn("call 1 attempt 1: invalid", out)
        finally:
            self.stop_all(started)
            for p in (waiting, proc):
                if p is not None and p.poll() is None:
                    p.kill()
                    p.communicate()

    def test_a_receipt_run_where_the_review_scope_cannot_be_seen_records_nothing(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir, unit = f.rdir / "reviews" / "call-001-a1", self.unit(f)
        self.assertFalse(Path(f.dispatched(1)["scope"]).exists())
        order = ["host", "machine_id", "boot_id", "cgroup_ns", "cgroup_dev"]
        for here in ({"cgroup_ns": 1}, {"cgroup_dev": 1}, {"host": "elsewhere"}, {"machine_id": "another"},
                     {"boot_id": "another-boot", "host": "elsewhere"}, {"boot_id": "another-boot", "machine_id": None},
                     {"boot_id": None}):
            with self.subTest(here=here):
                code = self.driver(f, VIEWED, json.dumps(here), *receipt)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
                differs = "; ".join(f"{key}: dispatch.json records {f.dispatched(1)['view'][key]!r}, here {value!r}"
                                    for key, value in sorted(here.items(), key=lambda kv: order.index(kv[0])))
                self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its "
                              f"review, and this command does not see cgroups as its dispatch did ({differs}), so a "
                              "scope that is absent here may still hold a process there; nothing was recorded: run "
                              f"`receipt --run {RUN} --call 1 --attempt 1` on the host and in the session (not a "
                              "container, another distribution or another cgroup namespace) that dispatched it; if "
                              "there is none any more (the host was renamed, its machine id changed or cannot be "
                              f"read), check by hand that nothing runs in that scope (`systemd-cgls --user-unit {unit}` "
                              f"lists no process, or says the unit is not found), then remove {call_dir} (what it "
                              "records of the attempt is discarded) and dispatch call 1 attempt 1 again\n",
                              f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").exists())
                self.assertTrue((call_dir / "running.json").exists())
        self.assertEqual(self.driver(f, VIEWED, json.dumps({"boot_id": "another-boot", "cgroup_ns": 1, "cgroup_dev": 1}),
                                     *receipt), 0, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertFalse((call_dir / "running.json").exists())

    def test_a_private_copy_name_that_is_taken_is_refused_and_left_alone(self):
        f = self.f
        self.ready_to_dispatch(f)
        taken = f.isolated_base / "isolated" / "r-fixed"
        (taken / "repo").mkdir(parents=True)
        (taken / "repo" / "kept.txt").write_text("kept\n")
        code = self.driver(f, FIXED_PRIVATE, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not prepare call 1 attempt 1 ([Errno 17] File exists: '{taken}'); nothing "
                      "was reserved and Codex did not run", f.last.stderr)
        self.assertEqual((taken / "repo" / "kept.txt").read_text(), "kept\n")
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse((f.state / RUN / "calls").exists() and os.listdir(f.state / RUN / "calls"))
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_an_earlier_attempt_whose_recorded_snapshot_is_not_a_path_never_stops_a_later_receipt(self):
        for value in (7, "/s\0", "\udcff", None):
            with self.subTest(value=value):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                f.tool(*self.dispatch_args(), env={"FAKE_MODE": "no_rollout"}, expect=1)
                path = f.rdir / "reviews" / "call-001-a1" / "input" / "dispatch.json"
                path.chmod(0o644)
                path.write_text(json.dumps({**json.loads(path.read_text()), "snapshot": value}))
                f.tool(*self.dispatch_args(2))
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_removing_running_json_never_frees_a_call_whose_scope_still_holds_a_process(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f = self.f
        started = self.orphaned_codex(f)
        call_dir, unit = f.rdir / "reviews" / "call-001-a1", self.unit(f)
        (call_dir / "running.json").unlink()
        f.tool(*receipt, expect=3)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its review, "
                      f"and 1 process still runs in it ({started[1]} is `", f.last.stderr)
        self.assertFalse((call_dir / "receipt.json").exists())
        self.assertFalse(gone(started[1]))
        self.systemctl(f, "KILL")
        self.assertTrue(self.wait_gone(started[1]))
        self.assertTrue(self.emptied(f))
        f.tool(*receipt, expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_systemd_run_is_told_not_to_expand_the_command_and_one_that_cannot_be_told_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        log = f.root / "systemd-run.log"
        env = {**self.fake_systemd_run(f, SYSTEMD_RUN_LOGGED), "SYSTEMD_RUN_LOG": str(log)}
        f.tool(*self.dispatch_args(), env={**env, "SYSTEMD_RUN_OLD": "1"}, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user", f.last.stderr)
        self.assertIn("systemd-run: unrecognized option '--expand-environment=no'", f.last.stderr)
        self.assertIn("; no call was reserved and Codex did not run\n", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        log.unlink()
        f.tool(*self.dispatch_args(), env=env)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        told = r"^ --user --scope --quiet --collect --expand-environment=no --slice=app\.slice --description=planloop "
        self.assertRegex(lines[0], told + r"probe --unit=planloop-probe-[0-9a-f]{32}\.scope$")
        self.assertRegex(lines[1], told + r"review --unit=planloop-\S+\.scope$")
        self.assertTrue(lines[1].endswith(f" --unit={self.unit(f)}"), lines)

    def test_a_shell_that_cannot_reach_the_user_manager_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        env = f.env
        f.env = {k: v for k, v in env.items() if k not in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")}
        f.tool(*self.dispatch_args(), expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user", f.last.stderr)
        self.assertIn("Failed to connect to bus", f.last.stderr)
        self.assertIn("; no call was reserved and Codex did not run\n", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse(list((f.state / RUN / "calls").glob("*")) if (f.state / RUN / "calls").exists() else [])
        f.env = env
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_systemd_run_that_does_not_scope_where_planloop_looks_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        f.tool(*self.dispatch_args(), env={**env, **self.fake_systemd_run(f, SYSTEMD_RUN_UNSCOPED)}, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user", f.last.stderr)
        self.assertRegex(f.last.stderr, r": a probe scope could not be started and seen \(systemd-run did not move it "
                         r"into /sys/fs/cgroup/user\.slice/user-\d+\.slice/user@\d+\.service/app\.slice/planloop-probe-"
                         r"[0-9a-f]{32}\.scope within 10 seconds\); no call was reserved and Codex did not run\n")
        self.assertFalse(pids.exists())
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())

    def test_dispatch_without_this_users_manager_cgroup_reserves_nothing(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, NO_MANAGER, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user", f.last.stderr)
        self.assertIn("; no call was reserved and Codex did not run\n", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())

    def unshared(self):
        if subprocess.run([sys.executable, "-c", "import os\nos.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)"],
                          capture_output=True).returncode:
            self.skipTest("this user cannot create a user and mount namespace")
        base = f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
        return base, {"tmpfs_over_slice": ([["none", f"{base}/app.slice", "tmpfs", 0]], f"{base}/app.slice"),
                      "cgroup_over_slice": ([[f"{base}/init.scope", f"{base}/app.slice", "", 4096]], f"{base}/app.slice"),
                      "tmpfs_over_user_slice": ([["none", "/sys/fs/cgroup/user.slice", "tmpfs", 0]],
                                                "/sys/fs/cgroup/user.slice"),
                      "tmpfs_over_cgroup": ([["none", "/sys/fs/cgroup", "tmpfs", 0]], None)}

    def no_probe_left(self):
        for _ in range(100):
            listed = subprocess.run(["systemctl", "--user", "list-units", "planloop-probe-*", "--all", "--no-legend",
                                     "--plain"], capture_output=True, text=True, timeout=30)
            self.assertEqual(listed.returncode, 0, f"systemctl could not list units: {listed.stderr}")
            units = listed.stdout.strip()
            if not units:
                return
            time.sleep(0.1)
        self.fail(f"a probe scope was left behind: {units}")

    def test_a_receipt_run_where_something_is_mounted_over_the_cgroup_tree_records_nothing(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f = self.f
        base, mounts = self.unshared()
        started = self.orphaned_codex(f)
        call_dir, unit = f.rdir / "reviews" / "call-001-a1", self.unit(f)
        for case, (mount, over) in mounts.items():
            with self.subTest(case=case):
                code = self.driver(f, MOUNTED_OVER, json.dumps(mount), *receipt)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
                self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its "
                              "review, and " + ("whether a process still runs in it cannot be checked ([Errno 18] "
                                                f"another filesystem is mounted over it: '{over}'); nothing was "
                                                "recorded: " if over else "this command does not see cgroups as its "
                                                "dispatch did (cgroup_dev: dispatch.json records "), f.last.stderr)
                self.assertFalse((call_dir / "receipt.json").exists())
                self.assertFalse(gone(started[1]))
        self.assertEqual(self.driver(f, MOUNTED_OVER, "[]", *receipt), 3, f.last.stdout + f.last.stderr)
        self.assertIn(f"and 1 process still runs in it ({started[1]} is `", f.last.stderr)
        os.kill(started[1], signal.SIGKILL)
        self.assertTrue(self.emptied(f))
        self.assertEqual(self.driver(f, MOUNTED_OVER, json.dumps(mounts["tmpfs_over_slice"][0]), *receipt), 3)
        self.assertFalse((call_dir / "receipt.json").exists())
        self.assertEqual(self.driver(f, MOUNTED_OVER, "[]", *receipt), 1, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_a_dispatch_that_cannot_see_the_scope_it_would_start_reserves_nothing(self):
        base, mounts = self.unshared()
        for case in ("tmpfs_over_slice", "cgroup_over_slice", "tmpfs_over_user_slice", "tmpfs_over_cgroup"):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                mount, over = mounts[case]
                code = self.driver(f, MOUNTED_OVER, json.dumps(mount), *self.dispatch_args(), env=env)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                self.assertFalse(pids.exists(), "the runner ran in a scope its dispatch could not see")
                self.assertRegex(f.last.stderr, r"UNVERIFIABLE  dispatch runs each review in a systemd scope of this "
                                 r"user, .*: a probe scope could not be started and seen \(it runs in " + re.escape(base)
                                 + r"/app\.slice/planloop-probe-[0-9a-f]{32}\.scope, which this shell cannot see \(\[Errno "
                                 r"18\] " + re.escape(f"another filesystem is mounted over it: '{over}'" if over else
                                                      "not a cgroup2 mount of this cgroup namespace's root: "
                                                      "'/sys/fs/cgroup'")
                                 + r"\)\); no call was reserved and Codex did not run\n")
                self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
                self.assertFalse((f.state / RUN / "calls").exists() and os.listdir(f.state / RUN / "calls"))
                self.no_probe_left()
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_runner_whose_scope_is_hidden_once_the_probe_has_passed_never_runs(self):
        f = self.f
        base, mounts = self.unshared()
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        code = self.driver(f, MOUNTED_OVER_ONCE_PROBED, json.dumps(mounts["tmpfs_over_slice"][0]), *self.dispatch_args(),
                           env=env)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertFalse(pids.exists(), "the runner ran in a scope its dispatch could not see")
        scope = f.dispatched(1)["scope"]
        self.assertIn(f"NOTE  the review runner could not be started in its scope {self.unit(f)} (it runs in {scope}, "
                      "which this shell cannot see ([Errno 18] another filesystem is mounted over it: "
                      f"'{base}/app.slice')); Codex did not run\n", f.last.stderr)
        self.assertIn("whether a process still runs in it cannot be checked ([Errno 18] another filesystem is mounted "
                      f"over it: '{base}/app.slice'); nothing was recorded: ", f.last.stderr)
        self.assertTrue(self.emptied(f))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    ADMIT_AFTER = ("do not dispatch call 1 attempt 1 again (where that says to run the command again, it means "
                   f"`receipt`): run `receipt --run {RUN} --call 1 --attempt 1` once that is resolved, which records "
                   "it or prints its receipt\n")

    def test_an_admission_that_cannot_read_its_record_or_take_the_lock_keeps_the_errors_category(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        said = "call 1 attempt 1 was reserved, but its review runner was not started and Codex did not run"
        for mode in ("unreadable", "malformed", "lock_eio"):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                code = self.driver(f, TAKEN_BEFORE_THE_RUNNER, mode, *self.dispatch_args(), env=env)
                running = f.rdir / "reviews" / "call-001-a1" / "running.json"
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertFalse(pids.exists(), "the runner started although its admission failed")
                if mode == "unreadable":
                    self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                    self.assertIn(f"UNREADABLE  {running} could not be read ([Errno 13] Permission denied: "
                                  f"'{running}'); nothing was recorded from it, run the command again once it can be "
                                  f"read; {said}: " + self.ADMIT_AFTER, f.last.stderr)
                    running.chmod(0o644)
                elif mode == "malformed":
                    self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
                    self.assertIn(f"FAIL  {said} ({running}: malformed JSON (", f.last.stderr)
                    running.unlink()
                else:
                    self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                    self.assertRegex(f.last.stderr, r"UNVERIFIABLE  " + re.escape(said) + r" \(could not prepare the "
                                     r"lock in \S+/\.lock-tmp-[0-9a-f]{32} \(\[Errno 5\] Input/output error: ")
                self.assertTrue(f.last.stderr.endswith("): " + self.ADMIT_AFTER) or mode == "unreadable",
                                f.last.stderr)
                self.assertNotIn("CONFLICT", f.last.stderr)
                self.assertTrue(self.emptied(f))
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_run_lock_held_past_the_lock_timeout_when_the_runner_is_admitted_does_not_burn_the_attempt(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, TAKEN_BEFORE_THE_RUNNER, "held", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_signal_pending_when_the_runner_would_be_admitted_keeps_the_gate_shut(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        opened = f.root / "opened"
        code = self.driver(f, TAKEN_BEFORE_THE_RUNNER, "signalled", *self.dispatch_args(),
                           env={**env, "GO_WRITTEN": str(opened)})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertFalse(opened.exists(), "the gate was opened although a signal was pending")
        self.assertFalse(pids.exists())
        self.assertIn("NOTE  this dispatch was interrupted by SIGTERM before it let the review runner start, so the "
                      "runner never started and Codex did not run\n", f.last.stderr)
        self.assertNotIn("asked the review runner to stop", f.last.stderr)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        self.assertIsNone(json.loads((f.rdir / "reviews" / "call-001-a1" / "call.json").read_text())["runner_exit"])
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_an_admission_refused_while_the_gate_will_not_end_never_says_the_runner_ran(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        try:
            code = self.driver(f, TAKEN_BEFORE_THE_RUNNER, "replaced_stuck", *self.dispatch_args(), env=env)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
            self.assertFalse(pids.exists())
            self.assertIn("CONFLICT  the review runner of call 1 attempt 1 was never let start, so Codex did not run (",
                          f.last.stderr)
            self.assertIn(f", but its systemd scope {self.unit(f)} was killed and 1 process still runs in it (",
                          f.last.stderr)
            self.assertNotIn("while the review runner ran", f.last.stderr)
            self.assertNotIn("dispatch stopped on an unexpected error", f.last.stderr)
        finally:
            with contextlib.suppress(subprocess.CalledProcessError):
                self.systemctl(f, "KILL")
        self.assertTrue(self.emptied(f))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_a_dispatch_killed_while_it_marks_a_directory_it_made_leaves_nothing_the_next_one_keeps(self):
        for nth in ("1", "2"):
            with self.subTest(nth=nth):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                proc = self.launch(f, {}, driver=KILLED_AT_MARKER, arg=nth)
                proc.communicate(timeout=120)
                self.assertEqual(proc.returncode, -signal.SIGKILL)
                f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5", "PLANLOOP_CRASH_AT": "after_runner"},
                       expect=99)
                self.assertNotIn("Traceback", f.last.stderr)
                record, calls, isolated = f.dispatched(1), f.state / RUN / "calls", f.isolated_base / "isolated"
                self.assertEqual([str(p) for p in calls.iterdir()], [record["artifacts_root"]])
                isolated.chmod(0o700)
                self.assertEqual([str(p) for p in isolated.iterdir()], [str(Path(record["snapshot"]).parent)])
                isolated.chmod(0o300)
                self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_directory_already_at_a_name_a_dispatch_makes_is_refused_and_never_replaced(self):
        f = self.f
        self.ready_to_dispatch(f)
        held = f.state / RUN / "calls" / "call-001-a1-r-fixed"
        held.mkdir(parents=True)
        before = held.stat().st_ino
        code = self.driver(f, FIXED_PRIVATE, "x", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not prepare call 1 attempt 1 ([Errno 17] File exists: '{held}')",
                      f.last.stderr)
        self.assertEqual(held.stat().st_ino, before)
        self.assertEqual(os.listdir(held), [])
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))

    def test_a_marked_directory_whose_rename_landed_despite_its_error_is_never_left_behind(self):
        for prefix in ("r-", "call-001-a1-r-"):
            with self.subTest(prefix=prefix):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                code = self.driver(f, LANDED_EIO, prefix, *self.dispatch_args())
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                self.assertIn("UNVERIFIABLE  could not prepare call 1 attempt 1 ([Errno 5] Input/output error: ",
                              f.last.stderr)
                calls, isolated = f.state / RUN / "calls", f.isolated_base / "isolated"
                self.assertEqual(list(calls.iterdir()) if calls.exists() else [], [])
                isolated.chmod(0o700)
                self.assertEqual(list(isolated.iterdir()), [])
                isolated.chmod(0o300)
                self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))
                f.tool(*self.dispatch_args())
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def only_made_by(self, f, record):
        calls, isolated = f.state / RUN / "calls", f.isolated_base / "isolated"
        self.assertEqual([str(p) for p in calls.iterdir()], [record["artifacts_root"]])
        isolated.chmod(0o700)
        try:
            self.assertEqual(list(isolated.iterdir()), [])
        finally:
            isolated.chmod(0o300)
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))

    def test_a_dispatch_that_cannot_undo_what_it_made_keeps_its_reservation_until_the_next_removes_it(self):
        for prefix, what in (("r-", "private snapshot copy"), ("call-001-a1-r-", "artifact directory")):
            for landed in ("landed", "not"):
                with self.subTest(prefix=prefix, landed=landed):
                    f = Fixture(self)
                    self.ready_to_dispatch(f)
                    code = self.driver(f, UNDO_FAILS, f"{prefix}:{landed}", *self.dispatch_args())
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                    named = re.search(r"UNVERIFIABLE  could not prepare call 1 attempt 1 \(\[Errno 5\] Input/output "
                                      r"error: '(\S+)'\)", f.last.stderr)
                    self.assertIsNotNone(named, f.last.stderr)
                    final = Path(named[1])
                    self.assertTrue(final.name.startswith(prefix), final)
                    reserve, = (f.rdir / "reviews").glob(".reserve-*")
                    self.assertIn(f"NOTE  could not remove the {what} {final} ([Errno 16] Device or resource busy: "
                                  f"'{final.with_name('.marking-' + final.name)}'); no review used it, and its record "
                                  f"{reserve} is kept so that the next dispatch removes it\n", f.last.stderr)
                    self.assertTrue(os.path.lexists(final.with_name(".marking-" + final.name)))
                    self.assertFalse(os.path.lexists(final))
                    f.tool(*self.dispatch_args())
                    self.assertNotIn("NOTE  could not remove", f.last.stderr)
                    self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                    self.only_made_by(f, f.dispatched(1))

    def test_a_dispatch_killed_while_it_removes_what_it_made_leaves_nothing_the_next_one_keeps(self):
        for arg in ("r-", "call-001-a1-r-", "leftover"):
            with self.subTest(arg=arg):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                if arg == "leftover":
                    f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "before_reserve"}, expect=99)
                proc = self.launch(f, {"PLANLOOP_LOCK_TIMEOUT": "0.5"}, driver=KILLED_REMOVING, arg=arg)
                proc.communicate(timeout=120)
                self.assertEqual(proc.returncode, -signal.SIGKILL)
                self.assertTrue(list((f.rdir / "reviews").glob(".reserve-*")))
                f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertNotIn("NOTE  could not remove", f.last.stderr)
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                self.only_made_by(f, f.dispatched(1))

    def test_a_python_without_ctypes_runs_commands_and_dispatches_nothing_it_cannot_prove(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        self.assertEqual(self.driver(f, NO_CTYPES, "x", "ledger", "--run", RUN), 0, f.last.stdout + f.last.stderr)
        code = self.driver(f, NO_CTYPES, "x", *self.dispatch_args(), env=env)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        self.assertRegex(f.last.stderr, r"UNVERIFIABLE  dispatch runs each review in a systemd scope of this user, .*: "
                         r"a probe scope could not be started and seen \(it runs in \S+/app\.slice/planloop-probe-"
                         r"[0-9a-f]{32}\.scope, which this shell cannot see \(\[Errno 38\] fstatfs cannot be called "
                         r"through ctypes \(.*\), so it cannot be proven procfs: '/proc'\)\); no call was reserved and "
                         r"Codex did not run\n")
        self.assertFalse(pids.exists())
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))
        self.no_probe_left()
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_signal_while_the_admission_waits_for_the_run_lock_gives_the_admission_up_at_once(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        released, free = f.root / "released", f.root / "free"
        try:
            code = self.driver(f, ADMISSION_SIGNALLED, "held", *self.dispatch_args(),
                               env={**env, "PLANLOOP_LOCK_TIMEOUT": "2", "RELEASED": str(released), "FREE": str(free)})
        finally:
            free.write_text("x")
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
        self.assertLess(float(released.read_text()), 4)
        self.assertFalse(pids.exists())
        self.assertIn("NOTE  this dispatch was interrupted by SIGTERM before it let the review runner start, so the "
                      "runner never started and Codex did not run\n", f.last.stderr)
        self.assertIn("FAIL  call 1 attempt 1 was reserved, but this dispatch was interrupted while its admission "
                      "waited for the run lock, so its review runner was not started and Codex did not run; its "
                      "call.json is written and its receipt is not: do not dispatch call 1 attempt 1 again: record it "
                      f"with `receipt --run {RUN} --call 1 --attempt 1` (Codex did not run, so it is recorded invalid)",
                      f.last.stderr)
        self.assertNotIn("CONFLICT", f.last.stderr)
        self.assertNotIn("call 1 attempt 1:", f.last.stdout)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        self.assertTrue((call_dir / "call.json").exists())
        self.assertFalse((call_dir / "receipt.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        f.tool(*self.dispatch_args(2))
        self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_a_signal_during_a_refused_admission_never_replaces_the_refusal(self):
        for sig in ("SIGINT", "SIGTERM", "lost"):
            with self.subTest(sig=sig):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                handled = f.root / "handled"
                code = self.driver(f, ADMISSION_SIGNALLED, sig, *self.dispatch_args(),
                                   env={**env, "HANDLED": str(handled)})
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertNotIn("INTERRUPTED", f.last.stderr)
                self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
                signum = str(int(signal.SIGTERM if sig == "lost" else getattr(signal, sig)))
                self.assertEqual(handled.read_text().split(), [signum] if sig == "lost" else [signum, signum])
                self.assertFalse(pids.exists())
                why = (f"running.json was checked under the run lock, but lock {f.rdir / '.lock'} is no longer ours"
                       if sig == "lost" else f"{f.rdir / 'reviews' / 'call-001-a1' / 'running.json'} no longer names "
                       "this dispatch")
                self.assertIn("CONFLICT  call 1 attempt 1 was reserved, but its review runner was not started and "
                              f"Codex did not run ({why}", f.last.stderr)
                self.assertTrue(f.last.stderr.endswith("): " + self.ADMIT_AFTER), f.last.stderr)
                self.assertIn(f"NOTE  this dispatch was interrupted by {'SIGTERM' if sig == 'lost' else sig} before it "
                              "let the review runner start, so the runner never started and Codex did not run\n",
                              f.last.stderr)
                self.assertNotIn("is stopped again", f.last.stderr)
                self.assertTrue(self.emptied(f))
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1,
                       env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_a_receipt_that_cannot_take_the_run_lock_after_the_runner_ran_says_to_run_receipt(self):
        for mode, code, prefix in (("held", 3, "CONFLICT"), ("readonly", 2, "UNVERIFIABLE")):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                free = f.root / "free"
                try:
                    got = self.driver(f, RECEIPT_LOCKED, mode, *self.dispatch_args(),
                                      env={"PLANLOOP_LOCK_TIMEOUT": "1", "FREE": str(free),
                                           "HELD": str(f.root / "held")})
                finally:
                    free.write_text("x")
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertEqual(got, code, f.last.stdout + f.last.stderr)
                self.assertIn(f"{prefix}  the review runner ran for call 1 attempt 1 (exit 0); its call.json is "
                              "written but its receipt is not (", f.last.stderr)
                self.assertTrue(f.last.stderr.endswith(
                    "): do not dispatch call 1 attempt 1 again (where that says to run the command again, it means "
                    f"`receipt`): record it with `receipt --run {RUN} --call 1 --attempt 1`\n"), f.last.stderr)
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def no_marking_left(self, f):
        calls, isolated = f.state / RUN / "calls", f.isolated_base / "isolated"
        isolated.chmod(0o700)
        try:
            self.assertEqual(list(isolated.iterdir()), [])
        finally:
            isolated.chmod(0o300)
        self.assertEqual([p for p in calls.iterdir() if p.name.startswith(".")], [])
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))

    def test_a_dispatch_stopped_after_its_reservation_landed_leaves_nothing_its_receipt_keeps(self):
        for mode in ("interrupt-busy", "error-busy", "interrupt-kill1", "interrupt-kill2"):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                if "kill" in mode:
                    proc = self.launch(f, {}, driver=PUBLISHED_THEN, arg=mode)
                    proc.communicate(timeout=120)
                    self.assertEqual(proc.returncode, -signal.SIGKILL)
                else:
                    code = self.driver(f, PUBLISHED_THEN, mode, *self.dispatch_args())
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertEqual(code, 130 if mode.startswith("interrupt") else 2, f.last.stdout + f.last.stderr)
                record = f.dispatched(1)
                private, artifacts = Path(record["snapshot"]).parent, Path(record["artifacts_root"])
                left = {"interrupt-kill1": private, "interrupt-kill2": artifacts}.get(mode)
                if left is None:
                    busy = "[Errno 16] Device or resource busy"
                    self.assertIn(f"NOTE  could not remove the private snapshot copy {private} ({busy}: "
                                  f"'{private.with_name('.marking-' + private.name)}') or the artifact directory "
                                  f"{artifacts} ({busy}: '{artifacts.with_name('.marking-' + artifacts.name)}'); no "
                                  f"review used it, and call 1 attempt 1 is reserved in {call_dir}, so `receipt --run "
                                  f"{RUN} --call 1 --attempt 1` removes what is left of its private snapshot copy (an "
                                  "artifact directory left under its own name holds only its .planloop-reserve marker: "
                                  "remove it by hand)\n", f.last.stderr)
                    self.assertNotIn("the next dispatch removes it", f.last.stderr)
                else:
                    self.assertTrue(os.path.lexists(left.with_name(".marking-" + left.name)))
                self.assertFalse((call_dir / "call.json").exists())
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                self.assertNotIn("NOTE  could not remove", f.last.stderr)
                self.no_marking_left(f)
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)
                self.no_marking_left(f)

    def test_a_failing_existence_check_while_a_dispatch_undoes_what_it_made_keeps_its_record(self):
        f = self.f
        self.ready_to_dispatch(f)
        code = self.driver(f, LSTAT_EIO, "fail", *self.dispatch_args())
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
        reserve, = (f.rdir / "reviews").glob(".reserve-*")
        record = json.loads((reserve / "input" / "dispatch.json").read_text())
        private, artifacts = Path(record["snapshot"]).parent, Path(record["artifacts_root"])
        eio = "[Errno 5] Input/output error"
        self.assertIn(f"NOTE  could not remove the private snapshot copy {private} ({eio}: "
                      f"'{private.with_name('.marking-' + private.name)}') or the artifact directory {artifacts} "
                      f"({eio}: '{artifacts.with_name('.marking-' + artifacts.name)}'); no review used it, and its "
                      f"record {reserve} is kept so that the next dispatch removes it\n", f.last.stderr)
        self.assertIn(f"UNVERIFIABLE  could not prepare call 1 attempt 1 ({eio}: '{artifacts}'); no call was "
                      f"reserved and Codex did not run, but its record {reserve} is kept so that the next dispatch "
                      "removes it: run the command again once the path it names can be read and written\n",
                      f.last.stderr)
        self.assertNotIn("nothing was reserved", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        code = self.driver(f, LSTAT_EIO, "always", *self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "before_reserve"})
        self.assertEqual(code, 99, f.last.stdout + f.last.stderr)
        self.assertIn("NOTE  could not remove what a dispatch that ended before it reserved its call left (",
                      f.last.stderr)
        self.assertIn(f"its record {reserve} is kept so that the next dispatch removes it\n", f.last.stderr)
        self.assertTrue(reserve.exists())
        f.tool(*self.dispatch_args())
        self.assertNotIn("NOTE  could not remove", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.only_made_by(f, f.dispatched(1))

    def test_a_reserve_marker_that_is_a_link_keeps_the_reservation_and_says_how_to_repair_it(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "before_reserve"}, expect=99)
        reserve, = (f.rdir / "reviews").glob(".reserve-*")
        private = Path(json.loads((reserve / "input" / "dispatch.json").read_text())["snapshot"]).parent
        elsewhere = f.root / "elsewhere"
        elsewhere.write_text(reserve.name)
        (private / ".planloop-reserve").unlink()
        (private / ".planloop-reserve").symlink_to(elsewhere)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertIn(f"NOTE  could not remove what a dispatch that ended before it reserved its call left ([Errno 40] "
                      f"Too many levels of symbolic links; it is not a marker planloop wrote, so {private} is kept: "
                      f"remove it by hand once no planloop process runs if it is a leftover: "
                      f"'{private / '.planloop-reserve'}'); no review used it, and its record {reserve} is kept",
                      f.last.stderr)
        self.assertTrue(reserve.is_dir())
        self.assertTrue(private.is_dir())
        (private / ".planloop-reserve").unlink()
        (private / ".planloop-reserve").write_text(reserve.name)
        f.tool(*self.dispatch_args(), expect=1)
        self.assertFalse(reserve.exists())
        self.assertFalse(os.path.lexists(private))

    def test_a_dispatch_whose_attempt_was_taken_before_its_runner_started_never_starts_it(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for mode in ("receipted", "removed", "replaced", "receipt_written", "locked"):
            with self.subTest(mode=mode):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                code = self.driver(f, TAKEN_BEFORE_THE_RUNNER, mode, *self.dispatch_args(), env=env)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertFalse(pids.exists(), "the runner started although something else had taken its attempt")
                self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
                self.assertIn("CONFLICT  call 1 attempt 1 was reserved, but its review runner was not started and Codex "
                              "did not run (" + (f"{f.rdir / '.lock'} is held by " if mode == "locked" else
                                                 f"{call_dir / 'running.json'} no longer names this dispatch, or the "
                                                 "attempt's receipt.json is written: something else took the attempt): "
                                                 + self.ADMIT_AFTER), f.last.stderr)
                if mode == "locked":
                    self.assertTrue(f.last.stderr.endswith("): " + self.ADMIT_AFTER), f.last.stderr)
                self.assertEqual((call_dir / "receipt.json").exists(), mode in ("receipted", "receipt_written"))
                self.assertFalse((call_dir / "call.json").exists())
                self.assertTrue(self.emptied(f))
                if mode == "receipt_written":
                    continue
                f.tool(*receipt, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                f.tool(*receipt, expect=1)
                self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
                f.tool(*self.dispatch_args(2))
                self.assertIn("call 1 attempt 2: counted", f.last.stdout)

    def test_another_boot_is_told_from_another_host_only_by_a_machine_id_both_sides_read(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f = self.f
        self.ready_to_dispatch(f)
        self.assertEqual(self.driver(f, VIEWED, json.dumps({"machine_id": None}), *self.dispatch_args(),
                                     env={"PLANLOOP_CRASH_AT": "after_runner"}), 99, f.last.stdout + f.last.stderr)
        self.assertIsNone(f.dispatched(1)["view"]["machine_id"])
        call_dir, unit, boot = f.rdir / "reviews" / "call-001-a1", self.unit(f), f.dispatched(1)["view"]["boot_id"]
        code = self.driver(f, VIEWED, json.dumps({"machine_id": None, "boot_id": "another-boot"}), *receipt)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn(f"CONFLICT  call 1 attempt 1 cannot be recorded yet: {unit} is the systemd scope of its review, "
                      f"and this command does not see cgroups as its dispatch did (boot_id: dispatch.json records "
                      f"{boot!r}, here 'another-boot'; machine_id: none is recorded and none reads here, so another "
                      "boot of this host cannot be told from another host), so a scope that is absent here may still "
                      "hold a process there; nothing was recorded: ", f.last.stderr)
        self.assertIn(f"; if there is none any more (the host was renamed, its machine id changed or cannot be read), "
                      f"check by hand that nothing runs in that scope (`systemd-cgls --user-unit {unit}` lists no "
                      f"process, or says the unit is not found), then remove {call_dir} (what it records of the "
                      "attempt is discarded) and dispatch call 1 attempt 1 again\n", f.last.stderr)
        self.assertFalse((call_dir / "receipt.json").exists())
        self.assertEqual(self.driver(f, VIEWED, json.dumps({"machine_id": None}), *receipt), 0,
                         f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_call_that_cannot_be_checked_where_it_ran_is_recovered_by_hand_as_advised(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        code = self.driver(f, VIEWED, json.dumps({"host": "renamed"}), "receipt", "--run", RUN, "--call", "1",
                           "--attempt", "1")
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn(f"then remove {call_dir} (what it records of the attempt is discarded) and dispatch call 1 "
                      "attempt 1 again\n", f.last.stderr)
        listed = subprocess.run(["systemd-cgls", "--user-unit", self.unit(f)], capture_output=True, text=True)
        self.assertIn("not found", listed.stdout + listed.stderr)
        for dirpath, dirnames, filenames in os.walk(call_dir):
            os.chmod(dirpath, 0o755)
        shutil.rmtree(call_dir)
        self.assertEqual(self.driver(f, VIEWED, json.dumps({"host": "renamed"}), *self.dispatch_args()), 0,
                         f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_the_probe_is_not_held_to_the_stop_grace_and_does_not_hold_the_run_lock(self):
        f = self.f
        self.ready_to_dispatch(f)
        probing = f.root / "probing"
        env = self.fake_systemd_run(f, SYSTEMD_RUN_PROBE.replace("PROBE", f"echo x > {shlex.quote(str(probing))}\nsleep 4"))
        proc = self.launch(f, env, driver=GRACE, arg="1")
        try:
            self.wait_for(probing)
            f.tool("state", "--run", RUN, "--set", "active", "--reason", "set while a dispatch probes")
            self.assertNotIn("Traceback", f.last.stderr)
            code, out, err = self.finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertNotIn("Traceback", err)
        self.assertEqual(code, 0, out + err)
        self.assertIn("call 1 attempt 1: counted", out)
        self.no_probe_left()

    def test_a_probe_that_hangs_or_does_not_end_is_given_up_in_bounded_time_and_reserves_nothing(self):
        hangs = SYSTEMD_RUN_PROBE.replace("PROBE", 'sleep 60 &\necho $! > "$RUNNER_PIDS"\nwait')
        for case in ("hangs", "does_not_end"):
            with self.subTest(case=case):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                env, pids = self.runner_env(f, MARKING_RUNNER)
                started, began = [], time.monotonic()
                try:
                    code = self.driver(f, PROBE_BOUNDS, "x" if case == "hangs" else "import time\ntime.sleep(300)",
                                       *self.dispatch_args(),
                                       env={**env, **(self.fake_systemd_run(f, hangs) if case == "hangs" else {})})
                    took = time.monotonic() - began
                    if case == "hangs":
                        started = self.started(pids, 1)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertEqual(code, 2, f.last.stdout + f.last.stderr)
                    self.assertLess(took, 20, "dispatch waited for a probe it had given up")
                    self.assertIn("UNVERIFIABLE  dispatch runs each review in a systemd scope of this user",
                                  f.last.stderr)
                    if case == "hangs":
                        self.assertRegex(f.last.stderr, r": a probe scope could not be started and seen \(systemd-run "
                                         r"did not move it into \S+/planloop-probe-[0-9a-f]{32}\.scope within 1 "
                                         r"seconds\); no call was reserved and Codex did not run\n")
                    else:
                        self.assertRegex(f.last.stderr, r": the probe scope planloop-probe-[0-9a-f]{32}\.scope did not "
                                         r"end once it was released \(1 process still runs in it \(\d+ is `\S+ -I -c "
                                         r"import time time\.sleep\(300\) \d+ \S+`\)\), and was killed; no call was "
                                         r"reserved and Codex did not run\n")
                    self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
                    self.no_probe_left()
                finally:
                    self.stop_all(started)

    def test_a_directory_that_held_a_private_copy_name_before_a_killed_dispatch_is_never_removed(self):
        f = self.f
        self.ready_to_dispatch(f)
        taken, held = f.isolated_base / "isolated" / "r-fixed", f.state / RUN / "calls" / "call-001-a1-r-fixed"
        (taken / "repo").mkdir(parents=True)
        (taken / "repo" / "kept.txt").write_text("kept\n")
        held.mkdir(parents=True)
        proc = self.launch(f, {}, driver=KILLED_AT_PRIVATE)
        proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, -signal.SIGKILL)
        reserve, = (f.rdir / "reviews").glob(".reserve-*")
        self.assertEqual(json.loads((reserve / "input" / "dispatch.json").read_text())["snapshot"], str(taken / "repo"))
        f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertFalse(list((f.rdir / "reviews").glob(".reserve-*")))
        self.assertEqual((taken / "repo" / "kept.txt").read_text(), "kept\n")
        self.assertTrue(held.is_dir())

    def test_a_leftover_whose_private_copy_cannot_be_removed_keeps_its_record_until_it_can(self):
        f = self.f
        self.ready_to_dispatch(f)
        f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "before_reserve"}, expect=99)
        reserve, = (f.rdir / "reviews").glob(".reserve-*")
        record = json.loads((reserve / "input" / "dispatch.json").read_text())
        private, made = Path(record["snapshot"]).parent, Path(record["artifacts_root"])
        self.assertEqual((private / ".planloop-reserve").read_text(), reserve.name)
        self.assertEqual((made / ".planloop-reserve").read_text(), reserve.name)
        stuck = private.with_name(f".marking-{private.name}")
        code = self.driver(f, COPY_STUCK, str(stuck), *self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5"})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        self.assertIn("NOTE  could not remove what a dispatch that ended before it reserved its call left ([Errno 5] "
                      f"Input/output error: '{stuck}'); no review used it, and its record {reserve} is kept so that "
                      "the next dispatch removes it\n", f.last.stderr)
        self.assertTrue(reserve.is_dir())
        self.assertTrue(os.path.lexists(stuck))
        self.assertFalse(os.path.lexists(private))
        self.assertFalse(made.exists())
        f.tool(*self.dispatch_args(), expect=1)
        self.assertFalse(reserve.exists())
        self.assertFalse(os.path.lexists(stuck))

    def test_a_signal_module_in_the_working_directory_is_never_run_by_the_gate(self):
        f = self.f
        self.ready_to_dispatch(f)
        marker = f.root / "imported"
        (f.repo / "signal.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
        f.tool(*self.dispatch_args(), expect=None)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertFalse(marker.exists(), "the gate imported signal.py from the directory dispatch ran in")
        self.assertEqual(f.last.returncode, 0, f.last.stdout + f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_path_that_is_not_utf8_stops_the_command_before_anything_is_reserved(self):
        f = self.f
        self.ready_to_dispatch(f)
        bad = str(f.root / "bad\udcff")
        for case, what in (("PLANLOOP_ISOLATED", "the directory of private snapshot copies (PLANLOOP_ISOLATED)"),
                           ("PLANLOOP_STATE", "the state directory (PLANLOOP_STATE)"), ("repo", "the repository")):
            with self.subTest(case=case):
                cwd, env, shown = f.repo, {**f.env, case: bad}, bad if case == "PLANLOOP_ISOLATED" else f"{bad}/{RUN}"
                if case == "repo":
                    try:
                        os.rename(f.repo, bad)
                    except OSError:
                        self.skipTest("this filesystem holds no name that is not UTF-8")
                    cwd, env, shown = bad, f.env, bad
                proc = subprocess.run([sys.executable, str(TOOL), *self.dispatch_args()], cwd=cwd, env=env,
                                      capture_output=True, timeout=300)
                err = proc.stderr.decode("utf-8", "replace")
                self.assertNotIn("Traceback", err)
                self.assertEqual(proc.returncode, 2, err)
                self.assertIn(f"UNVERIFIABLE  {what} is {shown!a}, a path that is not UTF-8, which planloop's records "
                              "cannot hold; nothing was read or changed: use a UTF-8 path\n", err)
        if os.path.lexists(bad):
            os.rename(bad, f.repo)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        self.assertFalse((f.isolated_base / "isolated").exists())
        f.tool(*self.dispatch_args())
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_scope_kill_that_fails_is_not_reported_as_a_kill(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, ESCAPED_RUNNER)
        proc = self.launch(f, env, driver=KILL_FAILS)
        started = []
        try:
            started = self.started(pids, 2)
            unit, scope = self.unit(f), f.dispatched(1)["scope"]
            proc.send_signal(signal.SIGTERM)
            code, out, err = self.finish(proc)
            self.assertNotIn("Traceback", err)
            self.assertEqual(code, 3, out + err)
            self.assertIn(f"NOTE  this dispatch could not kill the review's scope {unit} (writing its cgroup.kill, "
                          "which kills every process in it, failed: [Errno 13] Permission denied: "
                          f"'{scope}/cgroup.kill')\n", err)
            self.assertNotIn("this dispatch killed the review's scope", err)
            self.systemctl(f, "KILL")
            self.assertTrue(self.emptied(f))
        finally:
            self.stop_all(started)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)

    def test_a_test_run_started_as_a_module_also_turns_sigterm_into_an_interrupt(self):
        proc = subprocess.run([sys.executable, "-c", "import signal, sys\nsys.path.insert(0, sys.argv[1])\n"
                               "import test_planloop\n"
                               "print(signal.getsignal(signal.SIGTERM) is signal.default_int_handler)", str(HERE)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual((proc.stdout, proc.stderr), ("True\n", ""))

    def test_a_recorded_path_that_is_not_text_stops_receipt_cleanly(self):
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        for name, key, value in (("dispatch.json", "artifacts_root", "/x/\udcff"), ("dispatch.json", "scope", "/x\0y"),
                                 ("dispatch.json", "artifacts_root", "/x/a\0b"), ("dispatch.json", "snapshot", "/s\0"),
                                 ("dispatch.json", "live_repo", "\udcff"), ("call.json", "artifacts", "/x/a\0b"),
                                 ("call.json", "artifacts", "/x/\udcff"), ("running.json", "scope", "/x/\udcff\0")):
            with self.subTest(name=name, key=key, value=value):
                f = Fixture(self)
                self.ready_to_dispatch(f)
                f.tool(*self.dispatch_args(), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
                call_dir = f.rdir / "reviews" / "call-001-a1"
                path = call_dir / ("input" if name == "dispatch.json" else "") / name
                path.chmod(0o644)
                path.write_text(json.dumps({**json.loads(path.read_text()), key: value}))
                f.tool(*receipt, expect=None)
                self.assertNotIn("Traceback", f.last.stderr)
                if name == "dispatch.json":
                    self.assertEqual(f.last.returncode, 1, f.last.stderr)
                    self.assertIn(f"FAIL  dispatch.json.{key}: not a path", f.last.stderr)
                    self.assertFalse((call_dir / "receipt.json").exists())
                elif name == "call.json":
                    self.assertEqual(f.last.returncode, 1, f.last.stderr)
                    self.assertIn("FAIL  call.json does not read (its artifacts is not a path), so the runner's result "
                                  "is not recorded for this call and the attempt is invalid", f.last.stdout)
                else:
                    self.assertEqual(f.last.returncode, 0, f.last.stderr)
                    self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_start_that_fails_while_something_holds_its_pipes_is_not_waited_for(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, MARKING_RUNNER)
        started, began = [], time.monotonic()
        try:
            code = self.driver(f, GRACE, "1", *self.dispatch_args(),
                               env={**env, **self.fake_systemd_run(f, SYSTEMD_RUN_HOLDS_PIPES)})
            took = time.monotonic() - began
            started = self.started(pids, 1)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertEqual(code, 1, f.last.stdout + f.last.stderr)
            self.assertFalse(gone(started[0]))
            self.assertLess(took, 20, "dispatch waited for a process that held the pipes of a start that had failed")
            self.assertIn(f"NOTE  the review runner could not be started in its scope {self.unit(f)} (systemd-run did "
                          f"not move it into {f.dispatched(1)['scope']} within 1 seconds); Codex did not run\n",
                          f.last.stderr)
            self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        finally:
            self.stop_all(started)

    def test_a_scope_killed_after_the_runner_exited_is_waited_for_until_it_is_empty(self):
        f = self.f
        self.ready_to_dispatch(f)
        env, pids = self.runner_env(f, STRAGGLING_RUNNER, str(HERE / "fake_runner.py"))
        started = []
        try:
            code = self.driver(f, SLOW_KILL, "1.5", *self.dispatch_args(), env=env)
            started = self.started(pids, 2)
            self.assertNotIn("Traceback", f.last.stderr)
            self.assertEqual(code, 0, f.last.stdout + f.last.stderr)
            self.assertIn("call 1 attempt 1: counted", f.last.stdout)
            self.assertTrue(gone(started[1]))
            self.assertIn(f"NOTE  this dispatch killed the review's scope {self.unit(f)} (cgroup.kill, which kills "
                          "every process in it), after the review runner had exited\n", f.last.stderr)
        finally:
            self.stop_all(started)

    def test_what_a_dispatch_killed_while_it_copied_the_snapshot_left_is_removed_by_the_next_dispatch(self):
        f = self.f
        self.ready_to_dispatch(f)
        proc = self.launch(f, {}, driver=KILLED_AT_COPY)
        proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, -signal.SIGKILL)
        calls, isolated = f.state / RUN / "calls", f.isolated_base / "isolated"
        f.tool(*self.dispatch_args(), env={"PLANLOOP_LOCK_TIMEOUT": "0.5", "PLANLOOP_CRASH_AT": "after_runner"},
               expect=99)
        self.assertNotIn("Traceback", f.last.stderr)
        record = f.dispatched(1)
        self.assertEqual([str(p) for p in calls.iterdir()], [record["artifacts_root"]])
        isolated.chmod(0o700)
        self.assertEqual([str(p) for p in isolated.iterdir()], [str(Path(record["snapshot"]).parent)])
        isolated.chmod(0o300)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_an_interrupted_test_run_leaves_no_scope_and_no_fixture_behind(self):
        script = self.f.root / "interrupted.py"
        script.write_text(INTERRUPTED_RUN)
        proc = subprocess.run([sys.executable, str(script), str(Path(__file__).resolve())], capture_output=True,
                              text=True, timeout=300)
        scope, root, *pids = proc.stdout.split()
        self.addCleanup(self.stop_all, [int(p) for p in pids])
        self.assertIn("KeyboardInterrupt", proc.stderr)
        self.assertRegex(Path(scope).name, r"^planloop-.*\.scope$")
        self.assertFalse(Path(scope).exists(), "an interrupted test run left a review scope behind")
        self.assertFalse(Path(root).exists())
        for pid in pids:
            self.assertTrue(self.wait_gone(int(pid)))


class ErrorContract(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_an_array_or_object_in_an_enum_field_is_a_fail_from_shape(self):
        tool = load_tool()
        for value in (["Mike"], {"by": "Mike"}, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(tool.Fail) as caught:
                    tool.shape({"by": value}, {"by": {"Mike"}}, "S1.json")
                self.assertEqual(str(caught.exception), f"S1.json.by: {value!r} not one of ['Mike']")
        self.assertEqual(tool.shape({"by": "Mike"}, {"by": {"Mike"}}, "S1.json"), {"by": "Mike"})

    def test_a_size_decision_with_an_array_or_object_in_an_enum_field_fails_gate_and_dispatch_cleanly(self):
        f = self.f
        f.init()
        f.publish(1, plan_text(1))
        for field, value in (("by", ["Mike"]), ("by", {"name": "Mike"}), ("schema", ["planloop-size-decision/1"])):
            with self.subTest(field=field, value=value):
                f.size_decision("S1", 1, T, **{field: value})
                f.tool("gate", "--run", RUN, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn("FAIL  [mechanical] size decision S1.json well formed", f.last.stdout)
                self.assertIn(f"S1.json.{field}: {value!r} not one of", f.last.stdout)
                f.review(review(), kind="gate", effort="high", expect=1)
                f.call -= 1
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"FAIL  size decision S1.json is malformed: S1.json.{field}: {value!r} not one of",
                              f.last.stderr)
                self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        c = f.review(review("REVISE", [finding("F1", "low")]))
        self.assertNotIn("Traceback", f.last.stderr)
        f.ingest(c, {"F1": "new"})

    def test_an_array_or_object_as_a_rollout_effort_is_unverifiable(self):
        tool = load_tool()
        for effort in (["medium"], {"effort": "medium"}):
            with self.subTest(effort=effort):
                path = self.f.root / f"rollout-{uuid.uuid4().hex[:6]}.jsonl"
                path.write_text("\n".join(json.dumps(r) for r in (
                    {"type": "session_meta", "payload": {"id": "s1", "cwd": "/x"}},
                    {"type": "turn_context", "payload": {"model": "m", "effort": effort,
                                                         "sandbox_policy": {"type": "read-only"}}})) + "\n")
                with self.assertRaises(tool.Unverifiable) as caught:
                    tool.parse_rollout(path, "s1", "prompt", "", check_version=False)
                self.assertEqual(str(caught.exception), "turn_context lacks model, effort or sandbox_policy")

    def test_a_write_error_while_building_a_bundle_publishes_nothing_and_the_next_bundle_succeeds(self):
        for where, code in ((r"/meaning-r2/after\.md$", "ENOSPC"), (r"/meaning-r2/index\.md$", "EIO"),
                            (r"/frozen/discovery\.json$", "EIO"), (r"/manifest\.json$", "ENOSPC"),
                            (r"/\.staging-002-[0-9a-f]+/revision\.json$", "ENOSPC"), (r"/\.bundle-tmp-[0-9a-f]{8}$", "EIO")):
            with self.subTest(where=where, code=code):
                f = Fixture(self)
                nonce = PolicyReviewFixes.shrink_staged(self, f)
                staging = f.rdir / f".staging-002-{nonce}"
                args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
                self.assertEqual(PolicyReviewFixes.driver(self, f, WRITE_FAILS, f"{where}|{code}", *args), 2,
                                 f.last.stdout + f.last.stderr)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertRegex(f.last.stderr, r"UNVERIFIABLE  could not read or write \S+"
                                 + where.split("/")[-1].rstrip("$"))
                self.assertIn(os.strerror(getattr(errno, code)), f.last.stderr)
                self.assertIn("nothing was published: run the command again once that path can be read and written",
                              f.last.stderr)
                self.assertFalse(probe_any(staging / "bundle"))
                self.assertFalse(list(staging.glob(".bundle-tmp-*")))
                self.assertFalse(probe_any(staging / "revision.json"))
                self.assertFalse(list(staging.glob(".revision.json.tmp-*")))
                self.assertFalse(probe_any(f.state / RUN / f"snap-r002-{nonce}"))
                f.tool(*args)
                self.assertTrue((f.state / RUN / f"snap-r002-{nonce}").is_dir())
                f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
                self.assertEqual(f.head(), 2)


class ErrorContractIO(unittest.TestCase):
    def drive(self, f, text, arg, *args, code=2):
        self.assertEqual(PolicyReviewFixes.driver(self, f, text, arg, *args), code, f.last.stdout + f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        return f.last.stdout + f.last.stderr

    def test_a_write_error_while_staging_a_handback_leaves_nothing_and_the_same_handback_succeeds_again(self):
        for where, code in ((r"/\.staging-001-[0-9a-f]+$", "EIO"), (r"/\.staging-001-[0-9a-f]+/plan\.md$", "ENOSPC"),
                            (r"/\.staging-001-[0-9a-f]+/handback\.json$", "ENOSPC")):
            with self.subTest(where=where):
                f = Fixture(self)
                f.init()
                nonce = uuid.uuid4().hex[:16]
                transcript = f.transcript(f.wrap(1, nonce, plan_text(1)))
                args = ("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript", str(transcript))
                out = self.drive(f, WRITE_FAILS, f"{where}|{code}", *args)
                self.assertRegex(out, rf"UNVERIFIABLE  could not stage revision 1 in \S+/\.staging-001-{nonce} \(")
                self.assertIn(os.strerror(getattr(errno, code)), out)
                self.assertIn("nothing was staged: run the command again once it can be written", out)
                self.assertFalse(probe_any(f.rdir / f".staging-001-{nonce}"))
                f.tool(*args)
                self.assertEqual((f.rdir / f".staging-001-{nonce}" / "plan.md").read_text(), plan_text(1))

    def test_a_write_error_on_a_whole_file_record_is_unverifiable_and_changes_nothing(self):
        f = Fixture(self)
        init = ("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "none",
                "--rationale", "test importer change with no persistence or ordering semantics")
        out = self.drive(f, WRITE_FAILS, r"/run\.json$|EIO", *init)
        self.assertRegex(out, r"UNVERIFIABLE  could not write \S+/run\.json \(\[Errno 5\] Input/output error")
        self.assertIn("the run was not created", out)
        self.assertEqual(sorted(p.name for p in f.rdir.glob("*")) if f.rdir.exists() else [], [])
        f.init()
        before = (f.rdir / "run.json").read_bytes()
        reviewers = ("reviewers", "--run", RUN, "--model", "gpt-6-sol", "--gate-model", "gpt-6-sol", "--quote", "use sol")
        out = self.drive(f, WRITE_FAILS, r"/run\.json$|ENOSPC", *reviewers)
        self.assertRegex(out, r"UNVERIFIABLE  could not write \S+/run\.json \(\[Errno 28\]")
        self.assertIn("the model change was not recorded", out)
        self.assertEqual((f.rdir / "run.json").read_bytes(), before)
        self.assertFalse(list(f.rdir.glob(".run.json.tmp-*")))
        f.tool(*reviewers)
        f.publish(1, plan_text(1))
        out = self.drive(f, WRITE_FAILS, r"/ledger\.md$|EIO", "ledger", "--run", RUN)
        self.assertRegex(out, r"UNVERIFIABLE  could not write \S+/ledger\.md \(\[Errno 5\]")
        self.assertFalse(probe_any(f.rdir / "ledger.md"))
        f.tool("ledger", "--run", RUN)
        self.assertTrue((f.rdir / "ledger.md").is_file())
        f.review(review(), mode="rollout_version=0.160.0", expect=None)
        adir = f.receipt(1)["artifacts"]["dir"]
        versions = f.versions.read_bytes()
        out = self.drive(f, WRITE_FAILS, r"/versions\.txt$|ENOSPC", "rollout-check", "--artifacts", adir, "--accept")
        self.assertRegex(out, r"UNVERIFIABLE  could not write \S+/versions\.txt \(\[Errno 28\]")
        self.assertIn("Codex 0.160.0 was not accepted", out)
        self.assertEqual(f.versions.read_bytes(), versions)
        f.versions.unlink()
        f.tool("rollout-check", "--artifacts", adir, "--accept")
        self.assertTrue(f.versions.read_text().startswith("0.160.0 "))
        (Path(adir) / "prompt.txt").write_bytes(b"\xff\xfe")
        f.tool("rollout-check", "--artifacts", adir, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  runner prompt.txt: not UTF-8", f.last.stderr)

    def test_a_read_error_while_building_a_bundle_is_unverifiable_and_the_next_bundle_succeeds(self):
        for kind, where, said in (("read", r"/plans/brief\.md$", "UNREADABLE  brief plans/brief.md could not be read ("),
                                  ("copy", r"/repo/src/a\.rs$", "UNVERIFIABLE  could not read or write ")):
            with self.subTest(kind=kind):
                f = Fixture(self)
                f.init()
                (f.repo / "src" / "a.rs").write_text("fn main() { }\n")
                nonce = f.hand(1, plan_text(1))
                args = ("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()))
                out = self.drive(f, READ_FAILS, f"{kind}|{where}|EIO", *args)
                self.assertIn(said, out)
                self.assertIn("Input/output error", out)
                self.assertNotIn("could not write", out)
                staging = f.rdir / f".staging-001-{nonce}"
                self.assertFalse(probe_any(staging / "bundle"))
                self.assertFalse(list(staging.glob(".bundle-tmp-*")))
                self.assertFalse(probe_any(f.state / RUN / f"snap-r001-{nonce}"))
                f.tool(*args)
                f.tool("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
                self.assertEqual(f.head(), 1)

    def test_an_obligation_source_that_is_missing_or_not_utf8_fails_the_bundle_cleanly(self):
        for case, said in (("missing", "FAIL  docs/req.md: missing or not a file"),
                           ("binary", "FAIL  obligation OB1: docs/req.md is not UTF-8"),
                           ("plan", "FAIL  staged plan.md: missing or not a file"),
                           ("handback", "FAIL  handback.json: not an object")):
            with self.subTest(case=case):
                f = Fixture(self)
                f.init()
                nonce = f.hand(1, plan_text(1))
                req, staging = f.repo / "docs" / "req.md", f.rdir / f".staging-001-{nonce}"
                if case == "missing":
                    req.unlink()
                elif case == "binary":
                    req.write_bytes(b"\xff\xfe" + OBLIGATION.encode())
                elif case == "plan":
                    (staging / "plan.md").unlink()
                else:
                    (staging / "handback.json").write_text("[]")
                f.tool("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()), expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(said, f.last.stderr)

    def test_a_bundle_whose_cleanup_fails_says_what_to_remove_and_the_next_bundle_succeeds_once_it_is_gone(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        staging = f.rdir / f".staging-002-{nonce}"
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        out = self.drive(f, BUNDLE_STUCK, r"/\.staging-002-[0-9a-f]+/revision\.json$|ENOSPC", *args)
        self.assertRegex(out, r"UNVERIFIABLE  could not write \S+/revision\.json \(\[Errno 28\] [^)]*\), and could not "
                         r"remove the bundle it was for, \S+/bundle \(\[Errno 16\] [^)]*\); nothing was published: remove "
                         rf"\S+/\.staging-002-{nonce}/bundle by hand, then run the command again")
        self.assertFalse(probe_any(staging / "revision.json"))
        self.assertFalse(probe_any(f.state / RUN / f"snap-r002-{nonce}"))
        shutil.rmtree(staging / "bundle")
        f.tool(*args)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)

    def test_a_rollout_copy_that_cannot_be_kept_records_nothing_and_receipt_records_it_later(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review()))
        args = ("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium")
        out = self.drive(f, OPEN_FAILS, r"/\.?rollout\.jsonl|ENOSPC", *args)
        self.assertRegex(out, r"could not keep a copy of Codex's session record \S+ as \S+/rollout\.jsonl "
                         r"\(\[Errno 28\]")
        call = f.rdir / "reviews" / "call-001-a1"
        self.assertFalse(probe_any(call / "receipt.json"))
        adir = Path(json.loads((call / "call.json").read_text())["artifacts"])
        self.assertFalse(probe_any(adir / "rollout.jsonl"))
        self.assertFalse(list(adir.glob(".rollout.jsonl.tmp-*")))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertEqual(f.receipt(1)["status"], "counted", f.receipt(1)["reasons"])

    def test_a_malformed_turn_context_value_is_unverifiable(self):
        tool = load_tool()
        good = {"model": "m", "effort": "medium", "sandbox_policy": {"type": "read-only"}, "approval_policy": "never"}
        for change, said in (({"sandbox_policy": {"type": ["read-only"]}}, "turn_context sandbox_policy type or "
                              "approval_policy is not a string"),
                             ({"approval_policy": {"never": True}}, "turn_context sandbox_policy type or "
                              "approval_policy is not a string"),
                             ({"collaboration_mode": ["plan"]}, "turn_context collaboration_mode has an unfamiliar shape"),
                             ({"collaboration_mode": {"settings": ["x"]}},
                              "turn_context collaboration_mode has an unfamiliar shape")):
            with self.subTest(change=change):
                path = Fixture(self).root / "rollout.jsonl"
                path.write_text("\n".join(json.dumps(r) for r in (
                    {"type": "session_meta", "payload": {"id": "s1", "cwd": "/x"}},
                    {"type": "turn_context", "payload": {**good, **change}})) + "\n")
                with self.assertRaises(tool.Unverifiable) as caught:
                    tool.parse_rollout(path, "s1", "prompt", "", check_version=False)
                self.assertEqual(str(caught.exception), said)

    def test_a_malformed_planner_transcript_is_refused_in_its_category(self):
        nonce = "0123456789abcdef"
        call = {"type": "tool_use", "id": "toolu_1", "name": "SubagentHandback", "input": {"message": "x"}}
        result = {"type": "tool_result", "tool_use_id": "toolu_1",
                  "content": [{"type": "text", "text": '{"success":true}'}]}

        def rows(c, r):
            return [{"type": "assistant", "message": {"content": [c]}}, {"type": "user", "message": {"content": [r]}}]
        not_string = "transcript format not recognised: a SubagentHandback call or tool_result has an id that is not a string"
        cases = (("result id an array", rows(call, {**result, "tool_use_id": ["toolu_1"]}), 2, not_string),
                 ("call id an object", rows({**call, "id": {"x": 1}}, result), 2, not_string),
                 ("input an array", rows({**call, "input": ["message"]}, result), 2, "handback input has no message string"),
                 ("a bare number row", [3, {"type": "assistant", "message": {"stop_reason": "end_turn", "content": []}}],
                  1, "handback must contain exactly one start and one end marker"),
                 ("message an array", [{"type": "assistant", "message": ["end_turn"]}], 2,
                  "transcript format not recognised: no handback call and no end_turn message"),
                 ("end_turn content a string", [{"type": "assistant", "message": {"stop_reason": "end_turn",
                                                                                   "content": "plan"}}], 2,
                  "transcript format not recognised: the last end_turn message's content is not a list of text blocks"),
                 ("end_turn text an array", [{"type": "assistant", "message": {"stop_reason": "end_turn", "content": [
                     {"type": "text", "text": ["plan"]}]}}], 2,
                  "transcript format not recognised: the last end_turn message's content is not a list of text blocks"),
                 ("meta an array", None, 1, "agent meta is not an object"))
        f = Fixture(self)
        f.init()
        for name, value, code, said in cases:
            with self.subTest(name=name):
                path = f.transcript("x", name=uuid.uuid4().hex[:8])
                if value is None:
                    path.with_name(path.name[:-len(".jsonl")] + ".meta.json").write_text("[]")
                else:
                    path.write_text("\n".join(json.dumps(r) for r in value) + "\n")
                f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript", str(path),
                       expect=code)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(said, f.last.stderr)
        f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
               str(f.root / "agents" / "agent-gone.jsonl"), expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        (f.root / "agents" / "agent-gone.meta.json").write_text(json.dumps({"finished": True, "agentType": "Plan"}))
        f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript",
               str(f.root / "agents" / "agent-gone.jsonl"), expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("transcript: missing or not a file", f.last.stderr)
        f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript", str(f.transcript("x")),
               "--draft", str(f.root / f"planloop-draft-{nonce}.md"), expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("draft file: missing or not a file", f.last.stderr)

    def test_a_hand_edited_receipt_fails_findings_check_and_ledger_naming_it(self):
        for name, change in (("coverage missing", lambda r: r.pop("coverage")),
                             ("finding id an array", lambda r: r["findings"].append(
                                 {"id": ["R1"], "severity": "low", "path": "p", "evidence": "e", "fix": "f"})),
                             ("requested an array", lambda r: r.update(requested=["medium"])),
                             ("effective an array", lambda r: r.update(effective=["high"])),
                             ("requested without effort", lambda r: r["requested"].pop("effort"))):
            with self.subTest(name=name):
                f = Fixture(self)
                f.to_gate_ready()
                path = f.rdir / "reviews" / "call-002-a1" / "receipt.json"
                record = json.loads(path.read_text())
                change(record)
                path.write_text(json.dumps(record))
                for args in (("findings", "check", "--run", RUN), ("ledger", "--run", RUN)):
                    f.tool(*args, expect=1)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertIn("call-002-a1/receipt.json is not a planloop receipt", f.last.stdout + f.last.stderr)
        f = Fixture(self)
        f.to_gate_ready()
        path = f.rdir / "reviews" / "call-002-a1" / "receipt.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "status": "invalid", "coverage": 5, "findings": 5}))
        f.tool("findings", "check", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  R1: receipt reviews/call-002-a1/receipt.json does not show a counted 'finding R1: "
                      "resolved' for it", f.last.stdout)
        f.tool("ledger", "--run", RUN)

    def test_a_hand_edited_bundle_manifest_or_published_handback_fails_receipt_and_propose_cleanly(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        c = f.review(review("REVISE", [finding("F1")]))
        manifest = f.rdir / "rev-001" / "bundle" / "manifest.json"
        kept = manifest.read_bytes()
        manifest.write_text("[]")
        f.tool("receipt", "--run", RUN, "--call", str(c), "--attempt", "1", expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  revision 1 bundle manifest does not match the bundle_sha256 it was published and "
                      "dispatched with", f.last.stderr)
        manifest.write_bytes(kept)
        f.ingest(c, {"F1": "new"})
        nonce = f.stage(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        handback = f.rdir / "rev-002" / "handback.json"
        handback.write_text(json.dumps({**json.loads(handback.read_text()), "answers": {"R9": "FIX"}}))
        f.tool("findings", "propose", "--run", RUN, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNVERIFIABLE  revision 2: revision 2 handback.json does not match", f.last.stderr)
        self.assertFalse(probe_any(f.rdir / "intents" / "propose-r002.json"))

    def test_an_evidence_record_that_is_not_an_object_fails_cleanly(self):
        f = Fixture(self)
        f.init()
        path = f.root / "ev.json"
        path.write_text("[]")
        f.tool("evidence", "--run", RUN, str(path), expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  evidence ?: not an object", f.last.stderr)

    def test_a_hand_edited_intent_fails_cleanly_and_is_not_applied(self):
        f = Fixture(self)
        f.to_gate_ready()
        intent = f.rdir / "intents" / "ingest-call-001-a1.json"
        for value in ([], {"schema": "planloop-intent/1", "name": "x", "state": ["verified"], "ops": []},
                      {"schema": "planloop-intent/1", "name": "x", "state": "planned", "ops": {"key": "x"}},
                      {"schema": "planloop-intent/1", "name": "x", "state": "planned", "ops": [{"key": ["run:x"]}]}):
            with self.subTest(value=value):
                intent.write_text(json.dumps(value))
                for args in (("findings", "check", "--run", RUN), ("publish", "--run", RUN, "--recover")):
                    f.tool(*args, expect=1)
                    self.assertNotIn("Traceback", f.last.stderr)
                    self.assertIn(f"intent {intent.name} is not a planloop intent (", f.last.stdout + f.last.stderr)
                    self.assertEqual(json.loads(intent.read_text()), value)

    def test_malformed_planloop_metadata_in_beads_fails_cleanly(self):
        f = Fixture(self)
        f.to_gate_ready()
        clean = f.bd()
        for kind, key, value in (("finding", "planloop_raised_call", "one"), ("finding", "planloop_finding", "R"),
                                 ("run", "planloop_redesigns", "R1:x"), ("run", "planloop_active_after_call", "x")):
            with self.subTest(key=key):
                db = json.loads(json.dumps(clean))
                bead = next(i for i in db["issues"].values() if i["metadata"].get("planloop_key") ==
                            (f"finding:{RUN}:R1" if kind == "finding" else f"run:{RUN}"))
                bead["metadata"][key] = value
                f.set_bd(db)
                f.tool("findings", "check", "--run", RUN, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"{kind} bead {bead['id']} holds malformed planloop metadata ({key}={value!r})",
                              f.last.stdout + f.last.stderr)
        f.set_bd(clean)
        f.tool("findings", "check", "--run", RUN)

    def test_a_probe_scope_seen_ending_is_not_rechecked_into_its_teardown(self):
        tool = load_tool()
        seen, calls = [], ["1 process still runs in it", None,
                           "whether a process still runs in it cannot be checked ([Errno 19] No such device)"]

        class Proc:
            def kill(self):
                seen.append("kill")

            def communicate(self, timeout=None):
                return b"", b""

        def start(argv, scope, child, what, wait):
            read, write = os.pipe()
            os.close(read)
            return Proc(), write
        tool.start_scoped, tool.scope_left = start, lambda scope: calls.pop(0) if calls else None
        tool.kill_scope = lambda scope: seen.append("kill_scope")
        tool.shutil = type("S", (), {"which": staticmethod(lambda name: "/usr/bin/" + name)})
        self.assertEqual(tool.scope_ready(), tool.view())
        self.assertEqual(seen, [])
        self.assertEqual(len(calls), 1)

    def test_a_stray_io_error_is_unverifiable_not_a_traceback(self):
        f = Fixture(self)
        f.init()
        out = self.drive(f, STRAY_OSERROR, "-", "ledger", "--run", RUN)
        self.assertIn("UNVERIFIABLE  [Errno 5] Input/output error: '/nowhere/ledger.md'", out)

    def corrupted(self, f, attempt, code, expect=1):
        wrapper = f.root / "corrupting_runner.py"
        wrapper.write_text(CORRUPTING_RUNNER)
        f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", str(attempt), "--kind", "working", "--effort",
               "medium", expect=expect, env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}",
                                             "CORRUPT": code})
        self.assertNotIn("Traceback", f.last.stderr)
        return f.receipt(1, attempt)

    def test_a_runner_artifact_that_is_not_utf8_records_the_attempt_invalid_and_the_next_attempt_runs(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review()))
        for attempt, name in ((1, "stdout.txt"), (2, "prompt.txt")):
            with self.subTest(name=name):
                record = self.corrupted(f, attempt, f"(adir / {name!r}).write_bytes(b'\\xff\\xfe')")
                self.assertEqual((record["status"], record["infrastructure"]), ("invalid", True))
                self.assertEqual(record["reasons"], [f"runner artifact {name}: not UTF-8"])
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", str(attempt), expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"FAIL  runner artifact {name}: not UTF-8", f.last.stdout)
        f.review(review(), call=1, attempt=3)
        self.assertEqual(f.receipt(1, 3)["status"], "counted", f.receipt(1, 3)["reasons"])

    def test_a_malformed_runner_output_records_the_attempt_invalid_with_a_reason(self):
        result = "p = adir / 'result.json'\nr = json.loads(p.read_text())\n{}\np.write_text(json.dumps(r))"
        cases = ((result.format("r['cli_version'] = 5"), "result.json cli_version is not a string or null"),
                 (result.format("r['cli_version'] = '  '"), "Codex CLI '  ' has not been validated"),
                 (result.format("r['response']['findings'] = 5"), "findings not a list"),
                 (result.format("r['response']['findings'] = [{'id': ['R1'], 'severity': 'low', 'path': 'p', "
                                "'evidence': 'e', 'fix': 'f'}]"), "malformed finding"),
                 ("p = adir / 'result.json'\np.write_text(p.read_text().replace('\"input_tokens\": 10', "
                  "'\"input_tokens\": 1e400', 1))",
                  "runner result.json: non-finite JSON number 1e400"),
                 ("p = adir / 'result.json'\np.write_text(p.read_text().replace('\"exit_code\": 0', "
                  "'\"exit_code\": 1' + '0' * 5000))", "runner result.json: malformed JSON (Exceeds the limit"),
                 ("(adir / 'reply.txt').write_text('[' * 100000)", "reply.txt: malformed JSON (maximum recursion"),
                 ("(adir / 'stdout.txt').write_text('1' + '0' * 5000 + '\\n' + (adir / 'stdout.txt').read_text())",
                  "stdout event 1: malformed JSON (Exceeds the limit"),
                 ("r = next(Path(os.environ['PLANLOOP_CODEX_SESSIONS']).rglob('rollout-*.jsonl'))\n"
                  "r.write_text(r.read_text() + '[' * 100000 + '\\n')", "effective settings unverifiable: rollout line "))
        for i in range(0, len(cases), 2):
            f = Fixture(self)
            f.init()
            f.publish(1, plan_text(1))
            f.review_file.write_text(json.dumps(review()))
            for attempt, (code, said) in enumerate(cases[i:i + 2], 1):
                with self.subTest(said=said):
                    record = self.corrupted(f, attempt, code)
                    self.assertEqual(record["status"], "invalid")
                    self.assertTrue(any(said in r for r in record["reasons"]), record["reasons"])
            f.review(review(), call=1, attempt=attempt + 1)
            self.assertEqual(f.receipt(1, attempt + 1)["status"], "counted", f.receipt(1, attempt + 1)["reasons"])

    def test_a_hand_edited_dispatch_record_or_feedback_is_refused_without_a_traceback(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        f.tool("findings", "propose", "--run", RUN)
        c = f.review(review(coverage=["plan read in full", *f.lines_for(2)]))
        call = f.rdir / "reviews" / f"call-{c:03d}-a1"
        dispatch, feedback = call / "input" / "dispatch.json", call / "input" / "feedback.md"
        kept = dispatch.read_bytes(), feedback.read_bytes()
        record = json.loads(kept[0])
        args = ("receipt", "--run", RUN, "--call", str(c), "--attempt", "1")
        for change, said in ((lambda r: r.update(expected_coverage=[["R1"]]),
                              "FAIL  dispatch.json expected_coverage is not a list of finding ids"),
                             (lambda r: r["meaning_check"][0].update(units=[["## Design"]]),
                              "FAIL  dispatch.json meaning_check is not a list of meaning obligations")):
            with self.subTest(said=said):
                edited = json.loads(json.dumps(record))
                change(edited)
                dispatch.write_text(json.dumps(edited))
                f.tool(*args, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(said, f.last.stderr)
        feedback.write_bytes(b"\xff\xfe" + kept[1])
        dispatch.write_text(json.dumps({**record, "feedback_sha256": hashlib.sha256(feedback.read_bytes()).hexdigest()}))
        f.tool(*args, expect=3)
        self.assertNotIn("Traceback", f.last.stderr)
        dispatch.write_bytes(kept[0])
        feedback.write_bytes(kept[1])
        f.tool(*args)

    def test_a_stray_io_error_without_a_path_or_after_a_reservation_says_what_to_run(self):
        f = Fixture(self)
        f.init()
        out = self.drive(f, STRAY_PIPE, "-", "ledger", "--run", RUN)
        self.assertIn("UNVERIFIABLE  [Errno 32] Broken pipe; what this command had written stands: run it again once "
                      "its cause is cleared, it re-checks what is on disk", out)
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review()))
        out = self.drive(f, STRAY_AFTER_RESERVE, "-", "dispatch", "--run", RUN, "--call", "1", "--attempt", "1",
                         "--kind", "working", "--effort", "medium")
        call_dir = f.rdir / "reviews" / "call-001-a1"
        self.assertIn(f"UNVERIFIABLE  [Errno 32] Broken pipe; what this command had written stands: if {call_dir} "
                      "exists now, do not dispatch call 1 attempt 1 again: run `receipt --run "
                      f"{RUN} --call 1 --attempt 1`", out)
        self.assertTrue(call_dir.is_dir())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(f.receipt(1)["status"], "invalid")
        f.review(review(), call=1, attempt=2)

    def test_hand_edited_finding_severity_or_state_is_refused_as_malformed(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        c = f.review(review("REVISE", [finding("F1")]))
        f.ingest(c, {"F1": "new"})
        clean = f.bd()

        def set_meta(key, value):
            db = json.loads(json.dumps(clean))
            bead = next(i for i in db["issues"].values() if i["metadata"].get("planloop_key") == f"finding:{RUN}:R1")
            bead["metadata"][key] = value
            f.set_bd(db)
            return bead["id"]
        for key, value in (("planloop_severity", "HIGH"), ("planloop_severity", ""), ("planloop_state", "bogus"),
                           ("planloop_state", "")):
            with self.subTest(key=key, value=value):
                bead = set_meta(key, value)
                f.check(plan_text(2), 1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"finding bead {bead} holds malformed planloop metadata ({key}={value!r})",
                              f.last.stdout + f.last.stderr)
        f.set_bd(clean)
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        c = f.review(review("REVISE", [finding("R1", "low")]))
        clean = f.bd()
        for value in ("HIGH", ""):
            with self.subTest(ingest=value):
                bead = set_meta("planloop_severity", value)
                f.ingest(c, {"R1": "R1"}, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"finding bead {bead} holds malformed planloop metadata (planloop_severity={value!r})",
                              f.last.stderr)
                self.assertFalse(probe_any(f.rdir / "intents" / f"ingest-call-{c:03d}-a1.json"))
        f.set_bd(clean)
        f.ingest(c, {"R1": "R1"})
        self.assertEqual(f.finding_bead("R1")["metadata"]["planloop_severity"], "high")

    def test_an_interrupted_or_killed_handback_can_be_handed_back_again(self):
        f = Fixture(self)
        f.init()
        nonce = uuid.uuid4().hex[:16]
        transcript = f.transcript(f.wrap(1, nonce, plan_text(1)))
        args = ("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript", str(transcript))
        staging = f.rdir / f".staging-001-{nonce}"
        out = self.drive(f, STOPPED_AT, r"/\.staging-001-[0-9a-f]+/handback\.json$|", *args, code=130)
        self.assertIn("INTERRUPTED  stopped by SIGINT before the command finished; what it had written stands: run it "
                      "again", out)
        self.assertFalse(probe_any(staging))
        staging.mkdir()
        (staging / "plan.md").write_text("partial")
        f.tool(*args, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  {staging} already exists, without handback.json: a handback with this nonce was killed "
                      "while staging it (or is staging it now); once no planloop command runs, remove it, then run "
                      "the command again", f.last.stderr)
        shutil.rmtree(staging)
        f.tool(*args)
        f.tool(*args, expect=1)
        self.assertEqual(f.last.stderr, f"FAIL  {staging} already exists\n")

    def test_a_bundle_stopped_before_revision_json_leaves_nothing_or_says_what_to_remove(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        staging, snap = f.rdir / f".staging-002-{nonce}", f.state / RUN / f"snap-r002-{nonce}"
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        self.drive(f, STOPPED_AT, r"/\.staging-002-[0-9a-f]+/revision\.json$|", *args, code=130)
        self.assertFalse(probe_any(staging / "bundle"))
        self.assertFalse(probe_any(staging / "revision.json"))
        self.assertFalse(list(staging.glob(".bundle-tmp-*")))
        self.assertFalse(probe_any(snap))
        f.tool(*args)
        (staging / "revision.json").unlink()
        f.tool(*args, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  staging already has a bundle, but no revision.json: a bundle was killed before it "
                      f"finished; remove {staging / 'bundle'}, then run the command again", f.last.stderr)
        shutil.rmtree(staging / "bundle")
        out = self.drive(f, STOPPED_AT, r"/\.staging-002-[0-9a-f]+/revision\.json$|landed", *args, code=130)
        self.assertIn("INTERRUPTED  stopped by SIGINT before the command finished; what it had written stands: "
                      "revision 2's bundle is complete and its revision.json is in place: publish it", out)
        self.assertTrue((staging / "revision.json").is_file())
        self.assertTrue(snap.is_dir())
        f.tool(*args, expect=1)
        self.assertEqual(f.last.stderr, f"FAIL  {BUNDLED}\n")
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertEqual(f.head(), 2)
        f.tool("findings", "propose", "--run", RUN)
        f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def test_two_bundles_of_one_staging_never_share_a_snapshot(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        self.drive(f, CONCURRENT_BUNDLE, "-", *args, code=0)
        other = json.loads(next(l for l in f.last.stderr.splitlines() if l.startswith('{"other"')))
        self.assertEqual(other["other"], 3, other["said"])
        self.assertRegex(other["said"], rf"CONFLICT  \S+/{RUN}/\.lock-bundle is held by")
        self.assertIn("took it and is alive: wait for it to finish", other["said"])
        self.assertTrue((f.state / RUN / f"snap-r002-{nonce}").is_dir())
        self.assertFalse(probe_any(f.state / RUN / ".lock-bundle"))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        f.tool("findings", "propose", "--run", RUN)
        f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def paused(self, f, text, *args, prefix=()):
        path, flag = f.root / f"driver-{uuid.uuid4().hex[:6]}.py", str(f.root / f"pause-{uuid.uuid4().hex[:6]}")
        path.write_text(text)
        proc = subprocess.Popen([*prefix, sys.executable, str(path), str(TOOL), flag, *args], cwd=f.repo, env=f.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        while not Path(flag + ".at").exists():
            self.assertIsNone(proc.poll(), "the paused command ended before its pause")
            time.sleep(0.05)

        def release():
            Path(flag + ".go").write_text("x")
            out, err = proc.communicate(timeout=300)
            self.assertNotIn("Traceback", err)
            return proc.returncode or json.loads(out.strip().splitlines()[-1])["code"], out + err
        return release

    def test_a_bundle_that_waited_for_the_lock_while_its_revision_was_published_or_removed_touches_nothing(self):
        for how in ("published", "removed"):
            with self.subTest(how=how):
                f = Fixture(self)
                nonce = PolicyReviewFixes.shrink_staged(self, f)
                staging, snap = f.rdir / f".staging-002-{nonce}", f.state / RUN / f"snap-r002-{nonce}"
                args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
                if how == "removed":
                    release = self.paused(f, PAUSED_AT_BUNDLE_LOCK, *args)
                    shutil.rmtree(staging)
                    code, out = release()
                    self.assertEqual(code, 1, out)
                    self.assertIn(f"FAIL  {staging.name} is gone or was never staged (HEAD is revision 1); nothing was "
                                  "changed", out)
                    self.assertFalse(probe_any(staging))
                    self.assertFalse(probe_any(snap))
                    continue
                f.tool(*args)
                release = self.paused(f, PAUSED_AT_BUNDLE_LOCK, *args)
                f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
                before = tree(snap)
                code, out = release()
                self.assertEqual(code, 1, out)
                self.assertIn("FAIL  revision 2 is already published (HEAD is revision 2); nothing was changed", out)
                self.assertEqual(tree(snap), before)
                self.assertTrue(snap.is_dir())
                self.assertFalse(probe_any(staging))
                self.assertFalse(list((f.rdir / "rev-002").glob(".bundle-tmp-*")))
                f.tool("findings", "propose", "--run", RUN)
                f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def test_a_publish_waits_for_a_bundle_still_finishing_so_its_snapshot_is_never_removed_after_publication(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        staging, snap = f.rdir / f".staging-002-{nonce}", f.state / RUN / f"snap-r002-{nonce}"
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        publish = ("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        release = self.paused(f, STOPPED_AFTER_REVISION, *args)
        f.tool(*publish, expect=3)
        self.assertRegex(f.last.stderr, rf"^CONFLICT  \S+/{RUN}/\.lock-bundle is held by")
        self.assertIn("took it and is alive: wait for it to finish", f.last.stderr)
        self.assertEqual(f.head(), 1)
        self.assertTrue((staging / "revision.json").is_file())
        self.assertFalse(probe_any(f.rdir / "rev-002"))
        self.assertFalse(probe_any(f.rdir / ".lock"))
        code, out = release()
        self.assertEqual(code, 130, out)
        self.assertIn("what it had written stands: revision 2's bundle is complete and its revision.json is in "
                      "place: publish it", out)
        self.assertTrue(snap.is_dir())
        f.tool(*publish)
        self.assertEqual(f.head(), 2)
        self.assertTrue(snap.is_dir())
        f.tool("findings", "propose", "--run", RUN)
        f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def test_a_bundle_never_runs_while_a_publish_is_verifying_and_moving_its_staging(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        snap = f.state / RUN / f"snap-r002-{nonce}"
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool(*args)
        before = tree(snap)
        release = self.paused(f, PAUSED_AT_STAGING_VERIFY, "publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        f.tool(*args, expect=3)
        self.assertRegex(f.last.stderr, rf"^CONFLICT  \S+/{RUN}/\.lock-bundle is held by")
        self.assertIn("took it and is alive: wait for it to finish", f.last.stderr)
        code, out = release()
        self.assertEqual(code, 0, out)
        self.assertEqual(f.head(), 2)
        self.assertEqual(tree(snap), before)
        self.assertFalse(probe_any(f.state / RUN / ".lock-bundle"))
        f.tool("findings", "propose", "--run", RUN)
        f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def test_a_revision_restaged_while_its_publication_is_interrupted_is_not_bundled_over_its_snapshot(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        nonce = uuid.uuid4().hex[:16]
        hand = ("handback", "--run", RUN, "--revision", "2", "--nonce", nonce, "--transcript",
                str(f.transcript(f.wrap(2, nonce, plan_text(2)))))
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        snap = f.state / RUN / f"snap-r002-{nonce}"
        f.tool(*hand)
        f.tool(*args)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=None)
        self.assertTrue((f.rdir / "rev-002").is_dir())
        self.assertEqual(f.head(), 1)
        before = tree(snap)
        f.tool(*hand)
        f.tool(*args, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  rev-002 exists and HEAD is revision 1: a publication of revision 2 was interrupted; "
                      f"nothing was changed: run `publish --run {RUN} --recover`, which completes it or moves it aside "
                      "to be re-staged", f.last.stderr)
        self.assertEqual(tree(snap), before)
        self.assertFalse(probe_any(f.rdir / f".staging-002-{nonce}" / "bundle"))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, expect=3)
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertIn("NOTE  recovered interrupted publication of revision 2", f.last.stderr)
        self.assertIn("CONFLICT  revision 2 is already published from another staging", f.last.stderr)
        self.assertEqual(f.head(), 2)
        self.assertEqual(tree(snap), before)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertEqual(f.head(), 2)
        self.assertFalse(list(f.rdir.glob(".lock-broken-*")) + list((f.state / RUN).glob(".lock-broken-*")))
        f.tool("findings", "propose", "--run", RUN)
        f.review(review())

    def test_a_revision_json_write_that_reports_an_error_but_landed_says_the_bundle_is_publishable(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        staging, snap = f.rdir / f".staging-002-{nonce}", f.state / RUN / f"snap-r002-{nonce}"
        args = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        (staging / ".revision.json.tmp-0123abcd").write_text("{")
        out = self.drive(f, REPLACE_LANDED_EIO, "revision.json", *args)
        self.assertIn("UNVERIFIABLE  [Errno 5] Input/output error: ", out)
        self.assertIn("; what this command had written stands: revision 2's bundle is complete and its revision.json "
                      "is in place: publish it", out)
        self.assertNotIn("nothing was published", out)
        self.assertTrue(snap.is_dir())
        self.assertFalse(list(staging.glob(".*tmp-*")))
        f.tool(*args, expect=1)
        self.assertEqual(f.last.stderr, f"FAIL  {BUNDLED}\n")
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        self.assertFalse(list((f.rdir / "rev-002").glob(".*tmp-*")))
        f.tool("findings", "propose", "--run", RUN)
        f.review(review(coverage=["plan read in full", *f.lines_for(2)]))

    def test_a_handback_that_lost_the_race_to_stage_its_nonce_says_so_and_leaves_the_other_alone(self):
        f = Fixture(self)
        f.init()
        nonce = uuid.uuid4().hex[:16]
        staging = f.rdir / f".staging-001-{nonce}"
        out = self.drive(f, STAGED_MEANWHILE, "-", "handback", "--run", RUN, "--revision", "1", "--nonce", nonce,
                         "--transcript", str(f.transcript(f.wrap(1, nonce, plan_text(1)))), code=1)
        self.assertIn(f"FAIL  {staging} already exists: another handback with this nonce staged it, or is staging "
                      "it, while this one ran; this one staged nothing and left it alone", out)
        self.assertNotIn("run the command again", out)
        self.assertEqual((staging / "plan.md").read_text(), "theirs")

    def test_a_hand_edited_receipt_finding_severity_is_refused_before_it_reaches_a_bead(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        c = f.review(review("REVISE", [finding("F1")]))
        f.ingest(c, {"F1": "new"})
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        c = f.review(review("REVISE", [finding("R1", "low"), finding("F2", "low")]))
        path = f.rdir / "reviews" / f"call-{c:03d}-a1" / "receipt.json"
        clean, beads = path.read_text(), f.bd()
        for which, value in ((0, "HIGH"), (1, "critical"), (1, "")):
            with self.subTest(which=which, value=value):
                record = json.loads(clean)
                record["findings"][which]["severity"] = value
                path.write_text(json.dumps(record))
                f.ingest(c, {"R1": "R1", "F2": "new"}, expect=1)
                self.assertNotIn("Traceback", f.last.stderr)
                self.assertIn(f"FAIL  {path} is not a planloop receipt for call {c} attempt 1 (its verdict, coverage "
                              "or findings are not the shape of a verified review)", f.last.stderr)
                self.assertFalse(probe_any(f.rdir / "intents" / f"ingest-call-{c:03d}-a1.json"))
                self.assertEqual(f.bd(), beads)
        path.write_text(clean)
        f.ingest(c, {"R1": "R1", "F2": "new"})
        self.assertEqual(f.finding_bead("R2")["metadata"]["planloop_severity"], "low")


def probe_any(path):
    return path.exists() or path.is_symlink()


class Scope(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_a_scope_is_one_cgroup_of_this_users_manager_named_for_the_run_and_the_artifact_directory(self):
        uid = os.getuid()
        scope = self.tool.scope_of(RUN, "/state/qz/calls/call-001-a1-r-abcdefgh")
        self.assertRegex(scope, rf"^/sys/fs/cgroup/user\.slice/user-{uid}\.slice/user@{uid}\.service/app\.slice/"
                         rf"planloop-{re.escape(RUN)}-call-001-a1-r-abcdefgh-[0-9a-f]{{32}}\.scope$")
        self.assertNotEqual(scope, self.tool.scope_of("qz-abd.pl1", "/state/qz/calls/call-001-a1-r-abcdefgh"))
        self.assertNotEqual(scope, self.tool.scope_of(RUN, "/other/qz/calls/call-001-a1-r-abcdefgh"))
        self.assertEqual(os.path.dirname(self.tool.scope_of(RUN, "/x/../../etc")), os.path.dirname(scope))
        for value in (None, 7, "", " ", [], {}, "/x/\udcff", "/x\0y"):
            self.assertIsNone(self.tool.scope_of(RUN, value))

    def faked(self):
        root = Path(tempfile.mkdtemp(prefix="planloop-cgroup-"))
        self.addCleanup(shutil.rmtree, root, True)

        def rooted():
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            return fd, self.tool.mount_of(fd)
        self.tool.CGROUP, self.tool.cgroup_root, self.tool.scope_base = str(root), rooted, lambda: f"{root}/base"
        scope = root / "base" / "app.slice" / "planloop-x.scope"
        scope.mkdir(parents=True)
        return scope

    def test_a_scope_is_empty_only_when_its_events_say_so(self):
        scope = self.faked()
        (scope / "cgroup.procs").write_text(f"{os.getpid()}\n")
        for events, empty in (("populated 0\nfrozen 0\n", True), ("populated 1\nfrozen 0\n", False), ("", False),
                              ("frozen 0\n", False)):
            with self.subTest(events=events):
                (scope / "cgroup.events").write_text(events)
                left = self.tool.scope_left(str(scope))
                if empty:
                    self.assertIsNone(left)
                else:
                    self.assertRegex(left, rf"^1 process still runs in it \({os.getpid()} is `\S*python\S* .*`\)$")
        (scope / "cgroup.procs").write_text("")
        self.assertEqual(self.tool.scope_left(str(scope)), "some processes still run in it")

    def test_a_scope_that_is_gone_is_empty_only_while_this_users_manager_cgroup_can_be_seen(self):
        scope = self.tool.scope_of(RUN, f"/nowhere/{uuid.uuid4().hex}")
        self.assertIsNone(self.tool.scope_left(scope))
        base = self.tool.scope_base()
        self.tool.scope_base = lambda: f"{os.path.dirname(base)}/user@planloop-no-such-manager.service"
        scope = self.tool.scope_of(RUN, f"/nowhere/{uuid.uuid4().hex}")
        self.assertEqual(self.tool.scope_left(scope), "whether a process still runs in it cannot be checked ([Errno 2] "
                         f"No such file or directory: '{self.tool.scope_base()}')")
        scope = self.faked()
        shutil.rmtree(scope.parent)
        self.assertIsNone(self.tool.scope_left(str(scope)))
        shutil.rmtree(scope.parent.parent)
        self.assertEqual(self.tool.scope_left(str(scope)), "whether a process still runs in it cannot be checked ([Errno 2] "
                         f"No such file or directory: '{scope.parent.parent}')")

    def test_a_scope_is_read_only_through_the_cgroup2_mount_of_this_cgroup_namespaces_root(self):
        mine = "/sys/fs/cgroup" + Path("/proc/self/cgroup").read_text().strip().removeprefix("0::")
        self.assertIn(str(os.getpid()), self.tool.scope_pids(mine))
        self.assertIsNone(self.tool.unseen(mine, os.getpid()))
        self.assertEqual(self.tool.unseen(mine, 1), f"it runs in {mine}, where this shell does not see it")
        self.assertEqual(self.tool.unseen("/sys/fs/kernel/x", 1), "it runs in /sys/fs/kernel/x, which this shell cannot "
                         "see ([Errno 18] another filesystem is mounted over it: '/sys/fs/cgroup/..')")
        self.assertEqual(self.tool.scope_left("/sys/fs/kernel/planloop-x.scope"), "whether a process still runs in it "
                         "cannot be checked ([Errno 18] another filesystem is mounted over it: '/sys/fs/cgroup/..')")
        fd, mount = self.tool.cgroup_root()
        self.addCleanup(os.close, fd)
        with self.assertRaisesRegex(OSError, r"^\[Errno 18\] another filesystem is mounted over it: 'named'$"):
            self.tool.enter(fd, "cgroup.procs", "0", "named", 0)
        os.close(self.tool.enter(fd, "cgroup.procs", mount, "named", 0))
        root = Path(tempfile.mkdtemp(prefix="planloop-cgroup-"))
        self.addCleanup(shutil.rmtree, root, True)
        for other in (str(root), "/proc"):
            self.tool.CGROUP = other
            self.assertEqual(self.tool.scope_left(f"{other}/planloop-x.scope"), "whether a process still runs in it "
                             f"cannot be checked ([Errno 18] not a cgroup2 mount of this cgroup namespace's root: "
                             f"'{other}')")

    def test_a_cgroup_mount_seen_from_another_cgroup_namespace_is_not_this_namespaces_root(self):
        if Path("/proc/self/cgroup").read_text().strip() == "0::/":
            self.skipTest("this process runs in the root cgroup, so a new cgroup namespace has the same root")
        code = ("import importlib.util, os, sys\nspec = importlib.util.spec_from_file_location('planloop', sys.argv[1])\n"
                "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                "os.close(tool.cgroup_root()[0])\nos.unshare(os.CLONE_NEWUSER | os.CLONE_NEWCGROUP)\n"
                "try:\n    tool.cgroup_root()\nexcept OSError as exc:\n    print(exc)")
        proc = subprocess.run([sys.executable, "-c", code, str(TOOL)], capture_output=True, text=True, timeout=60)
        if "unshare" in proc.stderr:
            self.skipTest("this user cannot create a user and cgroup namespace")
        self.assertEqual((proc.stdout, proc.stderr), ("[Errno 18] not a cgroup2 mount of this cgroup namespace's root: "
                                                      "'/sys/fs/cgroup'\n", ""))

    def test_a_marker_proves_a_directory_only_to_the_reservation_that_wrote_it(self):
        made = Path(tempfile.mkdtemp(prefix="planloop-made-"))
        self.addCleanup(shutil.rmtree, made, True)
        self.assertFalse(self.tool.reserved_by(made, ".reserve-a"))
        (made / ".planloop-reserve").write_text(".reserve-a")
        self.assertTrue(self.tool.reserved_by(made, ".reserve-a"))
        self.assertFalse(self.tool.reserved_by(made, ".reserve-b"))
        self.assertFalse(self.tool.reserved_by(made / ".planloop-reserve", ".reserve-a"))
        self.assertFalse(self.tool.reserved_by(made / "gone", ".reserve-a"))
        (made / ".planloop-reserve").write_bytes(b"\xff")
        self.assertFalse(self.tool.reserved_by(made, ".reserve-a"))
        (made / ".planloop-reserve").unlink()
        (made / ".planloop-reserve").mkdir()
        with self.assertRaisesRegex(OSError, r"^\[Errno 22\] not a regular file; it is not a marker planloop wrote"):
            self.tool.reserved_by(made, ".reserve-a")

    def bounded(self, call, unblock):
        out = []

        def run():
            try:
                out.append(call())
            except Exception as exc:
                out.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(10)
        if thread.is_alive():
            unblock()
            thread.join(10)
            self.fail("a read blocked on a FIFO")
        return out[0]

    def test_a_marker_that_is_a_fifo_a_link_or_too_large_is_refused_without_blocking(self):
        made = Path(tempfile.mkdtemp(prefix="planloop-made-"))
        self.addCleanup(shutil.rmtree, made, True)
        marker = made / ".planloop-reserve"
        os.mkfifo(marker)
        got = self.bounded(lambda: self.tool.reserved_by(made, ".reserve-a"),
                           lambda: os.close(os.open(marker, os.O_WRONLY | os.O_NONBLOCK)))
        kept = f"; it is not a marker planloop wrote, so {made} is kept: remove it by hand once no planloop process runs " \
            f"if it is a leftover: '{marker}'"
        self.assertEqual(str(got), "[Errno 22] not a regular file" + kept)
        marker.unlink()
        (made / "elsewhere").write_text(".reserve-a")
        marker.symlink_to(made / "elsewhere")
        self.assertEqual(str(self.bounded(lambda: self.tool.reserved_by(made, ".reserve-a"), lambda: None)),
                         "[Errno 40] Too many levels of symbolic links" + kept)
        marker.unlink()
        marker.write_text(".reserve-a" + " " * 5000)
        self.assertEqual(str(self.bounded(lambda: self.tool.reserved_by(made, ".reserve-a"), lambda: None)),
                         "[Errno 27] larger than 4096 bytes" + kept)

    def test_a_control_file_that_is_a_fifo_a_link_or_too_large_is_refused_without_blocking(self):
        scope = self.faked()
        events, procs, cannot = scope / "cgroup.events", scope / "cgroup.procs", "whether a process still runs in it " \
            "cannot be checked "
        os.mkfifo(events)
        self.assertEqual(self.bounded(lambda: self.tool.scope_left(str(scope)),
                                      lambda: os.close(os.open(events, os.O_WRONLY | os.O_NONBLOCK))),
                         cannot + f"([Errno 22] not a regular file: '{events}')")
        events.unlink()
        (scope / "real").write_text("populated 0\n")
        events.symlink_to(scope / "real")
        self.assertEqual(self.tool.scope_left(str(scope)), cannot + "([Errno 40] Too many levels of symbolic links: "
                         f"'{events}')")
        events.unlink()
        events.write_text("populated 1\n")
        procs.write_text(f"{os.getpid()}\n" * (1 << 20))
        self.assertEqual(self.tool.scope_left(str(scope)), cannot + f"([Errno 27] larger than 1048576 bytes: '{procs}')")

    def scope_that_ends(self, wait="0.5"):
        unit = f"planloop-test-{uuid.uuid4().hex}.scope"
        scope = f"{self.tool.scope_base()}/app.slice/{unit}"
        proc = subprocess.Popen(self.tool.scoped(unit, "planloop test") + ["sleep", wait])
        self.addCleanup(lambda: proc.poll() is None and (proc.kill(), proc.wait()))
        for _ in range(2000):
            with contextlib.suppress(OSError):
                if "populated 1" in Path(scope, "cgroup.events").read_text().splitlines():
                    return proc, scope
            time.sleep(0.005)
        self.fail("the test scope never appeared")

    def test_a_scope_removed_once_its_directory_was_entered_is_gone_not_unreadable(self):
        plain = self.tool.enter
        for name in ("cgroup.events", "cgroup.procs"):
            with self.subTest(name=name):
                proc, scope = self.scope_that_ends("60")
                hit = []

                def enter(fd, entry, mount, path, flags=os.O_DIRECTORY):
                    if entry == name and not flags & os.O_DIRECTORY and not hit:
                        hit.append(proc.poll())
                        proc.kill()
                        proc.wait(timeout=10)
                        for _ in range(1000):
                            if not os.path.isdir(scope):
                                break
                            time.sleep(0.01)
                        else:
                            raise AssertionError("the scope's directory was never removed")
                    return plain(fd, entry, mount, path, flags)
                self.tool.enter = enter
                try:
                    self.assertIsNone(self.tool.scope_left(scope))
                finally:
                    self.tool.enter = plain
                self.assertEqual(hit, [None], "the scope was not removed while its control file was being opened")
                self.assertFalse(os.path.isdir(scope))
        scope = self.faked()
        (scope / "cgroup.events").write_text("populated 1\n")
        plain_read = self.tool.read_small

        def removed(fd, path, *a, remove=True):
            if not path.endswith("/cgroup.events"):
                return plain_read(fd, path, *a)
            if remove:
                shutil.rmtree(scope)
            raise OSError(errno.ENODEV, "No such device", path)
        self.tool.read_small = removed
        self.assertIsNone(self.tool.scope_left(str(scope)))
        scope.mkdir()
        (scope / "cgroup.events").write_text("populated 1\n")
        self.tool.read_small = lambda fd, path, *a: removed(fd, path, *a, remove=False)
        self.assertEqual(self.tool.scope_left(str(scope)), "whether a process still runs in it cannot be checked "
                         f"([Errno 19] No such device: '{scope}/cgroup.events')")
        self.tool.read_small = plain_read

    def test_a_proc_that_is_not_procfs_or_names_no_mount_id_is_refused(self):
        mine = "/sys/fs/cgroup" + Path("/proc/self/cgroup").read_text().strip().removeprefix("0::")
        cannot = "whether a process still runs in it cannot be checked "
        fake = Path(tempfile.mkdtemp(prefix="planloop-proc-"))
        self.addCleanup(shutil.rmtree, fake, True)
        (fake / "self").mkdir()
        (fake / "self" / "mountinfo").write_bytes(Path("/proc/self/mountinfo").read_bytes())
        self.tool.PROC = str(fake)
        self.assertEqual(self.tool.scope_left(mine), cannot + f"([Errno 18] not procfs: '{fake}')")
        self.tool.PROC = "/proc"
        plain = self.tool.proc_text
        for said in ("pos:\t0\nmnt_id:\n", "mnt_id:\tx1\n", "mnt_id:\t1 2\n"):
            with self.subTest(said=said):
                self.tool.proc_text = lambda rel: said if rel.startswith("self/fdinfo/") else plain(rel)
                self.assertRegex(self.tool.scope_left(mine), "^" + re.escape(cannot) + r"\(\[Errno 95\] the kernel does "
                                 r"not say which mount it is on: '/proc/self/fdinfo/\d+'\)$")
        self.tool.proc_text = plain
        code = (UNSHARED.replace("json.loads(arg)", "json.loads(sys.argv[3])") + "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\n"
                "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                "mounted()\nprint(tool.scope_left(sys.argv[2]))")
        copy = fake / "mountinfo"
        copy.write_bytes(Path("/proc/self/mountinfo").read_bytes())
        proc = subprocess.run([sys.executable, "-c", "import importlib.util, json, os, sys\nfrom pathlib import Path\n"
                               + code, str(TOOL), mine, json.dumps([[str(copy), "/proc/self/mountinfo", "", 4096]])],
                              capture_output=True, text=True, timeout=60)
        if "unshare" in proc.stderr:
            self.skipTest("this user cannot create a user and mount namespace")
        self.assertEqual((proc.stdout, proc.stderr), (cannot + "([Errno 18] not on procfs: '/proc/self/mountinfo')\n", ""))

    def test_a_scope_kill_says_whether_it_was_written(self):
        scope = self.faked()
        (scope / "cgroup.kill").write_text("")
        self.assertIsNone(self.tool.kill_scope(str(scope)))
        self.assertEqual((scope / "cgroup.kill").read_text(), "1")
        self.assertIsNone(self.tool.kill_scope(str(scope / "gone.scope")))
        (scope / "cgroup.kill").unlink()
        failed = self.tool.kill_scope(str(scope))
        self.assertIsInstance(failed, FileNotFoundError)
        self.assertFalse((scope / "cgroup.kill").exists(), "a scope kill created cgroup.kill")

    def test_a_scope_kill_through_something_mounted_over_the_scope_is_refused(self):
        if subprocess.run([sys.executable, "-c", "import os\nos.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)"],
                          capture_output=True).returncode:
            self.skipTest("this user cannot create a user and mount namespace")
        proc, scope = self.scope_that_ends("60")
        code = (UNSHARED.replace("json.loads(arg)", "json.loads(sys.argv[3])") + "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\n"
                "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                "mounted()\nprint(tool.kill_scope(sys.argv[2]))\nprint(os.path.exists(sys.argv[2] + '/cgroup.kill'))")
        out = subprocess.run([sys.executable, "-c", "import importlib.util, json, os, sys\nfrom pathlib import Path\n"
                              + code, str(TOOL), scope, json.dumps([["none", scope, "tmpfs", 0]])],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual((out.stdout, out.stderr), (f"[Errno 18] another filesystem is mounted over it: '{scope}'\nFalse\n",
                                                    ""))
        self.assertIsNone(proc.poll(), "the scope was killed through a mount over it")
        self.assertIsNone(self.tool.kill_scope(scope))
        self.assertEqual(proc.wait(timeout=10), -signal.SIGKILL)

    def test_how_this_shell_sees_cgroups_never_holds_a_value_that_cannot_be_recorded(self):
        seen = self.tool.view()
        self.assertRegex(seen["machine_id"], r"^[0-9a-f]{32}$")
        self.tool.canon(seen)
        plain_bytes, plain_text, host = Path.read_bytes, Path.read_text, socket.gethostname
        self.addCleanup(setattr, Path, "read_bytes", plain_bytes)
        self.addCleanup(setattr, Path, "read_text", plain_text)
        self.addCleanup(setattr, socket, "gethostname", host)
        for raw in (b"\xff\xfe\n", b"not a machine id\n", b"", b"0123456789ABCDEF0123456789abcdef\n",
                    "0123456789abcdef0123456789abcdeé\n".encode()):
            with self.subTest(raw=raw):
                Path.read_bytes = lambda path: raw if str(path) == "/etc/machine-id" else plain_bytes(path)
                Path.read_text = lambda path, *a, **kw: Path.read_bytes(path).decode()
                self.assertEqual(self.tool.view(), {**seen, "machine_id": None})
        Path.read_bytes = lambda path: b"\xff\n" if "boot_id" in str(path) else plain_bytes(path)
        self.assertEqual(self.tool.view(), {**seen, "boot_id": None})
        Path.read_bytes = plain_bytes
        socket.gethostname = lambda: "host\udcff"
        self.assertEqual(self.tool.view(), {**seen, "host": None})

    def test_an_entry_that_vanishes_while_hashing_is_not_called_a_special_file(self):
        root = Path(tempfile.mkdtemp(prefix="planloop-hash-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "a.txt").write_text("a\n")
        expected = self.tool.tree_hash(root)
        walk = self.tool.walk
        self.tool.walk = lambda r: ((d, n, f + ["ghost"]) for d, n, f in walk(r))
        self.assertEqual(self.tool.tree_hash(root), expected)

    def test_a_scope_name_fits_a_unit_name_however_long_the_run_id_is(self):
        names = set()
        for run_id in ("qz-" + "a" * 300 + ".pl1", "qz-" + "a" * 300 + ".pl2", "qz-" + "a" * 299 + "b.pl1"):
            scope = self.tool.scope_of(run_id, "/state/calls/call-001-a1-r-0123456789abcdef")
            names.add(Path(scope).name)
            self.assertLessEqual(len(Path(scope).name.encode()), 255)
            self.assertEqual(os.path.dirname(scope), f"{self.tool.scope_base()}/app.slice")
        self.assertEqual(len(names), 3)
        name = sorted(names)[0]
        self.assertRegex(name, r"^planloop-qz-a+-[0-9a-f]{32}\.scope$")
        made = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={name}", "true"],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        odd = Path(self.tool.scope_of(RUN, "/state/calls/call 1\n$x;é")).name
        self.assertRegex(odd, rf"^planloop-{re.escape(RUN)}-call_1__x__-[0-9a-f]{{32}}\.scope$")

    def test_a_scope_whose_directory_is_there_is_never_empty_because_a_control_file_is_missing(self):
        scope = self.faked()
        self.assertEqual(self.tool.scope_left(str(scope)), "whether a process still runs in it cannot be checked "
                         f"([Errno 2] No such file or directory: '{scope}/cgroup.events')")
        (scope / "cgroup.events").write_text("populated 1\n")
        self.assertEqual(self.tool.scope_left(str(scope)), "whether a process still runs in it cannot be checked "
                         f"([Errno 2] No such file or directory: '{scope}/cgroup.procs')")
        (scope / "cgroup.events").unlink()
        (scope / "cgroup.events").mkdir()
        self.assertIn("cannot be checked ([Errno 22] not a regular file", self.tool.scope_left(str(scope)))
        self.assertIsNone(self.tool.scope_left(str(scope / "gone.scope")))
        (scope / "file").write_text("")
        self.assertIn("cannot be checked ([Errno 20] Not a directory", self.tool.scope_left(str(scope / "file" / "x")))

    def gated(self, go, *argv):
        gate, write = os.pipe()
        os.write(write, go)
        os.close(write)
        try:
            return subprocess.run([sys.executable, "-I", "-c", self.tool.GATE, str(gate), *argv], pass_fds=(gate,),
                                  capture_output=True, text=True, timeout=60)
        finally:
            os.close(gate)

    def test_the_gate_never_starts_the_command_when_its_pipe_closes_without_the_go_byte(self):
        self.assertEqual(self.gated(b"1", "echo", "ran").stdout, "ran\n")
        closed = self.gated(b"", "echo", "ran")
        self.assertEqual((closed.returncode, closed.stdout, closed.stderr), (0, "", ""))

    def test_the_gate_starts_the_command_with_no_signal_ignored(self):
        ignored = int(self.gated(b"1", "grep", "SigIgn", "/proc/self/status").stdout.split()[1], 16)
        self.assertEqual([s.name for s in (signal.SIGPIPE, signal.SIGXFSZ) if ignored >> (s - 1) & 1], [])

    def test_a_scope_that_empties_while_it_is_killed_counts_as_killed(self):
        scope = self.faked()
        (scope / "cgroup.kill").write_text("")
        plain = self.tool.enter

        def enter(fd, name, mount, path, flags=os.O_DIRECTORY):
            if name == "cgroup.kill":
                shutil.rmtree(scope)
            return plain(fd, name, mount, path, flags)
        self.tool.enter = enter
        try:
            self.assertIsNone(self.tool.kill_scope(str(scope)))
        finally:
            self.tool.enter = plain
        scope.mkdir()
        (scope / "cgroup.events").write_text("populated 1\n")
        (scope / "cgroup.procs").write_text(f"{os.getpid()}\n")
        failed = self.tool.kill_scope(str(scope))
        self.assertIsInstance(failed, FileNotFoundError)
        self.assertEqual(str(failed), f"[Errno 2] No such file or directory: '{scope}/cgroup.kill'")

    def test_a_mountinfo_larger_than_a_control_file_is_read_whole(self):
        mine = "/sys/fs/cgroup" + Path("/proc/self/cgroup").read_text().strip().removeprefix("0::")
        fake = Path(tempfile.mkdtemp(prefix="planloop-proc-"))
        self.addCleanup(shutil.rmtree, fake, True)
        (fake / "self").mkdir()
        text = "".join(f"{900000 + i} 1 0:99 / /planloop-pad/{i:06d} rw - tmpfs none rw\n" for i in range(30000)) \
            + Path("/proc/self/mountinfo").read_text()
        (fake / "self" / "mountinfo").write_text(text)
        self.assertGreater(len(text), 1 << 20)
        magic = int(subprocess.run(["stat", "-f", "-c", "%t", str(fake)], capture_output=True, text=True,
                                   check=True).stdout, 16)
        plain = self.tool.mount_of

        def mount_of(fd):
            self.tool.PROC, self.tool.PROC_MAGIC = "/proc", 0x9FA0
            try:
                return plain(fd)
            finally:
                self.tool.PROC, self.tool.PROC_MAGIC = str(fake), magic
        self.tool.PROC, self.tool.PROC_MAGIC, self.tool.mount_of = str(fake), magic, mount_of
        self.assertEqual(self.tool.proc_text("self/mountinfo"), text)
        self.assertIn(str(os.getpid()), self.tool.scope_pids(mine))

    def test_a_python_without_ctypes_loads_the_tool_and_proves_no_scope(self):
        mine = "/sys/fs/cgroup" + Path("/proc/self/cgroup").read_text().strip().removeprefix("0::")
        cannot = "whether a process still runs in it cannot be checked ([Errno 38] fstatfs cannot be called through " \
            "ctypes ({}), so it cannot be proven procfs: '/proc')"
        code = ("import importlib.util, sys\nsys.modules['ctypes'] = None\n"
                "spec = importlib.util.spec_from_file_location('p', sys.argv[1])\n"
                "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                "print(tool.scope_left(sys.argv[2]))")
        proc = subprocess.run([sys.executable, "-c", code, str(TOOL), mine], capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.stdout, proc.stderr),
                         (cannot.format("import of ctypes halted; None in sys.modules") + "\n", ""))
        import ctypes
        plain = ctypes.CDLL
        self.addCleanup(setattr, ctypes, "CDLL", plain)
        for cdll, said in ((lambda *a, **kw: (_ for _ in ()).throw(OSError("no libc")), "no libc"),
                           (lambda *a, **kw: object(), "'object' object has no attribute 'fstatfs'")):
            with self.subTest(said=said):
                ctypes.CDLL, self.tool.LIBC = cdll, None
                self.assertEqual(self.tool.scope_left(mine), cannot.format(said))
        ctypes.CDLL, self.tool.LIBC = plain, None
        self.assertIn(str(os.getpid()), self.tool.scope_pids(mine))


FG03 = ('    gate_lines = {c.strip() for c in fresh["coverage"]} if fresh["status"] == "counted" else set()',
        '    gate_lines = {c.strip() for c in fresh["coverage"]}')
FG04 = ("            canon(result)\n", "            pass\n")
FG05 = ("sorted(settings, key=repr)", "sorted(settings)")
FG06 = ("item = items.get(s) if isinstance(s, int) else None", "item = items.get(s)")
FG07 = ("\"planloop_min_effort\": f\"({'|'.join(EFFORTS)})?\",\n            ", "")
MALFORMED_AT = PATCHED.replace("PATCH", """import builtins
kind, where = arg.split(":")
def broken(*a, **kw):
    if kind == "RecursionError":
        return broken(*a, **kw)
    raise getattr(builtins, kind)("a bug in " + where)
setattr(tool, where, broken)""")
APPROVAL_STOPS = PATCHED.replace("PATCH", """ready, update = tool.readiness, tool.Beads.update
def readiness(*a, **kw):
    seen.append(1)
    if arg == "recheck" and len(seen) == 2:
        raise KeyError("recheck")
    return ready(*a, **kw)
def updating(self, bead, meta, *a, **kw):
    if arg == "approval" and "planloop_approval" in meta:
        raise TypeError("a bug in the Beads update")
    return update(self, bead, meta, *a, **kw)
tool.readiness, tool.Beads.update = readiness, updating""")


def reverted(f, *pairs):
    text = TOOL.read_text()
    for fixed, old in pairs:
        assert text.count(fixed) == 1, fixed
        text = text.replace(fixed, old)
    path = f.root / f"planloop-reverted-{uuid.uuid4().hex[:6]}.py"
    path.write_text(text)
    return path


class MalformedInput(unittest.TestCase):
    def boundary(self, f, command, kind, said):
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  {command}: a record it read is malformed ({kind}: {said}", f.last.stderr)
        self.assertIn("; it stopped there, and what it had written before stands: ", f.last.stderr)
        self.assertIn(" (PLANLOOP_DEBUG=1 prints where it stopped)", f.last.stderr)

    def test_fg03_a_gate_whose_receipt_failed_verification_is_not_approved_cleanly(self):
        f = Fixture(self)
        f.to_gate_ready()
        f.review(review(coverage=[None]), kind="gate", effort="high", expect=1)
        self.assertEqual(f.receipt(f.call)["coverage"], [None])
        f.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  [mechanical] gate call verified", f.last.stdout)
        self.assertIn("NOT APPROVED: ", f.last.stdout)
        old = reverted(f, FG03)
        f.tool("gate", "--run", RUN, expect=1, old=old)
        self.boundary(f, "gate", "AttributeError", "'NoneType' object has no attribute 'strip')")
        self.assertIn("repair or restore that record, then run the command again", f.last.stderr)
        f.tool("gate", "--run", RUN, expect=1, old=old, env={"PLANLOOP_DEBUG": "1"})
        self.assertIn("Traceback (most recent call last):", f.last.stderr)
        self.assertIn("AttributeError: 'NoneType' object has no attribute 'strip'", f.last.stderr)
        self.assertIn("FAIL  gate: a record it read is malformed (AttributeError", f.last.stderr)
        f.tool("gate", "--run", RUN, expect=1, old=old, env={"PLANLOOP_DEBUG": "0"})
        self.assertNotIn("Traceback", f.last.stderr)

    def test_fg04_runner_json_with_an_unpaired_surrogate_records_an_invalid_attempt(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review(review(coverage=["plan read in full \ud800"]), expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        r = f.receipt(1)
        self.assertEqual(r["status"], "invalid")
        self.assertEqual(r["reasons"], ["runner result.json holds an unpaired surrogate escape (\\ud800 to \\udfff "
                                        "alone), which is not text, so no receipt could record it"])
        f.review(review(), call=1, attempt=2)
        self.assertEqual(f.receipt(1, 2)["status"], "counted")
        path = next(f.sessions.rglob(f"rollout-*-{f.receipt(1, 2)['session_id']}.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        at = next(i for i, r in enumerate(rows) if r["type"] == "turn_context")
        rows[at]["payload"]["model"] += "\ud800"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        (f.rdir / "reviews" / "call-001-a2" / "receipt.json").unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "2", expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertEqual(f.receipt(1, 2)["status"], "invalid")
        self.assertIn(f"effective settings unverifiable: rollout line {at + 1} is not JSON text",
                      f.receipt(1, 2)["reasons"])
        g = Fixture(self)
        g.init()
        g.publish(1, plan_text(1))
        g.review(review(coverage=["plan read in full \ud800"]), expect=1, old=reverted(g, FG04))
        self.boundary(g, "dispatch", "UnicodeEncodeError", "'utf-8' codec can't encode character '\\ud800'")
        call = g.rdir / "reviews" / "call-001-a1"
        self.assertIn(f"stands: if {call} exists now, do not dispatch call 1 attempt 1 again: run `receipt --run "
                      f"{RUN} --call 1 --attempt 1`", g.last.stderr)
        self.assertFalse(probe_any(call / "receipt.json"))
        g.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertEqual(g.receipt(1)["status"], "invalid")

    def test_fg05_settings_that_differ_only_by_a_null_field_are_reported_not_sorted_into_a_crash(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review(review())
        path = next(f.sessions.rglob("rollout-*.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        at = next(i for i, r in enumerate(rows) if r["type"] == "turn_context")
        rows.insert(at + 1, {**rows[at], "payload": {**rows[at]["payload"], "approval_policy": None}})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        adir = next(f.artifacts(1).glob("claudex-*"))
        changed = "turn_context settings change within the session: [("
        f.tool("rollout-check", "--artifacts", str(adir), expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  {changed}", f.last.stderr)
        (f.rdir / "reviews" / "call-001-a1" / "receipt.json").unlink()
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn(f"FAIL  {changed}", f.last.stdout)
        self.assertEqual(f.receipt(1)["status"], "invalid")
        f.tool("rollout-check", "--artifacts", str(adir), expect=1, old=reverted(f, FG05))
        self.boundary(f, "rollout-check", "TypeError", "'<' not supported between instances of")

    def test_fg06_a_mandate_revision_that_is_not_a_number_fails_as_an_unbound_receipt(self):
        f = Fixture(self)
        nonce = PolicyReviewFixes.shrink_staged(self, f)
        f.tool("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce)
        f.tool("findings", "propose", "--run", RUN)
        c = f.review(review(coverage=["plan read in full", *f.lines_for(2)]))
        path = f.rdir / "reviews" / f"call-{c:03d}-a1" / "input" / "dispatch.json"
        record = json.loads(path.read_text())
        record["meaning_check"][0]["revision"] = [2]
        path.write_text(json.dumps(record))
        said = f"receipt of call {c} attempt 1: its dispatch's mandate for revision [2] is not the meaning obligation"
        f.tool("gate", "--run", RUN, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  [mechanical] every stored meaning receipt is bound to revisions 1 to 2: " + said,
                      f.last.stdout)
        f.tool("ledger", "--run", RUN, expect=2)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("UNBOUND  " + said, f.last.stderr)
        f.tool("ledger", "--run", RUN, expect=1, old=reverted(f, FG06))
        self.boundary(f, "ledger", "TypeError", "unhashable type: 'list')")

    def set_floor(self, f, value):
        db = f.bd()
        bead = next(i for i in db["issues"].values() if i["metadata"].get("planloop_key") == f"run:{RUN}")
        bead["metadata"]["planloop_min_effort"] = value
        f.set_bd(db)

    def test_fg07_a_run_bead_effort_floor_outside_planloops_efforts_is_malformed_metadata(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review()))
        dispatch = ("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium")
        self.set_floor(f, "HIGH")
        f.tool(*dispatch, expect=1)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertRegex(f.last.stderr, r"FAIL  run bead \S+ holds malformed planloop metadata "
                         r"\(planloop_min_effort='HIGH'\); repair it with bd, then run the command again")
        self.assertFalse(probe_any(f.rdir / "reviews" / "call-001-a1"))
        f.tool(*dispatch, expect=1, old=reverted(f, FG07))
        self.boundary(f, "dispatch", "KeyError", "'HIGH')")
        self.assertIn("repair or restore that record, then run the command again", f.last.stderr)
        self.assertFalse(probe_any(f.rdir / "reviews" / "call-001-a1"))
        self.set_floor(f, "")
        f.tool(*dispatch)
        self.assertEqual(f.receipt(1)["status"], "counted")

    def test_recursion_and_programming_errors_are_reported_and_a_name_error_still_has_its_traceback(self):
        f = Fixture(self)
        f.init()
        drive = PolicyReviewFixes.driver
        self.assertEqual(drive(self, f, MALFORMED_AT, "RecursionError:meta_of", "findings", "check", "--run", RUN), 1)
        self.boundary(f, "findings check", "RecursionError", "maximum recursion depth exceeded")
        self.assertEqual(drive(self, f, MALFORMED_AT, "IndexError:policy_now", "ledger", "--run", RUN), 1)
        self.boundary(f, "ledger", "IndexError", "a bug in policy_now)")
        self.assertEqual(drive(self, f, MALFORMED_AT, "TypeError:cmd_ledger", "ledger", "--run", RUN), 1)
        self.boundary(f, "ledger", "TypeError", "a bug in cmd_ledger)")
        self.assertEqual(drive(self, f, MALFORMED_AT, "TypeError:cmd_ledger", "ledger", "--run", RUN,
                               env={"PLANLOOP_DEBUG": "1"}), 1)
        self.assertRegex(f.last.stderr, r"(?s)^Traceback \(most recent call last\):.*TypeError: a bug in cmd_ledger\n"
                         r"FAIL  ledger: a record it read is malformed \(TypeError: a bug in cmd_ledger\)")
        self.assertEqual(drive(self, f, MALFORMED_AT, "NameError:cmd_ledger", "ledger", "--run", RUN), 1)
        self.assertIn("Traceback (most recent call last):", f.last.stderr)
        self.assertTrue(f.last.stderr.rstrip().endswith("NameError: a bug in cmd_ledger"), f.last.stderr)
        self.assertNotIn("FAIL  ", f.last.stderr)

    def test_a_malformed_record_after_the_receipt_is_written_says_the_receipt_stands(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        f.review_file.write_text(json.dumps(review()))
        code = PolicyReviewFixes.driver(self, f, MALFORMED_AT, "ValueError:prune_copies", "dispatch", "--run", RUN,
                                        "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium")
        self.assertEqual(code, 1, f.last.stderr)
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertIn("FAIL  a record it read is malformed (ValueError: a bug in prune_copies); call 1 attempt 1 is "
                      "recorded counted in ", f.last.stderr)
        self.assertIn("do not dispatch that attempt again", f.last.stderr)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertEqual(f.receipt(1)["status"], "counted")

    def test_a_gate_publish_stopped_by_a_malformed_record_says_what_it_left(self):
        f = Fixture(self)
        f.to_gate_ready()
        f.ingest(f.review(review(), kind="gate", effort="high"), {})
        publish = ("gate", "--run", RUN, "--publish")
        self.assertEqual(PolicyReviewFixes.driver(self, f, APPROVAL_STOPS, "recheck", *publish), 1)
        self.boundary(f, "gate", "KeyError", "'recheck')")
        name = re.search(r"the approval record (approval-r002-[0-9a-f]{12}\.json) is written and unreferenced, and "
                         r"APPROVAL is unchanged: run `gate --run \S+ --publish` again", f.last.stderr)
        self.assertTrue(name, f.last.stderr)
        self.assertTrue((f.rdir / "approvals" / name.group(1)).is_file())
        self.assertFalse(probe_any(f.rdir / "APPROVAL"))
        self.assertEqual(PolicyReviewFixes.driver(self, f, APPROVAL_STOPS, "approval", *publish), 1)
        self.boundary(f, "gate", "TypeError", "a bug in the Beads update)")
        self.assertRegex(f.last.stderr, r"APPROVAL names approval-r002-[0-9a-f]{12}\.json, and Beads may not record it "
                         r"yet: run `gate --run \S+ --publish` again, which publishes the approval afresh")
        f.tool("gate", "--run", RUN, expect=1)
        f.tool(*publish)
        f.tool("gate", "--run", RUN)


class PublishAndBundleOrder(unittest.TestCase):
    def test_bundle_names_a_published_interrupted_or_unstaged_revision_before_reading_its_handback(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        inputs = str(f.inputs())
        bundle = ("bundle", "--run", RUN, "--revision", "2", "--nonce", nonce, "--inputs", inputs)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", nonce, env={"PLANLOOP_CRASH_AT": "after_rename"},
               expect=99)
        f.tool(*bundle, expect=1)
        self.assertEqual(f.last.stderr, "FAIL  rev-002 exists and HEAD is revision 1: a publication of revision 2 was "
                         f"interrupted; nothing was changed: run `publish --run {RUN} --recover`, which completes it "
                         "or moves it aside to be re-staged\n")
        f.tool("publish", "--run", RUN, "--recover")
        f.tool(*bundle, expect=1)
        self.assertEqual(f.last.stderr, "FAIL  revision 2 is already published (HEAD is revision 2); nothing was "
                         "changed\n")
        f.tool("bundle", "--run", RUN, "--revision", "3", "--nonce", "0123abcd", "--inputs", inputs, expect=1)
        self.assertEqual(f.last.stderr, "FAIL  .staging-003-0123abcd is gone or was never staged (HEAD is revision 2); "
                         "nothing was changed\n")

    def test_a_publish_waiting_for_the_bundle_lock_holds_no_run_lock(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        nonce = f.stage(2, plan_text(2))
        release = ErrorContractIO.paused(self, f, PAUSED_AT_BUNDLE_LOCK, "publish", "--run", RUN, "--revision", "2",
                                         "--nonce", nonce)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "a run-lock command while publish waits")
        self.assertFalse(probe_any(f.rdir / ".lock"))
        code, out = release()
        self.assertEqual(code, 0, out)
        self.assertEqual(f.head(), 2)

    def test_publish_names_a_stale_second_staging_and_an_unbundled_one(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        first, second = f.stage(2, plan_text(2)), f.stage(2, plan_text(2))
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", first)
        f.tool("publish", "--run", RUN, "--revision", "2", "--nonce", second, expect=3)
        stale = f.rdir / f".staging-002-{second}"
        self.assertEqual(f.last.stderr, "CONFLICT  revision 2 is already published from another staging (HEAD is revision "
                         f"2); {stale.name} is a stale staging of it and nothing was published: remove {stale}\n")
        self.assertTrue(stale.is_dir())
        f.tool("findings", "propose", "--run", RUN)
        nonce = f.hand(3, plan_text(3))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", nonce, expect=1)
        self.assertEqual(f.last.stderr, f"FAIL  revision 3 is not bundled: .staging-003-{nonce} has no revision.json "
                         "(no bundle ran for it, or one was stopped before it finished); nothing was published: run "
                         f"`bundle --run {RUN} --revision 3 --nonce {nonce} --inputs INPUTS.json` (it says what to "
                         "remove if a stopped bundle left one), then publish\n")
        f.tool("bundle", "--run", RUN, "--revision", "3", "--nonce", nonce, "--inputs", str(f.inputs()))
        f.tool("publish", "--run", RUN, "--revision", "3", "--nonce", nonce)
        self.assertEqual(f.head(), 3)


class OwnerNamespace(unittest.TestCase):
    def far(self, f, *args, expect):
        proc = subprocess.run([*FAR, sys.executable, str(TOOL), *args], cwd=f.repo, capture_output=True, text=True,
                              env=f.env, timeout=300)
        f.last = proc
        self.assertNotIn("Traceback", proc.stderr)
        if expect is not None:
            self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc.returncode

    def namespaces(self):
        try:
            if subprocess.run([*FAR, "true"], capture_output=True, timeout=60).returncode:
                self.skipTest("this user cannot create a user and PID namespace")
        except OSError:
            self.skipTest("unshare is not installed")

    def owner(self, pid, **changes):
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return {"host": socket.gethostname(), "boot_id": boot, "pid": pid, "pid_ns": PID_NS, "start": "1",
                "nonce": "e" * 32, "acquired_at": "2026-11-13T00:00:00Z", **changes}

    def refused(self, f, lock, far):
        self.assertNotIn("broke stale lock", f.last.stderr)
        self.assertRegex(f.last.stderr, rf"^CONFLICT  {re.escape(str(lock))} is held by \{{")
        self.assertIn("; it is never broken unless its owner is provably dead on this host and in this PID namespace; "
                      f"{far}, and this command runs in PID namespace ", f.last.stderr)
        self.assertIn("where the process ids of another one mean nothing, so whether its owner is alive cannot be "
                      "checked here: run the command where that lock was taken (the container, sandbox or session of "
                      "that PID namespace), which breaks it if its owner is dead, or check there that process ",
                      f.last.stderr)
        self.assertRegex(f.last.stderr, r" is not a running planloop command \(or that nothing of that namespace runs "
                         r"any more(: run from the host's own PID namespace, `lsns -t pid \| grep \d+` lists it while anything of it runs, and from inside another namespace no match proves nothing)?; " + re.escape(
                             WSL + f", then remove {lock} by hand") + "\n")

    def test_fg08_a_live_lock_is_never_broken_from_another_pid_namespace(self):
        self.namespaces()
        f = Fixture(self)
        f.init()
        nonce = f.hand(1, plan_text(1))
        bundle = ("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()))
        recover = ("publish", "--run", RUN, "--recover")
        state = ("state", "--run", RUN, "--set", "active", "--reason", "holding the run lock")
        named = f"its record names PID namespace {PID_NS}"
        for held, lock, other in ((bundle, f.state / RUN / ".lock-bundle", bundle), (state, f.rdir / ".lock", recover)):
            with self.subTest(lock=lock.name, holder="here"):
                release = ErrorContractIO.paused(self, f, PAUSED_HOLDING_LOCK, *held)
                owner = (lock / "owner.json").read_bytes()
                self.far(f, *other, expect=3)
                self.refused(f, lock, named)
                self.assertEqual(json.loads(owner)["pid_ns"], PID_NS)
                self.assertEqual((lock / "owner.json").read_bytes(), owner)
                code, out = release()
                self.assertEqual(code, 0, out)
                self.assertNotIn("is no longer ours", out)
                self.assertFalse(probe_any(lock))
        for lock, other in ((f.state / RUN / ".lock-bundle", ("publish", "--run", RUN, "--revision", "1", "--nonce",
                                                               nonce)), (f.rdir / ".lock", recover)):
            with self.subTest(lock=lock.name, holder="there"):
                release = ErrorContractIO.paused(self, f, PAUSED_HOLDING_LOCK, *(
                    recover if lock.name == ".lock" else other), prefix=FAR)
                owner = json.loads((lock / "owner.json").read_text())
                self.assertLess(owner["pid"], 10)
                f.tool(*other, expect=3)
                self.refused(f, lock, f"its record names PID namespace {owner['pid_ns']}")
                self.assertNotEqual(owner["pid_ns"], PID_NS)
                self.assertEqual(json.loads((lock / "owner.json").read_text()), owner)
                code, out = release()
                self.assertEqual(code, 0, out)
                self.assertNotIn("is no longer ours", out)
        self.assertEqual(f.head(), 1)
        self.assertTrue((f.state / RUN / f"snap-r001-{nonce}").is_dir())

    def test_fg08_a_bundle_paused_at_its_snapshot_keeps_its_lock_and_the_published_snapshot_survives(self):
        self.namespaces()
        f = Fixture(self)
        f.init()
        nonce = f.hand(1, plan_text(1))
        bundle = ("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()))
        publish = ("publish", "--run", RUN, "--revision", "1", "--nonce", nonce)
        snap, lock = f.state / RUN / f"snap-r001-{nonce}", f.state / RUN / ".lock-bundle"
        release = ErrorContractIO.paused(self, f, PAUSED_AT_SNAPSHOT, *bundle)
        built = self.far(f, *bundle, expect=None)
        said = f.last.stderr
        self.far(f, *publish, expect=None)
        code, out = release()
        f.tool(*publish)
        self.assertEqual(f.head(), 1)
        self.assertTrue(snap.is_dir(), "the published revision's snapshot was removed by the bundle that lost its lock")
        self.assertIn(str(snap), [item.get("path") for item in f.manifest(1)["items"]])
        self.assertEqual((built, code), (3, 0), said + out)
        self.assertIn(f"its record names PID namespace {PID_NS}", said)
        self.assertNotIn("broke stale lock", said)
        self.assertNotIn("is no longer ours", out)
        self.assertFalse(probe_any(lock))
        self.assertFalse(list(f.rdir.glob("*/.bundle-tmp-*")))

    def test_fg08_a_lock_whose_owner_names_another_or_no_pid_namespace_is_never_broken(self):
        f = Fixture(self)
        f.init()
        nonce = f.hand(1, plan_text(1))
        bundle = ("bundle", "--run", RUN, "--revision", "1", "--nonce", nonce, "--inputs", str(f.inputs()))
        dead = subprocess.Popen(["true"])
        dead.wait()
        legacy = self.owner(dead.pid)
        del legacy["pid_ns"]
        none = "its record names no PID namespace (a planloop that did not yet record one wrote it)"
        start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
        for lock, command in ((f.state / RUN / ".lock-bundle", bundle), (f.rdir / ".lock", ("publish", "--run", RUN,
                                                                                         "--recover"))):
            lock.mkdir(parents=True)
            for owner, far in ((self.owner(dead.pid, pid_ns=PID_NS + 1),
                                f"its record names PID namespace {PID_NS + 1}"),
                               (self.owner(os.getpid(), pid_ns=PID_NS + 1, start=start),
                                f"its record names PID namespace {PID_NS + 1}"),
                               (self.owner(dead.pid, pid_ns=str(PID_NS)), f"its record names PID namespace '{PID_NS}'"),
                               (self.owner(dead.pid, pid_ns=None), none), (legacy, none)):
                with self.subTest(lock=lock.name, owner=owner):
                    (lock / "owner.json").write_text(json.dumps(owner))
                    f.tool(*command, expect=3)
                    self.refused(f, lock, far)
                    self.assertIn(f"check there that process {owner['pid']} is not a running planloop command",
                                  f.last.stderr)
                    self.assertEqual(f": run from the host's own PID namespace, `lsns -t pid | grep {owner.get('pid_ns')}` lists it while anything of it runs, and from inside another namespace no match proves nothing;"
                                     in f.last.stderr, type(owner.get("pid_ns")) is int)
                    self.assertEqual(json.loads((lock / "owner.json").read_text()), owner)
            (lock / "owner.json").write_text(json.dumps({**legacy, "boot_id": "another-boot"}))
            f.tool(*command)
            self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
            lock.mkdir()
            (lock / "owner.json").write_text(json.dumps(self.owner(dead.pid)))
            f.tool(*command, expect=1 if lock.name == ".lock-bundle" else 0)
            self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
            self.assertFalse(probe_any(lock))

    def test_fg08_a_receipt_never_takes_a_call_whose_dispatch_names_another_or_no_pid_namespace(self):
        f = Fixture(self)
        PolicyReviewFixes.ready_to_dispatch(self, f)
        dispatch = PolicyReviewFixes.dispatch_args(self)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f.tool(*dispatch, env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        call_dir = f.rdir / "reviews" / "call-001-a1"
        running = call_dir / "running.json"
        written = json.loads(running.read_text())
        legacy = {k: v for k, v in written.items() if k != "pid_ns"}
        tail = (f" remove {running} by hand and run `receipt --run {RUN} --call 1 --attempt 1` again: that gives up "
                "only the wait for the dispatching process")
        for record, far, lsns in (({**written, "pid_ns": PID_NS + 1}, f"its record names PID namespace {PID_NS + 1}",
                                   f": run from the host's own PID namespace, `lsns -t pid | grep {PID_NS + 1}` lists it while anything of it runs, and from inside another namespace no match proves nothing"),
                                  (legacy, "its record names no PID namespace (a planloop that did not yet record one "
                                   "wrote it)", "")):
            with self.subTest(record=record):
                running.write_text(json.dumps(record))
                f.tool(*receipt, expect=3)
                self.assertIn(f"CONFLICT  call 1 attempt 1 is still being reviewed by process {written['pid']}; wait "
                              f"for it; {far}, and this command runs in PID namespace {PID_NS}, where the process ids "
                              "of another one mean nothing, so whether it is alive cannot be checked here: run "
                              f"`receipt --run {RUN} --call 1 --attempt 1` where the call was dispatched (the "
                              "container, sandbox or session of that PID namespace), or check there that process "
                              f"{written['pid']} is not a planloop dispatch (or that nothing of that namespace runs "
                              f"any more{lsns}; {WSL}, then{tail}", f.last.stderr)
                self.assertFalse(probe_any(call_dir / "receipt.json"))
        self.assertEqual(written["pid_ns"], PID_NS)
        running.write_text(json.dumps(written))
        code = PolicyReviewFixes.driver(self, f, OWN_PID_ELSEWHERE, str(running), *receipt)
        self.assertEqual(code, 3, f.last.stdout + f.last.stderr)
        self.assertIn(f"its record names PID namespace {PID_NS + 1}", f.last.stderr)
        self.assertFalse(probe_any(call_dir / "receipt.json"))
        running.write_text(json.dumps(written))
        try:
            unshared = not subprocess.run([*FAR, "true"], capture_output=True, timeout=60).returncode
        except OSError:
            unshared = False
        if unshared:
            self.far(f, *receipt, expect=3)
            self.assertIn(f"its record names PID namespace {PID_NS}, and this command runs in PID namespace ",
                          f.last.stderr)
            self.assertFalse(probe_any(call_dir / "receipt.json"))
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_publish_recover_breaks_a_bundle_lock_only_when_its_owner_is_provably_dead(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        lock = f.state / RUN / ".lock-bundle"
        dead = subprocess.Popen(["true"])
        dead.wait()
        start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
        for owner in (self.owner(os.getpid(), start=start), self.owner(dead.pid, pid_ns=PID_NS + 1),
                      self.owner(dead.pid, host="elsewhere")):
            with self.subTest(owner=owner):
                lock.mkdir()
                (lock / "owner.json").write_text(json.dumps(owner))
                f.tool("publish", "--run", RUN, "--recover")
                self.assertNotIn("broke stale lock", f.last.stderr)
                self.assertEqual(json.loads((lock / "owner.json").read_text()), owner)
                shutil.rmtree(lock)
        lock.mkdir()
        (lock / "owner.json").write_text(json.dumps(self.owner(dead.pid)))
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertFalse(probe_any(lock))
        self.assertFalse(probe_any(f.state / RUN / ".lock-break"))


class Round33(unittest.TestCase):
    def test_a_live_read_command_with_an_unpaired_surrogate_records_an_invalid_attempt(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        wrapper = f.root / "surrogate_runner.py"
        wrapper.write_text(SURROGATE_RUNNER)
        f.review_file.write_text(json.dumps(review()))
        dispatch = ("dispatch", "--run", RUN, "--call", "1", "--kind", "working", "--effort", "medium", "--attempt")
        f.tool(*dispatch, "1", expect=1,
               env={"PLANLOOP_RUNNER": f"{sys.executable} {wrapper} {HERE / 'fake_runner.py'}"})
        self.assertNotIn("Traceback", f.last.stderr)
        self.assertNotIn("a record it read is malformed", f.last.stderr)
        stdout = next(f.artifacts(1).glob("claudex-*/stdout.txt")).read_text()
        self.assertIn('"command": "ls ~/.codex/sessions \\ud800; ', stdout)
        at = next(i for i, line in enumerate(stdout.splitlines(), 1) if "\\ud800" in line)
        r = f.receipt(1)
        self.assertEqual(r["status"], "invalid")
        self.assertIn(f"stdout event {at} holds an unpaired surrogate escape (\\ud800 to \\udfff alone), which is not "
                      "text, so no receipt could record it", r["reasons"])
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertEqual(f.receipt(1), r)
        f.tool(*dispatch, "2")
        self.assertEqual(f.receipt(1, 2)["status"], "counted")

    def test_a_handback_with_an_unpaired_surrogate_goes_back_to_the_planner_with_nothing_written(self):
        f = Fixture(self)
        f.init()
        nonce = "0123456789abcdef"
        plan = plan_text(1).replace("Line two of the design.", "Line two of the design \ud800.")
        transcript = f.transcript(f.wrap(1, nonce, plan))
        self.assertIn("\\ud800", transcript.read_text())
        before = tree(f.rdir)
        f.tool("handback", "--run", RUN, "--revision", "1", "--nonce", nonce, "--transcript", str(transcript), expect=1)
        self.assertEqual(f.last.stderr, "FAIL  the planner's handback holds an unpaired surrogate escape (\\ud800 to "
                         "\\udfff alone), so the plan is not valid text; nothing was written: send it back to the "
                         "planner\n")
        self.assertEqual(tree(f.rdir), before)
        self.assertEqual(f.staged(1, f.hand(1, plan_text(1)))["revision"], 1)

    def test_a_debug_traceback_follows_the_output_before_it_and_is_not_advertised_again(self):
        f = Fixture(self)
        f.to_gate_ready()
        f.review(review(coverage=[None]), kind="gate", effort="high", expect=1)
        old = reverted(f, FG03)
        suffix = " (PLANLOOP_DEBUG=1 prints where it stopped)"
        for debug in ("1", "0"):
            with self.subTest(debug=debug):
                out = f.root / f"debug-{debug}.txt"
                with out.open("w") as sink:
                    code = subprocess.run([sys.executable, str(old), "gate", "--run", RUN], cwd=f.repo, stdout=sink,
                                          stderr=subprocess.STDOUT, env={**f.env, "PLANLOOP_DEBUG": debug},
                                          timeout=300).returncode
                said = out.read_text()
                self.assertEqual(code, 1, said)
                printed, fail = said.index("PASS  "), said.index("FAIL  gate: a record it read is malformed (")
                self.assertLess(printed, fail)
                self.assertEqual(said.rstrip("\n").endswith(suffix), debug == "0", said)
                self.assertEqual(suffix in said, debug == "0")
                if debug == "1":
                    self.assertLess(printed, said.index("Traceback (most recent call last):"))
                    self.assertLess(said.index("Traceback (most recent call last):"), fail)
                    self.assertGreater(said.index("Traceback (most recent call last):"), said.rindex("PASS  "))
                else:
                    self.assertNotIn("Traceback", said)


NO_PID_NS = PATCHED.replace("PATCH", "tool.pid_ns = lambda: None")
NO_PROC = tuple(a for a in FAR if a != "--mount-proc")
BLIND = ("UNVERIFIABLE  this dispatch cannot tell its own PID namespace (/proc/self/ns/pid cannot be read, or /proc is "
         "not mounted for it: /proc/self is not its pid), so no planloop command could ever check the process its "
         "records name; nothing was reserved and Codex did not run: dispatch where /proc is that of its PID namespace "
         "(`unshare --pid` needs --mount-proc)\n")


class Round34(unittest.TestCase):
    def test_a_recorded_call_reprints_its_receipt_whatever_its_leftover_running_json_names(self):
        f = Fixture(self)
        PolicyReviewFixes.ready_to_dispatch(self, f)
        f.tool(*PolicyReviewFixes.dispatch_args(self))
        call_dir = f.rdir / "reviews" / "call-001-a1"
        running, receipt = call_dir / "running.json", (call_dir / "receipt.json").read_bytes()
        self.assertFalse(probe_any(running))
        start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
        legacy = {k: v for k, v in OwnerNamespace.owner(self, os.getpid(), start=start).items()
                  if k not in ("pid_ns", "acquired_at")}
        for record in (legacy, {**legacy, "pid_ns": PID_NS + 1}, {**legacy, "host": "elsewhere"}):
            with self.subTest(record=record):
                running.write_text(json.dumps(record))
                f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
                self.assertIn("call 1 attempt 1: counted", f.last.stdout)
                self.assertNotIn("still being reviewed", f.last.stderr)
                self.assertFalse(probe_any(running))
                self.assertEqual((call_dir / "receipt.json").read_bytes(), receipt)

    def test_a_process_that_cannot_tell_its_pid_namespace_never_dispatches_or_breaks_a_lock(self):
        f = Fixture(self)
        PolicyReviewFixes.ready_to_dispatch(self, f)
        dispatch = PolicyReviewFixes.dispatch_args(self)
        code = PolicyReviewFixes.driver(self, f, NO_PID_NS, "-", *dispatch)
        self.assertEqual((code, f.last.stderr), (2, BLIND))
        self.assertFalse(probe_any(f.rdir / "reviews" / "call-001-a1"))
        dead = subprocess.Popen(["true"])
        dead.wait()
        lock = f.rdir / ".lock"
        lock.mkdir()
        (lock / "owner.json").write_text(json.dumps(OwnerNamespace.owner(self, dead.pid)))
        code = PolicyReviewFixes.driver(self, f, NO_PID_NS, "-", "publish", "--run", RUN, "--recover")
        self.assertEqual(code, 3, f.last.stderr)
        self.assertIn(f"its record names PID namespace {PID_NS}, and this command cannot tell its own PID namespace "
                      "(/proc/self/ns/pid cannot be read, or /proc is not mounted for it), where the process ids of "
                      "another one mean nothing", f.last.stderr)
        self.assertTrue(probe_any(lock))
        f.tool(*dispatch)
        self.assertIn("NOTE  broke stale lock of dead owner", f.last.stderr)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_pid_namespace_without_its_own_proc_records_none_and_never_dispatches(self):
        try:
            seen = subprocess.run([*NO_PROC, sys.executable, "-c", "import os; print(os.getpid(), os.readlink("
                                   "'/proc/self'))"], capture_output=True, text=True, timeout=60)
        except OSError:
            self.skipTest("unshare is not installed")
        if seen.returncode:
            self.skipTest("this user cannot create a user and PID namespace")
        pid, link = seen.stdout.split()
        self.assertEqual(pid, "1")
        self.assertNotEqual(link, "1")
        read = subprocess.run([*NO_PROC, sys.executable, "-c", "import importlib.util, sys\n"
                               "spec = importlib.util.spec_from_file_location('planloop', sys.argv[1])\n"
                               "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                               "print(tool.pid_ns(), tool.identity()['pid_ns'])", str(TOOL)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(read.stdout.split(), ["None", "None"], read.stderr)
        f = Fixture(self)
        PolicyReviewFixes.ready_to_dispatch(self, f)
        dispatch = PolicyReviewFixes.dispatch_args(self)
        proc = subprocess.run([*NO_PROC, sys.executable, str(TOOL), *dispatch], cwd=f.repo, capture_output=True,
                              text=True, env=f.env, timeout=300)
        self.assertEqual((proc.returncode, proc.stderr), (2, BLIND))
        self.assertFalse(probe_any(f.rdir / "reviews" / "call-001-a1"))
        f.tool(*dispatch)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)

    def test_a_lock_names_the_other_lock_its_owner_holds_and_recover_says_which_bundle_lock_it_left(self):
        f = Fixture(self)
        f.init()
        f.publish(1, plan_text(1))
        dead = subprocess.Popen(["true"])
        dead.wait()
        bundle, run_lock = f.state / RUN / ".lock-bundle", f.rdir / ".lock"
        owner = OwnerNamespace.owner(self, dead.pid, pid_ns=PID_NS + 1)
        bundle.mkdir()
        (bundle / "owner.json").write_text(json.dumps(owner))
        left = (f"NOTE  {bundle} is held by {owner} and publish --recover left it; its record names PID namespace "
                f"{PID_NS + 1}, and this command runs in PID namespace {PID_NS}, where the process ids of another one "
                "mean nothing, so whether its owner is alive cannot be checked here: run the command where that lock "
                "was taken (the container, sandbox or session of that PID namespace), which breaks it if its owner is "
                f"dead, or check there that process {dead.pid} is not a running planloop command (or that nothing of "
                f"that namespace runs any more: run from the host's own PID namespace, `lsns -t pid | grep {PID_NS + 1}` lists it while anything of it runs, and from inside another namespace no match proves nothing; "
                f"{WSL}, then remove {bundle} by hand")
        same = "(its owner.json names the same host, boot, PID namespace, pid and start), which is settled the same way"
        f.tool("publish", "--run", RUN, "--recover")
        self.assertIn(left + "\n", f.last.stderr)
        self.assertNotIn("the same process also holds", f.last.stderr)
        self.assertEqual(json.loads((bundle / "owner.json").read_text()), owner)
        for other, shared in (({**owner, "nonce": "f" * 32}, True), ({**owner, "nonce": "f" * 32, "start": "2"}, False),
                              ({**owner, "nonce": "f" * 32, "pid_ns": PID_NS + 2}, False)):
            with self.subTest(other=other):
                run_lock.mkdir(exist_ok=True)
                (run_lock / "owner.json").write_text(json.dumps(other))
                f.tool("publish", "--run", RUN, "--recover", expect=3)
                self.assertIn(left, f.last.stderr)
                self.assertRegex(f.last.stderr, rf"(?m)^CONFLICT  {re.escape(str(run_lock))} is held by ")
                conflict = f.last.stderr[f.last.stderr.index("CONFLICT  "):]
                self.assertEqual(f"; the same process also holds {bundle} {same}" in conflict, shared)
                self.assertEqual(f"; the same process also holds {run_lock} {same}" in f.last.stderr, shared)
        shutil.rmtree(run_lock)
        shutil.rmtree(bundle)
        f.tool("publish", "--run", RUN, "--recover")
        self.assertNotIn("publish --recover left it", f.last.stderr)

    def test_a_dot_component_is_refused_even_where_pathlib_drops_it(self):
        code = ("import importlib.util, sys\nspec = importlib.util.spec_from_file_location('planloop', sys.argv[1])\n"
                "tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n"
                "for p in sys.argv[2:]:\n    try:\n        tool.safe_rel(p, 'x')\n        print('ok', p)\n"
                "    except tool.Fail as e:\n        print('fail', p, e)\n")
        paths = ["results/./out.txt", "./a", "a/.", "a/../b", "results/out.txt", "a.b/c..d"]
        out = subprocess.run([sys.executable, "-I", "-c", code, str(TOOL), *paths], capture_output=True, text=True,
                             timeout=60, check=True).stdout.splitlines()
        self.assertEqual([line.split()[0] for line in out], ["fail"] * 4 + ["ok"] * 2, out)
        self.assertIn("must not contain . or ..", out[0])

    def test_a_receipt_names_the_host_that_dispatched_a_call_held_elsewhere(self):
        f = Fixture(self)
        PolicyReviewFixes.ready_to_dispatch(self, f)
        receipt = ("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        f.tool(*PolicyReviewFixes.dispatch_args(self), env={"PLANLOOP_CRASH_AT": "after_runner"}, expect=99)
        running = f.rdir / "reviews" / "call-001-a1" / "running.json"
        written = json.loads(running.read_text())
        running.write_text(json.dumps({**written, "host": "elsewhere"}))
        f.tool(*receipt, expect=3)
        self.assertIn(f"CONFLICT  call 1 attempt 1 is still being reviewed by process {written['pid']}; wait for it; "
                      f"it was taken on host 'elsewhere': check on that host that process {written['pid']} is not a "
                      f"planloop dispatch, then remove {running} by hand and run `receipt --run {RUN} --call 1 "
                      "--attempt 1` again\n", f.last.stderr)
        self.assertFalse(probe_any(running.parent / "receipt.json"))
        running.write_text(json.dumps(written))
        f.tool(*receipt)
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)


class ClaudeBackend(unittest.TestCase):
    """The claude reviewer backend (Mike, 2026-11-14): a fresh read-only Opus Plan agent at high effort reviews each
    round and the gate; a receipt verifies its transcript; approval also needs Mike's sign-off file."""

    def setUp(self):
        self.f = Fixture(self)

    def claude_run(self, rev1=True):
        f = self.f
        f.init(backend=None)
        if rev1:
            f.publish(1, plan_text(1))
        return f

    def invalid(self, call, *reasons, attempt=1):
        r = self.f.receipt(call, attempt)
        self.assertEqual(r["status"], "invalid", r["reasons"])
        for reason in reasons:
            self.assertTrue(any(reason in x for x in r["reasons"]), (reason, r["reasons"]))
        return r

    def to_gate(self):
        f = self.claude_run()
        c = f.claude_review(review("REVISE", [finding("F1")]))
        f.ingest(c, {"F1": "new"})
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        c = f.claude_review(review("APPROVED", coverage=["plan read in full", "finding R1: resolved"]))
        f.ingest(c, {})
        f.accept_risk()
        g = f.claude_review(review(), kind="gate")
        f.ingest(g, {})
        return g

    def test_a_new_run_defaults_to_claude_and_a_run_json_without_the_field_is_codex(self):
        f = self.claude_run(rev1=False)
        self.assertEqual(json.loads((f.rdir / "run.json").read_text())["reviewer_backend"], "claude")
        self.assertIn("(claude backend)", f.last.stdout)
        f.tool("init", "--run", RUN, "--bead", BEAD, "--track", "ordinary", "--risk-domains", "none", "--rationale",
               "test importer change with no persistence or ordering semantics", "--reviewer-backend", "codex",
               expect=1)
        self.assertIn("its reviewer backend is changed only with `backend --quote`", f.last.stderr)
        legacy = Fixture(self)
        legacy.init(old=True)
        run_json = (legacy.rdir / "run.json").read_bytes()
        self.assertNotIn(b"reviewer_backend", run_json)
        legacy.init(backend=None)
        self.assertEqual((legacy.rdir / "run.json").read_bytes(), run_json)
        legacy.publish(1, plan_text(1))
        c = legacy.review(review())
        r = legacy.receipt(c)
        self.assertEqual(r["status"], "counted")
        self.assertNotIn("backend", r)
        self.assertIn("Codex rollout", r["effective"]["source"])
        codex = Fixture(self)
        codex.init()
        self.assertNotIn(b"reviewer_backend", (codex.rdir / "run.json").read_bytes())

    def test_a_valid_review_counts_and_binds_the_kept_transcript(self):
        f = self.claude_run()
        f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "working", "--effort", "medium",
               expect=1)
        self.assertIn("reviews at high effort only", f.last.stderr)
        f.tool("dispatch", "--run", RUN, "--call", "1", "--attempt", "1", "--kind", "triage", "--effort", "low",
               expect=1)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1").exists())
        c = f.claude_review(review(), receipt=False)
        record = f.dispatched(c)
        prompt = (f.rdir / "reviews" / "call-001-a1" / "input" / "prompt.txt").read_text()
        self.assertIn("-----BEGIN PLANLOOP PROMPT-----\n" + prompt + "\n-----END PLANLOOP PROMPT-----", f.launched)
        self.assertIn('subagent_type "Plan", model "opus", effort "high"', f.launched)
        self.assertEqual((record["backend"], record["model"], record["effort"], record["scope"]),
                         ("claude", "opus", "high", None))
        self.assertIn(f"cd {record['snapshot']} && ", prompt)
        copy = Path(record["snapshot"])
        self.assertEqual((copy / ".planloop-call" / "feedback.md").read_text(), f.feedback(c))
        self.assertIn(f"{copy} is a frozen, read-only snapshot", f.feedback(c))
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "running.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("record it with `receipt", f.last.stderr)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--artifacts", str(copy), expect=1)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--transcript", str(f.transcript_path))
        r = f.receipt(c)
        self.assertEqual(r["status"], "counted", r["reasons"])
        self.assertEqual((r["backend"], r["requested"], r["effective"]["model"], r["effective"]["effort"], r["fresh"]),
                         ("claude", {"model": "opus", "effort": "high"}, "claude-opus-5-5", "high", True))
        kept = Path(r["transcript"]["kept"])
        self.assertEqual(hashlib.sha256(kept.read_bytes()).hexdigest(), r["transcript"]["sha256"])
        self.assertEqual(hashlib.sha256(f.transcript_path.read_bytes()).hexdigest(), r["transcript"]["sha256"])
        self.assertEqual(r["transcript"]["source"], str(f.transcript_path))
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1")
        self.assertIn("call 1 attempt 1: counted", f.last.stdout)
        f.ingest(c, {})
        f.tool("ledger", "--run", RUN)

    def test_a_model_or_effort_other_than_opus_high_is_rejected(self):
        f = self.claude_run()
        c = f.claude_review(review(), model="claude-sonnet-5-5", expect=1)
        self.invalid(c, "is not an Opus model")
        c = f.claude_review(review(), attempt=2, call=c, alias="sonnet", expect=1)
        self.invalid(c, "agent meta records model 'sonnet'", attempt=2)
        c = f.claude_review(review(), attempt=3, call=c, effort="medium", expect=1)
        self.invalid(c, "effective effort medium differs from requested high", attempt=3)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "three bad reviewer launches")
        c = f.claude_review(review(), drop_effort=True, expect=1)
        r = self.invalid(c, "assistant turn(s) record no effort")
        self.assertTrue(r["infrastructure"])

    def test_an_edited_prompt_or_a_resumed_agent_is_rejected(self):
        f = self.claude_run()
        c = f.claude_review(review(), prompt_edit=lambda p: p.replace("fresh read-only", "fresh"), expect=1)
        self.invalid(c, "first user turn is not this call's prompt.txt byte for byte")
        c = f.claude_review(review(), attempt=2, call=c, prompt_edit=lambda p: p + "\n", expect=1)
        self.invalid(c, "byte for byte", attempt=2)
        c = f.claude_review(review(), attempt=3, call=c, later_user=True, expect=1)
        self.invalid(c, "context is not provably fresh", attempt=3)

    def test_a_tool_call_that_writes_is_rejected(self):
        f = self.claude_run()
        c = 1
        for attempt, extra, why in (
                (1, lambda copy: ("Edit", {"file_path": f"{copy}/src/a.rs", "old_string": "a", "new_string": "b"}),
                 "writes"),
                (2, lambda copy: ("Bash", {"command": f"cd {copy} && echo hi > src/b.rs"}), "writes"),
                (3, lambda copy: ("Bash", {"command": f"cd {copy} && git commit -am x"}), "writes")):
            f.claude_review(review(), call=c, attempt=attempt, receipt=False)
            copy = f.dispatched(c, attempt)["snapshot"]
            extra = extra(copy)
            prompt = (f.rdir / "reviews" / f"call-{c:03d}-a{attempt}" / "input" / "prompt.txt").read_text()
            path = FAKE_REVIEWER.write(f.transcripts, uuid.uuid4().hex[:17], prompt, review(), copy, str(f.repo),
                                       tools=FAKE_REVIEWER.default_tools(copy) + [extra])
            f.tool("receipt", "--run", RUN, "--call", str(c), "--attempt", str(attempt), "--transcript", str(path),
                   expect=1)
            self.invalid(c, why, attempt=attempt)
        f.call = c
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "reviewer wrote files")
        c = f.claude_review(review(), tools=[], expect=1)
        self.invalid(c, "never opened the plan", "never opened the feedback")
        ok = Fixture(self)
        ok.init(backend=None)
        ok.publish(1, plan_text(1))
        c = ok.claude_review(review(), receipt=False)
        copy = ok.dispatched(c)["snapshot"]
        fine = [("Bash", {"command": f"cd {copy} && grep -rn x src 2>/dev/null | sort > /dev/null; ls -la docs"}),
                ("Bash", {"command": f"cd '{copy}' && sed -n 1,5p src/a.rs && git log --oneline | head"}),
                ("Bash", {"command": f"cd {copy}/.planloop-bundle && sed -n 1,5p plan.md && cat ../src/a.rs"})]
        prompt = (ok.rdir / "reviews" / "call-001-a1" / "input" / "prompt.txt").read_text()
        path = FAKE_REVIEWER.write(ok.transcripts, uuid.uuid4().hex[:17], prompt, review(), copy, str(ok.repo),
                                   tools=FAKE_REVIEWER.default_tools(copy) + fine)
        ok.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--transcript", str(path))
        self.assertEqual(ok.receipt(1)["status"], "counted", ok.receipt(1)["reasons"])

    def test_a_bash_command_may_start_in_a_directory_inside_the_copy(self):
        """jade-8n2.pl1: `cd <copy>/<sub> && ` is as good as `cd <copy> && `; a cd target outside the copy, a sibling
        sharing its prefix, or a later climb above it still voids the call."""
        from types import SimpleNamespace
        sys.path.insert(0, str(TOOL.parent))
        import planloop
        base = self.f.root / "iso-check"
        copy = base / "isolated" / "r-1" / "repo"
        (copy / "src" / "sub").mkdir(parents=True)
        (copy / ".planloop-bundle").mkdir()
        run = SimpleNamespace(state=base / "state" / RUN, isolated=base / "isolated")
        dispatch = {"snapshot": str(copy), "live_repo": str(base / "live")}
        cases = [(f"cd {copy} && cat src/a.rs", True), (f"cd {copy}/ && ls", True),
                 (f"cd {copy}/src/sub && ls && cat ../a.rs", True),
                 (f"cd {copy}/.planloop-bundle && sed -n 1,5p plan.md", True),
                 (f"cd '{copy}/src/sub' && ls", True), (f'cd "{copy}/src" && ls', True),
                 (f"cd {copy}/./src && ls", True),
                 (f"cd {copy}/../x && ls", False), (f"cd {copy}/src/../.. && ls", False),
                 (f"cd {copy}-evil && ls", False), (f"cd {copy}2 && ls", False),
                 (f"cd '{copy}-evil' && ls", False), (f"cd {copy}-evil/src && ls", False),
                 (f"cd {copy}/src && cd ../.. && cat x", False), (f"cd {copy}/src/sub && cat ../../../x", False),
                 (f"cd {copy}/src && cat {copy}-evil/x", False), (f'cd "{copy}/$X" && ls', False),
                 (f"cd {copy}/src* && ls", False), (f"cd src && ls", False), ("cat src/a.rs", False),
                 (f"cd {base / 'live'} && ls", False), (f"cd {copy} ; ls", False)]
        wrong = []
        for command, ok in cases:
            writes, reads, other = planloop.claude_tool_problems([("Bash", {"command": command})], dispatch, run)
            if (not writes and not reads and not other) != ok:
                wrong.append((command, reads))
        self.assertEqual(wrong, [])
        writes, _, _ = planloop.claude_tool_problems([("Bash", {"command": f"cd {copy}/src && rm a.rs"})], dispatch,
                                                     run)
        self.assertTrue(writes)

    def test_a_list_only_git_branch_is_not_a_write(self):
        """jade-ahw: `git branch` that only lists or shows branches is read-only; one that could create, delete,
        rename, copy or reconfigure a branch, or uses an option off the allowlist, still counts as a write. git's
        global options are skipped to find the subcommand; `-c`, `--exec-path` and an unknown one count as a write,
        and --version/--help alone do not."""
        sys.path.insert(0, str(TOOL.parent))
        import planloop
        reads = ["git branch", "git branch -a", "git branch -r", "git branch --list", "git branch --list 'feat*'",
                 "git branch --show-current", "git branch -vv", "git branch --contains HEAD", "git branch --merged main",
                 "git log --oneline | head -5; git branch -a; cat .gitignore", "git -C x log", "git --no-pager diff",
                 "git -C x branch -a", "git --version", "git --help"]
        writes = ["git branch foo", "git branch -d foo", "git branch -D foo", "git branch -m a b", "git branch -c a b",
                  "git branch -f foo HEAD", "git branch -u origin/x", "git branch --set-upstream-to=origin/x",
                  "git branch --edit-description", "git branch --unknown-opt", "git branch -- foo",
                  "git branch -a; git commit -m x", "git branch -a > out.txt", "git -C x branch foo",
                  "git -C x commit -m y", "git -c a=b commit", "git --git-dir=.git add x",
                  "git --no-pager -C x reset --hard", "git --weird-opt status", "git -c core.pager=touch log",
                  "git -c a=b status", "git --exec-path=/x log", "git --exec-path log"]
        self.assertEqual([c for c in reads if planloop.writes_files(c)], [])
        self.assertEqual([c for c in writes if not planloop.writes_files(c)], [])
        self.assertIn("branch", planloop.GIT_WRITES)
        f = Fixture(self)
        f.init(backend=None)
        f.publish(1, plan_text(1))
        c = f.claude_review(review(), receipt=False)
        copy = f.dispatched(c)["snapshot"]
        voided = [("Bash", {"command": f"cd {copy} && git log --oneline | head -5; git branch -a; cat .gitignore"})]
        prompt = (f.rdir / "reviews" / "call-001-a1" / "input" / "prompt.txt").read_text()
        path = FAKE_REVIEWER.write(f.transcripts, uuid.uuid4().hex[:17], prompt, review(), copy, str(f.repo),
                                   tools=FAKE_REVIEWER.default_tools(copy) + voided)
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--transcript", str(path))
        self.assertEqual(f.receipt(1)["status"], "counted", f.receipt(1)["reasons"])

    def test_a_path_outside_the_private_copy_is_rejected(self):
        f = self.claude_run()
        live = str(f.repo.resolve())
        cases = (lambda copy: ("Read", {"file_path": f"{live}/src/a.rs"}),
                 lambda copy: ("Bash", {"command": "grep -rn checksum docs"}),
                 lambda copy: ("Bash", {"command": f"cd {copy} && cat ../../x"}),
                 lambda copy: ("Grep", {"pattern": "checksum"}),
                 lambda copy: ("Read", {"file_path": f"{copy}/../other/repo/src/a.rs"}),
                 lambda copy: ("Bash", {"command": f"cd {copy} && cat {f.state}/{RUN}/x"}),
                 lambda copy: ("WebFetch", {"url": "https://example.com"}))
        call, attempt = 0, 3
        for case in cases:
            if attempt == 3:
                call, attempt = call + 1, 1
                if call > 1:
                    f.tool("state", "--run", RUN, "--set", "active", "--reason", "next isolation case")
            else:
                attempt += 1
            f.claude_review(review(), call=call, attempt=attempt, receipt=False)
            f.call = call
            copy = f.dispatched(call, attempt)["snapshot"]
            prompt = (f.rdir / "reviews" / f"call-{call:03d}-a{attempt}" / "input" / "prompt.txt").read_text()
            path = FAKE_REVIEWER.write(f.transcripts, uuid.uuid4().hex[:17], prompt, review(), copy, str(f.repo),
                                       tools=FAKE_REVIEWER.default_tools(copy) + [case(copy)])
            f.tool("receipt", "--run", RUN, "--call", str(call), "--attempt", str(attempt), "--transcript", str(path),
                   expect=1)
            r = self.invalid(call, attempt=attempt)
            self.assertTrue(any("outside its private snapshot copy" in x or "does not allow a reviewer" in x
                                for x in r["reasons"]), r["reasons"])

    def test_malformed_json_or_coverage_is_rejected(self):
        f = self.claude_run()
        good = json.dumps(review())
        c = f.claude_review(good[:-1] + ', "verdict": "APPROVED"}', expect=1)
        self.invalid(c, "not one strict JSON object", "duplicate JSON key")
        c = f.claude_review("```json\n" + good + "\n```", call=c, attempt=2, expect=1)
        self.invalid(c, "not one strict JSON object", attempt=2)
        c = f.claude_review({**review(), "extra": 1}, call=c, attempt=3, expect=1)
        self.invalid(c, "does not have exactly the runner's fields", attempt=3)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "malformed responses")
        c = f.claude_review(review("REVISE", [finding("F1")]))
        f.ingest(c, {"F1": "new"})
        f.publish(2, plan_text(2, answers=["FIX R1: add the checksum lookup"]))
        c = f.claude_review(review(), expect=1)
        self.invalid(c, "reviewer did not report on findings ['R1']")
        c = f.claude_review(review(coverage=["plan read in full", "finding R1: resolved."]), call=c, attempt=2, expect=1)
        self.invalid(c, "looks like a finding status", attempt=2)
        c = f.claude_review(review(coverage=["plan read in full", "finding R1: resolved"]), call=c, attempt=3,
                            final="end_turn")
        self.assertEqual(f.receipt(c, 3)["status"], "counted", f.receipt(c, 3)["reasons"])

    def test_an_unfinished_agent_is_not_recorded_until_it_finishes_or_is_given_up(self):
        f = self.claude_run()
        c = f.claude_review(review(), finished=False, expect=3)
        self.assertIn("has not finished", f.last.stderr)
        self.assertFalse((f.rdir / "reviews" / "call-001-a1" / "receipt.json").exists())
        self.assertFalse((f.artifacts(c) / "transcript.jsonl").exists())
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", "--transcript", "none", expect=1)
        self.invalid(c, "no reviewer transcript is recorded")
        f.tool("receipt", "--run", RUN, "--call", "1", "--attempt", "1", expect=1)
        self.assertIn("call 1 attempt 1: invalid", f.last.stdout)
        c = f.claude_review(review(), call=1, attempt=2, delivered=False, expect=1)
        self.invalid(c, "not acknowledged as delivered", attempt=2)
        c = f.claude_review(review(), call=1, attempt=3, agent_type="general-purpose", expect=1)
        self.invalid(c, "read-only Plan agent", attempt=3)

    def test_the_gate_needs_mikes_sign_off_and_reverifies_after_approval(self):
        f = self.f
        g = self.to_gate()
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [host-attested] Mike signed off revision 2", f.last.stdout)
        self.assertIn("PASS  [mechanical] gate requested Opus at high effort", f.last.stdout)
        f.tool("gate", "--run", RUN, "--publish", expect=1)
        self.assertFalse((f.rdir / "APPROVAL").exists())
        receipt_sha = hashlib.sha256((f.rdir / "reviews" / f"call-{g:03d}-a1" / "receipt.json").read_bytes()).hexdigest()
        plan_sha = f.receipt(g)["plan_sha256"]
        wrong = {"schema": "planloop-signoff/1", "id": "A1", "by": "Mike", "quote": "ship it",
                 "recorded_at": "2026-11-14T12:00:00Z", "recorded_by": "orchestrator", "revision": 2,
                 "plan_sha256": plan_sha, "gate_call": g, "gate_attempt": 1, "gate_receipt_sha256": "0" * 64}
        (f.rdir / "decisions" / "A1.json").write_text(json.dumps(wrong))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("NOTE  decisions/A1.json signs off revision 2", f.last.stdout)
        (f.rdir / "decisions" / "A1.json").write_text(json.dumps({**wrong, "by": "Someone"}))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] sign-off A1.json well formed", f.last.stdout)
        (f.rdir / "decisions" / "A1.json").unlink()
        f.tool("signoff", "--run", RUN, "--quote", "Approved, go ahead with the plan as reviewed.")
        signed = json.loads((f.rdir / "decisions" / "A1.json").read_text())
        self.assertEqual((signed["gate_receipt_sha256"], signed["plan_sha256"], signed["by"]),
                         (receipt_sha, plan_sha, "Mike"))
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PLAN APPROVED: revision 2", f.last.stdout)
        bead = f.run_bead()
        self.assertEqual(bead["metadata"]["planloop_state"], "approved")
        self.assertIn(f"gate call {g} attempt 1 by a fresh Plan agent on claude-opus-5-5 at high effort, verdict "
                      "APPROVED", bead["notes"])
        self.assertIn('Mike\'s sign-off A1: "Approved, go ahead with the plan as reviewed."', bead["notes"])
        approval = json.loads((f.rdir / "approvals" / json.loads((f.rdir / "APPROVAL").read_text())["record"])
                              .read_text())
        self.assertEqual((approval["reviewer_backend"], approval["signoff"]["id"]), ("claude", "A1"))
        f.tool("gate", "--run", RUN, "--publish")
        self.assertEqual(f.run_bead()["notes"].count("planloop approval"), 1)
        f.tool("gate", "--run", RUN)
        self.assertIn("PASS  [mechanical] gate receipt re-derived from the reviewer's kept transcript matches",
                      f.last.stdout)
        self.assertIn("PLAN APPROVED", f.last.stdout)
        proc = subprocess.run([str(HERE.parent / "check_receipt.sh"), "--run", RUN], cwd=f.repo, env=f.env,
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        kept = Path(f.receipt(g)["transcript"]["kept"])
        original = kept.read_bytes()
        kept.chmod(0o644)
        kept.write_bytes(original.replace(b"claude-opus-5-5", b"claude-opus-5-6", 1))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] gate receipt re-derived from the reviewer's kept transcript", f.last.stdout)
        kept.write_bytes(original)
        f.tool("gate", "--run", RUN)
        signed_path = f.rdir / "decisions" / "A1.json"
        signed_path.write_text(json.dumps({**signed, "quote": "Approved."}))
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] the published approval matches the current state", f.last.stdout)

    def test_a_backend_switch_voids_a_prior_gate(self):
        f = self.f
        g = self.to_gate()
        f.tool("signoff", "--run", RUN, "--quote", "Approved.")
        f.tool("gate", "--run", RUN, "--publish")
        f.tool("backend", "--run", RUN, "--set", "claude", "--quote", "stay on claude", expect=1)
        f.tool("backend", "--run", RUN, "--set", "codex", "--quote", "", expect=1)
        f.tool("backend", "--run", RUN, "--set", "codex", "--quote", "Use Codex for this one, usage is low.")
        self.assertIn(f"no gate of call {g} or earlier counts", f.last.stdout)
        config = json.loads((f.rdir / "run.json").read_text())
        self.assertEqual(config["reviewer_backend"], "codex")
        self.assertEqual({k: v for k, v in config["backend_changes"][0].items() if k != "at"},
                         {"from": "claude", "to": "codex", "quote": "Use Codex for this one, usage is low.",
                          "after_call": g})
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] the gate was reviewed by this run's reviewer backend (codex)", f.last.stdout)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "Mike moved this run to Codex")
        c = f.review(review(), kind="gate", effort="high")
        self.assertNotIn("backend", f.receipt(c))
        f.ingest(c, {})
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PLAN APPROVED: revision 2", f.last.stdout)
        f.tool("backend", "--run", RUN, "--set", "claude", "--quote", "Back to Opus.")
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [mechanical] the gate was reviewed by this run's reviewer backend (claude)",
                      f.last.stdout)
        self.assertIn(f"calls up to {c} predate the switch to claude", f.last.stdout)
        f.tool("state", "--run", RUN, "--set", "active", "--reason", "Mike moved this run back to claude")
        g2 = f.claude_review(review(), kind="gate", call=c + 1)
        f.ingest(g2, {})
        f.tool("gate", "--run", RUN, expect=1)
        self.assertIn("FAIL  [host-attested] Mike signed off", f.last.stdout)
        self.assertIn("NOTE  decisions/A1.json signs off revision 2 gate call", f.last.stdout)
        f.tool("signoff", "--run", RUN, "--quote", "Approved again.")
        self.assertTrue((f.rdir / "decisions" / "A2.json").exists())
        f.tool("gate", "--run", RUN, "--publish")
        self.assertIn("PLAN APPROVED: revision 2", f.last.stdout)


atexit.register(lambda: [f.cleanup() for f in FIXTURES])
signal.signal(signal.SIGTERM, signal.default_int_handler)

if __name__ == "__main__":
    from run_parallel import main
    main()
