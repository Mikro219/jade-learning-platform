#!/usr/bin/env python3
"""
planloop support tool (quartz-rs-lur, 2026-10-22). Python 3.10+, standard
library only. Only the host orchestrator runs it, except `handback --check`,
which planners run on their draft; reviewers never do. Policy: ../SKILL.md.
Planner handback contract: ../references/handback.md. Every file format:
../references/formats.md.

  init      --run R --bead B --track ordinary|escalated --risk-domains LIST|none --rationale TEXT
            [--reviewer-model M] [--gate-model G]
  handback  --run R --revision N --nonce X --transcript AGENT.jsonl
            --run R --check [--revision N] < DRAFT   read-only self-check of plan content (planners may run it)
  bundle    --run R --revision N --nonce X --inputs INPUTS.json
  publish   --run R --revision N --nonce X     |   publish --run R --recover
  dispatch  --run R --call C --attempt A --kind K --effort E
  receipt   --run R --call C --attempt A [--artifacts DIR]
  findings  ingest --run R --call C --attempt A --map MAP.json
            propose --run R
            decide --run R --decision decisions/Dn.json
            check --run R
  evidence  --run R FILE...
  state     --run R --set active|blocked|needs_decision --reason TEXT
  planner   --run R --model opus --quote TEXT   (Mike's escalated-track planner override)
  reviewers --run R --model M --gate-model G --quote TEXT   (Mike's Codex model choice for this run)
  ledger    --run R
  gate      --run R [--publish]
  rollout-check --artifacts RUNNER_DIR [--accept]   validate a new Codex version

Exit codes: 0 success or ready; 1 a check failed (each failure is printed);
2 usage error or unverifiable input; 3 lock, publication or Beads conflict.

Test hooks, never set outside tests: PLANLOOP_CRASH_AT=<point> ends the
process at that point; PLANLOOP_NOW fixes the clock (ISO 8601, UTC);
PLANLOOP_BD, PLANLOOP_RUNNER, PLANLOOP_STATE and PLANLOOP_CODEX_SESSIONS
redirect the Beads CLI, the claudex-loop runner, the state directory and
Codex's session store; PLANLOOP_LOCK_TIMEOUT shortens lock waits;
PLANLOOP_ROLLOUT_VERSIONS points at another accepted-versions list.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

POLICY = "planloop/3 (quartz-rs-lur, 2026-10-22)"
ROLLOUT_PARSER = "codex-rollout/1"
VERSIONS_FILE = Path(os.environ.get("PLANLOOP_ROLLOUT_VERSIONS",
                                    Path(__file__).resolve().parent / "codex_rollout_versions.txt"))
EFFORTS = {"low": 0, "medium": 1, "high": 2}
KINDS = ("working", "focused", "adjudication", "gate", "triage")
STATES = ("open", "fix_proposed", "reopened", "verified", "withdrawn", "decided")
OPEN_STATES = ("open", "fix_proposed", "reopened")
DEFAULT_REVIEWER_MODEL, DEFAULT_GATE_MODEL = "gpt-6-astra", "gpt-6-astra"
BEAD_FIELDS = ("title", "description", "acceptance_criteria", "design", "notes")
DEFAULT_BEAD_FIELDS = ("title", "description", "acceptance_criteria", "design")
PLAN_ID = re.compile(r"\b(OB|INV|RR|AC|EV)\d+\b")
FINDING_ID = re.compile(r"^R[1-9]\d*$")
ANSWER = re.compile(r"^\s*[-*]?\s*(FIX|REDESIGN|REJECT)\s+(R[1-9]\d*):\s*(\S.*)$")
REMOVED = re.compile(r"^\s*[-*]?\s*REMOVED\s+(\S.*)$")
SHRINK = re.compile(r"^\s*[-*]?\s*SHRINK\s+(\S.*)$")
RUN_AREA = "plans/planloop"
COVERAGE = re.compile(r"^finding (R[1-9]\d*): (resolved|unresolved|withdrawal confirmed|withdrawn: (\S.{39,}))$")
COVERAGE_LIKE = re.compile(r"^\s*finding\s+R\d+\s*:\s*(resolved|unresolved|withdraw)", re.I)
TITLE = re.compile(r"^# PLAN (\S+): .+ \(revision (\d+), (\d{4}-\d{2}-\d{2})\)$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_DEFAULT = {"max_rows": 1000, "max_bytes": 1 << 20}
EVIDENCE_CAP = {"max_rows": 100000, "max_bytes": 64 << 20}
RETRY_BACKOFF = (5, 15)
RISK_DOMAINS = ("recovery", "reconciliation", "persistence", "ordering", "idempotency", "session-identity",
                "state-machine", "cross-system-consistency", "silent-corruption", "concurrency")
MAX_ATTEMPTS = 3


class Fail(Exception):
    code = 1


class Unverifiable(Exception):
    code = 2


class Conflict(Exception):
    code = 3


def crash_point(name: str) -> None:
    if os.environ.get("PLANLOOP_CRASH_AT") == name:
        os._exit(99)


def now() -> dt.datetime:
    fixed = os.environ.get("PLANLOOP_NOW")
    return parse_time(fixed) if fixed else dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(text, what="timestamp") -> dt.datetime:
    if not isinstance(text, str):
        raise Fail(f"{what} is not a string")
    try:
        t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Fail(f"{what} {text!r} is not ISO 8601") from exc
    if t.tzinfo is None:
        raise Fail(f"{what} {text!r} has no zone")
    return t


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(path.read_bytes())


def canon(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Fail(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _constant(name):
    raise Fail(f"non-finite JSON number {name}")


def loads(text: str, what: str):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as exc:
        raise Fail(f"{what}: malformed JSON ({exc})") from exc
    except Fail as exc:
        raise Fail(f"{what}: {exc}") from exc


def load(path: Path, what: str | None = None):
    what = what or str(path)
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError as exc:
        raise Fail(f"{what}: missing") from exc
    except UnicodeDecodeError as exc:
        raise Fail(f"{what}: not UTF-8") from exc
    return loads(text, what)


def shape(value, spec: dict, what: str, exact: bool = True) -> dict:
    if not isinstance(value, dict):
        raise Fail(f"{what}: not an object")
    missing = [k for k in spec if k not in value]
    extra = [k for k in value if k not in spec]
    if missing:
        raise Fail(f"{what}: missing {', '.join(missing)}")
    if exact and extra:
        raise Fail(f"{what}: unexpected {', '.join(extra)}")
    for key, kind in spec.items():
        item = value[key]
        if isinstance(kind, (set, frozenset)):
            if item not in kind:
                raise Fail(f"{what}.{key}: {item!r} not one of {sorted(map(str, kind))}")
        elif kind == "hex":
            if not isinstance(item, str) or not HEX64.match(item):
                raise Fail(f"{what}.{key}: not a SHA-256")
        elif kind == "hex?":
            if item is not None and (not isinstance(item, str) or not HEX64.match(item)):
                raise Fail(f"{what}.{key}: not a SHA-256 or null")
        elif kind == "str":
            if not isinstance(item, str) or not item.strip():
                raise Fail(f"{what}.{key}: empty or not a string")
        elif kind == "str?":
            if item is not None and not isinstance(item, str):
                raise Fail(f"{what}.{key}: not a string or null")
        elif kind == "int":
            if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                raise Fail(f"{what}.{key}: not a non-negative integer")
        elif kind == "int?":
            if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0):
                raise Fail(f"{what}.{key}: not a non-negative integer or null")
        elif kind == "bool":
            if not isinstance(item, bool):
                raise Fail(f"{what}.{key}: not a boolean")
        elif kind == "list":
            if not isinstance(item, list):
                raise Fail(f"{what}.{key}: not a list")
        elif kind == "dict":
            if not isinstance(item, dict):
                raise Fail(f"{what}.{key}: not an object")
        elif kind == "any":
            pass
        else:
            raise AssertionError(kind)
    return value


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def rename(src: Path, dst: Path) -> None:
    for delay in (0.1, 0.3, 1.0, 2.0, None):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if delay is None:
                raise Conflict(f"could not rename {src} -> {dst}: a file inside is held open (drvfs EACCES)")
            time.sleep(delay)


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=120)
    if check and proc.returncode:
        raise Unverifiable(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
    if out.returncode:
        raise Unverifiable("not inside a git checkout")
    return Path(out.stdout.decode().strip()).resolve()


def safe_rel(path: str, what: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise Fail(f"{what}: {path!r} must be a repository-relative path")
    parts = Path(path).parts
    if any(p in ("..", ".") for p in parts):
        raise Fail(f"{what}: {path!r} must not contain . or ..")
    return path


def ok(msg: str) -> None:
    print(f"PASS  {msg}")


class Report:
    def __init__(self):
        self.failures = []

    def check(self, cond: bool, label: str, detail: str = "") -> bool:
        if cond:
            ok(label)
        else:
            print(f"FAIL  {label}{': ' + detail if detail else ''}")
            self.failures.append(label)
        return cond


def proc_start(pid: int):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return text.rsplit(")", 1)[1].split()[19]


def identity() -> dict:
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = ""
    return {"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(), "start": proc_start(os.getpid())}


def owner_alive(owner: dict) -> bool:
    me = identity()
    if owner.get("host") != me["host"]:
        return True
    if owner.get("boot_id") and me["boot_id"] and owner["boot_id"] != me["boot_id"]:
        return False
    pid = owner.get("pid")
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    start = proc_start(pid)
    return start is None or start == owner.get("start")


class Lock:
    def __init__(self, directory: Path, name: str = ".lock"):
        self.path = directory / name
        self.nonce = None
        self.timeout = float(os.environ.get("PLANLOOP_LOCK_TIMEOUT", "30"))

    def read_owner(self, path: Path | None = None):
        try:
            value = loads((path or self.path).joinpath("owner.json").read_text(), "lock owner")
        except (OSError, Fail):
            return None
        return value if isinstance(value, dict) and isinstance(value.get("nonce"), str) else None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            nonce = uuid.uuid4().hex
            tmp = self.path.parent / f".lock-tmp-{nonce}"
            tmp.mkdir()
            (tmp / "owner.json").write_bytes(canon({**identity(), "nonce": nonce, "acquired_at": iso(now())}))
            try:
                os.rename(tmp, self.path)
                self.nonce = nonce
                crash_point("lock_acquired")
                return self
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
            if self._break_stale():
                continue
            if time.monotonic() > deadline:
                breaker = self.path.parent / ".lock-break"
                hint = (f"; {breaker} exists, left by a crashed lock breaker: remove it once no planloop process "
                        "runs") if breaker.exists() else ""
                raise Conflict(f"{self.path} is held by {self.read_owner()}; it is never broken unless its "
                               f"owner is provably dead on this host{hint}")
            time.sleep(0.2)

    def _break_stale(self) -> bool:
        owner = self.read_owner()
        if owner is None or owner_alive(owner):
            return False
        breaker = self.path.parent / ".lock-break"
        try:
            breaker.mkdir()
        except FileExistsError:
            return False
        try:
            again = self.read_owner()
            if again is None or again["nonce"] != owner["nonce"]:
                return False
            crash_point("lock_breaking")
            rename(self.path, self.path.parent / f".lock-broken-{owner['nonce']}")
            print(f"NOTE  broke stale lock of dead owner {owner}", file=sys.stderr)
            return True
        finally:
            breaker.rmdir()

    def __exit__(self, *exc):
        owner = self.read_owner()
        if owner is None or owner["nonce"] != self.nonce:
            raise Conflict(f"lock {self.path} is no longer ours; another writer broke it")
        dest = self.path.parent / f".lock-released-{self.nonce}"
        rename(self.path, dest)
        shutil.rmtree(dest, ignore_errors=True)
        return False


def norm_meta(record):
    if isinstance(record, dict) and isinstance(record.get("metadata"), dict):
        record["metadata"] = {k: ("true" if v is True else "false" if v is False else "" if v is None else str(v))
                              for k, v in record["metadata"].items()}
    return record


class Beads:
    MISSING = "no issues found matching the provided IDs"

    def __init__(self, repo: Path):
        self.cmd = shlex.split(os.environ.get("PLANLOOP_BD", "bd"))
        self.repo = repo

    def _run(self, args):
        try:
            proc = subprocess.run(self.cmd + args, cwd=self.repo, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired:
            return None
        return proc

    def _json(self, proc, what):
        if proc is None:
            raise Unverifiable(f"bd {what} timed out")
        if proc.returncode:
            raise Unverifiable(f"bd {what} failed: {proc.stderr.decode(errors='replace').strip()[:300]}")
        return loads(proc.stdout.decode("utf-8"), f"bd {what}")

    def get(self, bead_id: str):
        proc = self._run(["show", bead_id, "--json"])
        if proc is not None and proc.returncode:
            try:
                value = json.loads(proc.stdout.decode("utf-8"))
            except ValueError:
                value = None
            if isinstance(value, dict) and value.get("error") == self.MISSING:
                return None
        value = self._json(proc, f"show {bead_id}")
        if isinstance(value, list):
            if len(value) != 1:
                raise Unverifiable(f"bd show {bead_id} returned {len(value)} records")
            value = value[0]
        if not isinstance(value, dict) or value.get("id") != bead_id:
            raise Unverifiable(f"bd show {bead_id} returned another record")
        return norm_meta(value)

    def by_key(self, key: str) -> list:
        value = self._json(self._run(["list", "--all", "--metadata-field", f"planloop_key={key}",
                                      "-n", "0", "--json"]), f"list key {key}")
        if not isinstance(value, list):
            raise Unverifiable("bd list did not return a list")
        return [norm_meta(v) for v in value if (v.get("metadata") or {}).get("planloop_key") == key]

    def keyed(self, key: str):
        found = self.by_key(key)
        if len(found) > 1:
            raise Conflict(f"Beads holds {len(found)} records for logical key {key}: "
                           f"{[f['id'] for f in found]}; reconcile by hand before continuing")
        return found[0] if found else None

    def create_keyed(self, key: str, parent: str, title: str, kind: str, meta: dict) -> dict:
        existing = self.keyed(key)
        if existing:
            return existing
        nonce = uuid.uuid4().hex
        body = {**{k: str(v) for k, v in meta.items()}, "planloop_key": key, "planloop_write": nonce}
        proc = self._run(["create", "--parent", parent, "--title", title, "--type", kind,
                          "--metadata", json.dumps(body, sort_keys=True), "--silent"])
        crash_point("bead_created")
        found = self.keyed(key)
        if found is None:
            raise Unverifiable(f"bd create for {key} left no record "
                               f"(rc {None if proc is None else proc.returncode}); re-run to retry")
        if found["metadata"].get("planloop_write") != nonce:
            raise Conflict(f"{key} was created by another writer ({found['id']}); our create did not land")
        if proc is not None and proc.returncode == 0:
            reported = proc.stdout.decode().strip().splitlines()[-1:] or [""]
            if reported[0] != found["id"]:
                raise Conflict(f"bd reported {reported[0]!r} but {key} is {found['id']}")
        return found

    def update(self, bead: dict, meta: dict, status: str | None = None, reason: str = "") -> dict:
        key = bead["metadata"]["planloop_key"]
        meta = {k: str(v) for k, v in meta.items()}
        current = self.keyed(key)
        if current is None or current["id"] != bead["id"]:
            raise Conflict(f"{key} no longer resolves to {bead['id']}")
        need_meta = {k: v for k, v in meta.items() if (current.get("metadata") or {}).get(k) != v}
        if need_meta:
            args = ["update", current["id"]]
            for k, v in sorted(need_meta.items()):
                args += ["--set-metadata", f"{k}={v}"]
            self._run(args)
        if status == "closed" and current.get("status") != "closed":
            self._run(["close", current["id"], "--reason", reason or "planloop"])
        elif status == "open" and current.get("status") == "closed":
            self._run(["update", current["id"], "--status", "open"])
        crash_point("bead_updated")
        after = self.keyed(key)
        if after is None or after["id"] != bead["id"]:
            raise Conflict(f"{key} vanished during update")
        bad = {k: v for k, v in meta.items() if after["metadata"].get(k) != v}
        wrong_status = (status == "closed" and after.get("status") != "closed") or \
            (status == "open" and after.get("status") == "closed")
        if bad or wrong_status:
            raise Unverifiable(f"update of {after['id']} did not read back ({bad or after.get('status')}); re-run")
        return after

    def children(self, parent: str) -> list:
        value = self._json(self._run(["list", "--all", "--parent", parent, "-n", "0", "--json"]),
                           f"list --parent {parent}")
        if not isinstance(value, list):
            raise Unverifiable("bd list did not return a list")
        return [norm_meta(v) for v in value]


class Run:
    ID = re.compile(r"^([a-z0-9][a-z0-9-]*)\.pl([1-9]\d*)$")

    def __init__(self, run_id: str):
        match = self.ID.match(run_id or "")
        if not match:
            raise Fail(f"run id {run_id!r} must look like <bead>.pl<N>")
        self.id = run_id
        self.bead = match.group(1)
        self.repo = repo_root()
        self.dir = self.repo / "plans" / "planloop" / run_id
        root = Path(os.environ.get("PLANLOOP_STATE", "~/.local/state/planloop")).expanduser()
        self.state = root.resolve() / run_id
        self.isolated = Path(os.environ.get("PLANLOOP_ISOLATED", "~/.local/state/planloop-isolated")).expanduser().resolve()
        self.beads = Beads(self.repo)

    def config(self) -> dict:
        value = load(self.dir / "run.json")
        if isinstance(value, dict):
            value.setdefault("gate_model", None)
            value.setdefault("model_changes", [])
        value = shape(value, {"schema": {"planloop-run/1"}, "run_id": "str", "bead": "str",
                              "reviewer_model": "str?", "gate_model": "str?", "model_changes": "list",
                              "policy": "str", "created_at": "str"}, "run.json")
        if value["run_id"] != self.id or value["bead"] != self.bead:
            raise Fail("run.json does not describe this run")
        return value

    def head(self):
        path = self.dir / "HEAD"
        if not path.exists():
            return None
        value = shape(load(path, "HEAD"), {"schema": {"planloop-head/1"}, "revision": "int",
                                           "revision_sha256": "hex"}, "HEAD")
        return value["revision"], value["revision_sha256"]

    def rev_dir(self, n: int) -> Path:
        return self.dir / f"rev-{n:03d}"

    def staging(self, n: int, nonce: str) -> Path:
        if not re.match(r"^[0-9a-f]{8,64}$", nonce or ""):
            raise Fail("nonce must be 8-64 lowercase hex characters")
        return self.dir / f".staging-{n:03d}-{nonce}"

    def snapshot(self, n: int, nonce: str) -> Path:
        return self.state / f"snap-r{n:03d}-{nonce}"

    def call_dir(self, call: int, attempt: int) -> Path:
        return self.dir / "reviews" / f"call-{call:03d}-a{attempt}"

    def run_bead(self) -> dict:
        bead = self.beads.keyed(f"run:{self.id}")
        if bead is None:
            raise Fail(f"no run bead for {self.id}; run init")
        return bead

    def findings(self) -> dict:
        out = {}
        run_bead = self.run_bead()
        for child in self.beads.children(run_bead["id"]):
            meta = child.get("metadata") or {}
            if meta.get("planloop_kind") != "finding" or meta.get("planloop_run") != self.id:
                continue
            fid = meta.get("planloop_finding", "")
            if fid in out:
                raise Conflict(f"two beads carry finding {fid}: {out[fid]['id']}, {child['id']}")
            out[fid] = child
        return out


def finding_key(run: Run, fid: str) -> str:
    return f"finding:{run.id}:{fid}"


def headings(text: str) -> list:
    out, fence = [], False
    for line in text.split("\n"):
        if line.startswith("```") or line.startswith("~~~"):
            fence = not fence
            continue
        if not fence and (line.startswith("## ") or line.startswith("### ")):
            out.append(line.rstrip())
    return out


def sections(text: str) -> dict:
    out, current, fence = {}, None, False
    for line in text.split("\n"):
        if line.startswith("```") or line.startswith("~~~"):
            fence = not fence
        if not fence and (line.startswith("## ") or line.startswith("### ")):
            current = line.rstrip()
            out[current] = []
            continue
        if current is not None:
            out[current].append(line)
    return out


def inventory(text: str):
    secs = sections(text)
    body = secs.get("## Artifact inventory")
    if body is None:
        raise Fail("plan has no '## Artifact inventory' section")
    listed_sections, listed_ids = [], []
    for line in body:
        line = line.strip()
        if line.startswith("- section: "):
            listed_sections.append(line[len("- section: "):].strip())
        elif line.startswith("- id: "):
            listed_ids.append(line[len("- id: "):].strip())
        elif line:
            raise Fail(f"artifact inventory line not understood: {line!r}")
    return listed_sections, listed_ids


def analyse_plan(text: str, run: Run, revision: int) -> dict:
    if text.startswith("﻿"):
        raise Fail("plan starts with a byte-order mark")
    first = text.split("\n", 1)[0]
    match = TITLE.match(first)
    if not match:
        raise Fail(f"first line is not '# PLAN <bead>: <title> (revision N, YYYY-MM-DD)': {first!r}")
    if match.group(1) != run.bead or int(match.group(2)) != revision:
        raise Fail(f"title names {match.group(1)} revision {match.group(2)}, expected {run.bead} revision {revision}")
    heads = headings(text)
    dup = sorted({h for h in heads if heads.count(h) > 1})
    if dup:
        raise Fail(f"duplicate headings: {dup}")
    for required in ("## Artifact inventory", "## Change log"):
        if required not in heads:
            raise Fail(f"plan lacks {required!r}")
    listed_sections, listed_ids = inventory(text)
    if sorted(set(listed_sections)) != sorted(listed_sections) or sorted(set(listed_ids)) != sorted(listed_ids):
        raise Fail("artifact inventory lists an entry twice")
    missing = [h for h in heads if h not in listed_sections]
    phantom = [s for s in listed_sections if s not in heads]
    if missing or phantom:
        raise Fail(f"inventory and headings disagree: unlisted {missing}, listed but absent {phantom}")
    bad_ids = [i for i in listed_ids if not PLAN_ID.fullmatch(i)]
    if bad_ids:
        raise Fail(f"inventory ids outside OB/INV/RR/AC/EV: {bad_ids}")
    secs = sections(text)
    outside = "\n".join(line for h, body in secs.items() if h != "## Artifact inventory" for line in [h, *body]
                        if not REMOVED.match(line))
    used = {m.group(0) for m in PLAN_ID.finditer(outside)}
    undefined = sorted(i for i in listed_ids if i not in used)
    dangling = sorted(i for i in used if i not in listed_ids)
    if undefined or dangling:
        raise Fail(f"ids listed but never used {undefined}; ids used but not in the inventory {dangling}")
    log = secs["## Change log"]
    answers, removed, shrink = {}, [], []
    for line in log:
        if (m := ANSWER.match(line)):
            if m.group(2) in answers:
                raise Fail(f"change log answers {m.group(2)} twice")
            answers[m.group(2)] = m.group(1)
        elif (m := REMOVED.match(line)):
            removed.append(m.group(1).strip())
        elif (m := SHRINK.match(line)):
            shrink.append(m.group(1).strip())
    rr = {}
    for line in secs.get("## Residual risks", []):
        m = re.match(r"^\s*[-*]\s*(RR\d+):\s*(\S.*)$", line)
        if m:
            if m.group(1) in rr:
                raise Fail(f"{m.group(1)} is stated twice")
            rr[m.group(1)] = m.group(2).strip()
    rr_ids = sorted(i for i in listed_ids if i.startswith("RR"))
    if rr_ids != sorted(rr):
        raise Fail(f"every RR id needs exactly one '- RR<n>: <text>' line under '## Residual risks': "
                   f"inventory {rr_ids}, stated {sorted(rr)}")
    return {"sections": listed_sections, "ids": listed_ids, "answers": answers, "removed": removed,
            "shrink": shrink, "residual_risks": rr, "section_lines": {h: b for h, b in secs.items()}}


def disposition(entries: list, item: str):
    for entry in entries:
        if entry.startswith(item + ":"):
            return entry[len(item) + 1:].strip()
    return None


def extract_handback(transcript: Path) -> tuple[str, dict]:
    meta_path = transcript.with_name(transcript.name[:-len(".jsonl")] + ".meta.json") \
        if transcript.name.endswith(".jsonl") else None
    if meta_path is None or not meta_path.exists():
        raise Unverifiable(f"no agent meta file beside {transcript}; completion cannot be verified")
    meta = load(meta_path, "agent meta")
    if meta.get("finished") is not True:
        raise Fail("agent meta does not record a finished run")
    if meta.get("agentType") != "Plan":
        raise Fail(f"the planner must be the read-only Plan agent, not {meta.get('agentType')!r}")
    rows = []
    for number, line in enumerate(transcript.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise Unverifiable(f"transcript line {number} is not JSON") from exc
    handbacks, results = [], {}
    for row in rows:
        message = row.get("message") if isinstance(row, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if row.get("type") == "assistant" and block.get("type") == "tool_use" \
                    and block.get("name") == "SubagentHandback":
                handbacks.append(block)
            if row.get("type") == "user" and block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = block
    if handbacks:
        last = handbacks[-1]
        result = results.get(last.get("id"))
        text = json.dumps(result.get("content")) if result else ""
        if not result or result.get("is_error") or '\\"success\\":true' not in text:
            raise Fail("the agent's final handback was not acknowledged as delivered")
        message = (last.get("input") or {}).get("message")
        if not isinstance(message, str):
            raise Unverifiable("handback input has no message string")
        return message, {"kind": "SubagentHandback", "tool_use_id": last.get("id"), "meta_finished": True,
                         "agent_type": meta.get("agentType"), "model": meta.get("model")}
    finals = [r for r in rows if r.get("type") == "assistant"
              and (r.get("message") or {}).get("stop_reason") == "end_turn"]
    if not finals:
        raise Unverifiable("transcript format not recognised: no handback call and no end_turn message")
    texts = [b.get("text", "") for b in finals[-1]["message"]["content"] if b.get("type") == "text"]
    return "".join(texts), {"kind": "end_turn", "meta_finished": True, "agent_type": meta.get("agentType"),
                            "model": meta.get("model")}


def cmd_init(args) -> int:
    domains = sorted({d.strip() for d in args.risk_domains.split(",") if d.strip()} - {"none"})
    unknown = [d for d in domains if d not in RISK_DOMAINS]
    if unknown:
        raise Fail(f"unknown risk domains {unknown}; use {', '.join(RISK_DOMAINS)} or none")
    if domains and args.track != "escalated":
        raise Fail(f"risk domains {domains} require --track escalated (Fable drafts and redesigns, Opus writes FIX "
                   "revisions, Codex reviews at high)")
    if args.risk_domains.strip() != "none" and not domains:
        raise Fail("--risk-domains must list domains or say none")
    if len(args.rationale.strip()) < 20:
        raise Fail("--rationale must say why, in a sentence naming what the work changes")
    run = Run(args.run)
    path = run.dir / "run.json"
    old = run.config() if path.exists() else {"reviewer_model": DEFAULT_REVIEWER_MODEL, "gate_model": DEFAULT_GATE_MODEL}
    config = {"schema": "planloop-run/1", "run_id": run.id, "bead": run.bead,
              "reviewer_model": args.reviewer_model or old["reviewer_model"],
              "gate_model": args.gate_model or old["gate_model"], "model_changes": [],
              "policy": POLICY, "created_at": iso(now())}
    if path.exists():
        fixed = ("created_at", "model_changes")
        if {k: v for k, v in old.items() if k not in fixed} != {k: v for k, v in config.items() if k not in fixed}:
            raise Fail("run.json exists with different settings")
    else:
        write_atomic(path, canon(config))
    if run.beads.get(run.bead) is None:
        raise Fail(f"implementation bead {run.bead} does not exist")
    classification = {"planloop_risk_domains": ",".join(domains) or "none",
                      "planloop_risk_rationale": f"text: {args.rationale.strip()[:400]}"}
    with Lock(run.dir):
        next_revision = str((run.head() or (0,))[0] + 1)
        bead = run.beads.create_keyed(f"run:{run.id}", run.bead, f"planloop run {run.id}", "task", {
            **classification,
            "planloop_escalated_revision": next_revision if args.track == "escalated" else "",
            "planloop_kind": "run", "planloop_run": run.id, "planloop_state": "active",
            "planloop_track": args.track, "planloop_min_effort": "high" if args.track == "escalated" else "medium",
            "planloop_redesign_required": "", "planloop_redesigns": "", "planloop_reason": "",
            "planloop_approval_candidate": "", "planloop_approval": "", "planloop_active_after_call": "0"})
        current = meta_of(bead)
        if args.track == "ordinary" and current.get("planloop_track") == "escalated":
            raise Fail("the run is on the escalated track; a track is never lowered")
        if current.get("planloop_risk_domains") != classification["planloop_risk_domains"] or \
                current.get("planloop_track") != args.track:
            if args.track != "escalated":
                raise Fail("an existing run's classification changes only by escalating it")
            flip = {} if current.get("planloop_track") == "escalated" else \
                {"planloop_escalated_revision": next_revision}
            bead = run.beads.update(bead, {**classification, **flip, "planloop_track": "escalated",
                                           "planloop_min_effort": "high"})
    print(f"run {run.id}: bead {bead['id']}, track {meta_of(bead).get('planloop_track')}, directory {run.dir}")
    return 0


def check_content(run: Run, plan: str, revision: int, prev: int | None) -> dict:
    facts = analyse_plan(plan, run, revision)
    findings = run.findings()
    run_meta = meta_of(run.run_bead())
    problems, lost_lines = [], {}
    unknown = [r for r in facts["answers"] if r not in findings]
    if unknown:
        problems.append(f"change log answers findings that do not exist: {unknown}")
    redesign = [r for r in run_meta.get("planloop_redesign_required", "").split(",") if r]
    unanswered = sorted(fid for fid, bead in findings.items()
                        if meta_of(bead).get("planloop_state") in ("open", "reopened")
                        and meta_of(bead).get("planloop_severity") in ("high", "medium") and fid not in facts["answers"])
    if unanswered:
        problems.append(f"open high/medium findings not answered by FIX/REDESIGN/REJECT: {unanswered}")
    weak = [r for r in redesign if facts["answers"].get(r) != "REDESIGN"
            and meta_of(findings.get(r)).get("planloop_state") in OPEN_STATES]
    if weak:
        problems.append(f"findings requiring a structural redesign are not answered with REDESIGN: {weak}")
    if prev:
        try:
            prev_text = (run.rev_dir(prev) / "plan.md").read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise Conflict(f"revision {prev}'s plan.md vanished while reading it (a publication or recovery in "
                           "progress?); retry") from exc
        old = analyse_plan(prev_text, run, prev)
        for item in old["sections"] + old["ids"]:
            if item not in facts["sections"] + facts["ids"] and disposition(facts["removed"], item) is None:
                problems.append(f"{item!r} was in revision {prev} and has no REMOVED disposition")
        for heading, body in old["section_lines"].items():
            if heading not in facts["section_lines"] or heading in ("## Change log", "## Artifact inventory"):
                continue
            new_lines = list(facts["section_lines"][heading])
            lost = []
            for line in body:
                if line in new_lines:
                    new_lines.remove(line)
                elif line.strip():
                    lost.append(line)
            if lost and disposition(facts["shrink"], heading) is None:
                lost_lines[heading] = lost
                problems.append(f"{heading!r} lost {len(lost)} line(s) of revision {prev} (deleted, edited in "
                                f"place, merged or rewrapped) with no 'SHRINK {heading}:' disposition")
    known = facts["sections"] + facts["ids"] + (old["sections"] + old["ids"] if prev else [])
    weak_text = [e for e in facts["removed"] + facts["shrink"] if len(disposition_text(e, known) or "") < 20]
    if weak_text:
        problems.append(f"REMOVED/SHRINK dispositions too short to explain anything: {weak_text}")
    fable_reasons, leftover = [], []
    if run_meta.get("planloop_track") == "escalated":
        first = escalated_revision(run_meta)
        if revision == first:
            fable_reasons.append("revision 1 is drafted by Fable" if first == 1 else
                                 f"revision {revision} is the run's first escalated revision, drafted by Fable")
        if redesign:
            fable_reasons.append(f"planloop_redesign_required is set ({','.join(redesign)})")
        live = {r for r in facts["answers"] if r in findings
                and meta_of(findings[r]).get("planloop_state") in ("open", "reopened")}
        redesigned = sorted(r for r, k in facts["answers"].items() if k == "REDESIGN" and r in live)
        if redesigned:
            fable_reasons.append(f"the change log answers open or reopened finding(s) {redesigned} with REDESIGN")
        leftover = sorted(r for r, k in facts["answers"].items() if r in findings and r not in live and
                          k == "REDESIGN")
    return {"facts": facts, "problems": problems, "lost_lines": lost_lines, "run_meta": run_meta,
            "fable_reasons": fable_reasons, "leftover": leftover}


def escalated_revision(run_meta: dict) -> int:
    value = run_meta.get("planloop_escalated_revision") or "1"
    if not re.fullmatch(r"[1-9]\d*", str(value)):
        raise Fail(f"run bead's planloop_escalated_revision is {value!r}, not a revision number; fix the run bead")
    return int(value)


def disposition_text(entry: str, known: list):
    best = max((i for i in known if entry.startswith(i + ":")), key=len, default=None)
    if best is not None:
        return entry[len(best) + 1:].strip()
    return entry.split(":", 1)[1].strip() if ":" in entry else None


def planner_basis(checked: dict, model) -> tuple[str | None, str | None]:
    run_meta = checked["run_meta"]
    track = run_meta.get("planloop_track")
    if track == "ordinary":
        return None, None
    if track != "escalated":
        return None, f"run bead records unknown track {track!r}; refusing to judge the planner model"
    override = run_meta.get("planloop_planner_override") or ""
    if model == "fable":
        return "fable", None
    if model == "opus" and not checked["fable_reasons"]:
        return "opus-fix-revision", None
    if override and model == override:
        return "override", None
    why = "; ".join(checked["fable_reasons"]) or "only Fable or Opus may plan on the escalated track"
    return None, (f"this run is on the escalated track: the plan must come from a Fable planner because {why} "
                  f"(agent meta records model {model!r}; Opus is accepted for every FIX revision)")


def refuse_bom(message: str) -> None:
    if message.startswith("\ufeff") or "\n\ufeff<<<PLANLOOP-HANDBACK" in message:
        raise Fail("the text carries a byte-order mark (U+FEFF) at its start or before a marker; remove it")


def plan_between_markers(message: str) -> str:
    refuse_bom(message)
    lines = message.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("<<<PLANLOOP-HANDBACK ")]
    if starts:
        ends = [i for i, line in enumerate(lines) if line.startswith("<<<PLANLOOP-HANDBACK-END") and i > starts[0]]
        lines = lines[starts[0] + 1:ends[0] if ends else len(lines)]
    plan = "\n".join(lines)
    return plan if plan.endswith("\n") else plan + "\n"


def cmd_handback(args) -> int:
    run = Run(args.run)
    run.config()
    head = run.head()
    if args.check:
        return check_handback(run, head, args)
    expected = (head[0] if head else 0) + 1
    if args.revision != expected:
        raise Fail(f"revision {args.revision} is not HEAD+1 ({expected})")
    staging = run.staging(args.revision, args.nonce)
    if staging.exists():
        raise Fail(f"{staging} already exists")
    transcript = Path(args.transcript).resolve()
    message, completion = extract_handback(transcript)
    draft = None
    if args.draft:
        draft = Path(args.draft).resolve()
        if args.nonce not in draft.name:
            raise Fail(f"draft file {draft.name} is not named with this request's nonce {args.nonce}")
        digest = sha_file(draft)
        if digest not in message:
            raise Fail(f"the agent's final message does not name the draft's sha256 {digest}; the draft is not "
                       "the planner's handback")
        try:
            message = draft.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Fail(f"the draft file is not valid UTF-8 ({exc})") from exc
        completion = {**completion, "kind": completion["kind"] + "+draft-file"}
    refuse_bom(message)
    unfinished = unfinished_intents(run)
    if unfinished:
        raise Fail(f"unfinished Beads intents {unfinished}; re-run the interrupted findings command (every locking "
                   "command replays unfinished intents first) before handing back, so the planner policy is judged "
                   "on settled state")
    start = f"<<<PLANLOOP-HANDBACK run={run.id} revision={args.revision} nonce={args.nonce}>>>"
    end = f"<<<PLANLOOP-HANDBACK-END run={run.id} revision={args.revision} nonce={args.nonce}>>>"
    lines = message.split("\n")
    markers = [i for i, line in enumerate(lines) if line.startswith("<<<PLANLOOP-HANDBACK")]
    starts = [i for i in markers if lines[i].rstrip("\r") == start]
    ends = [i for i in markers if lines[i].rstrip("\r") == end]
    if len(starts) != 1 or len(ends) != 1 or len(markers) != 2 or starts[0] > ends[0]:
        raise Fail("handback must contain exactly one start and one end marker for this run, revision and "
                   "nonce, in order (missing end marker = truncated)")
    plan = "\n".join(lines[starts[0] + 1:ends[0]])
    if not plan.endswith("\n"):
        plan += "\n"
    checked = check_content(run, plan, args.revision, head[0] if head else None)
    basis, refusal = planner_basis(checked, completion.get("model"))
    problems = checked["problems"] + ([refusal] if refusal else [])
    if problems:
        raise Fail("handback incomplete; send it back to the planner:\n  " + "\n  ".join(problems))
    if basis:
        completion = {**completion, "planner_basis": basis}
    if basis == "override":
        completion = {**completion, "planner_override": checked["run_meta"].get("planloop_planner_override"),
                      "planner_override_decision": checked["run_meta"].get("planloop_planner_override_decision")}
    facts = checked["facts"]
    staging.mkdir(parents=True)
    data = plan.encode("utf-8")
    (staging / "plan.md").write_bytes(data)
    record = {"schema": "planloop-handback/1", "run_id": run.id, "revision": args.revision, "nonce": args.nonce,
              "source": {"path": str(transcript), "sha256": sha_file(transcript)}, "completion": completion,
              "draft": {"path": str(draft), "sha256": sha_file(draft)} if draft else None,
              "plan_sha256": sha(data), "answers": facts["answers"], "removed": facts["removed"],
              "shrink": facts["shrink"], "residual_risks": facts["residual_risks"],
              "note": "byte equality with the source proves faithful transfer, not substantive completeness"}
    (staging / "handback.json").write_bytes(canon(record))
    print(f"staged {staging}: plan {sha(data)}")
    return 0


def unfinished_intents(run: Run) -> list:
    return [path.name for path in sorted(intents_dir(run).glob("*.json"))
            if load(path, str(path)).get("state") != "verified"]


def check_handback(run: Run, head, args) -> int:
    top = head[0] if head else 0
    revision = args.revision if args.revision is not None else top + 1
    if not 1 <= revision <= top + 1:
        raise Fail(f"--check --revision must be between 1 and HEAD+1 ({top + 1})")
    prev = revision - 1 if revision > 1 else None
    if prev and not (run.rev_dir(prev) / "plan.md").exists():
        raise Fail(f"revision {prev} has no plan.md to compare against")
    try:
        text = sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Fail(f"the draft on stdin is not valid UTF-8 ({exc})") from exc
    try:
        plan = plan_between_markers(text)
        checked = check_content(run, plan, revision, prev)
    except Fail as exc:
        print(f"check failed: handback would refuse this plan:\n  {exc}")
        return 1
    if revision <= top:
        print(f"NOTE  revision {revision} is already published; comparing with revision {prev}, but finding "
              "answers are checked against the run's current findings")
    unfinished = unfinished_intents(run)
    if unfinished:
        print(f"NOTE  unfinished Beads intents {unfinished}: the real handback refuses until they are replayed")
    track = checked["run_meta"].get("planloop_track")
    reasons = checked["fable_reasons"]
    if track == "escalated" and reasons:
        override = " Opus allowed by Mike's recorded override." \
            if checked["run_meta"].get("planloop_planner_override") == "opus" else ""
        print("planner policy: this content needs a Fable planner (" + "; ".join(reasons) + ")." + override)
    elif track == "escalated":
        print("planner policy: Fable or Opus may hand this content back (a FIX revision)")
    elif track == "ordinary":
        print("planner policy: ordinary track, Opus plans")
    else:
        print(f"planner policy: run bead records unknown track {track!r}; the real handback refuses")
    if checked["leftover"]:
        print(f"NOTE  REDESIGN answers to {checked['leftover']} name findings that are not open or "
              "reopened; they do not affect the planner policy")
    if not checked["problems"]:
        print("check passed: handback would accept this plan content (markers, nonce and planner model are "
              "checked only by the real handback)")
        return 0
    print("check failed: handback would refuse this plan:")
    for problem in checked["problems"]:
        print(f"  {problem}")
    for heading, lost in checked["lost_lines"].items():
        print(f"\nlines of revision {prev} not found byte-identical in the new {heading!r} "
              f"(deleted, edited in place, merged or rewrapped):")
        for line in lost[:20]:
            print(f"  - {line[:100]}{'...' if len(line) > 100 else ''}")
        if len(lost) > 20:
            print(f"  +{len(lost) - 20} more")
    return 1


def tree_hash(root: Path) -> str:
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                lines.append(f"L {sha(os.fsencode(os.readlink(path)))} {rel}")
            else:
                lines.append(f"F {sha_file(path)} {rel}")
    return sha("\n".join(lines).encode())


def make_readonly(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def remove_tree(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        Path(dirpath).chmod(0o755)
    shutil.rmtree(root)


def head_bytes(repo: Path, commit: str, path: str):
    proc = subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], cwd=repo, capture_output=True)
    if proc.returncode:
        return None
    return git(repo, "show", f"{commit}:{path}")


def in_run_area(rel: str) -> bool:
    return rel == RUN_AREA or rel.startswith(RUN_AREA + "/")


def worktree_changes(repo: Path, commit: str) -> list:
    tracked = git(repo, "diff", "--name-only", "-z", commit, "--").split(b"\0")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    return sorted({os.fsdecode(n) for n in tracked + untracked if n} - {""} - {n for n in
                  (os.fsdecode(x) for x in tracked + untracked) if in_run_area(n)})


def live_file(repo: Path, rel: str):
    path = repo / rel
    if path.is_symlink():
        return "symlink:" + sha(os.fsencode(os.readlink(path)))
    if path.is_file():
        return sha_file(path)
    if path.exists():
        return "dir"
    return None


def dir_entries(repo: Path, rel: str) -> list:
    names = set()
    for args in (("ls-files", "-z", "--", rel), ("ls-files", "--others", "--exclude-standard", "-z", "--", rel)):
        names |= {os.fsdecode(n) for n in git(repo, *args).split(b"\0") if n}
    return [{"path": n, "sha256": live_file(repo, n)} for n in sorted(names) if not in_run_area(n)]


def bead_projection(beads: Beads, bead_id: str, fields: list) -> dict:
    bead = beads.get(bead_id)
    if bead is None:
        raise Fail(f"binding bead {bead_id} does not exist")
    return {f: bead.get(f) or "" for f in fields}


def validate_discovery(value: dict, repo_files: set, obligation_sources: set) -> None:
    shape(value, {"schema": {"planloop-discovery/1"}, "searches": "list", "sources": "list",
                  "known_omissions": "list"}, "discovery")
    if not value["searches"]:
        raise Fail("discovery records no searches")
    for i, s in enumerate(value["searches"]):
        shape(s, {"command": "str", "purpose": "str", "hits": "int", "match_proof": "str?"}, f"discovery.searches[{i}]")
        if s["hits"] == 0 and not (s["match_proof"] or "").strip():
            raise Fail(f"search {s['command']!r} found nothing and has no proof it can match")
    for i, s in enumerate(value["sources"]):
        shape(s, {"path": "str", "class": {"binding", "candidate", "irrelevant"}, "reason": "str"}, f"discovery.sources[{i}]")
        if s["class"] == "binding" and s["path"] not in obligation_sources:
            raise Fail(f"binding source {s['path']} has no obligation row")
        if s["class"] in ("binding", "candidate") and s["path"] not in repo_files and not s["path"].startswith("bead:"):
            raise Fail(f"{s['class']} source {s['path']} is not supplied to the reviewer (repo_files)")
    if value["known_omissions"]:
        raise Fail(f"discovery records known omissions: {value['known_omissions']}")


def check_evidence(record: dict, base: Path, repo: Path, at: dt.datetime | None, publication: bool = False) -> list:
    shape(record, {"schema": {"planloop-evidence/1"}, "id": "str", "claim": "str",
                   "kind": {"sql", "grep", "log", "file", "command"}, "source": "str", "query": "str",
                   "query_sha256": "hex", "inputs": "list", "observation_window": "any", "collected_at": "str",
                   "snapshot": "str?", "group": "str?", "status": {"result", "empty", "unknown", "error", "timeout"},
                   "truncated": "bool", "claim_needs_complete": "bool", "match_proof": "str?", "limits": "dict",
                   "limits_justification": "str?", "row_count": "int?", "bytes": "int", "output": "str",
                   "output_sha256": "hex", "attempts": "list", "validity": "dict"}, f"evidence {record.get('id')}")
    rid = record["id"]
    if not re.fullmatch(r"EV\d+", rid):
        raise Fail(f"evidence id {rid!r} must be EV<n>")
    problems = []
    if sha(record["query"].encode("utf-8")) != record["query_sha256"]:
        problems.append("query_sha256 does not match the query text")
    collected = parse_time(record["collected_at"], f"{rid}.collected_at")
    limits = shape(record["limits"], {"max_rows": "int", "max_bytes": "int"}, f"{rid}.limits")
    for key in ("max_rows", "max_bytes"):
        if limits[key] > EVIDENCE_CAP[key]:
            problems.append(f"{key} {limits[key]} exceeds the hard cap {EVIDENCE_CAP[key]}")
        if limits[key] > EVIDENCE_DEFAULT[key] and not (record["limits_justification"] or "").strip():
            problems.append(f"{key} above the default {EVIDENCE_DEFAULT[key]} needs limits_justification")
    output = base / safe_rel(record["output"], f"{rid}.output")
    if not output.is_file():
        problems.append(f"output {record['output']} missing")
    else:
        data = output.read_bytes()
        if sha(data) != record["output_sha256"]:
            problems.append("output_sha256 does not match the output file")
        if len(data) != record["bytes"]:
            problems.append("bytes does not match the output size")
    if record["bytes"] > limits["max_bytes"]:
        problems.append("output exceeds max_bytes")
    rows = record["row_count"]
    if rows is not None and rows > limits["max_rows"]:
        problems.append("row_count exceeds max_rows")
    attempts = record["attempts"]
    if not 1 <= len(attempts) <= MAX_ATTEMPTS:
        problems.append(f"{len(attempts)} attempts; 1 to {MAX_ATTEMPTS} allowed")
    for i, a in enumerate(attempts):
        shape(a, {"at": "str", "outcome": {"result", "empty", "unknown", "error", "timeout"}, "backoff_s": "int"},
              f"{rid}.attempts[{i}]")
        parse_time(a["at"], f"{rid}.attempts[{i}].at")
        if i and a["backoff_s"] < RETRY_BACKOFF[i - 1]:
            problems.append(f"retry {i} backed off {a['backoff_s']} s, below {RETRY_BACKOFF[i - 1]} s")
    if attempts and attempts[-1]["outcome"] != record["status"]:
        problems.append("status differs from the last attempt's outcome")
    status = record["status"]
    if status == "empty" and (rows != 0 or not (record["match_proof"] or "").strip()):
        problems.append("an empty result needs row_count 0 and a match_proof")
    if status == "result" and record["kind"] in ("sql", "grep") and not rows:
        problems.append("a result needs row_count > 0")
    if status in ("unknown", "error", "timeout"):
        problems.append(f"status {status} is UNKNOWN: it supports no claim")
    if record["truncated"] and record["claim_needs_complete"]:
        problems.append("output truncated but the claim needs the complete result")
    for i, item in enumerate(record["inputs"]):
        shape(item, {"path": "str", "sha256": "hex"}, f"{rid}.inputs[{i}]")
    validity = record["validity"]
    vtype = validity.get("type")
    if vtype == "historical":
        shape(validity, {"type": {"historical"}}, f"{rid}.validity")
        window = record["observation_window"]
        if not isinstance(window, dict):
            problems.append("historical evidence needs an observation_window")
        else:
            shape(window, {"start": "str", "end": "str"}, f"{rid}.observation_window")
            if parse_time(window["end"]) > collected:
                problems.append("observation window ends after collection")
    elif vtype == "until_input_change":
        shape(validity, {"type": {"until_input_change"}}, f"{rid}.validity")
        if not record["inputs"]:
            problems.append("until_input_change evidence needs inputs")
        for item in record["inputs"]:
            if live_file(repo, safe_rel(item["path"], f"{rid}.inputs")) != item["sha256"]:
                problems.append(f"input {item['path']} changed since collection")
    elif vtype == "observation":
        shape(validity, {"type": {"observation"}, "max_age_s": "int", "must_remain_current": "bool"},
              f"{rid}.validity")
        if at is not None and (at - collected).total_seconds() > validity["max_age_s"]:
            problems.append(f"observation is {(at - collected).total_seconds():.0f} s old at use, over max_age_s")
        if validity["must_remain_current"] and (now() - collected).total_seconds() > validity["max_age_s"]:
            problems.append("observation must remain current and has expired: recollect it into a new revision")
    else:
        problems.append(f"validity type {vtype!r} unknown")
    return problems


def check_groups(records: list) -> list:
    problems, groups = [], {}
    for r in records:
        if r["group"]:
            groups.setdefault(r["group"], []).append(r)
    for name, members in groups.items():
        snaps = {m["snapshot"] for m in members}
        if None in snaps or len(snaps) != 1:
            problems.append(f"group {name}: members do not share one snapshot; recollect the whole group")
        bad = [m["id"] for m in members if m["status"] in ("unknown", "error", "timeout")]
        if bad:
            problems.append(f"group {name}: {bad} failed; recollect the whole group, not the failed member")
    return problems


def cmd_bundle(args) -> int:
    run = Run(args.run)
    config = run.config()
    staging = run.staging(args.revision, args.nonce)
    handback = load(staging / "handback.json", "handback.json")
    plan_bytes = (staging / "plan.md").read_bytes()
    if sha(plan_bytes) != handback["plan_sha256"]:
        raise Fail("staged plan.md differs from the handback record")
    if (staging / "bundle").exists():
        raise Fail("staging already has a bundle")
    for leftover in staging.glob(".bundle-tmp-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    inputs = shape(load(Path(args.inputs), "inputs"), {"schema": {"planloop-inputs/1"}, "brief": "str",
                                                       "repo_files": "list", "dir_inventories": "list",
                                                       "beads": "list", "obligations": "list", "evidence": "list",
                                                       "discovery": "str"}, "inputs")
    repo = run.repo
    head = run.head()
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    bundle = staging / "bundle"
    items = [{"type": "plan", "sha256": sha(plan_bytes)}]
    policy_files = sorted([Path(__file__).resolve(), Path(__file__).resolve().parent.parent / "SKILL.md"])
    items.append({"type": "policy", "policy": POLICY,
                  "files": {p.name: sha_file(p) for p in policy_files if p.exists()}})
    brief = repo / safe_rel(inputs["brief"], "brief")
    if not brief.is_file():
        raise Fail(f"brief {inputs['brief']} does not exist")
    brief_bytes = brief.read_bytes()
    items.append({"type": "brief", "path": inputs["brief"], "sha256": sha(brief_bytes)})
    repo_files = set()
    for rel in inputs["repo_files"]:
        safe_rel(rel, "repo_files")
        if in_run_area(rel):
            raise Fail(f"{rel} is planloop's own run area, never a review input")
        if rel in repo_files:
            raise Fail(f"repo_files lists {rel} twice")
        repo_files.add(rel)
        live = live_file(repo, rel)
        if live == "dir":
            raise Fail(f"{rel} is a directory; list it under dir_inventories")
        old = head_bytes(repo, commit, rel)
        if live is None and old is None:
            raise Fail(f"declared input {rel} does not exist")
        items.append({"type": "repo_file", "path": rel, "sha256": live,
                      "head_sha256": sha(old) if old is not None else None})
    for rel in inputs["dir_inventories"]:
        safe_rel(rel, "dir_inventories")
        if not (repo / rel).is_dir():
            raise Fail(f"inventory directory {rel} does not exist")
        items.append({"type": "dir_inventory", "path": rel, "entries": dir_entries(repo, rel)})
    bead_copies = {}
    for i, entry in enumerate(inputs["beads"]):
        shape(entry, {"id": "str", "fields": "list"}, f"inputs.beads[{i}]")
        fields = entry["fields"] or list(DEFAULT_BEAD_FIELDS)
        if any(f not in BEAD_FIELDS for f in fields):
            raise Fail(f"bead {entry['id']}: fields must come from {BEAD_FIELDS}")
        projection = bead_projection(run.beads, entry["id"], fields)
        bead_copies[entry["id"]] = projection
        items.append({"type": "bead", "id": entry["id"], "fields": fields, "sha256": sha(canon(projection))})
    plan_text = plan_bytes.decode("utf-8")
    plan_obligations = {i for i in analyse_plan(plan_text, run, args.revision)["ids"] if i.startswith("OB")}
    obligations, sources = [], set()
    for i, entry in enumerate(inputs["obligations"]):
        shape(entry, {"id": "str", "source": "str", "section": "str", "text": "str"}, f"inputs.obligations[{i}]")
        if entry["source"].startswith("bead:"):
            bead_id = entry["source"][5:]
            if bead_id not in bead_copies:
                raise Fail(f"obligation {entry['id']} cites bead {bead_id}, which is not a bundled bead")
            if not any(entry["text"] in v for v in bead_copies[bead_id].values()):
                raise Fail(f"obligation {entry['id']}: text not found verbatim in bead {bead_id}")
        else:
            if entry["source"] not in repo_files:
                raise Fail(f"obligation {entry['id']}: source {entry['source']} is not in repo_files")
            if entry["text"] not in (repo / entry["source"]).read_text(encoding="utf-8"):
                raise Fail(f"obligation {entry['id']}: text not found verbatim in {entry['source']}")
        sources.add(entry["source"])
        obligations.append(entry)
    ob_ids = [o["id"] for o in obligations]
    if len(set(ob_ids)) != len(ob_ids) or set(ob_ids) != plan_obligations:
        raise Fail(f"obligation rows {sorted(ob_ids)} must match the plan's OB ids {sorted(plan_obligations)} one to one")
    items.append({"type": "obligations", "sha256": sha(canon(obligations))})
    evidence = []
    for rel in inputs["evidence"]:
        record = load(repo / safe_rel(rel, "evidence"), rel)
        problems = check_evidence(record, repo, repo, at=now())
        if problems:
            raise Fail(f"evidence {rel} does not support its claim: {problems}")
        evidence.append((rel, record))
    ev_ids = [r["id"] for _, r in evidence]
    if len(ev_ids) != len(set(ev_ids)):
        raise Fail(f"evidence ids repeat: {sorted(ev_ids)}")
    group_problems = check_groups([r for _, r in evidence])
    if group_problems:
        raise Fail("; ".join(group_problems))
    discovery = load(repo / safe_rel(inputs["discovery"], "discovery"), "discovery")
    validate_discovery(discovery, repo_files | {f"bead:{b}" for b in bead_copies}, sources)
    items.append({"type": "discovery", "sha256": sha(canon(discovery))})
    findings = {fid: {k: (b.get("metadata") or {}).get(f"planloop_{k}", "") for k in
                      ("state", "severity", "raised_call", "fix_proposals", "reopens")}
                for fid, b in sorted(run.findings().items())}
    items.append({"type": "findings_snapshot", "sha256": sha(canon(findings)), "revalidate": False})
    changes = worktree_changes(repo, commit)
    overlay = []
    final_bundle, bundle = bundle, staging / f".bundle-tmp-{uuid.uuid4().hex[:8]}"
    bundle.mkdir()
    try:
        return build_bundle(run, args, config, staging, final_bundle, bundle, repo, head, commit, plan_bytes,
                            brief_bytes, obligations, discovery, findings, bead_copies, evidence, items, changes,
                            overlay)
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        raise


def build_bundle(run, args, config, staging, final_bundle, bundle, repo, head, commit, plan_bytes, brief_bytes,
                 obligations, discovery, findings, bead_copies, evidence, items, changes, overlay) -> int:
    for rel in changes:
        live = live_file(repo, rel)
        if live == "dir":
            raise Fail(f"changed path {rel} is a directory or submodule; inspect it explicitly")
        overlay.append({"path": rel, "sha256": live})
        if live is not None:
            dest = bundle / "overlay" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / rel, dest, follow_symlinks=False)
    frozen = bundle / "frozen"
    frozen.mkdir()
    (frozen / "plan.md").write_bytes(plan_bytes)
    (frozen / "brief.md").write_bytes(brief_bytes)
    (frozen / "obligations.json").write_bytes(canon(obligations))
    (frozen / "discovery.json").write_bytes(canon(discovery))
    (frozen / "findings.json").write_bytes(canon(findings))
    for bead_id, projection in bead_copies.items():
        dest = frozen / "beads" / f"{bead_id}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(canon(projection))
    for rel, record in evidence:
        dest = frozen / "evidence" / f"{record['id']}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(canon(record))
        out = frozen / "evidence" / record["output"]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / record["output"], out)
        items.append({"type": "evidence", "id": record["id"], "path": rel, "record_sha256": sha(canon(record)),
                      "inputs": record["inputs"], "validity": record["validity"]})
    snap = run.snapshot(args.revision, args.nonce)
    remove_tree(snap)
    snap.mkdir(parents=True)
    try:
        fill_snapshot(repo, commit, snap, bundle, overlay, frozen := bundle / "frozen")
    except BaseException:
        remove_tree(snap)
        raise
    mismatches = []
    for item in items:
        if item["type"] == "repo_file":
            got = live_file(snap, item["path"])
            if got != item["sha256"]:
                mismatches.append(item["path"])
        elif item["type"] == "dir_inventory":
            for entry in item["entries"]:
                if live_file(snap, entry["path"]) != entry["sha256"]:
                    mismatches.append(entry["path"])
    if mismatches or git(repo, "rev-parse", "HEAD").decode().strip() != commit:
        remove_tree(snap)
        raise Fail(f"the repository changed while the bundle was built (HEAD moved or {mismatches[:5]} differ "
                   "between the snapshot and the recorded inputs); rebuild the bundle")
    snapshot_hash = tree_hash(snap)
    return finish_bundle(run, args, config, staging, final_bundle, bundle, head, commit, plan_bytes, items,
                         overlay, snap, snapshot_hash)


def fill_snapshot(repo: Path, commit: str, snap: Path, bundle: Path, overlay: list, frozen: Path) -> None:
    archive = subprocess.run(["git", "archive", "--format=tar", commit], cwd=repo, capture_output=True, timeout=600)
    if archive.returncode:
        raise Unverifiable(f"git archive failed: {archive.stderr.decode(errors='replace')}")
    untar = subprocess.run(["tar", "-x", "-C", str(snap)], input=archive.stdout, capture_output=True, timeout=600)
    if untar.returncode:
        raise Unverifiable(f"tar failed: {untar.stderr.decode(errors='replace')}")
    for entry in overlay:
        dest = snap / entry["path"]
        if entry["sha256"] is None:
            if dest.exists() or dest.is_symlink():
                dest.unlink()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            shutil.copy2(bundle / "overlay" / entry["path"], dest, follow_symlinks=False)
    if (snap / ".planloop-bundle").exists():
        raise Fail("the repository itself contains .planloop-bundle")
    shutil.copytree(frozen, snap / ".planloop-bundle", symlinks=True)
    make_readonly(snap)


def finish_bundle(run, args, config, staging, final_bundle, bundle, head, commit, plan_bytes, items, overlay, snap,
                  snapshot_hash) -> int:
    items.append({"type": "overlay", "entries": overlay, "revalidate": False})
    items.append({"type": "snapshot", "commit": commit, "tree_sha256": snapshot_hash, "path": str(snap),
                  "revalidate": False})
    manifest = {"schema": "planloop-bundle/1", "run_id": run.id, "revision": args.revision, "items": items}
    manifest_bytes = canon(manifest)
    (bundle / "manifest.json").write_bytes(manifest_bytes)
    base = {"revision": head[0], "revision_sha256": head[1]} if head else None
    revision = {"schema": "planloop-revision/1", "run_id": run.id, "revision": args.revision,
                "plan_sha256": sha(plan_bytes), "bundle_sha256": sha(manifest_bytes),
                "handback_sha256": sha_file(staging / "handback.json"), "base": base,
                "reviewer_model": config["reviewer_model"], "created_at": iso(now())}
    rename(bundle, final_bundle)
    (staging / "revision.json").write_bytes(canon(revision))
    print(f"bundle {sha(manifest_bytes)}; snapshot {snap} tree {snapshot_hash}")
    return 0


def verify_revision(run: Run, n: int, rev_dir: Path | None = None, deep: bool = True) -> dict:
    rev_dir = rev_dir or run.rev_dir(n)
    rev = shape(load(rev_dir / "revision.json", "revision.json"),
                {"schema": {"planloop-revision/1"}, "run_id": "str", "revision": "int", "plan_sha256": "hex",
                 "bundle_sha256": "hex", "handback_sha256": "hex", "base": "any", "reviewer_model": "str?",
                 "created_at": "str"}, f"revision {n}")
    if rev["run_id"] != run.id or rev["revision"] != n:
        raise Fail(f"{rev_dir}/revision.json describes another revision")
    if sha_file(rev_dir / "plan.md") != rev["plan_sha256"]:
        raise Fail(f"revision {n} plan.md does not match revision.json")
    if sha_file(rev_dir / "handback.json") != rev["handback_sha256"]:
        raise Fail(f"revision {n} handback.json does not match")
    manifest_bytes = (rev_dir / "bundle" / "manifest.json").read_bytes()
    if sha(manifest_bytes) != rev["bundle_sha256"]:
        raise Fail(f"revision {n} bundle manifest does not match")
    manifest = loads(manifest_bytes.decode("utf-8"), "manifest")
    if n > 1:
        base = rev["base"]
        if not isinstance(base, dict) or base.get("revision") != n - 1 or \
                sha_file(run.rev_dir(n - 1) / "revision.json") != base.get("revision_sha256"):
            raise Fail(f"revision {n} does not chain to revision {n - 1}")
    elif rev["base"] is not None:
        raise Fail("revision 1 names a base")
    for item in manifest["items"]:
        if item["type"] == "overlay":
            for entry in item["entries"]:
                if entry["sha256"] is not None:
                    path = rev_dir / "bundle" / "overlay" / entry["path"]
                    got = "symlink:" + sha(os.fsencode(os.readlink(path))) if path.is_symlink() else sha_file(path)
                    if got != entry["sha256"]:
                        raise Fail(f"revision {n} overlay copy of {entry['path']} changed")
        if item["type"] == "snapshot" and deep:
            snap = Path(item["path"])
            if not snap.is_dir() or tree_hash(snap) != item["tree_sha256"]:
                raise Fail(f"revision {n} snapshot {snap} is missing or changed")
    rev["manifest"] = manifest
    return rev


def cmd_publish(args) -> int:
    run = Run(args.run)
    run.config()
    with Lock(run.dir):
        prepare(run)
        if args.recover:
            return 0
        staging = run.staging(args.revision, args.nonce)
        rev = verify_revision(run, args.revision, staging)
        head = run.head()
        base = rev["base"]
        if (head is None and base is not None) or (head is not None and base != {"revision": head[0],
                                                                                   "revision_sha256": head[1]}):
            raise Conflict(f"staged revision {args.revision} was built on {base}, HEAD is now {head}; rebuild it")
        run_meta = meta_of(run.run_bead())
        if run_meta.get("planloop_track") == "escalated" and args.revision == escalated_revision(run_meta):
            completion = load(staging / "handback.json", "handback.json").get("completion") or {}
            if completion.get("model") != "fable" and completion.get("planner_basis") != "override":
                raise Fail(f"revision {args.revision} is the run's first escalated revision and its handback came "
                           f"from model {completion.get('model')!r}; re-plan that revision with Fable")
        target = run.rev_dir(args.revision)
        if target.exists():
            raise Conflict(f"{target} already exists (another writer published)")
        crash_point("before_rename")
        rename(staging, target)
        crash_point("after_rename")
        rev_sha = sha_file(target / "revision.json")
        write_atomic(run.dir / "HEAD", canon({"schema": "planloop-head/1", "revision": args.revision,
                                              "revision_sha256": rev_sha}))
        crash_point("after_head")
        if run.head() != (args.revision, rev_sha):
            raise Unverifiable("HEAD did not read back")
        verify_revision(run, args.revision)
    print(f"published revision {args.revision} ({rev_sha})")
    return 0


def recover(run: Run) -> None:
    head = run.head()
    current = head[0] if head else 0
    if head:
        verify_revision(run, current, deep=False)
        if sha_file(run.rev_dir(current) / "revision.json") != head[1]:
            raise Unverifiable("HEAD points at a revision whose record differs; inspect by hand")
    for path in sorted(run.dir.glob("rev-[0-9][0-9][0-9]")):
        n = int(path.name[4:])
        if n <= current:
            continue
        try:
            rev = verify_revision(run, n)
            chained = rev["base"] == ({"revision": head[0], "revision_sha256": head[1]} if head else None)
        except Fail:
            chained = False
        if n == current + 1 and chained:
            write_atomic(run.dir / "HEAD", canon({"schema": "planloop-head/1", "revision": n,
                                                  "revision_sha256": sha_file(path / "revision.json")}))
            print(f"NOTE  recovered interrupted publication of revision {n}", file=sys.stderr)
            head, current = run.head(), n
        else:
            dest = run.dir / f".orphan-{path.name}-{uuid.uuid4().hex[:8]}"
            rename(path, dest)
            print(f"NOTE  moved unreferenced {path.name} aside to {dest.name}", file=sys.stderr)


def prepare(run: Run) -> None:
    recover(run)
    recover_intents(run)


def call_dirs(run: Run) -> list:
    out = []
    for path in (run.dir / "reviews").glob("call-*-a*"):
        m = re.match(r"^call-(\d{3,})-a(\d)$", path.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), path))
    return sorted(out)


def receipts(run: Run) -> list:
    out = []
    for call, attempt, path in call_dirs(run):
        receipt = path / "receipt.json"
        value = None
        if receipt.exists():
            value = load(receipt, str(receipt))
            if not isinstance(value, dict) or value.get("schema") != "planloop-receipt/1" \
                    or value.get("status") not in ("counted", "invalid", "triage") \
                    or (value.get("call"), value.get("attempt")) != (call, attempt):
                raise Fail(f"{receipt} is not a planloop receipt for call {call} attempt {attempt}")
        out.append((call, attempt, path, value))
    return out


def findings_table(run: Run) -> str:
    rows = []
    for fid, bead in sorted(run.findings().items(), key=lambda kv: int(kv[0][1:])):
        m = bead["metadata"]
        rows.append(f"| {fid} | {m.get('planloop_severity')} | {m.get('planloop_state')} | "
                    f"{m.get('planloop_raised_call')} | {m.get('planloop_fix_proposals')} | "
                    f"{m.get('planloop_resolution') or '-'} |")
    return "| ID | severity | state | raised in call | fixes proposed | resolution |\n|---|---|---|---|---|---|\n" + \
        "\n".join(rows) if rows else "(no findings yet)"


def feedback_text(run: Run, n: int, rev: dict, kind: str, call: int, attempt: int) -> str:
    rev_dir = run.rev_dir(n)
    handback = load(rev_dir / "handback.json")
    frozen = rev_dir / "bundle" / "frozen"
    obligations = load(frozen / "obligations.json")
    lines = [f"PLANLOOP-BUNDLE run={run.id} revision={n} call={call} attempt={attempt} sha256={rev['bundle_sha256']}",
             f"Policy {POLICY}.", "",
             "Your working directory is a frozen, read-only snapshot of the repository for this revision. Read",
             "only files under it, using relative paths. Never read the original checkout or any other path",
             "outside this directory: such reads are detected in the event log and void the review.",
             ".planloop-bundle/ holds the frozen plan, brief, obligations, binding bead text, evidence and the",
             "discovery record; bead text cannot be fetched any other way (no bd in your sandbox).", "",
             "Coverage must contain, for every finding listed below in state fix_proposed, exactly one entry",
             "`finding R<k>: resolved` or `finding R<k>: unresolved`. To withdraw an open finding you judge invalid,",
             "write `finding R<k>: withdrawn: <evidence that its failure scenario cannot occur, at least 40 chars>`.",
             "When re-raising a known finding, use its R id as your finding id.",
             "Check every REMOVED and SHRINK disposition below: each must say what was removed, why, and which",
             "obligations or capabilities it affects; an unexplained removal is a finding.", ""]
    if kind == "gate":
        lines += ["This is the final gate: an independent, full-rubric review of the whole plan. Earlier rounds",
                  "are not evidence that anything is correct; check interactions between revised and unchanged",
                  "sections.", ""]
        for fid, bead in sorted(run.findings().items(), key=lambda kv: int(kv[0][1:])):
            meta = meta_of(bead)
            if meta.get("planloop_state") == "withdrawn":
                lines += [f"{fid} was withdrawn. Original failure scenario: {original_evidence(run, meta)}",
                          f"Withdrawal evidence: {meta.get('planloop_withdrawal', '')[6:]}",
                          f"Judge it: write `finding {fid}: withdrawal confirmed` only if the evidence defeats the "
                          f"scenario; otherwise re-raise it as finding {fid}.", ""]
    lines += ["--- REVIEW BRIEF (host) ---", (frozen / "brief.md").read_text(encoding="utf-8").rstrip(), "",
              "--- OBLIGATIONS (exact source text) ---"]
    for o in obligations:
        lines.append(f"{o['id']} [{o['source']} {o['section']}]: {o['text']}")
    lines += ["", "--- DISPOSITIONS IN THIS REVISION ---"]
    for kind_name, table in (("REMOVED", handback["removed"]), ("SHRINK", handback["shrink"])):
        for entry in table:
            lines.append(f"{kind_name} {entry}")
    for fid, answer in handback["answers"].items():
        lines.append(f"{answer} {fid}")
    reopened = sorted(f for f, b in run.findings().items() if meta_of(b).get("planloop_reopens", "0") not in ("", "0"))
    if reopened:
        lines += ["", f"Findings {', '.join(reopened)} were reopened after a fix: review every section their fixes "
                  "touched for interactions with the rest of the plan."]
    lines += ["", "--- FINDINGS (Beads, at dispatch) ---", findings_table(run), ""]
    return "\n".join(lines) + "\n"


def expected_coverage(run: Run, kind: str) -> list:
    wanted = ("fix_proposed", "withdrawn") if kind == "gate" else ("fix_proposed",)
    return sorted((f for f, b in run.findings().items() if meta_of(b).get("planloop_state") in wanted),
                  key=lambda r: int(r[1:]))


def original_evidence(run: Run, meta: dict) -> str:
    ref = meta.get("planloop_evidence", "")
    path, _, fid = ref.partition("#")
    try:
        receipt = load(run.dir / path)
        return next(f["evidence"] for f in receipt["findings"] if f["id"] == fid)
    except (Fail, StopIteration, KeyError):
        return f"(not found at {ref})"


def runner_path() -> list:
    explicit = os.environ.get("PLANLOOP_RUNNER")
    if explicit:
        return shlex.split(explicit)
    found = sorted(glob.glob(str(Path.home() / ".claude/plugins/cache/claudex-loop/claudex-loop/*/skills/"
                                 "claudex-loop/scripts/runner.py")))
    if not found:
        raise Unverifiable("claudex-loop runner.py not found")
    return [sys.executable, found[-1]]


def effort_policy(run_meta: dict, kind: str, effort: str) -> str | None:
    if effort not in EFFORTS:
        return f"effort {effort!r} is not used by planloop (xhigh/max need Mike)"
    if kind == "triage":
        return None if effort == "low" else "triage runs at low effort only"
    if kind == "gate" and effort != "high":
        return "a final gate runs at high effort"
    floor = run_meta.get("planloop_min_effort", "medium")
    if run_meta.get("planloop_track") == "escalated":
        floor = "high"
    if EFFORTS[effort] < EFFORTS[floor]:
        return f"effort {effort} is below this run's floor {floor}"
    return None


def cmd_dispatch(args) -> int:
    run = Run(args.run)
    config = run.config()
    with Lock(run.dir):
        prepare(run)
        head = run.head()
        if head is None:
            raise Fail("nothing published yet")
        n = head[0]
        rev = verify_revision(run, n)
        run_meta = run.run_bead()["metadata"]
        if run_meta.get("planloop_state") != "active":
            raise Fail(f"run state is {run_meta.get('planloop_state')} ({run_meta.get('planloop_reason')}); "
                       "record what changed with `state --set active` before dispatching")
        problem = effort_policy(run_meta, args.kind, args.effort)
        if problem:
            raise Fail(problem)
        sequence_check(run, args.call, args.attempt, n)
        streak = invalid_streak(run, run_meta)
        if streak >= MAX_ATTEMPTS:
            raise Fail(f"the last {streak} review attempts were all invalid; record what changed with "
                       "`state --set active` before trying again")
        for c, a, path, r in receipts(run):
            if r and r["status"] == "counted" and not (intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json").exists():
                raise Fail(f"call {c} attempt {a} is counted but not ingested; run `findings ingest` first")
        if n > 1 and not (intents_dir(run) / f"propose-r{n:03d}.json").exists():
            raise Fail(f"revision {n} is published but `findings propose` has not run for it")
        frozen = run.rev_dir(n) / "bundle" / "frozen"
        stale = []
        for item in rev["manifest"]["items"]:
            if item["type"] == "evidence" and item["validity"].get("type") == "observation":
                record = load(frozen / "evidence" / f"{item['id']}.json")
                stale += [f"{item['id']}: {p}" for p in check_evidence(record, frozen / "evidence", run.repo, at=now())]
        if stale:
            raise Fail(f"observation evidence no longer valid for a new round: {stale}; recollect and republish")
        call_dir = run.call_dir(args.call, args.attempt)
        model = config["gate_model"] if args.kind == "gate" and config["gate_model"] else config["reviewer_model"]
        feedback = feedback_text(run, n, rev, args.kind, args.call, args.attempt).encode("utf-8")
        expect = expected_coverage(run, args.kind)
        reserve = call_dir.parent / f".reserve-{uuid.uuid4().hex}"
        (reserve / "input").mkdir(parents=True)
        (reserve / "input" / "feedback.md").write_bytes(feedback)
        frozen_snap = next(i for i in rev["manifest"]["items"] if i["type"] == "snapshot")
        run.isolated.mkdir(parents=True, exist_ok=True)
        run.isolated.chmod(0o300)
        try:
            os.listdir(run.isolated)
            raise Unverifiable(f"{run.isolated} can still be listed after chmod 0300 (a filesystem that ignores "
                               "permissions, such as drvfs without metadata); put PLANLOOP_ISOLATED on ext4")
        except PermissionError:
            pass
        private = Path(tempfile.mkdtemp(prefix="r-", dir=run.isolated))
        try:
            copy = private / "repo"
            shutil.copytree(frozen_snap["path"], copy, symlinks=True)
            if tree_hash(copy) != frozen_snap["tree_sha256"]:
                raise Fail("the frozen snapshot changed since publication; republish")
            snap = {"path": str(copy), "tree_sha256": frozen_snap["tree_sha256"]}
            artifacts = run.state / "calls" / call_dir.name
            dispatch = {"schema": "planloop-dispatch/1", "run_id": run.id, "revision": n, "revision_sha256": head[1],
                        "bundle_sha256": rev["bundle_sha256"], "plan_sha256": rev["plan_sha256"], "call": args.call,
                        "attempt": args.attempt, "kind": args.kind, "effort": args.effort,
                        "model": model, "snapshot": snap["path"],
                        "snapshot_tree_sha256": snap["tree_sha256"], "feedback_sha256": sha(feedback),
                        "artifacts_root": str(artifacts), "live_repo": str(run.repo), "expected_coverage": expect,
                        "dispatched_at": iso(now())}
            write_new(reserve / "input" / "dispatch.json", canon(dispatch))
            (reserve / "running.json").write_bytes(canon({**identity(), "nonce": uuid.uuid4().hex}))
            crash_point("before_reserve")
            if call_dir.exists():
                raise Conflict(f"{call_dir} appeared concurrently")
            rename(reserve, call_dir)
        except BaseException:
            shutil.rmtree(reserve, ignore_errors=True)
            remove_tree(private)
            raise
    argv = runner_path() + ["review", "--host", "claude", "--repo", snap["path"], "--plan",
                            ".planloop-bundle/plan.md", "--effort", args.effort, "--timeout", "1800",
                            "--artifacts", str(artifacts), "--feedback", str(call_dir / "input" / "feedback.md")]
    if model:
        argv += ["--model", model]
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=1900)
        code, out = proc.returncode, proc.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        code, out = None, ""
    located = [p for p in artifacts.glob("claudex-*") if (p / "result.json").exists()]
    call = {"schema": "planloop-call/1", "runner_exit": code, "artifacts": str(located[0]) if len(located) == 1 else None,
            "runner_stdout_sha256": sha(out.encode())}
    write_new(call_dir / "call.json", canon(call))
    crash_point("after_runner")
    return finish_receipt(run, args.call, args.attempt)


def invalid_streak(run: Run, run_meta: dict) -> int:
    after = int(run_meta.get("planloop_active_after_call") or 0)
    streak = 0
    for c, a, path, r in reversed(receipts(run)):
        if c <= after or r is None or r["status"] != "invalid":
            break
        streak += 1
    return streak


def sequence_check(run: Run, call: int, attempt: int, n: int) -> None:
    existing = call_dirs(run)
    if run.call_dir(call, attempt).exists():
        raise Fail(f"call {call} attempt {attempt} already exists")
    if not 1 <= attempt <= MAX_ATTEMPTS:
        raise Fail(f"attempt {attempt}: 1 to {MAX_ATTEMPTS} attempts per call")
    last_call = max((c for c, _, _ in existing), default=0)
    if attempt == 1:
        if call != last_call + 1:
            raise Fail(f"next call number is {last_call + 1}")
        for c, a, path, receipt in receipts(run):
            if receipt is None:
                raise Fail(f"call {c} attempt {a} has no receipt; finish it with `receipt` first")
        return
    if call != last_call:
        raise Fail("a retry must reuse the latest call number")
    prior = [r for c, a, p, r in receipts(run) if c == call]
    if len(prior) != attempt - 1 or any(r is None for r in prior):
        raise Fail("retry out of order or an earlier attempt has no receipt")
    if any(r["status"] != "invalid" for r in prior):
        raise Fail(f"call {call} already has a counted receipt; a new review is a new call")
    if any(r["revision"] != n for r in prior):
        raise Fail("the plan changed since the first attempt: a changed plan is a new call")


def rollout_for(session: str):
    root = Path(os.environ.get("PLANLOOP_CODEX_SESSIONS", "~/.codex/sessions")).expanduser()
    found = sorted(root.glob(f"**/rollout-*-{session}.jsonl"))
    if len(found) != 1:
        return None, f"found {len(found)} Codex rollout files for session {session}"
    return found[0], None


def accepted_versions() -> set:
    try:
        lines = VERSIONS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.split()[0] for line in lines if line.strip() and not line.startswith("#")}


def context_item(text, cwd: str, agents_md) -> bool:
    if not isinstance(text, str):
        return False
    if agents_md is not None and text == f"# AGENTS.md instructions for {cwd}\n\n<INSTRUCTIONS>\n{agents_md}\n</INSTRUCTIONS>":
        return True
    return (text.startswith("<environment_context>\n") and text.endswith("\n</environment_context>")
            and f"\n  <cwd>{cwd}</cwd>\n" in text and text.count("<environment_context>") == 1
            and "<INSTRUCTIONS>" not in text)


def parse_rollout(path: Path, session: str, prompt: str, cli_version: str, check_version: bool = True,
                  context: dict | None = None) -> dict:
    version = cli_version.split()[-1] if cli_version else ""
    if check_version and version not in accepted_versions():
        raise Unverifiable(f"Codex CLI {cli_version!r} has not been validated against {ROLLOUT_PARSER}; run "
                           "`planloop.py rollout-check` on one real review from it before trusting it")
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise Unverifiable(f"rollout line {number} is not JSON") from exc
        if not isinstance(row, dict) or "type" not in row or not isinstance(row.get("payload"), (dict, list)):
            raise Unverifiable(f"rollout line {number} has an unfamiliar shape")
        records.append(row)
    metas = [r["payload"] for r in records if r["type"] == "session_meta"]
    contexts = [r["payload"] for r in records if r["type"] == "turn_context"]
    if len(metas) != 1 or not contexts:
        raise Unverifiable(f"rollout has {len(metas)} session_meta and {len(contexts)} turn_context records")
    meta = metas[0]
    if not isinstance(meta, dict) or meta.get("id") != session:
        raise Unverifiable("rollout session_meta does not name this session")
    lineage = sorted(k for k in meta if re.search(r"fork|parent|resum", k))
    users = []
    for r in records:
        p = r["payload"]
        if r["type"] == "response_item" and isinstance(p, dict) and p.get("type") == "message" and p.get("role") == "user":
            content = p.get("content")
            if not isinstance(content, list):
                raise Unverifiable("user message content has an unfamiliar shape")
            users.append([c.get("text") for c in content if isinstance(c, dict) and c.get("type") == "input_text"])
    settings = set()
    for c in contexts:
        if not isinstance(c, dict) or not isinstance(c.get("model"), str) or c.get("effort") not in EFFORTS \
                or not isinstance(c.get("sandbox_policy"), dict):
            raise Unverifiable("turn_context lacks model, effort or sandbox_policy")
        mode = (c.get("collaboration_mode") or {}).get("settings") or {}
        if mode.get("reasoning_effort") not in (None, c["effort"]):
            raise Fail("turn_context effort and collaboration_mode effort disagree")
        settings.add((c["model"], c["effort"], c["sandbox_policy"].get("type"), c.get("approval_policy")))
    if len(settings) != 1:
        raise Fail(f"turn_context settings change within the session: {sorted(settings)}")
    model, effort, sandbox, approval = settings.pop()
    context_turns = 0
    if context is not None and context.get("cwd") == meta.get("cwd"):
        while (context_turns < len(users) and users[context_turns] and prompt not in users[context_turns]
               and all(context_item(t, context["cwd"], context.get("agents_md")) for t in users[context_turns])):
            context_turns += 1
    users = users[context_turns:]
    prompt_turns = [i for i, texts in enumerate(users) if prompt in texts]
    return {"path": str(path), "sha256": sha_file(path), "parser": ROLLOUT_PARSER, "model": model,
            "effort": effort, "sandbox": sandbox, "approval_policy": approval, "user_turns": len(users),
            "prompt_in_first_turn": prompt_turns == [0], "lineage_fields": lineage,
            "cwd": meta.get("cwd"), "context_turns": context_turns}


def response_problems(value) -> list:
    if not isinstance(value, dict) or set(value) != {"verdict", "summary", "findings", "coverage", "limitations"}:
        return ["review response does not have exactly the runner's fields"]
    out = []
    if value["verdict"] not in ("APPROVED", "REVISE", "BLOCKED"):
        out.append("verdict not APPROVED/REVISE/BLOCKED")
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        out.append("empty summary")
    for key in ("coverage", "limitations"):
        if not isinstance(value[key], list) or any(not isinstance(x, str) or not x.strip() for x in value[key]):
            return out + [f"{key} is not a list of non-empty strings"]
    if value["verdict"] != "BLOCKED" and not value["coverage"]:
        out.append("a completed review must state its coverage")
    if value["verdict"] == "BLOCKED" and not value["limitations"]:
        out.append("BLOCKED without limitations")
    if not isinstance(value["findings"], list):
        return out + ["findings not a list"]
    ids = []
    for f in value["findings"]:
        if not isinstance(f, dict) or set(f) != {"id", "severity", "path", "evidence", "fix"} \
                or f.get("severity") not in ("high", "medium", "low") \
                or any(not isinstance(v, str) or not v.strip() for v in f.values()):
            out.append("malformed finding")
            continue
        ids.append(f["id"])
    if len(ids) != len(set(ids)):
        out.append("duplicate finding ids")
    material = [f for f in value["findings"] if isinstance(f, dict) and f.get("severity") in ("high", "medium")]
    if value["verdict"] == "APPROVED" and material:
        out.append("APPROVED with high/medium findings")
    if value["verdict"] == "REVISE" and not value["findings"]:
        out.append("REVISE without findings")
    return out


def forbidden_patterns(dispatch: dict, run: Run) -> list:
    roots = [dispatch["live_repo"], str(run.state.parent), str(run.isolated.resolve()),
             str(Path.home() / ".codex")]
    out = [re.compile(r"(?<![\w.-])" + re.escape(r.rstrip("/")) + r"(?=/|$|[\s'\"`;|&)<>])") for r in roots]
    out.append(re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.(?:codex|local/state/planloop)"))
    return out


def climbs_out(command: str, root: Path | None = None) -> bool:
    wrapped = re.match(r"""^\S*/(?:ba)?sh\s+-l?c\s+(['"])(.*)\1\s*$""", command, re.S)
    inner = wrapped.group(2).replace('\\"', '"') if wrapped else command
    tokens = []
    for m in re.finditer(r"""'([^']*)'|"([^"]*)"|(\()|(\))|([^\s'";|&()<>`]+)|([;|&\n]+)""", inner):
        if m.group(6):
            tokens.append((";", False))
        elif m.group(3) or m.group(4):
            tokens.append((m.group(0), False))
        elif m.group(5) is not None:
            tokens.append((m.group(5), False))
        else:
            tokens += [(t, True) for t in (m.group(1) if m.group(1) is not None else m.group(2)).split()]
    cwd, stack = [], []
    for i, (token, quoted) in enumerate(tokens):
        if token == "(" and not quoted:
            stack.append(list(cwd))
            continue
        if token == ")" and not quoted:
            cwd = stack.pop() if stack else cwd
            continue
        is_cd = i > 0 and tokens[i - 1] == ("cd", False)
        if token == "cd" and not quoted and (i + 1 == len(tokens) or tokens[i + 1][0] in ("~", "-", "(", ")", ";")):
            return True
        if token.startswith(("/", "~", "$")):
            continue
        parts = token.split("/")
        if ".." not in parts and not is_cd:
            continue
        if quoted and "/" not in token and not is_cd:
            continue
        path = list(cwd)
        for part in parts:
            if part == "..":
                if not path:
                    return True
                path.pop()
            elif part not in ("", "."):
                path.append(part)
        if is_cd and (root is None or root.joinpath(*path).is_dir()):
            cwd = path
    return False


def live_reads(events: list, rollout_path: Path, dispatch: dict, run: Run) -> list:
    own = dispatch["snapshot"].rstrip("/")
    patterns = forbidden_patterns(dispatch, run)

    class Pattern:
        @staticmethod
        def search(text):
            text = text.replace(own, "<SNAPSHOT>")
            return any(p.search(text) for p in patterns)
    pattern = Pattern
    hits = []
    for e in events:
        item = e.get("item") if isinstance(e, dict) else None
        if isinstance(item, dict) and item.get("type") == "command_execution":
            command = item.get("command")
            if isinstance(command, str) and (pattern.search(command) or climbs_out(command, Path(own))):
                hits.append(command[:200])
    for line in rollout_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict) and payload.get("type") in ("custom_tool_call", "function_call", "local_shell_call"):
            fields = [payload.get(k) for k in ("input", "arguments", "action", "command")]
            text = json.dumps([f for f in fields if f is not None])
            if pattern.search(text):
                hits.append(f"rollout {payload.get('type')}: {text[:160]}")
    return sorted(set(hits))


def verify_call(run: Run, call: int, attempt: int, artifacts_override: str | None = None) -> dict:
    call_dir = run.call_dir(call, attempt)
    dispatch = shape(load(call_dir / "input" / "dispatch.json", "dispatch.json"),
                     {"schema": {"planloop-dispatch/1"}, "run_id": "str", "revision": "int", "revision_sha256": "hex",
                      "bundle_sha256": "hex", "plan_sha256": "hex", "call": "int", "attempt": "int",
                      "kind": set(KINDS), "effort": set(EFFORTS), "model": "str?", "snapshot": "str",
                      "snapshot_tree_sha256": "hex", "feedback_sha256": "hex", "artifacts_root": "str",
                      "live_repo": "str", "expected_coverage": "list", "dispatched_at": "str"}, "dispatch.json")
    if (dispatch["run_id"], dispatch["call"], dispatch["attempt"]) != (run.id, call, attempt):
        raise Fail("dispatch.json belongs to another call")
    feedback = (call_dir / "input" / "feedback.md").read_bytes()
    reasons, infra = [], []
    record = {"schema": "planloop-receipt/1", "run_id": run.id, "call": call, "attempt": attempt,
              "kind": dispatch["kind"], "revision": dispatch["revision"], "revision_sha256": dispatch["revision_sha256"],
              "bundle_sha256": dispatch["bundle_sha256"], "plan_sha256": dispatch["plan_sha256"],
              "requested": {"model": dispatch["model"], "effort": dispatch["effort"]}, "effective": None,
              "session_id": None, "fresh": False, "verdict": None, "findings": [], "coverage": [],
              "live_reads": [], "revalidation": [], "artifacts": {}, "dispatched_at": dispatch["dispatched_at"]}
    if sha(feedback) != dispatch["feedback_sha256"]:
        reasons.append("feedback.md changed after dispatch")
    artifacts = artifacts_override
    if artifacts is None and (call_dir / "call.json").exists():
        artifacts = load(call_dir / "call.json").get("artifacts")
    if not artifacts:
        infra.append("runner left no artifact directory (failed before launch, timed out or crashed)")
        return finalize(record, reasons, infra)
    adir = Path(artifacts)
    if adir.parent != Path(dispatch["artifacts_root"]):
        reasons.append("artifact directory is not the one reserved for this call")
    try:
        result = load(adir / "result.json", "runner result.json")
    except Fail as exc:
        infra.append(str(exc))
        return finalize(record, reasons, infra)
    try:
        shape(result, {"status": "str", "mode": "str", "provider": "str", "repo": "str", "plan": "str",
                       "plan_sha256": "hex", "requested_model": "str?", "requested_effort": "str?",
                       "previous": "str?", "artifacts": "str"}, "result.json", exact=False)
    except Fail as exc:
        reasons.append(str(exc))
        return finalize(record, reasons, infra)
    if result["status"] != "completed":
        infra.append(f"runner status {result['status']}: {str(result.get('error', ''))[:200]}")
        return finalize(record, reasons, infra)
    for key in ("session_id", "response", "cli_version", "executable", "exit_code"):
        if key not in result:
            reasons.append(f"result.json lacks {key}")
    if reasons:
        return finalize(record, reasons, infra)
    files = {}
    for name in ("result.json", "command.json", "prompt.txt", "reply.txt", "stdout.txt", "stderr.txt", "schema.json"):
        path = adir / name
        if not path.exists():
            infra.append(f"runner artifact {name} missing")
        else:
            files[name] = sha_file(path)
    record["artifacts"] = {"dir": str(adir), "files": files}
    if infra:
        return finalize(record, reasons, infra)
    snap = Path(dispatch["snapshot"])
    expect = {"mode": "review", "provider": "codex", "repo": str(snap), "plan": str(snap / ".planloop-bundle/plan.md"),
              "plan_sha256": dispatch["plan_sha256"], "requested_effort": dispatch["effort"],
              "requested_model": dispatch["model"], "previous": None, "artifacts": str(adir), "exit_code": 0}
    for key, want in expect.items():
        if result.get(key) != want:
            reasons.append(f"result.json {key} is {result.get(key)!r}, expected {want!r}")
    session = result.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[0-9a-f-]{36}", session):
        reasons.append("result.json has no session UUID")
        return finalize(record, reasons, infra)
    record["session_id"] = session
    try:
        argv = load(adir / "command.json", "command.json")
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            raise Fail("command.json is not a list of strings")
    except Fail as exc:
        reasons.append(str(exc))
        return finalize(record, reasons, infra)
    flags = list(zip(argv, argv[1:]))
    efforts = [b for a, b in flags if a == "-c" and b.startswith("model_reasoning_effort=")]
    models = [b for a, b in flags if a in ("-m", "--model")]
    if argv[1:2] != ["exec"] or "resume" in argv[2:3]:
        reasons.append("invocation is not a fresh `codex exec` (resume or another subcommand)")
    if efforts != [f'model_reasoning_effort="{dispatch["effort"]}"']:
        reasons.append(f"invocation effort flags {efforts} do not request {dispatch['effort']} exactly once")
    if models != ([dispatch["model"]] if dispatch["model"] else []):
        reasons.append(f"invocation model flags {models} differ from the requested model")
    if ("-s", "read-only") not in flags:
        reasons.append("invocation is not read-only")
    if result.get("executable") != argv[:1]:
        reasons.append("result.json executable differs from command.json")
    events = []
    for number, line in enumerate((adir / "stdout.txt").read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                events.append(loads(line, f"stdout event {number}"))
            except Fail as exc:
                reasons.append(str(exc))
    threads = [e.get("thread_id") for e in events if isinstance(e, dict) and e.get("type") == "thread.started"]
    if threads != [session]:
        reasons.append(f"event stream thread ids {threads} differ from session {session}")
    if [e for e in events if isinstance(e, dict) and e.get("type") in ("error", "turn.failed")]:
        reasons.append("event stream reports a failed turn")
    if len([e for e in events if isinstance(e, dict) and e.get("type") == "turn.completed"]) != 1:
        reasons.append("event stream lacks exactly one completed turn")
    try:
        reply = load(adir / "reply.txt", "reply.txt")
    except Fail as exc:
        reasons.append(str(exc))
        reply = None
    if reply != result.get("response"):
        reasons.append("reply.txt differs from result.json response")
    response = result.get("response")
    reasons += response_problems(response)
    prompt = (adir / "prompt.txt").read_text(encoding="utf-8")
    plan_text = (run.rev_dir(dispatch["revision"]) / "plan.md").read_text(encoding="utf-8")
    marker = f"sha256={dispatch['bundle_sha256']}"
    if f"PLAN SHA256: {dispatch['plan_sha256']}\n" not in prompt or f"<plan>\n{plan_text}\n</plan>\n" not in prompt:
        reasons.append("prompt.txt does not carry this revision's plan")
    if not prompt.endswith("HOST DISPOSITIONS / FIX REQUEST:\n" + feedback.decode("utf-8")) or marker not in prompt:
        reasons.append("prompt.txt does not end with this call's feedback and bundle marker")
    rollout_path, missing = rollout_for(session)
    if missing and (adir / "rollout.jsonl").exists():
        rollout_path, missing = adir / "rollout.jsonl", None
    if missing:
        infra.append(f"effective settings unverifiable: {missing}")
        return finalize(record, reasons, infra)
    manifest = json.loads((run.rev_dir(dispatch["revision"]) / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    frozen = Path(next(i for i in manifest["items"] if i["type"] == "snapshot")["path"]) / "AGENTS.md"
    context = {"cwd": str(snap),
               "agents_md": frozen.read_text(encoding="utf-8") if frozen.is_file() else None}
    try:
        rollout = parse_rollout(rollout_path, session, prompt, result.get("cli_version", ""), context=context)
    except Unverifiable as exc:
        infra.append(f"effective settings unverifiable: {exc}")
        return finalize(record, reasons, infra)
    except Fail as exc:
        reasons.append(str(exc))
        return finalize(record, reasons, infra)
    keep = adir / "rollout.jsonl"
    if not keep.exists():
        shutil.copy2(rollout_path, keep)
    if sha_file(keep) != rollout["sha256"]:
        reasons.append("the kept copy of the rollout differs from Codex's session record")
    record["effective"] = {"model": rollout["model"], "effort": rollout["effort"], "sandbox": rollout["sandbox"],
                           "source": f"Codex rollout turn_context ({rollout['parser']})",
                           "rollout_sha256": rollout["sha256"]}
    if rollout["effort"] != dispatch["effort"]:
        reasons.append(f"effective effort {rollout['effort']} differs from requested {dispatch['effort']}"
                       + (" (downgrade)" if EFFORTS[rollout["effort"]] < EFFORTS[dispatch["effort"]] else ""))
    if dispatch["model"] and rollout["model"] != dispatch["model"]:
        reasons.append(f"effective model {rollout['model']} differs from requested {dispatch['model']}")
    if rollout["sandbox"] != "read-only" or rollout["approval_policy"] != "never":
        reasons.append("effective sandbox/approval is not read-only/never")
    if rollout["cwd"] != str(snap):
        reasons.append(f"reviewer ran in {rollout['cwd']}, not the frozen snapshot")
    earlier = {r["session_id"] for c, a, p, r in receipts(run) if r and (c, a) != (call, attempt) and r["session_id"]}
    fresh = (rollout["prompt_in_first_turn"] and rollout["user_turns"] == 1 and not rollout["lineage_fields"]
             and session not in earlier and result.get("previous") is None and "resume" not in argv[2:3])
    record["fresh"] = fresh
    if not fresh:
        reasons.append("context is not provably fresh (resume, earlier user turns, lineage fields or reused session)")
    record["live_reads"] = live_reads(events, rollout_path, dispatch, run)
    if record["live_reads"]:
        reasons.append(f"reviewer reached outside its private snapshot (live checkout, planloop state, Codex "
                       f"home, or a relative path climbing above the snapshot root): {record['live_reads'][:3]}")
    if tree_hash(snap) != dispatch["snapshot_tree_sha256"]:
        reasons.append("frozen snapshot changed during the review")
    if isinstance(response, dict) and isinstance(response.get("coverage"), list):
        seen = {}
        for line in response["coverage"]:
            if not isinstance(line, str) or not COVERAGE_LIKE.match(line):
                continue
            m = COVERAGE.match(line.strip())
            if not m:
                reasons.append(f"coverage line {line[:80]!r} looks like a finding status but is not exactly "
                               "`finding R<k>: resolved|unresolved|withdrawal confirmed` or "
                               "`finding R<k>: withdrawn: <evidence, 40+ chars>`")
                continue
            if m.group(1) in seen:
                reasons.append(f"coverage states {m.group(1)} more than once")
            seen[m.group(1)] = m.group(2).split(":")[0]
        raised = {f.get("id") for f in response.get("findings", []) if isinstance(f, dict)}
        missing = [r for r in dispatch["expected_coverage"] if r not in seen and r not in raised]
        if missing:
            reasons.append(f"reviewer did not report on findings {missing} (fix-proposed: resolved/unresolved; "
                           "withdrawn, at the gate: withdrawal confirmed, or re-raise)")
        clash = [r for r in seen if r in raised and seen[r] != "unresolved"]
        if clash:
            reasons.append(f"findings {clash} are both re-raised and reported {', '.join(seen[r] for r in clash)}")
    record["verdict"] = response.get("verdict") if isinstance(response, dict) else None
    record["findings"] = response.get("findings", []) if isinstance(response, dict) else []
    record["coverage"] = response.get("coverage", []) if isinstance(response, dict) else []
    record["usage"] = result.get("usage")
    record["cli_version"] = result.get("cli_version")
    try:
        record["revalidation"] = revalidate(run, dispatch["revision"])
    except Unverifiable as exc:
        infra.append(f"live inputs could not be revalidated: {exc}")
    if record["revalidation"]:
        reasons.append(f"relevant inputs changed during the review: {record['revalidation'][:5]}")
    return finalize(record, reasons, infra)


def finalize(record: dict, reasons: list, infra: list) -> dict:
    record["reasons"] = reasons + infra
    record["infrastructure"] = bool(infra) and not reasons
    if reasons or infra:
        record["status"] = "invalid"
    else:
        record["status"] = "triage" if record["kind"] == "triage" else "counted"
    return record


def revalidate(run: Run, n: int) -> list:
    manifest = loads((run.rev_dir(n) / "bundle" / "manifest.json").read_text(encoding="utf-8"), "manifest")
    changes = []
    for item in manifest["items"]:
        kind = item["type"]
        if kind == "repo_file":
            if live_file(run.repo, item["path"]) != item["sha256"]:
                changes.append(f"file {item['path']} changed or was deleted")
        elif kind == "dir_inventory":
            if dir_entries(run.repo, item["path"]) != item["entries"]:
                changes.append(f"directory {item['path']} gained, lost or changed a file")
        elif kind == "bead":
            if sha(canon(bead_projection(run.beads, item["id"], item["fields"]))) != item["sha256"]:
                changes.append(f"binding text of bead {item['id']} changed")
        elif kind == "evidence" and item["validity"].get("type") == "until_input_change":
            for entry in item["inputs"]:
                if live_file(run.repo, entry["path"]) != entry["sha256"]:
                    changes.append(f"evidence {item['id']} input {entry['path']} changed")
    return changes


def finish_receipt(run: Run, call: int, attempt: int, artifacts: str | None = None) -> int:
    running = run.call_dir(call, attempt) / "running.json"
    if running.exists():
        owner = load(running, "running.json")
        if owner.get("pid") != os.getpid() and owner_alive(owner):
            raise Conflict(f"call {call} attempt {attempt} is still being reviewed by process {owner.get('pid')}; "
                           "wait for it")
    with Lock(run.dir):
        record = verify_call(run, call, attempt, artifacts)
        path = run.call_dir(call, attempt) / "receipt.json"
        if path.exists():
            old = load(path)
            if {k: v for k, v in old.items() if k != "created_at"} != record:
                raise Conflict(f"{path} exists and differs from a fresh verification")
        else:
            record["created_at"] = iso(now())
            write_new(path, canon(record))
            record.pop("created_at")
        prune_copies(run, call, attempt, record)
        bead = run.run_bead()
        if record["status"] == "invalid" and invalid_streak(run, meta_of(bead)) >= MAX_ATTEMPTS:
            run.beads.update(bead, {"planloop_state": "blocked",
                                    "planloop_reason": f"text: {MAX_ATTEMPTS} review attempts in a row failed; "
                                                       f"last: {record['reasons'][0][:200]}"})
    for reason in record["reasons"]:
        print(f"FAIL  {reason}")
    print(f"call {call} attempt {attempt}: {record['status']}, verdict {record['verdict']}, "
          f"effort {record['requested']['effort']}->{(record['effective'] or {}).get('effort')}, fresh {record['fresh']}")
    return 0 if record["status"] in ("counted", "triage") else 1


def prune_copies(run: Run, call: int, attempt: int, record: dict) -> None:
    keep = record["kind"] == "gate" and record["status"] == "counted"
    for c, a, path, r in receipts(run):
        if r is None:
            continue
        dispatch = load(path / "input" / "dispatch.json")
        private = Path(dispatch["snapshot"]).parent
        own = (c, a) == (call, attempt)
        if private.parent != run.isolated or not private.exists() or (own and keep):
            continue
        if own or not (r["kind"] == "gate" and r["status"] == "counted") or keep:
            remove_tree(private)


def cmd_receipt(args) -> int:
    run = Run(args.run)
    run.config()
    return finish_receipt(run, args.call, args.attempt, args.artifacts)


def intents_dir(run: Run) -> Path:
    return run.dir / "intents"


def save_intent(run: Run, name: str, intent: dict) -> Path:
    path = intents_dir(run) / f"{name}.json"
    write_atomic(path, canon(intent))
    return path


def apply_intent(run: Run, path: Path) -> None:
    intent = load(path, str(path))
    if intent["state"] == "verified":
        return
    run_bead = run.run_bead()
    for op in intent["ops"]:
        key = op["key"]
        if key.startswith("run:"):
            run_bead = run.beads.update(run_bead, op["meta"])
            continue
        bead = run.beads.keyed(key)
        if bead is None:
            if op.get("create") is None:
                raise Unverifiable(f"intent {path.name} expects {key} to exist")
            bead = run.beads.create_keyed(key, run_bead["id"], op["create"]["title"], "task", op["create"]["meta"])
        run.beads.update(bead, op["meta"], op.get("status"), op.get("reason", ""))
    intent["state"] = "applied"
    write_atomic(path, canon(intent))
    crash_point("intent_applied")
    for op in intent["ops"]:
        bead = run.beads.keyed(op["key"])
        if bead is None or any(bead["metadata"].get(k) != str(v) for k, v in op["meta"].items()):
            raise Unverifiable(f"intent {path.name}: {op['key']} did not read back; re-run")
        if op.get("status") == "closed" and bead.get("status") != "closed":
            raise Unverifiable(f"intent {path.name}: {op['key']} is not closed")
        if op.get("status") == "open" and bead.get("status") == "closed":
            raise Unverifiable(f"intent {path.name}: {op['key']} is still closed")
    intent["state"] = "verified"
    write_atomic(path, canon(intent))


def recover_intents(run: Run) -> None:
    for path in sorted(intents_dir(run).glob("*.json")):
        intent = load(path, str(path))
        if intent.get("state") != "verified":
            print(f"NOTE  replaying unfinished intent {path.name}", file=sys.stderr)
            apply_intent(run, path)


def meta_of(bead) -> dict:
    return dict((bead or {}).get("metadata") or {})


def cmd_findings(args) -> int:
    run = Run(args.run)
    run.config()
    if args.action == "check":
        problems = reconcile(run)
        for p in problems:
            print(f"FAIL  {p}")
        if not problems:
            ok("Beads finding state is consistent with receipts, intents and decisions")
        return 1 if problems else 0
    with Lock(run.dir):
        prepare(run)
        if args.action == "ingest":
            path = ingest_intent(run, args.call, args.attempt, Path(args.map))
        elif args.action == "propose":
            path = propose_intent(run)
        else:
            path = decide_intent(run, Path(args.decision))
        if path is not None:
            apply_intent(run, path)
            print(f"applied {path.name}")
    return 0


def ingest_intent(run: Run, call: int, attempt: int, map_path: Path):
    name = f"ingest-call-{call:03d}-a{attempt}"
    existing = intents_dir(run) / f"{name}.json"
    if existing.exists():
        return existing
    receipt = load(run.call_dir(call, attempt) / "receipt.json")
    if receipt["status"] != "counted":
        raise Fail(f"call {call} attempt {attempt} is {receipt['status']}; only counted reviews change findings")
    for c, a, path, r in receipts(run):
        done = (intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json").exists()
        if r and r["status"] == "counted" and c < call and not done:
            raise Fail(f"ingest call {c} first: findings are ingested in call order")
        if r and r["status"] == "counted" and c > call and done:
            raise Fail(f"call {c} is already ingested; an older review cannot be ingested after a newer one")
    mapping = load(map_path, "finding map")
    if not isinstance(mapping, dict):
        raise Fail("finding map must be an object")
    reviewer_ids = [f["id"] for f in receipt["findings"]]
    if sorted(mapping) != sorted(reviewer_ids):
        raise Fail(f"map keys {sorted(mapping)} must be exactly the reviewer's finding ids {sorted(reviewer_ids)}")
    findings = run.findings()
    run_bead = run.run_bead()
    run_meta = meta_of(run_bead)
    next_n = max([int(f[1:]) for f in findings] + [0]) + 1
    ops, raised, run_updates = [], set(), {}
    redesign = {r for r in run_meta.get("planloop_redesign_required", "").split(",") if r}
    redesigns = {}
    for item in run_meta.get("planloop_redesigns", "").split(","):
        if ":" in item:
            redesigns[item.split(":")[0]] = int(item.split(":")[1])
    sev_rank = {"low": 0, "medium": 1, "high": 2}
    for f in receipt["findings"]:
        target = mapping[f["id"]]
        if target == "new" or (isinstance(target, str) and target.startswith("new:")):
            fid = f"R{next_n}"
            next_n += 1
            lineage = target[4:] if target.startswith("new:") else ""
            if lineage and lineage not in findings:
                raise Fail(f"lineage {lineage} is not a known finding")
            meta = {"planloop_kind": "finding", "planloop_run": run.id, "planloop_finding": fid,
                    "planloop_severity": f["severity"], "planloop_state": "open", "planloop_raised_call": call,
                    "planloop_fix_proposals": 0, "planloop_unresolved_after_fix": 0, "planloop_reopens": 0,
                    "planloop_last_fix_revision": 0, "planloop_resolution": "", "planloop_lineage": lineage,
                    "planloop_evidence": f"reviews/{run.call_dir(call, attempt).name}/receipt.json#{f['id']}"}
            ops.append({"key": finding_key(run, fid), "meta": meta, "status": "open",
                        "create": {"title": f"[{f['severity']}] {fid}: {f['evidence'][:90]}", "meta": meta}})
            raised.add(fid)
            continue
        if not FINDING_ID.match(str(target)) or target not in findings:
            raise Fail(f"map target {target!r} is neither new nor a known finding")
        fid, meta = target, meta_of(findings[target])
        raised.add(fid)
        state = meta.get("planloop_state")
        update = {"planloop_severity": max(meta.get("planloop_severity", "low"), f["severity"], key=sev_rank.get)}
        if state in ("verified", "withdrawn", "decided"):
            update |= {"planloop_state": "reopened", "planloop_reopens": int(meta.get("planloop_reopens", 0)) + 1,
                       "planloop_resolution": ""}
            run_updates["planloop_min_effort"] = "high"
            ops.append({"key": finding_key(run, fid), "meta": update, "status": "open"})
            continue
        if state == "fix_proposed":
            if receipt["revision"] < int(meta.get("planloop_last_fix_revision") or 0):
                ops.append({"key": finding_key(run, fid), "meta": update})
                continue
            count = int(meta.get("planloop_unresolved_after_fix", 0)) + 1
            update |= {"planloop_state": "open", "planloop_unresolved_after_fix": count}
            if count >= 2:
                redesign.add(fid)
        ops.append({"key": finding_key(run, fid), "meta": update})
    for line in receipt["coverage"]:
        m = COVERAGE.match(line.strip())
        if not m or m.group(1) not in findings or m.group(1) in raised:
            continue
        fid, verdict, explanation = m.group(1), m.group(2).split(":")[0], m.group(3)
        meta = meta_of(findings[fid])
        state = meta.get("planloop_state")
        ref = f"reviews/{run.call_dir(call, attempt).name}/receipt.json"
        current = receipt["revision"] >= int(meta.get("planloop_last_fix_revision") or 0)
        if verdict == "resolved" and state == "fix_proposed" and current \
                and call > int(meta.get("planloop_raised_call", 0)):
            ops.append({"key": finding_key(run, fid), "meta": {"planloop_state": "verified", "planloop_resolution": ref},
                        "status": "closed", "reason": f"verified by planloop {ref}"})
            redesign.discard(fid)
        elif verdict == "unresolved" and state == "fix_proposed" and current:
            count = int(meta.get("planloop_unresolved_after_fix", 0)) + 1
            ops.append({"key": finding_key(run, fid), "meta": {"planloop_state": "open",
                                                               "planloop_unresolved_after_fix": count}})
            if count >= 2:
                redesign.add(fid)
        elif verdict == "withdrawn" and state in OPEN_STATES:
            ops.append({"key": finding_key(run, fid), "status": "closed", "reason": f"withdrawn by a reviewer in {ref}",
                        "meta": {"planloop_state": "withdrawn", "planloop_resolution": ref,
                                 "planloop_withdrawal": f"text: {explanation[:400]}"}})
            redesign.discard(fid)
    for fid in redesign:
        if redesigns.get(fid, 0) >= 1:
            if run_meta.get("planloop_track") != "escalated":
                run_updates["planloop_escalated_revision"] = str((run.head() or (0,))[0] + 1)
            run_updates["planloop_track"] = "escalated"
            run_updates["planloop_min_effort"] = "high"
    run_updates["planloop_redesign_required"] = ",".join(sorted(redesign, key=lambda r: int(r[1:])))
    ops.append({"key": f"run:{run.id}", "meta": run_updates})
    return save_intent(run, name, {"schema": "planloop-intent/1", "name": name, "state": "planned", "ops": ops})


def propose_intent(run: Run):
    head = run.head()
    if head is None:
        raise Fail("nothing published")
    n = head[0]
    name = f"propose-r{n:03d}"
    if (intents_dir(run) / f"{name}.json").exists():
        return intents_dir(run) / f"{name}.json"
    handback = load(run.rev_dir(n) / "handback.json")
    findings = run.findings()
    run_meta = meta_of(run.run_bead())
    redesign = {r for r in run_meta.get("planloop_redesign_required", "").split(",") if r}
    redesigns = {}
    for item in run_meta.get("planloop_redesigns", "").split(","):
        if ":" in item:
            redesigns[item.split(":")[0]] = int(item.split(":")[1])
    ops, run_updates = [], {}
    for fid, answer in handback["answers"].items():
        meta = meta_of(findings[fid])
        if meta.get("planloop_state") not in ("open", "reopened") or int(meta.get("planloop_last_fix_revision", 0)) >= n:
            continue
        if answer == "REJECT":
            ops.append({"key": finding_key(run, fid), "meta": {"planloop_rejected_revision": n}})
            continue
        update = {"planloop_state": "fix_proposed", "planloop_last_fix_revision": n,
                  "planloop_fix_proposals": int(meta.get("planloop_fix_proposals", 0)) + 1}
        if answer == "REDESIGN":
            update["planloop_unresolved_after_fix"] = 0
            redesign.discard(fid)
            redesigns[fid] = redesigns.get(fid, 0) + 1
            run_updates["planloop_min_effort"] = "high"
        ops.append({"key": finding_key(run, fid), "meta": update})
    run_updates["planloop_redesign_required"] = ",".join(sorted(redesign, key=lambda r: int(r[1:])))
    run_updates["planloop_redesigns"] = ",".join(f"{k}:{v}" for k, v in sorted(redesigns.items()))
    ops.append({"key": f"run:{run.id}", "meta": run_updates})
    return save_intent(run, name, {"schema": "planloop-intent/1", "name": name, "state": "planned", "ops": ops})


def load_decision(run: Run, path: Path) -> dict:
    value = shape(load(path, str(path)), {"schema": {"planloop-decision/1"}, "id": "str", "by": {"Mike"},
                                         "quote": "str", "recorded_at": "str", "recorded_by": "str",
                                         "subjects": "list", "outcome": {"accepted-risk", "rejected-finding",
                                                                         "deferred", "scope-out"},
                                         "follow_up": "str?"}, path.name)
    parse_time(value["recorded_at"])
    if path.parent != run.dir / "decisions" or path.name != f"{value['id']}.json":
        raise Fail(f"decision {value['id']} must live at decisions/{value['id']}.json")
    for i, s in enumerate(value["subjects"]):
        shape(s, {"id": "str", "text_sha256": "hex?"}, f"{path.name}.subjects[{i}]")
    if value["outcome"] == "deferred" and not value["follow_up"]:
        raise Fail("a deferral names its follow-up bead")
    return value


def decide_intent(run: Run, path: Path):
    path = path.resolve()
    decision = load_decision(run, path)
    if decision["follow_up"] and run.beads.get(decision["follow_up"]) is None:
        raise Fail(f"follow-up bead {decision['follow_up']} does not exist")
    name = f"decide-{decision['id']}"
    if (intents_dir(run) / f"{name}.json").exists():
        return intents_dir(run) / f"{name}.json"
    findings = run.findings()
    ops = []
    for s in decision["subjects"]:
        if FINDING_ID.match(s["id"]):
            if s["id"] not in findings:
                raise Fail(f"decision names unknown finding {s['id']}")
            if meta_of(findings[s["id"]]).get("planloop_state") not in OPEN_STATES:
                continue
            ops.append({"key": finding_key(run, s["id"]), "status": "closed",
                        "meta": {"planloop_state": "decided", "planloop_resolution": f"decisions/{path.name}"},
                        "reason": f"decided by Mike, decisions/{path.name}"})
    if not ops:
        return None
    run_meta = meta_of(run.run_bead())
    decided = {o["key"].rsplit(":", 1)[1] for o in ops}
    redesign = [r for r in run_meta.get("planloop_redesign_required", "").split(",") if r and r not in decided]
    ops.append({"key": f"run:{run.id}", "meta": {"planloop_redesign_required": ",".join(redesign)}})
    return save_intent(run, name, {"schema": "planloop-intent/1", "name": name, "state": "planned", "ops": ops})


def reconcile(run: Run) -> list:
    problems = []
    for path in sorted(intents_dir(run).glob("*.json")):
        if load(path).get("state") != "verified":
            problems.append(f"intent {path.name} is unfinished; re-run any findings command to replay it")
    try:
        findings = run.findings()
        run_meta = meta_of(run.run_bead())
    except (Unverifiable, Conflict) as exc:
        return problems + [f"Beads unreadable or inconsistent: {exc}"]
    for c, a, p, r in receipts(run):
        if r and r["status"] == "counted" and not (intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json").exists():
            problems.append(f"counted review call {c} attempt {a} has not been ingested")
    for fid, bead in findings.items():
        meta = meta_of(bead)
        state = meta.get("planloop_state")
        if state not in STATES:
            problems.append(f"{fid} has unknown state {state!r}")
            continue
        closed = bead.get("status") == "closed"
        if (state in OPEN_STATES) == closed:
            problems.append(f"{fid}: state {state} but bead status {bead.get('status')}")
        ref = meta.get("planloop_resolution", "")
        if state in ("verified", "withdrawn"):
            rpath = run.dir / ref
            try:
                r = load(rpath)
            except Fail:
                problems.append(f"{fid}: resolution {ref!r} is not a receipt")
                continue
            want = f"finding {fid}: resolved" if state == "verified" else f"finding {fid}: withdrawn: "
            lines = [c.strip() for c in r["coverage"]]
            shown = want in lines if state == "verified" else any(c.startswith(want) and COVERAGE.match(c) for c in lines)
            if r["status"] != "counted" or not shown or fid in {f["id"] for f in r["findings"]}:
                problems.append(f"{fid}: receipt {ref} does not show a counted '{want}' for it")
            if state == "verified" and r["call"] <= int(meta.get("planloop_raised_call", 0)):
                problems.append(f"{fid}: verified by the call that raised it")
        if state == "decided":
            try:
                d = load_decision(run, (run.dir / ref).resolve())
                if fid not in [s["id"] for s in d["subjects"]]:
                    problems.append(f"{fid}: decision {ref} does not name it")
            except Fail as exc:
                problems.append(f"{fid}: decision {ref}: {exc}")
    pending = [r for r in run_meta.get("planloop_redesign_required", "").split(",")
               if r and meta_of(findings.get(r)).get("planloop_state") in OPEN_STATES]
    if pending:
        problems.append(f"structural redesign still required for {','.join(pending)}")
    return problems


def cmd_evidence(args) -> int:
    run = Run(args.run)
    records, bad = [], 0
    for name in args.files:
        record = load(Path(name), name)
        problems = check_evidence(record, run.repo, run.repo, at=now())
        records.append(record)
        for p in problems:
            print(f"FAIL  {record.get('id')}: {p}")
        bad += bool(problems)
        if not problems:
            ok(f"{record['id']} supports its claim")
    for p in check_groups(records):
        print(f"FAIL  {p}")
        bad += 1
    return 1 if bad else 0


def cmd_state(args) -> int:
    run = Run(args.run)
    run.config()
    with Lock(run.dir):
        prepare(run)
        bead = run.run_bead()
        if meta_of(bead).get("planloop_state") == "approved" and approval_holds(run):
            raise Fail("the run is approved and its approval still verifies; nothing to reopen")
        last_call = max((c for c, _, _ in call_dirs(run)), default=0)
        update = {"planloop_state": args.set, "planloop_reason": f"text: {args.reason}"}
        if args.set == "active":
            update["planloop_active_after_call"] = last_call
        run.beads.update(bead, update)
    print(f"run {run.id}: {args.set} ({args.reason})")
    return 0


def cmd_planner(args) -> int:
    run = Run(args.run)
    run.config()
    if not args.quote.strip():
        raise Fail("a planner override needs Mike's exact words")
    with Lock(run.dir):
        prepare(run)
        bead = run.run_bead()
        update = {"planloop_planner_override": args.model,
                  "planloop_planner_override_decision": f"text: {args.quote} (recorded {iso(now())})"}
        run.beads.update(bead, update)
    print(f"run {run.id}: escalated-track planner override {args.model!r} recorded")
    return 0


def cmd_reviewers(args) -> int:
    run = Run(args.run)
    if not args.quote.strip():
        raise Fail("a reviewer model choice needs Mike's exact words")
    with Lock(run.dir):
        prepare(run)
        config = run.config()
        config["model_changes"].append({"at": iso(now()), "from": [config["reviewer_model"], config["gate_model"]],
                                        "to": [args.model, args.gate_model], "quote": args.quote})
        config.update({"reviewer_model": args.model, "gate_model": args.gate_model})
        write_atomic(run.dir / "run.json", canon(config))
    print(f"run {run.id}: Codex reviews on {args.model!r}, the final gate on {args.gate_model!r}, from the next dispatch")
    return 0


def approval_holds(run: Run) -> bool:
    pointer = run.dir / "APPROVAL"
    if not pointer.exists():
        return False
    try:
        p = shape(load(pointer, "APPROVAL"), {"schema": {"planloop-approval-pointer/1"}, "record": "str",
                                              "sha256": "hex"}, "APPROVAL")
        record = load(run.dir / "approvals" / p["record"], "approval record")
        report = Report()
        with contextlib.redirect_stdout(io.StringIO()):
            facts = readiness(run, report, at_publication=False)
        return not report.failures and facts == {k: v for k, v in record.items() if k not in ("approved_at", "schema")}
    except (Fail, Unverifiable, Conflict):
        return False


def cmd_ledger(args) -> int:
    run = Run(args.run)
    run.config()
    head = run.head()
    lines = ["<!-- GENERATED by .claude/skills/planloop/scripts/planloop.py ledger. Not authoritative and not",
             "     to be edited: finding status lives in Beads, review facts in reviews/*/receipt.json. -->",
             f"# planloop ledger: {run.id}", "",
             f"HEAD: revision {head[0] if head else '-'}; run state {meta_of(run.run_bead()).get('planloop_state')}", "",
             "| call | attempt | kind | revision | status | effort req -> eff | fresh | verdict | reasons |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c, a, p, r in receipts(run):
        if r is None:
            lines.append(f"| {c} | {a} | ? | ? | no receipt | | | | |")
            continue
        lines.append(f"| {c} | {a} | {r['kind']} | {r['revision']} | {r['status']} | {r['requested']['effort']} -> "
                     f"{(r['effective'] or {}).get('effort')} | {r['fresh']} | {r['verdict']} | "
                     f"{'; '.join(r['reasons'])[:160]} |")
    lines += ["", findings_table(run), ""]
    write_atomic(run.dir / "ledger.md", "\n".join(lines).encode("utf-8"))
    print(f"wrote {run.dir / 'ledger.md'}")
    return 0


def readiness(run: Run, report: Report, at_publication: bool) -> dict | None:
    head = run.head()
    if not report.check(head is not None, "[mechanical] a revision is published"):
        return None
    n, rev_sha = head
    try:
        rev = verify_revision(run, n)
        report.check(True, f"[mechanical] revision {n} integrity, chain and frozen snapshot verify")
    except Fail as exc:
        report.check(False, "[mechanical] revision integrity", str(exc))
        return None
    all_receipts = receipts(run)
    last = all_receipts[-1] if all_receipts else None
    gate_ok = bool(last and last[3] and last[3]["kind"] == "gate" and last[3]["revision"] == n)
    report.check(gate_ok, "[mechanical] the latest review call is a final gate on the published revision")
    if not gate_ok:
        return None
    c, a, _, stored = last
    fresh = verify_call(run, c, a)
    same = {k: v for k, v in stored.items() if k != "created_at"} == fresh
    report.check(same, "[mechanical] gate receipt re-derived from runner and Codex records matches the stored receipt")
    report.check(fresh["status"] == "counted", "[mechanical] gate call verified",
                 "; ".join(fresh["reasons"]))
    report.check(fresh["verdict"] == "APPROVED", "[mechanical] gate verdict APPROVED", str(fresh["verdict"]))
    report.check(fresh["requested"]["effort"] == "high" and (fresh["effective"] or {}).get("effort") == "high",
                 "[mechanical] gate requested and effective effort high (effective = Codex CLI's turn_context)")
    report.check(fresh["fresh"], "[mechanical] gate context fresh (invocation, session lineage, first user turn)")
    report.check(not fresh["live_reads"], "[mechanical] gate reviewer read no live-checkout path")
    report.check(fresh["bundle_sha256"] == rev["bundle_sha256"], "[mechanical] the gate was given exactly this "
                 "revision's plan and bundle (delivery and input consistency, not proof each source was examined)")
    gate_lines = {c.strip() for c in fresh["coverage"]}
    unconfirmed = sorted(f for f, b in run.findings().items() if meta_of(b).get("planloop_state") == "withdrawn"
                         and f"finding {f}: withdrawal confirmed" not in gate_lines)
    report.check(not unconfirmed, "[mechanical] the final gate confirmed every withdrawn finding against its "
                 "original failure scenario", ", ".join(unconfirmed))
    changes = revalidate(run, n)
    report.check(not changes, "[mechanical] relevant live inputs unchanged since the bundle was frozen", "; ".join(changes))
    frozen = run.rev_dir(n) / "bundle" / "frozen"
    try:
        discovery = load(frozen / "discovery.json")
        report.check(not discovery["known_omissions"], "[host-attested] discovery recorded with no known omissions "
                     "(the record is mechanical; that it is complete is not)")
    except Fail as exc:
        report.check(False, "[mechanical] discovery record", str(exc))
    at = parse_time(fresh["dispatched_at"])
    ev_problems = []
    records = []
    for item in rev["manifest"]["items"]:
        if item["type"] == "evidence":
            record = load(frozen / "evidence" / f"{item['id']}.json")
            records.append(record)
            ev_problems += [f"{item['id']}: {p}" for p in
                            check_evidence(record, frozen / "evidence", run.repo, at=at)]
    ev_problems += check_groups(records)
    report.check(not ev_problems, "[mechanical] bundled evidence supports its claims as of the gate's dispatch "
                 "(and must_remain_current observations still now)", "; ".join(ev_problems))
    observations = [{"id": r["id"], "collected_at": r["collected_at"], "certified_as_of": fresh["dispatched_at"],
                     "must_remain_current": r["validity"]["must_remain_current"]}
                    for r in records if r["validity"]["type"] == "observation"]
    problems = reconcile(run)
    report.check(not problems, "[mechanical] Beads findings reconciled with receipts, intents and decisions",
                 "; ".join(problems))
    findings = run.findings()
    still_open = sorted(f for f, b in findings.items() if meta_of(b).get("planloop_state") in OPEN_STATES)
    report.check(not still_open, "[mechanical] no unresolved finding (requirement conflicts are recorded as findings)", ", ".join(still_open))
    ingested = (intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json").exists()
    report.check(ingested or not fresh["findings"], "[mechanical] the gate's own findings are ingested")
    run_meta = meta_of(run.run_bead())
    report.check(run_meta.get("planloop_state") in ("active", "approved"), "[mechanical] run is not blocked or "
                 "awaiting a decision", f"{run_meta.get('planloop_state')}: {run_meta.get('planloop_reason')}")
    handback = load(run.rev_dir(n) / "handback.json")
    accepted = {}
    for path in sorted((run.dir / "decisions").glob("D*.json")):
        try:
            d = load_decision(run, path.resolve())
        except Fail as exc:
            report.check(False, f"[mechanical] decision {path.name} well formed", str(exc))
            continue
        if d["outcome"] == "accepted-risk":
            for s in d["subjects"]:
                accepted[(s["id"], s["text_sha256"])] = path.name
    missing = [rr for rr, text in handback["residual_risks"].items()
               if (rr, sha(text.encode("utf-8"))) not in accepted]
    report.check(not missing, "[host-attested] every residual risk accepted by Mike for its current wording "
                 "(the record and its binding are mechanical; that Mike said it is attested by the recorder)",
                 ", ".join(missing))
    return {"revision": n, "revision_sha256": rev_sha, "plan_sha256": rev["plan_sha256"],
            "bundle_sha256": rev["bundle_sha256"], "gate_call": c, "gate_attempt": a,
            "gate_receipt_sha256": sha_file(run.call_dir(c, a) / "receipt.json"),
            "risk_acceptances": sorted(set(accepted.values())), "observations": observations}


def cmd_rollout_check(args) -> int:
    adir = Path(args.artifacts).resolve()
    result = shape(load(adir / "result.json", "runner result.json"),
                   {"status": {"completed"}, "provider": {"codex"}, "session_id": "str", "cli_version": "str",
                    "requested_effort": set(EFFORTS)}, "result.json", exact=False)
    prompt = (adir / "prompt.txt").read_text(encoding="utf-8")
    path, missing = rollout_for(result["session_id"])
    if missing:
        raise Unverifiable(missing)
    facts = parse_rollout(path, result["session_id"], prompt, result["cli_version"], check_version=False)
    report = Report()
    report.check(facts["effort"] == result["requested_effort"], "rollout effort equals the requested effort",
                 f"{facts['effort']} vs {result['requested_effort']}")
    report.check(facts["prompt_in_first_turn"] and facts["user_turns"] == 1,
                 "the runner's exact prompt is the rollout's first and only user turn")
    report.check(facts["sandbox"] == "read-only" and facts["approval_policy"] == "never",
                 "rollout records the read-only sandbox and approval policy never")
    report.check(not facts["lineage_fields"], "rollout carries no fork/parent/resume lineage fields",
                 str(facts["lineage_fields"]))
    version = result["cli_version"].split()[-1]
    if report.failures:
        print(f"Codex {version}: rollout does NOT match {ROLLOUT_PARSER}; update the parser and its fixture first")
        return 1
    if args.accept:
        if version in accepted_versions():
            print(f"{version} is already accepted")
            return 0
        text = VERSIONS_FILE.read_text(encoding="utf-8")
        line = f"{version} {now().date()} rollout-check of session {result['session_id']} ({adir})\n"
        write_atomic(VERSIONS_FILE, (text + line).encode("utf-8"))
        print(f"accepted Codex {version} for {ROLLOUT_PARSER}")
    else:
        print(f"Codex {version} matches {ROLLOUT_PARSER}; re-run with --accept to record it")
    return 0


def cmd_gate(args) -> int:
    run = Run(args.run)
    run.config()
    report = Report()
    if not args.publish:
        facts = readiness(run, report, at_publication=False)
        pointer = run.dir / "APPROVAL"
        if facts and pointer.exists():
            p = shape(load(pointer, "APPROVAL"), {"schema": {"planloop-approval-pointer/1"}, "record": "str",
                                                  "sha256": "hex"}, "APPROVAL")
            record = load(run.dir / "approvals" / p["record"], "approval record")
            same = {k: v for k, v in record.items() if k not in ("approved_at", "schema")} == facts \
                and sha_file(run.dir / "approvals" / p["record"]) == p["sha256"]
            report.check(same, "[mechanical] the published approval matches the current state")
            report.check(meta_of(run.run_bead()).get("planloop_approval") == p["sha256"],
                         "[mechanical] Beads records this approval")
        elif facts:
            report.check(False, "[mechanical] an approval is published", "ready, not yet published: run gate --publish")
        print("PLAN APPROVED (implementation still needs Mike's separate authorization)" if not report.failures
              else f"NOT APPROVED: {len(report.failures)} check(s) failed")
        return 1 if report.failures else 0
    with Lock(run.dir):
        prepare(run)
        facts = readiness(run, report, at_publication=True)
        if report.failures or facts is None:
            print(f"NOT APPROVED: {len(report.failures)} check(s) failed")
            return 1
        record = {"schema": "planloop-approval/1", **facts, "approved_at": iso(now())}
        data = canon(record)
        name = f"approval-r{facts['revision']:03d}-{sha(data)[:12]}.json"
        write_new(run.dir / "approvals" / name, data)
        crash_point("approval_pending")
        bead = run.run_bead()
        run.beads.update(bead, {"planloop_approval_candidate": sha(data)})
        crash_point("beads_candidate")
        again = Report()
        if readiness(run, again, at_publication=True) != facts or again.failures:
            print("NOT APPROVED: inputs changed while publishing; the pending record stays unreferenced")
            return 1
        write_atomic(run.dir / "APPROVAL", canon({"schema": "planloop-approval-pointer/1", "record": name,
                                                  "sha256": sha(data)}))
        crash_point("approval_pointer")
        run.beads.update(run.run_bead(), {"planloop_state": "approved", "planloop_approval": sha(data),
                                          "planloop_reason": f"text: approved revision {facts['revision']}"})
    print(f"PLAN APPROVED: revision {facts['revision']}, {name}. Implementation still needs Mike's separate "
          "authorization; the implementation bead stays open.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="planloop support tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--run", required=True)
    p.add_argument("--bead", required=True)
    p.add_argument("--reviewer-model")
    p.add_argument("--gate-model")
    p.add_argument("--track", choices=("ordinary", "escalated"), required=True)
    p.add_argument("--risk-domains", required=True)
    p.add_argument("--rationale", required=True)
    p = sub.add_parser("handback")
    p.add_argument("--run", required=True)
    p.add_argument("--nonce")
    p.add_argument("--transcript")
    p.add_argument("--draft")
    p.add_argument("--revision", type=int)
    p.add_argument("--check", action="store_true")
    p = sub.add_parser("bundle")
    for a in ("--run", "--nonce", "--inputs"):
        p.add_argument(a, required=True)
    p.add_argument("--revision", type=int, required=True)
    p = sub.add_parser("publish")
    p.add_argument("--run", required=True)
    p.add_argument("--nonce")
    p.add_argument("--revision", type=int)
    p.add_argument("--recover", action="store_true")
    p = sub.add_parser("dispatch")
    p.add_argument("--run", required=True)
    p.add_argument("--call", type=int, required=True)
    p.add_argument("--attempt", type=int, required=True)
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--effort", required=True)
    p = sub.add_parser("receipt")
    p.add_argument("--run", required=True)
    p.add_argument("--call", type=int, required=True)
    p.add_argument("--attempt", type=int, required=True)
    p.add_argument("--artifacts")
    p = sub.add_parser("findings")
    p.add_argument("action", choices=("ingest", "propose", "decide", "check"))
    p.add_argument("--run", required=True)
    p.add_argument("--call", type=int)
    p.add_argument("--attempt", type=int)
    p.add_argument("--map")
    p.add_argument("--decision")
    p = sub.add_parser("evidence")
    p.add_argument("--run", required=True)
    p.add_argument("files", nargs="+")
    p = sub.add_parser("state")
    p.add_argument("--run", required=True)
    p.add_argument("--set", choices=("active", "blocked", "needs_decision"), required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("planner")
    p.add_argument("--run", required=True)
    p.add_argument("--model", choices=("opus",), required=True)
    p.add_argument("--quote", required=True)
    p = sub.add_parser("reviewers")
    p.add_argument("--run", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--gate-model", required=True)
    p.add_argument("--quote", required=True)
    p = sub.add_parser("ledger")
    p.add_argument("--run", required=True)
    p = sub.add_parser("gate")
    p.add_argument("--run", required=True)
    p.add_argument("--publish", action="store_true")
    p = sub.add_parser("rollout-check")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--accept", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "handback" and args.check and (args.nonce is not None or args.transcript is not None
                                                          or args.draft is not None):
        parser.error("handback --check reads the draft from stdin; it takes no --nonce, --transcript or --draft")
    if args.command == "handback" and not args.check and None in (args.nonce, args.transcript, args.revision):
        parser.error("handback needs --revision, --nonce and --transcript, or --check (plan on stdin)")
    if args.command == "publish" and not args.recover and (args.nonce is None or args.revision is None):
        parser.error("publish needs --revision and --nonce, or --recover")
    if args.command == "findings":
        need = {"ingest": ("call", "attempt", "map"), "decide": ("decision",)}.get(args.action, ())
        if any(getattr(args, k) is None for k in need):
            parser.error(f"findings {args.action} needs {', '.join('--' + k for k in need)}")
    handlers = {"init": cmd_init, "handback": cmd_handback, "bundle": cmd_bundle, "publish": cmd_publish,
                "dispatch": cmd_dispatch, "receipt": cmd_receipt, "findings": cmd_findings, "evidence": cmd_evidence,
                "state": cmd_state, "planner": cmd_planner, "reviewers": cmd_reviewers, "ledger": cmd_ledger, "gate": cmd_gate, "rollout-check": cmd_rollout_check}
    try:
        return handlers[args.command](args)
    except (Fail, Unverifiable, Conflict) as exc:
        print(f"{type(exc).__name__.upper()}  {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
