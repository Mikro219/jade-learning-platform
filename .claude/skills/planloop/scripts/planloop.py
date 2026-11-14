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

Size policy (quartz-rs-72m): every publish reports plan.md's bytes; over the threshold a plan reaches the gate only
after a shrink-only revision a counted reviewer judged for meaning, or under Mike's decisions/S<n>.json size decision.

Exit codes: 0 success or ready; 1 a check failed (each failure is printed);
2 usage error or unverifiable input; 3 lock, publication or Beads conflict, or
a review scope that is not empty; 130 stopped by SIGINT (one INTERRUPTED
line; a dispatch signalled twice while recording dies by the signal instead).
Bad input never produces a traceback: specific checks remain where they give
better advice, and any other TypeError, KeyError, AttributeError, ValueError,
IndexError or RecursionError from a malformed record is one FAIL line naming
the command and the exception, exit 1; PLANLOOP_DEBUG=1 also prints the
traceback of any failure.

dispatch runs each review in a systemd user scope (cgroup v2): it needs
systemd-run 254 or later on PATH and this user's systemd manager reachable
from the shell it runs in, proves both, and that it sees the scope it starts,
with a probe scope before it reserves a call, and has no fallback. A scope is
read only through /sys/fs/cgroup proven to be a cgroup2 mount of this cgroup
namespace's root with nothing mounted over the path to the scope
(/proc/self/mountinfo and fdinfo mount ids); receipt records a call only on
that proof and where the host, machine id, boot, cgroup namespace and cgroup
device are the ones its dispatch recorded. Threat model (Mike, 2026-11-13):
accidents (crashes and kills anywhere, races between planloop's own commands,
reboots, containers and other namespaces, slow or failing systemd, bus or
filesystem), not a hostile process of this user forging /proc, mounting over
cgroup files or planting FIFOs; the mount and /proc checks are accident
hardening, not a security boundary. Lock owners and running.json record the
host, boot id, PID namespace, pid and start time: a process is taken for dead
only on its host, after a reboot or from the PID namespace it recorded; a
record of another PID namespace, or of none, is a CONFLICT to settle by hand,
and dispatch refuses where /proc is not that of its own PID namespace.

Test hooks, never set outside tests: PLANLOOP_CRASH_AT=<point> ends the
process at that point; PLANLOOP_NOW fixes the clock (ISO 8601, UTC);
PLANLOOP_BD, PLANLOOP_RUNNER, PLANLOOP_STATE and PLANLOOP_CODEX_SESSIONS
redirect the Beads CLI, the claudex-loop runner, the state directory and
Codex's session store; PLANLOOP_LOCK_TIMEOUT shortens lock waits;
PLANLOOP_ROLLOUT_VERSIONS points at another accepted-versions list.
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import datetime as dt
import difflib
import errno
import fnmatch
import io
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import traceback
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
PRESERVED = re.compile(r"^\s*[-*]?\s*PRESERVED\s+(\S.*)$")
MEANING_LIKE = re.compile(r"^\s*meaning\s+revision\b", re.I)
SIZE_THRESHOLD_BYTES = 250000
CUT_WARN_PERCENT = 5
PREAMBLE = "(preamble)"
EXEMPT = ("## Change log", "## Artifact inventory")
CUT_SPEC = {"shrink_only": "bool", "lost_lines": "int", "removed_sections": "int", "threshold_bytes": "int",
            "live_answers": "list"}
SIZE_DECISION_NAME = re.compile(r"^S[1-9]\d*\.json$")
RUN_AREA = "plans/planloop"
RUN_META = {"planloop_active_after_call": r"\d*", "planloop_min_effort": f"({'|'.join(EFFORTS)})?",
            "planloop_redesign_required": r"(R[1-9]\d*(,R[1-9]\d*)*)?",
            "planloop_redesigns": r"(R[1-9]\d*:\d+(,R[1-9]\d*:\d+)*)?"}
FINDING_META = {"planloop_finding": r"R[1-9]\d*", "planloop_severity": "low|medium|high",
                "planloop_state": "|".join(STATES), **{f"planloop_{k}": r"\d*" for k in (
                    "raised_call", "fix_proposals", "unresolved_after_fix", "reopens", "last_fix_revision")}}
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
RUNNER_WAIT, STOP_GRACE, PIPE_GRACE, PROBE_WAIT = 1900, 10, 5, 10
CGROUP, MARKER, PROC, PROC_MAGIC = "/sys/fs/cgroup", ".planloop-reserve", "/proc", 0x9FA0
READ_LIMIT, ADMIT_WAIT = 1 << 20, 10
LIBC = None
MACHINE_ID = re.compile(r"^[0-9a-f]{32}$")
FORWARDED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
GATE = ("import os, signal, sys\nfd = int(sys.argv[1])\ngo = os.read(fd, 1)\nos.close(fd)\n"
        "signal.signal(signal.SIGPIPE, signal.SIG_DFL)\nsignal.signal(signal.SIGXFSZ, signal.SIG_DFL)\n"
        "go and os.execvp(sys.argv[2], sys.argv[2:])")
MALFORMED = (TypeError, KeyError, AttributeError, ValueError, IndexError, RecursionError)
VIEW = {"host": "str", "machine_id": "str?", "boot_id": "str", "cgroup_ns": "int", "cgroup_dev": "int"}


class Fail(Exception):
    code = 1


class Unverifiable(Exception):
    code = 2


class Conflict(Exception):
    code = 3


class Unbound(Unverifiable):
    pass


class Abandoned(Exception):
    pass


class NotFile(Fail):
    def __init__(self, path: Path, message: str):
        self.path = path
        super().__init__(message)


class Unreadable(Unverifiable):
    NOTHING = "nothing was recorded from it, run the command again once it can be read"
    SPECIAL = ("nothing was recorded from it: a FIFO, socket or device never reads as a file, so running the command "
               "again cannot help: remove it, or find what put it there, then run the command again")

    def __init__(self, what, error: OSError, then: str = NOTHING):
        self.what, self.error, self.then = what, error, then
        self.why = f"{what} could not be read ({error})"
        super().__init__(f"{self.why}; {then}")


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


def read_file(path: Path, what: str | None = None, text: bool = False):
    try:
        return path.read_text(encoding="utf-8") if text else path.read_bytes()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        raise
    except OSError as exc:
        raise Unreadable(what or str(path), exc) from exc
    except UnicodeDecodeError as exc:
        raise Fail(f"{what or path}: not UTF-8") from exc


def probe(path: Path, test: str = "exists") -> bool:
    try:
        return getattr(path, test)() or test == "exists" and path.is_symlink()
    except OSError as exc:
        raise Unreadable(str(path), exc) from exc


def on_disk(path: Path, follow: bool = False) -> bool:
    try:
        (os.stat if follow else os.lstat)(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def listing(directory: Path, pattern: str) -> list:
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise Unreadable(str(directory), exc) from exc
    return [directory / name for name in sorted(fnmatch.filter(names, pattern))]


def walk(root: Path):
    def failed(exc):
        if not isinstance(exc, FileNotFoundError):
            raise Unreadable(exc.filename or str(root), exc) from exc
    return os.walk(root, onerror=failed)


def sha_file(path: Path) -> str:
    return sha(read_file(path))


def present(path: Path, what: str, link: bool = False, text: bool = False):
    try:
        if link:
            return os.fsencode(os.readlink(path))
        if (path.exists() or path.is_symlink()) and not path.is_file():
            raise NotFile(path, f"{what}: missing or not a file")
        return read_file(path, what, text)
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
        raise Fail(f"{what}: missing or not a file") from exc
    except OSError as exc:
        raise Unreadable(what, exc) from exc


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


def _float(text):
    value = float(text)
    if abs(value) == float("inf"):
        _constant(text)
    return value


def loads(text: str, what: str):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except (ValueError, RecursionError) as exc:
        raise Fail(f"{what}: malformed JSON ({exc})") from exc
    except Fail as exc:
        raise Fail(f"{what}: {exc}") from exc


def load(path: Path, what: str | None = None):
    what = what or str(path)
    try:
        special = (path.exists() or path.is_symlink()) and not path.is_file()
        data = b"" if special else path.read_bytes()
    except FileNotFoundError as exc:
        raise Fail(f"{what}: missing") from exc
    except OSError as exc:
        raise Unreadable(what, exc) from exc
    if special:
        raise Fail(f"{what}: not a file (repair it by hand; reading it again cannot help)")
    return parse(data, what)


def parse(data: bytes, what: str):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Fail(f"{what}: not UTF-8") from exc
    return loads(text, what)


def text_path(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value \
        and value == value.encode("utf-8", "ignore").decode()


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
            if not isinstance(item, str) or item not in kind:
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
        elif kind in ("path", "path?"):
            if not text_path(item) and (item is not None or kind == "path"):
                raise Fail(f"{what}.{key}: not a path (a string that is not blank and holds no NUL and no unpaired "
                           f"surrogate){' or null' if kind == 'path?' else ''}")
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
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def save(path: Path, data: bytes, then: str) -> None:
    try:
        write_atomic(path, data)
    except OSError as exc:
        raise Unverifiable(f"could not write {path} ({exc}); {then}: run the command again once it can be "
                           "written") from exc


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def rename(src: Path, dst: Path, then: str = "run the command again, it re-checks what is on disk") -> None:
    for delay in (0.1, 0.3, 1.0, 2.0, None):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if delay is None:
                raise Conflict(f"could not rename {src} -> {dst}: a file inside is held open (drvfs EACCES)")
            time.sleep(delay)
        except OSError as exc:
            raise Unverifiable(f"could not rename {src} -> {dst} ({exc}); the rename did not report success, "
                               f"so it may or may not have taken effect; {then}") from exc


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=120)
    if check and proc.returncode:
        raise Unverifiable(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
    if out.returncode:
        raise Unverifiable("not inside a git checkout")
    return Path(os.fsdecode(out.stdout.rstrip(b"\n"))).resolve()


def safe_rel(path: str, what: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\0" in path:
        raise Fail(f"{what}: {path!r} must be a repository-relative path")
    if any(p in ("..", ".") for p in path.split("/")):
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


def proc_stat(pid: int):
    try:
        return Path(f"/proc/{pid}/stat").read_bytes().rsplit(b")", 1)[1].decode("ascii").split()
    except (OSError, ValueError, IndexError):
        return None


def proc_start(pid: int):
    fields = proc_stat(pid)
    return fields[19] if fields else None


def pid_ns():
    try:
        return os.stat("/proc/self/ns/pid").st_ino if os.readlink("/proc/self") == str(os.getpid()) else None
    except OSError:
        return None


def identity() -> dict:
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = ""
    return {"host": socket.gethostname(), "boot_id": boot, "pid": os.getpid(), "pid_ns": pid_ns(),
            "start": proc_start(os.getpid())}


def owner_pid(owner: dict):
    pid = owner.get("pid")
    return pid if type(pid) is int and 0 < pid < 2 ** 31 else None


def owner_far(owner: dict) -> str | None:
    theirs, mine = owner.get("pid_ns"), pid_ns()
    if type(theirs) is int and theirs == mine:
        return None
    return ("its record names no PID namespace (a planloop that did not yet record one wrote it)" if theirs is None
            else f"its record names PID namespace {theirs!r}") + \
        (f", and this command runs in PID namespace {mine}" if mine else ", and this command cannot tell its own PID "
         "namespace (/proc/self/ns/pid cannot be read, or /proc is not mounted for it)") + \
        ", where the process ids of another one mean nothing"


def far_check(owner: dict) -> str:
    ns = owner.get("pid_ns")
    return "(or that nothing of that namespace runs any more" + (
        f": run from the host's own PID namespace, `lsns -t pid | grep {ns}` lists it while anything of it runs, and "
        "from inside another namespace no match proves nothing" if type(ns) is int else "") + \
        "; a WSL distribution restarted while its VM runs keeps the boot id but gets a new PID namespace, so what a " \
        "crash left before that restart is settled this way)"


def elsewhere(owner: dict, what: str, path) -> str:
    return f"; it was taken on host {owner.get('host')!r}: check on that host that {owner_named(owner)} is not " \
        f"{what}, then remove {path} by hand"


def owner_alive(owner: dict) -> bool:
    me = identity()
    if owner.get("host") != me["host"]:
        return True
    if owner.get("boot_id") and me["boot_id"] and owner["boot_id"] != me["boot_id"]:
        return False
    pid = owner_pid(owner)
    if pid is None or owner_far(owner):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    fields = proc_stat(pid)
    if fields and fields[0] == "Z":
        return False
    start = fields[19] if fields else None
    return start is None or owner.get("start") is None or start == owner.get("start")


def owner_proven(owner: dict) -> bool:
    pid = owner_pid(owner)
    if pid is None or owner_far(owner):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return owner_alive(owner) and owner.get("start") is not None and proc_start(pid) == owner["start"]


def owner_named(owner: dict) -> str:
    pid = owner_pid(owner)
    return f"process {pid}" if pid else f"the process its record names ({owner.get('pid')!r}, which cannot be checked)"


def scope_base() -> str:
    return f"{CGROUP}/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"


def scope_of(run_id: str, artifacts) -> str | None:
    if not text_path(artifacts):
        return None
    named = re.sub(r"[^A-Za-z0-9:_.-]", "_", f"{run_id}-{os.path.basename(artifacts)}")[:150]
    return f"{scope_base()}/app.slice/planloop-{named}-{sha(f'{run_id}/{artifacts}'.encode())[:32]}.scope"


def view() -> dict:
    host = socket.gethostname()
    out = {"host": host if text_path(host) else None}
    for key, path in (("machine_id", "/etc/machine-id"), ("boot_id", "/proc/sys/kernel/random/boot_id")):
        try:
            out[key] = Path(path).read_bytes().decode("ascii").strip() or None
        except (OSError, ValueError):
            out[key] = None
    if not MACHINE_ID.match(out["machine_id"] or ""):
        out["machine_id"] = None
    for key, path in (("cgroup_ns", "/proc/self/ns/cgroup"), ("cgroup_dev", "/sys/fs/cgroup")):
        try:
            out[key] = os.stat(path).st_ino if key == "cgroup_ns" else os.stat(path).st_dev
        except OSError:
            out[key] = None
    return out


def scoped(unit: str, what: str) -> list:
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--expand-environment=no",
            "--slice=app.slice", f"--description={what}", f"--unit={unit}", "--"]


def scope_ready() -> dict:
    needs = ("dispatch runs each review in a systemd scope of this user, which needs systemd-run 254 or later on "
             "PATH, cgroup v2 mounted at /sys/fs/cgroup and this user's systemd manager reachable from this shell and "
             f"running in the cgroup {scope_base()} as this shell sees it (`systemctl --user status` shows it): {{}}; "
             "no call was reserved and Codex did not run")
    if shutil.which("systemd-run") is None:
        raise Unverifiable(needs.format("systemd-run is not on PATH"))
    seen = view()
    try:
        shape(seen, VIEW, "view")
    except Fail as exc:
        raise Unverifiable(needs.format(f"how this shell sees cgroups cannot be recorded ({exc})")) from exc
    scope = f"{scope_base()}/app.slice/planloop-probe-{uuid.uuid4().hex}.scope"
    try:
        proc, go = start_scoped([sys.executable], scope, None, "planloop probe", PROBE_WAIT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unverifiable(needs.format(f"a probe scope could not be started and seen ({exc})")) from exc
    os.close(go)
    end = time.monotonic() + PROBE_WAIT
    while (left := scope_left(scope)) is not None and time.monotonic() < end:
        time.sleep(0.01)
    if left is not None:
        proc.kill()
        failed = kill_scope(scope)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=PIPE_GRACE)
    if left is not None:
        unit = Path(scope).name
        raise Unverifiable(needs.format(f"the probe scope {unit} did not end once it was released ({left}), and "
                                        + ("was killed" if failed is None else f"could not be killed ({failed}): stop "
                                           f"it with `systemctl --user stop {unit}`")))
    return seen


def read_small(fd: int, path: str, limit: int | None = READ_LIMIT) -> bytes:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise OSError(errno.EINVAL, "not a regular file", path)
    data = bytearray()
    while limit is None or len(data) <= limit:
        part = os.read(fd, 1 << 16 if limit is None else limit + 1 - len(data))
        if not part:
            return bytes(data)
        data += part
    raise OSError(errno.EFBIG, f"larger than {limit} bytes", path)


def libc():
    global LIBC
    if LIBC is None:
        try:
            import ctypes
            LIBC = ctypes, ctypes.CDLL(None, use_errno=True).fstatfs
        except (ImportError, OSError, AttributeError) as exc:
            raise OSError(errno.ENOSYS, f"fstatfs cannot be called through ctypes ({exc}), so it cannot be proven "
                          "procfs", PROC) from None
    return LIBC


def proc_text(rel: str) -> str:
    ctypes, fstatfs = libc()
    root = os.open(PROC, os.O_RDONLY | os.O_DIRECTORY)
    try:
        buf = ctypes.create_string_buffer(256)
        if fstatfs(root, buf):
            raise OSError(ctypes.get_errno(), "fstatfs failed", PROC)
        if int.from_bytes(buf.raw[:ctypes.sizeof(ctypes.c_long)], sys.byteorder) != PROC_MAGIC:
            raise OSError(errno.EXDEV, "not procfs", PROC)
        fd = os.open(rel, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        try:
            if os.fstat(fd).st_dev != os.fstat(root).st_dev:
                raise OSError(errno.EXDEV, "not on procfs", f"{PROC}/{rel}")
            return read_small(fd, f"{PROC}/{rel}", None).decode("utf-8", "replace")
        finally:
            os.close(fd)
    finally:
        os.close(root)


def mount_of(fd: int) -> str:
    for line in proc_text(f"self/fdinfo/{fd}").splitlines():
        if line.startswith("mnt_id:"):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                return parts[1]
            break
    raise OSError(errno.ENOTSUP, "the kernel does not say which mount it is on", f"/proc/self/fdinfo/{fd}")


def cgroup_root() -> tuple:
    fd = os.open(CGROUP, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        mount = mount_of(fd)
        for line in proc_text("self/mountinfo").splitlines():
            head, _, tail = line.partition(" - ")
            if head.split()[:1] == [mount] and (head.split()[3:5], tail.split()[:1]) == (["/", CGROUP], ["cgroup2"]):
                return fd, mount
        raise OSError(errno.EXDEV, "not a cgroup2 mount of this cgroup namespace's root", CGROUP)
    except BaseException:
        os.close(fd)
        raise


def enter(fd: int, name: str, mount: str, path: str, flags: int = os.O_DIRECTORY) -> int:
    try:
        new = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | flags, dir_fd=fd)
    except OSError as exc:
        raise type(exc)(exc.errno, exc.strerror, path) from None
    try:
        if mount_of(new) != mount:
            raise OSError(errno.EXDEV, "another filesystem is mounted over it", path)
    except BaseException:
        os.close(new)
        raise
    return new


def scope_chain(scope: str, held, deep: int | None = None):
    names = os.path.relpath(scope, CGROUP).split("/")
    fd, mount = cgroup_root()
    held.callback(os.close, fd)
    fds = [fd]
    for depth, name in enumerate(names):
        try:
            fd = enter(fd, name, mount, os.path.join(CGROUP, *names[:depth + 1]))
        except FileNotFoundError:
            if deep is None or depth < deep:
                raise
            return None
        held.callback(os.close, fd)
        fds.append(fd)
    return fds, mount


def scope_pids(scope: str) -> list | None:
    with contextlib.ExitStack() as held:
        chain = scope_chain(scope, held, len(os.path.relpath(scope_base(), CGROUP).split("/")))
        if chain is None:
            return None
        (*_, parent, fd), mount = chain

        def control(name):
            path = f"{scope}/{name}"
            try:
                part = enter(fd, name, mount, path, os.O_NONBLOCK)
                held.callback(os.close, part)
                return read_small(part, path).decode()
            except OSError as exc:
                if exc.errno not in (errno.ENOENT, errno.ENODEV):
                    raise
                try:
                    os.close(enter(parent, os.path.basename(scope), mount, scope))
                except FileNotFoundError:
                    return None
                raise
        events = control("cgroup.events")
        if events is None or "populated 0" in events.splitlines():
            return None
        procs = control("cgroup.procs")
        return None if procs is None else procs.split()


def scope_left(scope: str) -> str | None:
    try:
        pids = scope_pids(scope)
    except (OSError, ValueError) as exc:
        return f"whether a process still runs in it cannot be checked ({exc})"
    if pids is None:
        return None
    said = []
    for pid in pids[:5]:
        with contextlib.suppress(OSError):
            line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            said.append(f"{pid} is `{' '.join(line.split())[:120]}`")
    return (f"{len(pids) or 'some'} process{'' if len(pids) == 1 else 'es'} still run{'s' if len(pids) == 1 else ''} "
            f"in it{' (' + '; '.join(said) + ('; ...' if len(pids) > 5 else '') + ')' if said else ''}")


def unseen(scope: str, pid: int) -> str | None:
    try:
        if str(pid) in (scope_pids(scope) or ()):
            return None
        return f"it runs in {scope}, where this shell does not see it"
    except (OSError, ValueError) as exc:
        return f"it runs in {scope}, which this shell cannot see ({exc})"


def kill_scope(scope: str) -> OSError | None:
    try:
        with contextlib.ExitStack() as held:
            (*_, fd), mount = scope_chain(scope, held)
            path = f"{scope}/cgroup.kill"
            part = enter(fd, "cgroup.kill", mount, path, os.O_WRONLY | os.O_NONBLOCK)
            held.callback(os.close, part)
            os.write(part, b"1")
    except OSError as exc:
        return None if scope_left(scope) is None else exc
    return None


def scope_exit(scope: str, then: str) -> str:
    unit = Path(scope).name
    return (f"wait for it to end, or stop it (`systemctl --user kill --signal=INT {unit}`, then `systemctl --user kill "
            f"--signal=KILL {unit}` if that is ignored; `systemd-cgls --user-unit {unit}` shows it), then {then}")


def start_scoped(argv: list, scope: str, child, what: str = "planloop review", wait: float | None = None) -> tuple:
    if shutil.which(argv[0]) is None:
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", argv[0])
    wait = STOP_GRACE if wait is None else wait
    why, where = f"systemd-run did not move it into {scope} within {wait} seconds", f"0::{scope.removeprefix(CGROUP)}\n"
    gate, go = os.pipe()
    try:
        proc = subprocess.Popen(scoped(Path(scope).name, what) + [sys.executable, "-I", "-c", GATE, str(gate), *argv],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                preexec_fn=child, pass_fds=(gate,))
        end = time.monotonic() + wait
        while time.monotonic() < end and proc.poll() is None:
            with contextlib.suppress(OSError):
                if Path(f"/proc/{proc.pid}/cgroup").read_text() == where:
                    why = unseen(scope, proc.pid)
                    break
            time.sleep(0.01)
        if why is None:
            return proc, go
    finally:
        os.close(gate)
        if why is not None:
            os.close(go)
    proc.kill()
    try:
        said = proc.communicate(timeout=PIPE_GRACE)[1]
    except subprocess.TimeoutExpired as exc:
        said = exc.stderr or b""
    said = said.decode("utf-8", "replace").split("\n")[0]
    raise ChildProcessError(said or why)


def stop_scope(proc, scope: str) -> None:
    with contextlib.suppress(OSError):
        proc.send_signal(signal.SIGINT)
    for kill in (False, True):
        if kill:
            kill_scope(scope)
        end = time.monotonic() + STOP_GRACE
        while time.monotonic() < end and scope_left(scope) is not None and (kill or proc.poll() is None):
            time.sleep(0.1)


def await_runner(proc, scope: str, stopped: list) -> tuple:
    deadline, exited, asked, killed, out, read = time.monotonic() + RUNNER_WAIT, None, None, None, b"", False
    unkilled = None
    while True:
        if read:
            time.sleep(0.2)
        else:
            try:
                out, read = proc.communicate(timeout=1)[0], True
            except subprocess.TimeoutExpired as exc:
                out = exc.output or b""
        at = time.monotonic()
        if proc.poll() is not None:
            exited = exited or at
        empty = scope_left(scope) is None
        if asked is None and not stopped and at > deadline:
            asked = at
            with contextlib.suppress(OSError):
                proc.send_signal(signal.SIGINT)
        since = stopped[0][1] if stopped else asked
        if killed is None and (len(stopped) > 1 or exited and not empty
                               or since is not None and at - since > STOP_GRACE):
            killed, unkilled = at, kill_scope(scope)
        elif exited and empty and (read or at - exited > PIPE_GRACE) or killed is not None and at - killed > STOP_GRACE:
            return out, asked is not None, killed, unkilled


class Lock:
    peers = ()

    def __init__(self, directory: Path, name: str = ".lock"):
        self.path = directory / name
        self.nonce = None
        self.done = "the command's work completed (see the output above)"
        self.timeout = float(os.environ.get("PLANLOOP_LOCK_TIMEOUT", "30"))
        self.abandon = lambda: False

    def read_owner(self, path: Path | None = None):
        try:
            value = loads((path or self.path).joinpath("owner.json").read_text(), "lock owner")
        except (OSError, ValueError, Fail):
            return None
        return value if isinstance(value, dict) and isinstance(value.get("nonce"), str) else None

    def __enter__(self):
        try:
            return self._take()
        except (Conflict, Unverifiable) as exc:
            exc.lock = True
            raise

    def _take(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Unverifiable(f"could not prepare the lock in {self.path.parent} ({exc}); the lock was not taken and "
                               "nothing else was changed (at most empty directories on its path were created), run "
                               "the command again") from exc
        deadline, retried = time.monotonic() + self.timeout, False
        while True:
            nonce = uuid.uuid4().hex
            tmp = self.path.parent / f".lock-tmp-{nonce}"
            try:
                tmp.mkdir()
                (tmp / "owner.json").write_bytes(canon({**identity(), "nonce": nonce, "acquired_at": iso(now())}))
            except OSError as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                raise Unverifiable(f"could not prepare the lock in {tmp} ({exc}); the lock was not taken and "
                                   "nothing else was changed, run the command again") from exc
            try:
                os.rename(tmp, self.path)
                self.nonce = nonce
                crash_point("lock_acquired")
                return self
            except OSError as exc:
                failed = exc
                shutil.rmtree(tmp, ignore_errors=True)
            if self._break_stale():
                continue
            if self.abandon():
                raise Abandoned()
            if time.monotonic() > deadline:
                owner = self.read_owner()
                gone = owner is None and not os.path.lexists(self.path)
                if gone and not retried:
                    retried = True
                    continue
                if owner is None and (gone or failed.errno not in (errno.EEXIST, errno.ENOTEMPTY)):
                    raise Unverifiable(f"could not take the lock {self.path}: renaming {tmp.name} onto it failed "
                                       f"({failed}) until the lock timeout; the lock was not taken and nothing else "
                                       "was changed, run the command again")
                if owner is None:
                    raise Conflict(f"could not take the lock {self.path} and its owner.json does not read, so its "
                                   "owner cannot be checked and it is never broken automatically; nothing else was "
                                   "changed, run the command again, and if this persists while no planloop process "
                                   f"runs, remove {self.path} by hand")
                raise Conflict(f"{self.path} is held by {owner}; it is never broken unless its "
                               f"owner is provably dead on this host and in this PID namespace{self.advice(owner)}")
            time.sleep(0.2)

    def advice(self, owner: dict) -> str:
        breaker = self.path.parent / ".lock-break"
        hint = (f"; {breaker} exists, left by a crashed lock breaker: remove it once no planloop process "
                "runs") if probe(breaker) else ""
        far = owner_far(owner)
        hint += elsewhere(owner, "a running planloop command", self.path) if owner.get("host") != socket.gethostname() \
            else f"; process {owner['pid']} on this host took it and is alive: wait for it to finish, or stop it, " \
            "then run the command again" if owner_proven(owner) else \
            f"; {far}, so whether its owner is alive cannot be checked here: run the command where that lock was " \
            "taken (the container, sandbox or session of that PID namespace), which breaks it if its owner is dead, " \
            f"or check there that {owner_named(owner)} is not a running planloop command {far_check(owner)}, then " \
            f"remove {self.path} by hand" if far else \
            f"; if {owner_named(owner)} on this host is not a running planloop command, remove {self.path} by hand"
        keys = ("host", "boot_id", "pid_ns", "pid", "start")
        for peer in Lock.peers:
            other = self.read_owner(peer) if peer != self.path else None
            if other is not None and all(other.get(k) == owner.get(k) for k in keys):
                hint += f"; the same process also holds {peer} (its owner.json names the same host, boot, PID " \
                    "namespace, pid and start), which is settled the same way"
        return hint

    def _break_stale(self) -> bool:
        owner = self.read_owner()
        if owner is None or owner_alive(owner):
            return False
        breaker = self.path.parent / ".lock-break"
        try:
            breaker.mkdir()
        except FileExistsError:
            return False
        except OSError as exc:
            raise Unverifiable(f"could not create {breaker} to break the stale lock of dead owner {owner} ({exc}); "
                               f"the lock was not taken, nothing else was changed, and if {breaker} exists now, "
                               "remove it once no planloop process runs; run the command again") from exc
        try:
            again = self.read_owner()
            if again is None or again["nonce"] != owner["nonce"]:
                return False
            crash_point("lock_breaking")
            broken = self.path.parent / f".lock-broken-{owner['nonce']}"
            rename(self.path, broken)
            shutil.rmtree(broken, ignore_errors=True)
            sys.stdout.flush()
            print(f"NOTE  broke stale lock of dead owner {owner}", file=sys.stderr)
            return True
        finally:
            try:
                breaker.rmdir()
            except OSError as exc:
                sys.stdout.flush()
                print(f"NOTE  could not remove {breaker} ({exc}); remove it by hand once no planloop process runs, "
                      "until then no stale lock is broken automatically", file=sys.stderr)

    def __exit__(self, kind, *rest):
        owner = self.read_owner()
        if owner is None or owner["nonce"] != self.nonce:
            lost = f"lock {self.path} is no longer ours (its owner.json now reads {owner}): another writer broke " \
                "it, or it was removed or cannot be read; it was not released here"
            if kind is None:
                raise Conflict(f"{self.done}, but {lost}")
            sys.stdout.flush()
            print(f"NOTE  {lost}", file=sys.stderr)
            return False
        dest = self.path.parent / f".lock-released-{self.nonce}"
        try:
            rename(self.path, dest)
        except (Conflict, Unverifiable) as exc:
            if (self.read_owner(dest) or {}).get("nonce") != self.nonce:
                why = f"{exc.__context__ or exc}; if it is still there, a planloop command run after this process " \
                    "has exited breaks it"
                if kind is not None:
                    sys.stdout.flush()
                    print(f"NOTE  could not release lock {self.path} ({why})", file=sys.stderr)
                    return False
                raise Unverifiable(f"{self.done}; the lock {self.path} could not be released ({why})") from exc
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
        return [v for v in self.records(value) if v["metadata"].get("planloop_key") == key]

    @staticmethod
    def records(value) -> list:
        if not isinstance(value, list) or any(not isinstance(v, dict) or not isinstance(v.get("id"), str)
                                              or not isinstance(v.get("metadata") or {}, dict) for v in value):
            raise Unverifiable("bd list did not return a list of issues, each with an id and metadata object")
        return [norm_meta({**v, "metadata": v.get("metadata") or {}}) for v in value]

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
        return self.records(value)


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
        Lock.peers = (self.dir / ".lock", self.state / ".lock-bundle")
        self.isolated = Path(os.environ.get("PLANLOOP_ISOLATED", "~/.local/state/planloop-isolated")).expanduser().resolve()
        for what, path in (("the repository", self.repo), ("the state directory (PLANLOOP_STATE)", self.state),
                           ("the directory of private snapshot copies (PLANLOOP_ISOLATED)", self.isolated)):
            if not text_path(str(path)):
                raise Unverifiable(f"{what} is {str(path)!a}, a path that is not UTF-8, which planloop's records "
                                   "cannot hold; nothing was read or changed: use a UTF-8 path")
        self.beads = Beads(self.repo)
        self.policy_cache = None

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
        if not probe(path):
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
        return malformed("run", bead, RUN_META)

    def findings(self) -> dict:
        out = {}
        run_bead = self.run_bead()
        for child in self.beads.children(run_bead["id"]):
            meta = child.get("metadata") or {}
            if meta.get("planloop_kind") != "finding" or meta.get("planloop_run") != self.id:
                continue
            malformed("finding", child, FINDING_META)
            fid = meta["planloop_finding"]
            if fid in out:
                raise Conflict(f"two beads carry finding {fid}: {out[fid]['id']}, {child['id']}")
            out[fid] = child
        return out


def malformed(kind: str, bead: dict, patterns: dict) -> dict:
    meta = bead["metadata"]
    for key, pattern in patterns.items():
        if not re.fullmatch(pattern, meta.get(key) or ""):
            raise Fail(f"{kind} bead {bead['id']} holds malformed planloop metadata ({key}={meta.get(key)!r}); "
                       "repair it with bd, then run the command again")
    return bead


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


def plan_parts(text: str) -> dict:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out, current, fence = {PREAMBLE: [1, 0, []]}, PREAMBLE, False
    for number, line in enumerate(lines, 1):
        if line.startswith("```") or line.startswith("~~~"):
            fence = not fence
        if not fence and (line.startswith("## ") or line.startswith("### ")):
            current = line.rstrip()
            out[current] = [number, number, []]
            continue
        if number == 1 and TITLE.match(line):
            line = re.sub(r" \(revision \d+, \d{4}-\d{2}-\d{2}\)$", "", line)
        out[current][1] = number
        out[current][2].append((number, line))
    return out


def unmatched(lines: list, others: list) -> list:
    pool = {}
    for _, line in others:
        pool[line] = pool.get(line, 0) + 1
    out = []
    for number, line in lines:
        if pool.get(line):
            pool[line] -= 1
        elif line.strip():
            out.append((number, line))
    return out


def lost_by_section(prev_text: str, new_text: str) -> dict:
    old, new = plan_parts(prev_text), plan_parts(new_text)
    out = {}
    for key, part in old.items():
        lost = unmatched(part[2], new[key][2]) if key in new else None
        if key not in EXEMPT and (lost is None or lost):
            out[key] = lost
    return out


def common_length(a: list, b: list) -> int:
    where, tails = {}, []
    for j, line in enumerate(b):
        where.setdefault(line, []).append(j)
    for line in a:
        for j in reversed(where.get(line, ())):
            k = bisect.bisect_left(tails, j)
            tails[k:k + 1] = [j]
    return len(tails)


def meaning_units(before_text: str, after_text: str) -> list:
    old, new = plan_parts(before_text), plan_parts(after_text)
    a_keys = [k for k in old if k not in EXEMPT and k != PREAMBLE]
    b_keys = [k for k in new if k not in EXEMPT and k != PREAMBLE]
    blocks = difflib.SequenceMatcher(None, a_keys, b_keys, autojunk=False).get_matching_blocks()
    placed = {a_keys[m.a + i] for m in blocks for i in range(m.size)}
    units = []
    for key in [PREAMBLE] + a_keys + [k for k in b_keys if k not in old]:
        a, b = old.get(key), new.get(key)
        lost, added = (unmatched(a[2], b[2]), unmatched(b[2], a[2])) if a and b else ([], [])
        if a is None or b is None:
            labels = ["new" if a is None else "removed"]
        else:
            before, after = [l for _, l in a[2] if l.strip()], [l for _, l in b[2] if l.strip()]
            same = common_length(before, after) == len(before) - len(lost)
            labels = (["lost"] if lost else []) + (["added"] if added else []) + ([] if same else ["order changed"]) + \
                ([] if key == PREAMBLE or key in placed else ["moved"])
        units.append({"unit": key, "before": a[:2] if a else None, "after": b[:2] if b else None, "labels": labels,
                      "lost": [n for n, _ in lost], "added": [n for n, _ in added]})
    return units


def unit_names(units: list) -> list:
    changed = [u for u in units if u["labels"]]
    return [u["unit"] for u in sorted((u for u in changed if u["after"]), key=lambda u: u["after"][0])] + \
        [u["unit"] for u in changed if not u["after"]]


def numbers(values) -> str:
    runs = []
    for v in sorted(values):
        if runs and v == runs[-1][1] + 1:
            runs[-1][1] = v
        else:
            runs.append([v, v])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def meaning_index(s: int, units: list) -> str:
    out = [f"Mechanical index: where the text of revision {s} differs from revision {s - 1}. It never shows that "
           "meaning survived; unchanged lines can change meaning in a changed context.", ""]
    for u in units:
        spans = [f"{name} " + (f"lines {numbers(range(r[0], r[1] + 1))}" if r and r[1] >= r[0] else "none")
                 for name, r in (("before.md", u["before"]), ("after.md", u["after"]))]
        words = {"lost": f"lost: before.md lines {numbers(u['lost'])}", "removed": f"removed in revision {s}",
                 "added": f"added: after.md lines {numbers(u['added'])}", "new": f"added in revision {s}"}
        out += [f"=== {u['unit']}", "; ".join(spans),
                "changed: " + "; ".join(words.get(l, l) for l in u["labels"]) if u["labels"] else "unchanged", ""]
    return "\n".join(out)


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
    answers, removed, shrink, preserved = {}, [], [], []
    for line in log:
        if (m := ANSWER.match(line)):
            if m.group(2) in answers:
                raise Fail(f"change log answers {m.group(2)} twice")
            answers[m.group(2)] = m.group(1)
        elif (m := REMOVED.match(line)):
            removed.append(m.group(1).strip())
        elif (m := SHRINK.match(line)):
            shrink.append(m.group(1).strip())
        elif (m := PRESERVED.match(line)):
            preserved.append(m.group(1).strip())
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
            "shrink": shrink, "preserved": preserved, "residual_risks": rr,
            "section_lines": {h: b for h, b in secs.items()}}


def disposition(entries: list, item: str):
    for entry in entries:
        if entry.startswith(item + ":"):
            return entry[len(item) + 1:].strip()
    return None


def extract_handback(transcript: Path) -> tuple[str, dict]:
    meta_path = transcript.with_name(transcript.name[:-len(".jsonl")] + ".meta.json") \
        if transcript.name.endswith(".jsonl") else None
    if meta_path is None or not probe(meta_path):
        raise Unverifiable(f"no agent meta file beside {transcript}; completion cannot be verified")
    meta = load(meta_path, "agent meta")
    if not isinstance(meta, dict):
        raise Fail("agent meta is not an object")
    if meta.get("finished") is not True:
        raise Fail("agent meta does not record a finished run")
    if meta.get("agentType") != "Plan":
        raise Fail(f"the planner must be the read-only Plan agent, not {meta.get('agentType')!r}")
    rows = []
    for number, line in enumerate(present(transcript, "transcript", text=True).splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise Unverifiable(f"transcript line {number} is not JSON") from exc
    unrecognised = "transcript format not recognised: "
    handbacks, results = [], {}
    rows = [row for row in rows if isinstance(row, dict)]
    for row in rows:
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            mine = row.get("type") == "assistant" and block.get("type") == "tool_use" \
                and block.get("name") == "SubagentHandback"
            result = row.get("type") == "user" and block.get("type") == "tool_result"
            if (mine or result) and not isinstance(block.get("id" if mine else "tool_use_id"), str):
                raise Unverifiable(unrecognised + "a SubagentHandback call or tool_result has an id that is not a "
                                   "string")
            if mine:
                handbacks.append(block)
            if result:
                results[block["tool_use_id"]] = block
    if handbacks:
        last = handbacks[-1]
        result = results.get(last["id"])
        text = json.dumps(result.get("content")) if result else ""
        if not result or result.get("is_error") or '\\"success\\":true' not in text:
            raise Fail("the agent's final handback was not acknowledged as delivered")
        message = last.get("input").get("message") if isinstance(last.get("input"), dict) else None
        if not isinstance(message, str):
            raise Unverifiable("handback input has no message string")
        return message, {"kind": "SubagentHandback", "tool_use_id": last.get("id"), "meta_finished": True,
                         "agent_type": meta.get("agentType"), "model": meta.get("model")}
    finals = [r["message"] for r in rows if r.get("type") == "assistant" and isinstance(r.get("message"), dict)
              and r["message"].get("stop_reason") == "end_turn"]
    if not finals:
        raise Unverifiable(unrecognised + "no handback call and no end_turn message")
    content = finals[-1].get("content")
    if not isinstance(content, list) or any(not isinstance(b, dict) or b.get("type") == "text"
                                            and not isinstance(b.get("text", ""), str) for b in content):
        raise Unverifiable(unrecognised + "the last end_turn message's content is not a list of text blocks")
    texts = [b.get("text", "") for b in content if b.get("type") == "text"]
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
    old = run.config() if probe(path) else {"reviewer_model": DEFAULT_REVIEWER_MODEL, "gate_model": DEFAULT_GATE_MODEL}
    config = {"schema": "planloop-run/1", "run_id": run.id, "bead": run.bead,
              "reviewer_model": args.reviewer_model or old["reviewer_model"],
              "gate_model": args.gate_model or old["gate_model"], "model_changes": [],
              "policy": POLICY, "created_at": iso(now())}
    if probe(path):
        fixed = ("created_at", "model_changes")
        if {k: v for k, v in old.items() if k not in fixed} != {k: v for k, v in config.items() if k not in fixed}:
            raise Fail("run.json exists with different settings")
    else:
        save(path, canon(config), "the run was not created, and nothing else was changed")
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


def check_content(run: Run, plan: str, revision: int, prev: int | None, prev_bytes: bytes | None = None,
                  threshold: int = SIZE_THRESHOLD_BYTES) -> dict:
    facts = analyse_plan(plan, run, revision)
    findings = run.findings()
    run_meta = meta_of(run.run_bead())
    problems, lost_lines, lost_items, preamble_lost, prev_text = [], {}, {}, [], ""
    live = {r for r in facts["answers"] if r in findings
            and meta_of(findings[r]).get("planloop_state") in ("open", "reopened")}
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
            prev_text = prev_bytes.decode("utf-8") if prev_bytes is not None else \
                read_file(run.rev_dir(prev) / "plan.md", text=True)
        except FileNotFoundError as exc:
            raise Conflict(f"revision {prev}'s plan.md vanished while reading it (a publication or recovery in "
                           "progress?); retry") from exc
        old = analyse_plan(prev_text, run, prev)
        for item in old["sections"] + old["ids"]:
            if item not in facts["sections"] + facts["ids"] and disposition(facts["removed"], item) is None:
                problems.append(f"{item!r} was in revision {prev} and has no REMOVED disposition")
        lost_items = lost_by_section(prev_text, plan)
        for heading, lost in lost_items.items():
            if heading == PREAMBLE:
                preamble_lost = [line for _, line in lost]
            elif lost is not None and disposition(facts["shrink"], heading) is None:
                lost_lines[heading] = [line for _, line in lost]
                problems.append(f"{heading!r} lost {len(lost)} line(s) of revision {prev} (deleted, edited in "
                                f"place, merged or rewrapped) with no 'SHRINK {heading}:' disposition")
    shrink_only = bool(prev) and not live and bool(lost_items)
    if shrink_only:
        kept = [i for i in old["ids"] if i in facts["ids"]]
        missing = [i for i in kept if disposition(facts["preserved"], i) is None]
        short = [i for i in kept if i not in missing and len(disposition(facts["preserved"], i)) < 20]
        if missing or short:
            problems.append(f"this is a shrink-only revision (it answers no open or reopened finding and loses text "
                            f"of revision {prev}), so every id inventoried in both revisions needs a change-log line "
                            "'PRESERVED <ID>: <where it is stated now, and what wording changed>' of 20+ characters: "
                            + "; ".join([f"missing {missing}"] * bool(missing) + [f"too short {short}"] * bool(short)))
    cut = {"shrink_only": shrink_only, "lost_lines": sum(len(v) for v in lost_items.values() if v),
           "removed_sections": sum(v is None for v in lost_items.values()), "threshold_bytes": threshold,
           "live_answers": sorted(live)}
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
        redesigned = sorted(r for r, k in facts["answers"].items() if k == "REDESIGN" and r in live)
        if redesigned:
            fable_reasons.append(f"the change log answers open or reopened finding(s) {redesigned} with REDESIGN")
        leftover = sorted(r for r, k in facts["answers"].items() if r in findings and r not in live and
                          k == "REDESIGN")
    return {"facts": facts, "problems": problems, "lost_lines": lost_lines, "run_meta": run_meta,
            "fable_reasons": fable_reasons, "leftover": leftover, "cut": cut, "live": sorted(live),
            "preamble_lost": preamble_lost, "size": len(plan.encode("utf-8")),
            "prev_size": len(prev_text.encode("utf-8")) if prev else None}


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
    pol = policy_range(run)
    if args.check:
        return check_handback(run, head, args, pol)
    expected = (head[0] if head else 0) + 1
    if args.revision != expected:
        raise Fail(f"revision {args.revision} is not HEAD+1 ({expected})")
    staging = run.staging(args.revision, args.nonce)
    if probe(staging):
        raise Fail(f"{staging} already exists" + ("" if probe(staging / "handback.json") else
                   ", without handback.json: a handback with this nonce was killed while staging it (or is staging it "
                   "now); once no planloop command runs, remove it, then run the command again"))
    transcript = Path(args.transcript).resolve()
    message, completion = extract_handback(transcript)
    draft = None
    if args.draft:
        draft = Path(args.draft).resolve()
        if args.nonce not in draft.name:
            raise Fail(f"draft file {draft.name} is not named with this request's nonce {args.nonce}")
        data = present(draft, "draft file")
        digest = sha(data)
        if digest not in message:
            raise Fail(f"the agent's final message does not name the draft's sha256 {digest}; the draft is not "
                       "the planner's handback")
        try:
            message = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Fail(f"the draft file is not valid UTF-8 ({exc})") from exc
        completion = {**completion, "kind": completion["kind"] + "+draft-file"}
    try:
        message.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise Fail("the planner's handback holds an unpaired surrogate escape (\\ud800 to \\udfff alone), so the "
                   "plan is not valid text; nothing was written: send it back to the planner") from exc
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
    prev = head[0] if head else None
    checked = check_content(run, plan, args.revision, prev, pol["plans"].get(prev or 0), pol["threshold"])
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
    report = handback_report(run, pol, checked, args.revision, prev)
    data = plan.encode("utf-8")
    record = {"schema": "planloop-handback/1", "run_id": run.id, "revision": args.revision, "nonce": args.nonce,
              "source": {"path": str(transcript), "sha256": sha(present(transcript, "transcript"))},
              "completion": completion, "draft": {"path": str(draft), "sha256": digest} if draft else None,
              "plan_sha256": sha(data), "answers": facts["answers"], "removed": facts["removed"],
              "shrink": facts["shrink"], "residual_risks": facts["residual_risks"], "cut": checked["cut"],
              "preserved": facts["preserved"],
              "note": "byte equality with the source proves faithful transfer, not substantive completeness"}
    made = False
    try:
        staging.mkdir(parents=True)
        made = True
        (staging / "plan.md").write_bytes(data)
        (staging / "handback.json").write_bytes(canon(record))
    except BaseException as exc:
        if isinstance(exc, FileExistsError):
            raise Fail(f"{staging} already exists: another handback with this nonce staged it, or is staging it, "
                       "while this one ran; this one staged nothing and left it alone") from exc
        why = f"could not stage revision {args.revision} in {staging} ({str(exc) or type(exc).__name__})"
        try:
            if made:
                shutil.rmtree(staging)
        except OSError as err:
            raise Unverifiable(f"{why}, and could not remove it ({err}): remove {staging} by hand, then run the "
                               "command again") from exc
        if not isinstance(exc, OSError):
            raise
        raise Unverifiable(f"{why}; nothing was staged: run the command again once it can be written") from exc
    print(f"staged {staging}: plan {sha(data)}")
    for line in report:
        print(line)
    return 0


def unfinished_intents(run: Run) -> list:
    return [path.name for path in listing(intents_dir(run), "*.json") if load_intent(path)["state"] != "verified"]


def check_handback(run: Run, head, args, pol: dict) -> int:
    top = head[0] if head else 0
    revision = args.revision if args.revision is not None else top + 1
    if not 1 <= revision <= top + 1:
        raise Fail(f"--check --revision must be between 1 and HEAD+1 ({top + 1})")
    prev = revision - 1 if revision > 1 else None
    if prev and not probe(run.rev_dir(prev) / "plan.md"):
        raise Fail(f"revision {prev} has no plan.md to compare against")
    try:
        text = sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Fail(f"the draft on stdin is not valid UTF-8 ({exc})") from exc
    try:
        plan = plan_between_markers(text)
        checked = check_content(run, plan, revision, prev, pol["plans"].get(prev or 0), pol["threshold"])
    except Fail as exc:
        print(f"check failed: handback would refuse this plan:\n  {exc}")
        return 1
    if revision <= top:
        print(f"NOTE  revision {revision} is already published; comparing with revision {prev}, but finding "
              "answers are checked against the run's current findings")
    unfinished = unfinished_intents(run)
    if unfinished:
        print(f"NOTE  unfinished Beads intents {unfinished}: the real handback refuses until they are replayed")
    for line in handback_report(run, pol, checked, revision, prev, bool(unfinished)):
        print(line)
    track = checked["run_meta"].get("planloop_track")
    reasons = checked["fable_reasons"]
    if track == "escalated" and reasons:
        override = " Opus allowed by Mike's recorded override." \
            if checked["run_meta"].get("planloop_planner_override") == "opus" else ""
        print("planner policy: this content needs a Fable planner (" + "; ".join(reasons) + ")." + override)
    elif track == "escalated":
        print("planner policy: Fable or Opus may hand this content back ("
              + ("a shrink-only revision" if checked["cut"]["shrink_only"] else "a FIX revision") + ")")
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
    for dirpath, dirnames, filenames in walk(root):
        dirnames.sort()
        for name in sorted(filenames + [d for d in dirnames if probe(Path(dirpath) / d, "is_symlink")]):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if probe(path, "is_symlink"):
                lines.append(f"L {sha(present(path, str(path), link=True))} {rel}")
            elif probe(path, "is_file"):
                lines.append(f"F {sha_file(path)} {rel}")
            elif not os.path.lexists(path):
                continue
            else:
                raise Unreadable(str(path), OSError(errno.EINVAL, "not a regular file or symbolic link when hashed"),
                                 Unreadable.SPECIAL)
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
    if not on_disk(root, follow=True):
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
    if probe(path, "is_symlink"):
        return "symlink:" + sha(present(path, str(path), link=True))
    if probe(path, "is_file"):
        return sha_file(path)
    if probe(path):
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
                   "output_sha256": "hex", "attempts": "list", "validity": "dict"},
          f"evidence {record.get('id') if isinstance(record, dict) else '?'}")
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
    if not probe(output, "is_file"):
        problems.append(f"output {record['output']} missing")
    else:
        data = read_file(output)
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

    def unbundled():
        head, rev_dir = run.head(), run.rev_dir(args.revision)
        at = f"HEAD is revision {head[0] if head else 0}"
        if head and head[0] >= args.revision:
            raise Fail(f"revision {args.revision} is already published ({at}); nothing was changed")
        if probe(rev_dir):
            raise Fail(f"{rev_dir.name} exists and {at}: a publication of revision {args.revision} was interrupted; "
                       f"nothing was changed: run `publish --run {run.id} --recover`, which completes it or moves it "
                       "aside to be re-staged")
        if not probe(staging / "handback.json"):
            raise Fail(f"{staging.name} is gone or was never staged ({at}); nothing was changed")
        return head
    unbundled()
    handback = shape(load(staging / "handback.json", "handback.json"), {"plan_sha256": "hex"}, "handback.json",
                     exact=False)
    plan_bytes = present(staging / "plan.md", "staged plan.md")
    if sha(plan_bytes) != handback["plan_sha256"]:
        raise Fail("staged plan.md differs from the handback record")
    if "cut" not in handback:
        raise Fail(STAGED_BEFORE.format(args.revision))
    pol, st = policy_now(run)
    why = cut_problem(run, pol, args.revision, plan_bytes, handback)
    if why:
        raise Fail(CUT_BAD.format(args.revision, why))
    meanings = []
    for s in sorted(set((st["unjudged"] if st else []) + ([args.revision] if handback["cut"]["shrink_only"] else []))):
        before, after = pol["plans"][s - 1], plan_bytes if s == args.revision else pol["plans"][s]
        units = meaning_units(before.decode("utf-8"), after.decode("utf-8"))
        meanings.append((s, before, after, meaning_index(s, units).encode("utf-8"), unit_names(units)))
    with Lock(run.state, ".lock-bundle"):
        head = unbundled()
        if probe(staging / "bundle"):
            raise Fail("staging already has a bundle" + (" and revision.json is in place: publish it"
                       if probe(staging / "revision.json") else
                       f", but no revision.json: a bundle was killed before it finished; remove {staging / 'bundle'}, "
                       "then run the command again"))
        for leftover in listing(staging, ".bundle-tmp-*"):
            shutil.rmtree(leftover, ignore_errors=True)
        for leftover in listing(staging, ".revision.json.tmp-*"):
            with contextlib.suppress(OSError):
                leftover.unlink()
        inputs = shape(load(Path(args.inputs), "inputs"), {"schema": {"planloop-inputs/1"}, "brief": "str",
                                                           "repo_files": "list", "dir_inventories": "list",
                                                           "beads": "list", "obligations": "list", "evidence": "list",
                                                           "discovery": "str"}, "inputs")
        repo = run.repo
        commit = git(repo, "rev-parse", "HEAD").decode().strip()
        bundle = staging / "bundle"
        items = [{"type": "plan", "sha256": sha(plan_bytes)}]
        policy_files = sorted([Path(__file__).resolve(), Path(__file__).resolve().parent.parent / "SKILL.md"])
        items.append({"type": "policy", "policy": POLICY,
                      "files": {p.name: sha_file(p) for p in policy_files if p.exists()}})
        brief_bytes = present(repo / safe_rel(inputs["brief"], "brief"), f"brief {inputs['brief']}")
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
            safe_rel(entry["id"], "inputs.beads.id")
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
                try:
                    source = present(repo / entry["source"], entry["source"]).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise Fail(f"obligation {entry['id']}: {entry['source']} is not UTF-8") from exc
                if entry["text"] not in source:
                    raise Fail(f"obligation {entry['id']}: text not found verbatim in {entry['source']}")
            sources.add(entry["source"])
            obligations.append(entry)
        ob_ids = [o["id"] for o in obligations]
        if len(set(ob_ids)) != len(ob_ids) or set(ob_ids) != plan_obligations:
            raise Fail(f"obligation rows {sorted(ob_ids)} must match the plan's OB ids {sorted(plan_obligations)} one "
                       "to one")
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
        claims = [(Path(f"{r['id']}.json").parts, False, f"{r['id']}'s record {r['id']}.json") for _, r in evidence] + \
            [(Path(r["output"]).parts, True, f"{r['id']}'s output {r['output']}") for _, r in evidence]
        for i, (a, out_a, x) in enumerate(claims):
            for b, out_b, y in claims[i + 1:]:
                if a[:len(b)] == b[:len(a)] and not (a == b and out_a and out_b):
                    raise Fail(f"evidence frozen paths collide: {x} and {y} (both under frozen/evidence/); rename one")
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
        try:
            bundle.mkdir()
            done = build_bundle(run, args, config, staging, final_bundle, bundle, repo, head, commit, plan_bytes,
                                brief_bytes, obligations, discovery, findings, bead_copies, evidence, items, changes,
                                overlay, meanings)
        except BaseException as exc:
            shutil.rmtree(bundle, ignore_errors=True)
            if getattr(exc, "bundled", False):
                args.interrupted = f"revision {args.revision}'s bundle is complete and its revision.json is in " \
                    "place: publish it"
            if getattr(exc, "bundled", False) or not isinstance(exc, OSError):
                raise
            raise Unverifiable(f"could not read or write {exc.filename or bundle} ({exc}); nothing was published: run "
                               "the command again once that path can be read and written") from exc
        print(done)
    return 0


def build_bundle(run, args, config, staging, final_bundle, bundle, repo, head, commit, plan_bytes, brief_bytes,
                 obligations, discovery, findings, bead_copies, evidence, items, changes, overlay, meanings) -> str:
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
    for s, before, after, index, units in meanings:
        dest = frozen / f"meaning-r{s}"
        dest.mkdir()
        for name, data in (("before.md", before), ("after.md", after), ("index.md", index)):
            (dest / name).write_bytes(data)
        items.append({"type": "meaning_obligation", "revision": s, "before_sha256": sha(before),
                      "after_sha256": sha(after), "index_sha256": sha(index), "units": units, "revalidate": False})
    snap = run.snapshot(args.revision, args.nonce)
    remove_tree(snap)
    snap.mkdir(parents=True)
    try:
        fill_snapshot(repo, commit, snap, bundle, overlay, frozen := bundle / "frozen")
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
            raise Fail(f"the repository changed while the bundle was built (HEAD moved or {mismatches[:5]} differ "
                       "between the snapshot and the recorded inputs); rebuild the bundle")
        return finish_bundle(run, args, config, staging, final_bundle, bundle, head, commit, plan_bytes, items,
                             overlay, snap, tree_hash(snap))
    except BaseException as exc:
        if not getattr(exc, "bundled", False):
            with contextlib.suppress(OSError):
                remove_tree(snap)
        raise


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
                  snapshot_hash) -> str:
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
    rename(bundle, final_bundle, then=f"if {final_bundle} exists now, remove it (no revision.json was written for it); "
           "then run the command again")
    data = canon(revision)
    try:
        write_atomic(staging / "revision.json", data)
    except BaseException as exc:
        with contextlib.suppress(OSError):
            exc.bundled = (staging / "revision.json").read_bytes() == data
        if getattr(exc, "bundled", False):
            raise
        try:
            shutil.rmtree(final_bundle)
        except OSError as err:
            raise Unverifiable(f"could not write {staging / 'revision.json'} ({str(exc) or type(exc).__name__}), and "
                               f"could not remove the bundle it was for, {final_bundle} ({err}); nothing was "
                               f"published: remove {final_bundle} by hand, then run the command again") from exc
        raise
    return f"bundle {sha(manifest_bytes)}; snapshot {snap} tree {snapshot_hash}"


FROZEN = {"plan": "plan.md", "brief": "brief.md", "obligations": "obligations.json", "discovery": "discovery.json",
          "findings_snapshot": "findings.json"}


def frozen_copies(item: dict) -> list:
    kind = item["type"]
    if kind in FROZEN:
        return [(FROZEN[kind], item.get("sha256"))]
    if kind == "bead":
        return [(f"beads/{item.get('id')}.json", item.get("sha256"))]
    if kind == "evidence":
        return [(f"evidence/{item.get('id')}.json", item.get("record_sha256"))]
    if kind == "meaning_obligation":
        return [(f"meaning-r{item.get('revision')}/{k}.md", item.get(f"{k}_sha256"))
                for k in ("before", "after", "index")]
    return []


def frozen_copy(rev_dir: Path, n: int, rel) -> bytes:
    try:
        safe_rel(rel, "frozen path")
    except Fail as exc:
        raise Fail(f"revision {n} manifest names an unsafe frozen path {rel!r}") from exc
    return present(rev_dir / "bundle" / "frozen" / rel, f"revision {n} frozen {rel}")


def verify_revision(run: Run, n: int, rev_dir: Path | None = None, deep: bool = True, files: dict | None = None) -> dict:
    rev_dir = rev_dir or run.rev_dir(n)
    record = present(rev_dir / "revision.json", "revision.json")
    rev = shape(parse(record, "revision.json"),
                {"schema": {"planloop-revision/1"}, "run_id": "str", "revision": "int", "plan_sha256": "hex",
                 "bundle_sha256": "hex", "handback_sha256": "hex", "base": "any", "reviewer_model": "str?",
                 "created_at": "str"}, f"revision {n}")
    if rev["run_id"] != run.id or rev["revision"] != n:
        raise Fail(f"{rev_dir}/revision.json describes another revision")
    plan, handback = present(rev_dir / "plan.md", f"revision {n} plan.md"), \
        present(rev_dir / "handback.json", f"revision {n} handback.json")
    if sha(plan) != rev["plan_sha256"]:
        raise Fail(f"revision {n} plan.md does not match revision.json")
    if sha(handback) != rev["handback_sha256"]:
        raise Fail(f"revision {n} handback.json does not match")
    what = f"revision {n} bundle manifest"
    manifest_bytes = present(rev_dir / "bundle" / "manifest.json", what)
    if sha(manifest_bytes) != rev["bundle_sha256"]:
        raise Fail(f"{what} does not match")
    manifest = parse(manifest_bytes, what)
    for item in shape(manifest, {"items": "list"}, what, exact=False)["items"]:
        shape(item, {"type": "str"}, f"{what} item", exact=False)
        if item["type"] == "overlay":
            for entry in shape(item, {"entries": "list"}, f"{what} overlay item", exact=False)["entries"]:
                shape(entry, {"path": "str", "sha256": "any"}, f"{what} overlay entry", exact=False)
        if item["type"] == "snapshot":
            shape(item, {"path": "str", "tree_sha256": "any"}, f"{what} snapshot item", exact=False)
    if [i.get("sha256") for i in manifest["items"] if i.get("type") == "plan"] != [rev["plan_sha256"]]:
        raise Fail(f"revision {n} bundle manifest names another plan")
    if n > 1:
        base = rev["base"]
        if not isinstance(base, dict) or base.get("revision") != n - 1 or \
                sha(present(run.rev_dir(n - 1) / "revision.json", f"revision {n - 1} revision.json")) != \
                base.get("revision_sha256"):
            raise Fail(f"revision {n} does not chain to revision {n - 1}")
    elif rev["base"] is not None:
        raise Fail("revision 1 names a base")
    for item in manifest["items"]:
        if item["type"] == "overlay":
            for entry in item["entries"]:
                if entry["sha256"] is not None:
                    path = rev_dir / "bundle" / "overlay" / entry["path"]
                    copy = f"revision {n} overlay copy of {entry['path']}"
                    got = "symlink:" + sha(present(path, copy, link=True)) if probe(path, "is_symlink") else \
                        sha(present(path, copy))
                    if got != entry["sha256"]:
                        raise Fail(f"revision {n} overlay copy of {entry['path']} changed")
        if item["type"] == "snapshot" and deep:
            snap = Path(item["path"])
            if not probe(snap, "is_dir") or tree_hash(snap) != item["tree_sha256"]:
                raise Fail(f"revision {n} snapshot {snap} is missing or changed")
        for rel, digest in frozen_copies(item):
            data = frozen_copy(rev_dir, n, rel)
            if sha(data) != digest:
                raise Fail(f"revision {n} frozen {rel} changed")
            if item["type"] == "evidence":
                ev = shape(parse(data, f"revision {n} frozen {rel}"), {"output": "str", "output_sha256": "hex"},
                           f"revision {n} frozen {rel}", exact=False)
                out = f"evidence/{ev['output']}"
                if sha(frozen_copy(rev_dir, n, out)) != ev["output_sha256"]:
                    raise Fail(f"revision {n} frozen {out} changed")
    rev["manifest"] = manifest
    if files is not None:
        files.update(plan=plan, handback=handback, revision=record, manifest=manifest_bytes)
    return rev


UNCHAINED = "the run's published records do not verify from HEAD; inspect by hand"
UNBOUND = "a stored receipt's binding to the authenticated revisions fails; inspect that receipt"
STAGED_BEFORE = ("revision {} was staged by planloop before the size policy; re-run handback for it (delete the "
                 "unreferenced staging directory first)")
CUT_BAD = ("revision {}'s staged handback.json cut does not hold: {}; re-run handback for it (delete the unreferenced "
           "staging directory first)")


def policy_range(run: Run) -> dict:
    head = run.head()
    if head is not None:
        try:
            pointed = sha_file(run.rev_dir(head[0]) / "revision.json") == head[1]
        except OSError:
            pointed = False
        if not pointed:
            raise Unverifiable(f"HEAD points at a revision whose record differs; {UNCHAINED}")
    if run.policy_cache and run.policy_cache[0] == head:
        return run.policy_cache[1]
    pol = {"head": head[0] if head else 0, "revs": {}, "rev_sha": {}, "plans": {}, "handbacks": {}, "first": None,
           "threshold": SIZE_THRESHOLD_BYTES}
    if head is None:
        run.policy_cache = (head, pol)
        return pol
    n, cuts = head[0], []
    try:
        for n in range(head[0], 0, -1):
            files = {}
            pol["revs"][n] = verify_revision(run, n, deep=False, files=files)
            pol["plans"][n] = files["plan"]
            pol["handbacks"][n] = loads(files["handback"].decode("utf-8"), f"revision {n} handback.json")
            pol["rev_sha"][n] = head[1] if n == head[0] else pol["revs"][n + 1]["base"]["revision_sha256"]
        cuts = [m for m in sorted(pol["handbacks"]) if "cut" in pol["handbacks"][m]]
        for n in cuts:
            shape(pol["handbacks"][n]["cut"], CUT_SPEC, f"revision {n} handback.json cut")
    except (Fail, OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise Unverifiable(f"revision {n}: {exc}; {UNCHAINED}") from exc
    if cuts:
        pol["first"], pol["threshold"] = cuts[0], pol["handbacks"][cuts[0]]["cut"]["threshold_bytes"]
    run.policy_cache = (head, pol)
    return pol


def walked(pol: dict, n: int, rev: dict) -> None:
    keys = ("plan_sha256", "bundle_sha256", "base")
    if pol["head"] != n or {k: rev[k] for k in keys} != {k: (pol["revs"].get(n) or {}).get(k) for k in keys}:
        raise Unverifiable(f"HEAD points at a revision whose record differs; {UNCHAINED}")


def cut_problem(run: Run, pol: dict, n: int, plan: bytes, handback: dict,
                live_states=("open", "reopened")) -> str | None:
    try:
        cut = shape(handback.get("cut"), CUT_SPEC, "cut")
        live = cut["live_answers"]
        if not all(isinstance(r, str) and FINDING_ID.match(r) for r in live) or live != sorted(set(live)):
            raise Fail("cut.live_answers: not a sorted list of distinct finding ids")
        try:
            findings = run.findings() if live else {}
        except (Fail, UnicodeDecodeError, AttributeError, KeyError, TypeError) as exc:
            raise Unverifiable(f"Beads could not be read to check revision {n}'s cut: {exc}") from exc
        for r in live:
            if r not in findings:
                raise Fail(f"cut.live_answers names {r}, which is not a finding of this run")
            if live_states and meta_of(findings[r]).get("planloop_state") not in live_states:
                raise Fail(f"cut.live_answers names {r}, which is not an open or reopened finding of this run")
        if n > 1 and pol["head"] != n - 1:
            raise Fail(f"it was classified against revision {n - 1}, but HEAD is revision {pol['head']}")
        text = plan.decode("utf-8")
        answers = analyse_plan(text, run, n)["answers"]
        lost = lost_by_section(pol["plans"][n - 1].decode("utf-8"), text) if n > 1 else {}
    except (Fail, UnicodeDecodeError) as exc:
        return str(exc)
    want = {"shrink_only": n > 1 and not live and bool(lost), "lost_lines": sum(len(v) for v in lost.values() if v),
            "removed_sections": sum(v is None for v in lost.values()), "threshold_bytes": pol["threshold"],
            "live_answers": live}
    wrong = [f"cut.{k} is {cut[k]!r}, expected {want[k]!r}" for k in CUT_SPEC if cut[k] != want[k]]
    wrong += [f"cut.live_answers names {r}, which the plan's change log does not answer" for r in live if r not in answers]
    return "; ".join(wrong) or None


def cut_of(pol: dict, n: int) -> dict:
    if "cut" in pol["handbacks"][n]:
        return pol["handbacks"][n]["cut"]
    lost = lost_by_section(pol["plans"][n - 1].decode("utf-8"), pol["plans"][n].decode("utf-8")) if n > 1 else {}
    return {"shrink_only": bool(lost), "lost_lines": sum(len(v) for v in lost.values() if v),
            "removed_sections": sum(v is None for v in lost.values()), "from_text": True}


def cut_warned(cut: dict, size: int, prev_size: int | None) -> bool:
    return prev_size is not None and bool(cut.get("live_answers")) and (prev_size - size) * 100 > CUT_WARN_PERCENT * prev_size


def judgement_problem(pol: dict, path: Path, r: dict) -> str | None:
    n = r.get("revision")
    if not isinstance(n, int) or n not in pol["revs"]:
        return f"it names revision {n!r}, which is not a published revision"
    want = {"revision": n, "revision_sha256": pol["rev_sha"][n], "bundle_sha256": pol["revs"][n]["bundle_sha256"],
            "plan_sha256": pol["revs"][n]["plan_sha256"]}
    try:
        dispatch = load(path / "input" / "dispatch.json", "dispatch.json")
    except Fail as exc:
        return str(exc)
    for record, what in ((r, "the receipt"), (dispatch, "its dispatch.json")):
        if not isinstance(record, dict) or {k: record.get(k) for k in want} != want:
            return f"{what} is not bound to revision {n}'s published record"
    items = {i.get("revision"): i for i in pol["revs"][n]["manifest"]["items"] if i.get("type") == "meaning_obligation"}
    mandate, judged = dispatch.get("meaning_check"), r["meaning_check"]
    if not isinstance(mandate, list) or not isinstance(judged, list) or len(mandate) != len(judged):
        return "its meaning verdicts do not answer its dispatch's mandate"
    keys = ("before_sha256", "after_sha256", "index_sha256", "units")
    for entry, got in zip(mandate, judged):
        s = entry.get("revision") if isinstance(entry, dict) else None
        item = items.get(s) if isinstance(s, int) else None
        if item is None or s not in pol["revs"] or s - 1 not in pol["revs"] or entry.get("previous_revision") != s - 1 \
                or {k: entry.get(k) for k in keys} != {k: item.get(k) for k in keys} \
                or (item["before_sha256"], item["after_sha256"]) != (pol["revs"][s - 1]["plan_sha256"],
                                                                     pol["revs"][s]["plan_sha256"]):
            return f"its dispatch's mandate for revision {s!r} is not the meaning obligation frozen in revision {n}"
        verdicts = got.get("verdicts") if isinstance(got, dict) else None
        if not isinstance(verdicts, dict) or (got.get("revision"), got.get("previous_revision")) != (s, s - 1) \
                or sorted(verdicts) != sorted(item["units"]) \
                or not all(v in ("preserved", "changed") for v in verdicts.values()):
            return f"its verdicts for revision {s} are not one per unit of the mandate"
        if "changed" in verdicts.values() and not r.get("findings"):
            return f"it records a changed unit of revision {s} without a finding"
    return None


def judgements(run: Run, pol: dict) -> dict:
    out = {}
    for c, a, path, r in receipts(run):
        if not r or r["status"] != "counted" or "meaning_check" not in r:
            continue
        why = judgement_problem(pol, path, r)
        if why:
            raise Unbound(f"receipt of call {c} attempt {a}: {why}; {UNBOUND}")
        digest = sha_file(path / "receipt.json")
        for entry in r["meaning_check"]:
            verdicts = list(entry["verdicts"].values())
            out.setdefault(entry["revision"], {"call": c, "attempt": a, "receipt_sha256": digest, "on": r["revision"],
                                               "preserved": verdicts.count("preserved"),
                                               "changed": verdicts.count("changed")})
    return out


def load_size_decision(run: Run, path: Path) -> dict:
    value = shape(load(path, path.name), {"schema": {"planloop-size-decision/1"}, "id": "str", "by": {"Mike"},
                                          "quote": "str", "recorded_at": "str", "recorded_by": "str", "revision": "int",
                                          "plan_sha256": "hex", "ceiling_bytes": "int"}, path.name)
    parse_time(value["recorded_at"])
    if not re.fullmatch(r"S[1-9]\d*", value["id"]) or path.name != f"{value['id']}.json":
        raise Fail(f"size decision {value['id']} must live at decisions/{value['id']}.json")
    return value


def policy_status(run: Run, pol: dict) -> dict:
    g, first, t = pol["head"], pol["first"], pol["threshold"]
    margin, size = t // 10, {n: len(b) for n, b in pol["plans"].items()}
    cuts = {n: cut_of(pol, n) for n in range(first, g + 1)}
    shrinks = [n for n, c in cuts.items() if c["shrink_only"]]
    judged = judgements(run, pol)
    done = [s for s in shrinks if s in judged]
    anchors = [s for s in done if size[s] <= t < size[s - 1]]
    over = [m for m in range(anchors[-1] + 1, g + 1) if size[m] > t + margin] if anchors else []
    renewal = anchors[-1] if anchors and not over else None
    prepolicy = [f"NOTE  revision {n} was published by planloop code that predates the size policy (no cut); "
                 f"classified from its text: {'shrink-only' if c['shrink_only'] else 'not shrink-only'}"
                 for n, c in cuts.items() if c.get("from_text")]
    notes, bad, covering = [], [], []
    for path in sorted(listing(run.dir / "decisions", "[sS]*.json"), key=lambda p: (len(p.stem), p.stem)):
        if not SIZE_DECISION_NAME.match(path.name):
            notes.append(f"NOTE  decisions/{path.name} is not named S<positive integer>.json, so it is not a size "
                         "decision; ignored")
            continue
        try:
            d = load_size_decision(run, path)
        except Fail as exc:
            bad.append((path.name, str(exc)))
            continue
        s, ceiling = d["revision"], d["ceiling_bytes"]
        why = (f"its revision {s} is above the head" if s > g else
               f"revision {s} is not a shrink-only policy revision" if s not in shrinks else
               f"revision {s} has no meaning judgement yet" if s not in judged else
               f"its plan_sha256 is not revision {s}'s" if d["plan_sha256"] != pol["revs"][s]["plan_sha256"] else
               f"its ceiling of {ceiling:,} bytes is below revision {s}'s {size[s]:,}" if ceiling < size[s] else
               f"its ceiling of {ceiling:,} bytes is below revision {g}'s {size[g]:,}" if ceiling < size[g] else None)
        if why:
            notes.append(f"NOTE  size decision {d['id']} gives revision {g} no basis: {why}")
        else:
            covering.append({"id": d["id"], "sha256": sha_file(path)})
    basis = decision = need = None
    if size[g] <= t:
        basis = "under-threshold"
    elif renewal and size[g] <= t + margin:
        basis = f"renewal after shrink r{renewal}"
    elif covering:
        decision = covering[0]
        basis = f"size decision {decision['id']}"
    else:
        s = done[-1] if done else None
        need = (f"revision {g} is {size[g]:,} bytes, over the threshold of {t:,} by {size[g] - t:,}"
                + (f"; the renewal after shrink r{anchors[-1]} lapsed when revision {over[0]} reached "
                   f"{size[over[0]]:,} bytes, over the allowance of {t + margin:,}" if over else "")
                + f"; needed: a judged shrink-only revision within the threshold (growth after it stays eligible up to "
                f"{t + margin:,} bytes) or Mike's size decision decisions/S<n>.json; "
                + (f"a size decision would name revision {s} (plan_sha256 {pol['revs'][s]['plan_sha256']}, "
                   f"{size[s]:,} bytes, {size[s] - size[s - 1]:+,} bytes against revision {s - 1}) with ceiling_bytes "
                   f"of at least {size[g]:,}" if s else "a size decision needs a judged shrink-only revision first"))
    facts = {"size": {"plan_bytes": size[g], "threshold_bytes": t, "margin_bytes": margin, "basis": basis,
                      "size_policy": {"threshold_bytes": t, "from_revision": first}, "decision": decision},
             "meaning_checks": [{"revision": s, **{k: v for k, v in judged[s].items() if k != "on"}} for s in done]}
    return {"sizes": size, "shrinks": shrinks, "judged": judged, "unjudged": [s for s in shrinks if s not in judged],
            "basis": basis, "need": need, "prepolicy": prepolicy, "notes": notes, "bad": bad, "facts": facts}


def policy_now(run: Run):
    pol = policy_range(run)
    return pol, (policy_status(run, pol) if pol["first"] else None)


def size_line(n: int, size: int, refs: list) -> str:
    parts = [f"{size - b:+,} bytes ({(size - b) / b * 100:+.2f}%) vs revision {m}{label}" for m, b, label in refs]
    return f"size: revision {n} is {size:,} bytes (1 kB = 1,000 bytes); " + ("; ".join(parts) or "(first revision)")


def policy_line(t: int, size: int, gate, unjudged: list) -> str:
    many = len(unjudged) > 1
    meaning = (f"revision{'s' if many else ''} {', '.join(map(str, unjudged))} await{'' if many else 's'} judgement, "
               "carried into this revision's reviews") if unjudged else "no shrink awaits judgement"
    over = f"WARN over the threshold by {size - t:,} bytes" if size > t else "within the threshold"
    return (f"size policy: threshold {t:,} bytes, renewal margin {t // 10:,} bytes; {over}; "
            + (f"gate: {gate}; " if gate else "") + f"meaning: {meaning}")


def size_warnings(n: int, size: int, prev_size, t: int, cut: dict) -> list:
    out = [f"WARN  revision {n} is {size:,} bytes, over the size threshold of {t:,} bytes by {size - t:,}; before a "
           "gate it needs a judged shrink-only revision within the threshold or Mike's size decision (SKILL.md)"] \
        if size > t else []
    if cut_warned(cut, size, prev_size):
        out.append(f"WARN  this revision answers findings and is {(prev_size - size) / prev_size * 100:.2f}% smaller "
                   f"than revision {n - 1}; a size cut belongs in its own shrink-only revision, which gets a meaning "
                   "check (SKILL.md)")
    return out


def policy_report(pol: dict, st: dict, warn: bool = False) -> list:
    g, size, t = pol["head"], st["sizes"], pol["threshold"]
    earlier = [s for s in st["shrinks"] if s < g]
    refs = {}
    for m, label in ((g - 1, ""), (1, ""), (earlier[-1] if earlier else 0, ", the latest shrink-only revision")):
        if 1 <= m < g:
            refs[m] = refs.get(m, "") + label
    gate = f"eligible ({st['basis']})" if st["basis"] else f"NOT eligible: {st['need']}"
    lines = [size_line(g, size[g], [(m, size[m], label) for m, label in refs.items()]),
             policy_line(t, size[g], gate, st["unjudged"]), *st["prepolicy"]]
    lines += [f"NOTE  revision {s} has no meaning judgement yet; its comparison is carried into the reviews of "
              f"revision {g}" for s in st["unjudged"] if s < g]
    return lines + (size_warnings(g, size[g], size.get(g - 1), t, cut_of(pol, g)) if warn else [])


def print_policy(run: Run, warn: bool = False, out=None) -> None:
    pol, st = policy_now(run)
    for line in policy_report(pol, st, warn) if st else []:
        print(line, file=out or sys.stdout)


def handback_report(run: Run, pol: dict, checked: dict, revision: int, prev, provisional: bool = False) -> list:
    cut, size, t = checked["cut"], checked["size"], pol["threshold"]
    unjudged = sorted(set((policy_status(run, pol)["unjudged"] if pol["first"] else []) +
                          ([revision] if cut["shrink_only"] else [])))
    lines = [size_line(revision, size, [(prev, checked["prev_size"], "")] if prev else []),
             policy_line(t, size, None, unjudged)]
    note = " (provisional: Beads intents are unfinished)" if provisional else ""
    if cut["shrink_only"]:
        lines += [f"classification: shrink-only revision (answers no open or reopened finding; loses "
                  f"{cut['lost_lines']} line(s) and {cut['removed_sections']} section(s) of revision {prev}){note}",
                  f"this is a shrink-only revision: an independent reviewer judges its meaning against revision {prev} "
                  "in the next counted review round, carried into later revisions until then; nothing this check "
                  "does judges meaning"]
    else:
        why = "first revision" if not prev else f"answers open or reopened finding(s) {checked['live']}" \
            if checked["live"] else f"loses no line of revision {prev}"
        lines.append(f"classification: not shrink-only ({why}){note}")
    lines += size_warnings(revision, size, checked["prev_size"], t, cut)
    if checked["preamble_lost"]:
        lost = checked["preamble_lost"]
        lines.append(f"lines of revision {prev} not found byte-identical in the new '{PREAMBLE}' (the title and the "
                     "lines above the first heading; listed for information, they need no disposition):")
        lines += [f"  - {line[:100]}{'...' if len(line) > 100 else ''}" for line in lost[:20]]
        lines += [f"  +{len(lost) - 20} more"] if len(lost) > 20 else []
    return lines


def cmd_publish(args) -> int:
    run = Run(args.run)
    run.config()
    with contextlib.ExitStack() as locks:
        bundle = Lock(run.state, ".lock-bundle")
        if not args.recover:
            locks.enter_context(bundle)
        elif not bundle._break_stale() and (owner := bundle.read_owner()) is not None:
            sys.stdout.flush()
            print(f"NOTE  {bundle.path} is held by {owner} and publish --recover left it{bundle.advice(owner)}",
                  file=sys.stderr)
        locks.enter_context(Lock(run.dir))
        prepare(run)
        if args.recover:
            print_policy(run)
            return 0
        staging, files = run.staging(args.revision, args.nonce), {}
        head = run.head()
        try:
            staged = staging.exists()
        except OSError as exc:
            raise Unverifiable(held_open(staging, exc)) from exc
        if staged and head and head[0] >= args.revision:
            raise Conflict(f"revision {args.revision} is already published from another staging (HEAD is revision "
                           f"{head[0]}); {staging.name} is a stale staging of it and nothing was published: remove "
                           f"{staging}")
        if staged and not probe(staging / "revision.json"):
            raise Fail(f"revision {args.revision} is not bundled: {staging.name} has no revision.json (no bundle ran "
                       "for it, or one was stopped before it finished); nothing was published: run `bundle --run "
                       f"{run.id} --revision {args.revision} --nonce {args.nonce} --inputs INPUTS.json` (it says what "
                       "to remove if a stopped bundle left one), then publish")
        if not staged:
            if head and head[0] >= args.revision:
                record = run.rev_dir(args.revision) / "handback.json"
                try:
                    done = parse(present(record, str(record)), str(record))
                except (OSError, Unreadable) as exc:
                    exc = exc.error if isinstance(exc, Unreadable) else exc
                    raise Unverifiable(held_open(record, exc)) from exc
                if isinstance(done, dict) and done.get("nonce") == args.nonce:
                    print(f"revision {args.revision} (nonce {args.nonce}) is already published (HEAD is revision "
                          f"{head[0]}); nothing to do")
                    return 0
                raise Fail(f"revision {args.revision} is already published from another staging (HEAD is revision "
                           f"{head[0]}); nothing was published")
            raise Fail(f"{staging.name} does not exist; revision {args.revision} is not published (HEAD is revision "
                       f"{head[0] if head else 0}); re-stage it (a recovery that moved rev-{args.revision:03d} aside "
                       "printed the handback command), then bundle and publish")
        rev = verify_revision(run, args.revision, staging, files=files)
        handback = parse(files["handback"], "handback.json")
        base = rev["base"]
        if (head is None and base is not None) or (head is not None and base != {"revision": head[0],
                                                                                   "revision_sha256": head[1]}):
            raise Conflict(f"staged revision {args.revision} was built on {base}, HEAD is now {head}; rebuild it")
        run_meta = meta_of(run.run_bead())
        if run_meta.get("planloop_track") == "escalated" and args.revision == escalated_revision(run_meta):
            completion = handback.get("completion") or {}
            if completion.get("model") != "fable" and completion.get("planner_basis") != "override":
                raise Fail(f"revision {args.revision} is the run's first escalated revision and its handback came "
                           f"from model {completion.get('model')!r}; re-plan that revision with Fable")
        target = run.rev_dir(args.revision)
        if probe(target):
            raise Conflict(f"{target} already exists (another writer published)")
        if "cut" not in handback:
            raise Fail(STAGED_BEFORE.format(args.revision))
        why = cut_problem(run, policy_range(run), args.revision, files["plan"], handback)
        if why:
            raise Fail(CUT_BAD.format(args.revision, why))
        crash_point("before_rename")
        rev_sha = sha(files["revision"])
        intent = run.dir / f".publishing-{target.name}"
        if probe(intent) and not probe(intent, "is_file"):
            raise Fail(f"{intent} exists and is not a file; remove it by hand, then publish again")
        try:
            write_atomic(intent, canon({"schema": "planloop-publishing/1", "revision": args.revision,
                                        "revision_sha256": rev_sha}))
        except OSError as exc:
            raise Unverifiable(f"could not write {intent} ({exc}); nothing was published, HEAD is unchanged; "
                               "publish again once it can be written") from exc
        crash_point("after_intent")
        rename(staging, target)
        crash_point("after_rename")
        held = {}
        try:
            verify_revision(run, args.revision, target, files=held)
            changed = [name for name, key in (("revision.json", "revision"), ("plan.md", "plan"),
                                              ("handback.json", "handback"), ("bundle/manifest.json", "manifest"))
                       if held[key] != files[key]]
        except NotFile as exc:
            raise Fail(held_open(exc.path, None, target)) from exc
        except Fail as exc:
            changed = [str(exc)]
        except (OSError, Unreadable) as exc:
            exc = exc.error if isinstance(exc, Unreadable) else exc
            raise Unverifiable(f"{target} could not be re-read after the rename ({exc}); HEAD is unchanged and the "
                               "next recovery publishes it only if it is the revision publish verified") from exc
        if changed:
            reason = f"{target} changed between its verification and HEAD ({', '.join(changed)}); HEAD is unchanged"
            dest = run.dir / f".orphan-{target.name}-{uuid.uuid4().hex[:8]}"
            later = "the next recovery moves it aside, or publishes it if it then holds exactly the revision publish " \
                "verified and that revision's cut still holds"
            try:
                rename(target, dest, then=f"if it is still present {later}")
            except Conflict as exc:
                raise Conflict(f"{reason}; {exc}, so it is still present and {later}; "
                               f"{again(run, args, staging, handback)}") from exc
            except Unverifiable as exc:
                raise Conflict(f"{reason}; {exc}; {again(run, args, staging, handback)}") from exc
            discard(intent)
            raise Conflict(f"{reason} and it was moved aside to {dest.name}; {again(run, args, staging, handback)}")
        try:
            write_atomic(run.dir / "HEAD", canon({"schema": "planloop-head/1", "revision": args.revision,
                                                  "revision_sha256": rev_sha}))
        except OSError as exc:
            raise Unverifiable(f"could not write HEAD ({exc}); revision {args.revision} is in place with its "
                               "publishing intent, the next locking command (or `publish --recover`) completes it, "
                               "or moves it aside with a NOTE to re-stage it if it no longer verifies") from exc
        crash_point("after_head")
        if run.head() != (args.revision, rev_sha):
            raise Unverifiable("HEAD did not read back")
        discard(intent)
        print(f"published revision {args.revision} ({rev_sha})")
        size_report(run, warn=True)
    return 0


def size_report(run: Run, warn: bool = False, out=None) -> None:
    try:
        print_policy(run, warn, out)
    except Exception as exc:
        if isinstance(exc, Unverifiable) and not isinstance(exc, (Unbound, Unreadable)):
            print(f"NOTE  the publication of revision {run.head()[0]} is complete; its size report found an "
                  "integrity failure:", file=out or sys.stdout)
            raise
        exc = exc.error if isinstance(exc, Unreadable) else exc
        print(f"WARN  size report unavailable: {type(exc).__name__}: {exc}", file=out or sys.stdout)


def again(run: Run, args, staging: Path, handback: dict) -> str:
    if not staging.exists():
        return f"re-stage it: {restage(run, args.revision, handback)}, then bundle and publish"
    try:
        verify_revision(run, args.revision, staging)
    except (Fail, OSError, Unreadable) as exc:
        exc = exc.error if isinstance(exc, Unreadable) else exc
        return (f"{staging.name} exists but does not verify ({exc}); remove it, then re-stage it: "
                f"{restage(run, args.revision, handback)}, then bundle and publish")
    return f"{staging.name} still verifies; publish it again: publish --run {run.id} --revision {args.revision} " \
        f"--nonce {args.nonce}"


def restage(run: Run, n: int, handback: dict) -> str:
    nonce, source, draft = handback.get("nonce"), handback.get("source"), handback.get("draft")
    nonce = nonce if isinstance(nonce, str) and re.match(r"^[0-9a-f]{8,64}$", nonce) else None
    path = source.get("path") if isinstance(source, dict) else None
    draft = draft.get("path") if isinstance(draft, dict) else None
    return (f"handback --run {run.id} --revision {n} --nonce {nonce or '<a new nonce>'} --transcript "
            f"{shlex.quote(path) if isinstance(path, str) else '<the agent transcript>'}"
            + (f" --draft {shlex.quote(str(draft))}" if draft else ""))


def held_open(path, exc: OSError | None, rev: Path | None = None) -> str:
    path = Path(path)
    lead = "; if it persists," if exc else ", or"
    way_out = f"{lead} move {rev} out of the run directory by hand (it can then be re-staged)" \
        if rev and rev in (path, *path.parents) else f"{lead} move it out of the run directory by hand " \
        "(a revision is then moved aside and can be re-staged)" if path.name.startswith(".publishing-rev-") else ""
    if exc is None:
        return (f"{path} is not a regular file (a directory, FIFO, socket, device or dangling symbolic link), so "
                f"reading it again cannot help; nothing was moved aside or discarded: repair it by hand{way_out}")
    return f"could not read {path} ({exc}); retry once it is no longer held open{way_out}"


def discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"NOTE  could not remove {path.name} ({exc}); "
              f"{'remove it by hand' if path.is_dir() else 'the next recovery removes it'}", file=sys.stderr)


def publishing(run: Run, n: int):
    path = run.dir / f".publishing-rev-{n:03d}"
    try:
        data = present(path, "publishing intent")
    except Fail as exc:
        if os.path.lexists(path):
            raise Fail(held_open(path, None)) from exc
        return None
    except (OSError, Unreadable) as exc:
        exc = exc.error if isinstance(exc, Unreadable) else exc
        raise Unverifiable(held_open(path, exc)) from exc
    try:
        value = parse(data, "publishing intent")
    except Fail:
        return ""
    return value["revision_sha256"] if isinstance(value, dict) and value.get("schema") == "planloop-publishing/1" \
        and value.get("revision") == n and isinstance(value.get("revision_sha256"), str) else ""


def recover(run: Run) -> None:
    policy_range(run)
    head = run.head()
    current = head[0] if head else 0
    for path in listing(run.dir, ".publishing-rev-[0-9][0-9][0-9]"):
        rev_dir = run.dir / path.name.removeprefix(".publishing-")
        try:
            stale = int(path.name[-3:]) <= current or not rev_dir.exists()
        except OSError as exc:
            raise Unverifiable(held_open(rev_dir, exc)) from exc
        if stale:
            discard(path)
    for path in listing(run.dir, "rev-[0-9][0-9][0-9]"):
        n = int(path.name[4:])
        if n <= current:
            continue
        files = {}
        try:
            rev = verify_revision(run, n, files=files)
            chained = rev["base"] == ({"revision": head[0], "revision_sha256": head[1]} if head else None)
        except NotFile as exc:
            intent_path = run.dir / f".publishing-{path.name}"
            try:
                held = n == current + 1 and on_disk(intent_path)
            except OSError as err:
                raise Unverifiable(held_open(intent_path, err, path)) from err
            if held:
                raise Fail(held_open(exc.path, None, path)) from exc
            chained = False
        except Fail:
            chained = False
        except (OSError, Unreadable) as exc:
            exc = exc.error if isinstance(exc, Unreadable) else exc
            raise Unverifiable(held_open(exc.filename or path, exc, path if exc.filename else None)) from exc
        verified = n == current + 1 and chained
        intent = publishing(run, n) if verified else None
        accepted = verified and intent == sha(files["revision"])
        handback = parse(files["handback"], "handback.json") if verified else {}
        why = cut_problem(run, policy_range(run), n, files["plan"], handback, None) \
            if accepted and "cut" in handback else None
        if accepted and "cut" in handback and not why:
            try:
                write_atomic(run.dir / "HEAD", canon({"schema": "planloop-head/1", "revision": n,
                                                      "revision_sha256": sha(files["revision"])}))
            except OSError as exc:
                raise Unverifiable(f"could not write HEAD ({exc}); revision {n} stays in place with its publishing "
                                   "intent, the next locking command (or `publish --recover`) completes it once HEAD "
                                   "can be written, or moves it aside with a NOTE to re-stage it if it no longer "
                                   "verifies") from exc
            print(f"NOTE  recovered interrupted publication of revision {n}", file=sys.stderr)
            head, current = run.head(), n
            if head == (n, sha(files["revision"])):
                discard(run.dir / f".publishing-{path.name}")
            size_report(run, out=sys.stderr)
        else:
            dest = run.dir / f".orphan-{path.name}-{uuid.uuid4().hex[:8]}"
            if not handback:
                try:
                    handback = parse((path / "handback.json").read_bytes(), "handback.json")
                except (Fail, OSError):
                    handback = {}
            ours = isinstance(handback, dict) and handback.get("run_id") == run.id and handback.get("revision") == n \
                and isinstance(handback.get("source"), dict) and isinstance(handback.get("draft") or {}, dict)
            rename(path, dest, then=f"run the command again, it re-checks what is on disk; if {path.name} is gone it "
                   f"is {dest.name}" + (f", re-stage it: {restage(run, n, handback)}, then bundle and publish"
                                        if ours else ""))
            discard(run.dir / f".publishing-{path.name}")
            if ours:
                cause = f"its handback.json cut does not hold ({why})" if why else \
                    "it was staged before the size policy" if accepted else \
                    "no publishing intent names it" if verified and intent is None else \
                    "its publishing intent cannot be read" if verified and intent == "" else \
                    "it is not the revision publish verified" if verified else \
                    "it does not verify as the revision after HEAD"
                print(f"NOTE  moved {path.name} aside to {dest.name}: {cause} and its publication did not complete; "
                      f"re-stage it: {restage(run, n, handback)}, then bundle and publish", file=sys.stderr)
            else:
                print(f"NOTE  moved unreferenced {path.name} aside to {dest.name}", file=sys.stderr)


def prepare(run: Run) -> None:
    recover(run)
    recover_intents(run)


def call_dirs(run: Run) -> list:
    out = []
    for path in listing(run.dir / "reviews", "call-*-a*"):
        m = re.match(r"^call-(\d{3,})-a(\d)$", path.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), path))
    return sorted(out)


RECEIPT = {"schema": {"planloop-receipt/1"}, "status": {"counted", "invalid", "triage"}, "call": "int",
           "attempt": "int", "kind": set(KINDS), "revision": "int", "requested": "dict", "effective": "any",
           "session_id": "str?", "fresh": "bool", "verdict": "any", "findings": "any", "coverage": "any",
           "reasons": "list"}


def load_receipt(path: Path, call: int | None = None, attempt: int | None = None, deep: bool = True) -> dict:
    value = load(path, str(path))
    try:
        shape(value, RECEIPT if deep else {k: RECEIPT[k] for k in ("schema", "status", "call", "attempt")}, "receipt",
              exact=False)
        if call is not None and (value["call"], value["attempt"]) != (call, attempt):
            raise Fail("it names another call")
        if not deep:
            return value
        if not isinstance(value["requested"].get("effort"), str) or not isinstance(value["effective"] or {}, dict):
            raise Fail("requested.effort is not a string or effective is not an object")
        if any(not isinstance(x, str) for x in value["reasons"]):
            raise Fail("reasons is not a list of strings")
        if value["status"] != "invalid" and (
                not isinstance(value["verdict"], str) or not isinstance(value["coverage"], list)
                or any(not isinstance(x, str) for x in value["coverage"]) or not isinstance(value["findings"], list)
                or any(not isinstance(f, dict) or any(not isinstance(f.get(k), str) for k in ("id", "evidence"))
                       or f.get("severity") not in ("low", "medium", "high") for f in value["findings"])):
            raise Fail("its verdict, coverage or findings are not the shape of a verified review")
    except Fail as exc:
        raise Fail(f"{path} is not a planloop receipt" + (f" for call {call} attempt {attempt}" if call else "")
                   + f" ({exc}); it was edited or damaged: restore it as it was written, or delete it and run "
                   "`receipt` for that call again, which re-derives it from the runner's artifacts and Codex's session "
                   "record (invalid once the call's private snapshot copy has been removed)") from exc
    return value


def receipts(run: Run, deep: bool = False) -> list:
    out = []
    for call, attempt, path in call_dirs(run):
        receipt = path / "receipt.json"
        out.append((call, attempt, path, load_receipt(receipt, call, attempt, deep) if probe(receipt) else None))
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


def feedback_text(run: Run, n: int, rev: dict, kind: str, call: int, attempt: int, extra: list = ()) -> str:
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
    lines += ["--- REVIEW BRIEF (host) ---", present(frozen / "brief.md", f"revision {n} frozen brief.md").decode(
              "utf-8").rstrip(), "",
              "--- OBLIGATIONS (exact source text) ---"]
    for o in obligations:
        lines.append(f"{o['id']} [{o['source']} {o['section']}]: {o['text']}")
    lines += ["", "--- DISPOSITIONS IN THIS REVISION ---"]
    for kind_name, table in (("REMOVED", handback["removed"]), ("SHRINK", handback["shrink"]),
                             ("PRESERVED", handback.get("preserved", []))):
        for entry in table:
            lines.append(f"{kind_name} {entry}")
    for fid, answer in handback["answers"].items():
        lines.append(f"{answer} {fid}")
    lines += extra
    reopened = sorted(f for f, b in run.findings().items() if meta_of(b).get("planloop_reopens", "0") not in ("", "0"))
    if reopened:
        lines += ["", f"Findings {', '.join(reopened)} were reopened after a fix: review every section their fixes "
                  "touched for interactions with the rest of the plan."]
    lines += ["", "--- FINDINGS (Beads, at dispatch) ---", findings_table(run), ""]
    return "\n".join(lines) + "\n"


def meaning_block(pol: dict, n: int, entry: dict) -> list:
    s = entry["revision"]
    lines = ["", f"--- MEANING CHECK (shrink-only revision {s} against revision {s - 1}) ---",
             f"Revision {s} answered no open finding and changed text of revision {s - 1}. "
             f".planloop-bundle/meaning-r{s}/before.md is revision {s - 1} exactly, after.md is revision {s} exactly, "
             "and index.md shows where the text differs, which is not evidence that meaning survived.",
             "For every unit listed below, read the old and the new text, added and reordered lines included, and find "
             "where the old meaning now lives. Check that every obligation, invariant, assumption, residual risk and "
             "named item (any label such as A5, OD15 or D10, not only inventoried ids) keeps each qualifier: "
             "quantifiers and negations (no, every, any, only, never, all), conditions (while, until, unless, when, "
             "after), ordering (before, ahead of, first), bounds (at most, at least, exactly, within) and the object "
             "each applies to, and that no added line narrows or makes an exception to one. Check every PRESERVED "
             "line against both texts.",
             "Drift that reads well: \"no unsignalled live loss goes unhandled\" becoming \"every signalled live loss "
             "handled\" inverts the guarantee, and dropping \"while continuity holds\" or \"written ahead of the "
             "fill\" removes a condition or an ordering.",
             "Raise each semantic difference as a finding quoting the old and the new text (a weakened or dropped "
             "guarantee is at least medium). Then write exactly one coverage line for each unit below: the line shown, "
             "followed by `preserved` or `changed`; `changed` only with at least one finding for that difference in "
             "this response. A unit you could not judge is `changed`, with a finding saying what you could not "
             "establish."]
    if s != n:
        lines.append(f"Revision {s} was not judged in its own round; .planloop-bundle/plan.md is revision {n}, and a "
                     f"difference that revision {n} no longer carries is still `changed`, with a low finding saying "
                     f"where revision {n} restored the meaning, closed like any other finding.")
    if "cut" not in pol["handbacks"][s]:
        lines.append(f"Revision {s} was published by planloop code that predates the size policy, so whether it "
                     "answered open findings was never recorded and its changes are judged as a shrink's; a difference "
                     "that its change log attributes to answering a finding is still `changed`, raised as a low "
                     "finding naming that answer, and closed like any other finding.")
    return lines + [f"`meaning revision {s} {u}: `" for u in entry["units"]]


def mandate_for(st: dict, n: int, rev: dict) -> list:
    items = {i["revision"]: i for i in rev["manifest"]["items"] if i["type"] == "meaning_obligation"}
    out = []
    for s in st["unjudged"]:
        if s not in items:
            raise Fail(f"revision {s}'s meaning obligation is not frozen in revision {n}; stage, bundle and publish a "
                       "successor with the current tool, whose bundle freezes it")
        out.append({"revision": s, "previous_revision": s - 1,
                    **{k: items[s][k] for k in ("before_sha256", "after_sha256", "index_sha256", "units")}})
    return out


def meaning_problems(mandate: list, response: dict, out: list) -> list:
    expect = {f"meaning revision {e['revision']} {u}: {v}": (o, u, v) for e, o in zip(mandate, out)
              for u in e["units"] for v in ("preserved", "changed")}
    problems = []
    for line in response["coverage"]:
        if not isinstance(line, str) or not MEANING_LIKE.match(line):
            continue
        hit = expect.get(line.strip())
        if hit is None:
            problems.append(f"meaning line {line[:80]!r} names no unit of this call's meaning check or is not exactly "
                            "`meaning revision <S> <unit>: preserved|changed`")
        elif hit[1] in hit[0]["verdicts"]:
            problems.append(f"meaning revision {hit[0]['revision']} {hit[1]} is stated more than once")
        else:
            hit[0]["verdicts"][hit[1]] = hit[2]
    missing = [f"revision {e['revision']} {u}" for e, o in zip(mandate, out) for u in e["units"]
               if u not in o["verdicts"]]
    if missing:
        problems.append(f"reviewer gave no meaning verdict for {missing} (one `meaning revision <S> <unit>: "
                        "preserved|changed` line per listed unit)")
    if any(v == "changed" for o in out for v in o["verdicts"].values()) and not response.get("findings"):
        problems.append("a meaning unit is `changed` but the response raises no finding for the difference")
    return problems


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
    except (Fail, StopIteration, KeyError, TypeError):
        return f"(not found at {ref})"


def runner_path() -> list:
    explicit = os.environ.get("PLANLOOP_RUNNER")
    if explicit:
        try:
            argv = shlex.split(explicit)
        except ValueError as exc:
            raise Unverifiable(f"PLANLOOP_RUNNER does not parse ({exc}); no call was reserved and Codex did not "
                               "run") from exc
        if not argv:
            raise Unverifiable("PLANLOOP_RUNNER holds no command; no call was reserved and Codex did not run")
        return argv
    found = sorted(glob.glob(str(Path.home() / ".claude/plugins/cache/claudex-loop/claudex-loop/*/skills/"
                                 "claudex-loop/scripts/runner.py")))
    if not found:
        raise Unverifiable("claudex-loop runner.py not found (install claudex-loop or set PLANLOOP_RUNNER); no call "
                           "was reserved and Codex did not run")
    return [sys.executable, found[-1]]


def effort_policy(run_meta: dict, kind: str, effort: str) -> str | None:
    if effort not in EFFORTS:
        return f"effort {effort!r} is not used by planloop (xhigh/max need Mike)"
    if kind == "triage":
        return None if effort == "low" else "triage runs at low effort only"
    if kind == "gate" and effort != "high":
        return "a final gate runs at high effort"
    floor = run_meta.get("planloop_min_effort") or "medium"
    if run_meta.get("planloop_track") == "escalated":
        floor = "high"
    if EFFORTS[effort] < EFFORTS[floor]:
        return f"effort {effort} is below this run's floor {floor}"
    return None


def reserved_by(path: Path, reserve: str) -> bool:
    name = path / MARKER
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            return read_small(fd, str(name), 4096).decode() == reserve
        finally:
            os.close(fd)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return False
    except OSError as exc:
        raise OSError(exc.errno, f"{exc.strerror}; it is not a marker planloop wrote, so {path} is kept: remove it by "
                      "hand once no planloop process runs if it is a leftover", str(name)) from None


def marking(path: Path) -> Path:
    return path.with_name(f".marking-{path.name}")


def mark(path: Path, reserve: str, mode: int = 0o777) -> None:
    tmp = marking(path)
    tmp.mkdir(mode)
    (tmp / MARKER).write_text(reserve)
    if on_disk(path):
        raise FileExistsError(errno.EEXIST, "File exists", str(path))
    try:
        os.rename(tmp, path)
    except OSError as exc:
        raise OSError(exc.errno, exc.strerror, str(path)) from None


def unmark(path: Path, reserve: str) -> None:
    if reserved_by(path, reserve):
        os.rename(path, marking(path))
    if on_disk(marking(path)):
        remove_tree(marking(path))


def clear_reserve(run: Run, left: Path) -> None:
    made = []
    with contextlib.suppress(Fail, AttributeError, KeyError, TypeError, ValueError):
        record = load(left / "input" / "dispatch.json")
        made = [(Path(record["artifacts_root"]), run.state / "calls"), (Path(record["snapshot"]).parent, run.isolated)]
    for path, home in made:
        if path.parent == home:
            unmark(path, left.name)
    shutil.rmtree(left, ignore_errors=True)


def cmd_dispatch(args) -> int:
    run = Run(args.run)
    config = run.config()
    if pid_ns() is None:
        raise Unverifiable("this dispatch cannot tell its own PID namespace (/proc/self/ns/pid cannot be read, or "
                           "/proc is not mounted for it: /proc/self is not its pid), so no planloop command could "
                           "ever check the process its records name; nothing was reserved and Codex did not run: "
                           "dispatch where /proc is that of its PID namespace (`unshare --pid` needs --mount-proc)")
    seen = scope_ready()
    with Lock(run.dir) as lock:
        prepare(run)
        for left in listing(run.dir / "reviews", ".reserve-*"):
            try:
                clear_reserve(run, left)
            except (OSError, Unverifiable) as exc:
                sys.stdout.flush()
                print(f"NOTE  could not remove what a dispatch that ended before it reserved its call left ({exc}); "
                      f"no review used it, and its record {left} is kept so that the next dispatch removes it",
                      file=sys.stderr)
        head = run.head()
        if head is None:
            raise Fail("nothing published yet")
        n = head[0]
        rev = verify_revision(run, n)
        pol, st = policy_now(run)
        walked(pol, n, rev)
        for line in policy_report(pol, st, warn=args.kind in ("working", "focused", "adjudication")) if st else []:
            print(line)
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
            if r and r["status"] == "counted" and not probe(intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json"):
                raise Fail(f"call {c} attempt {a} is counted but not ingested; run `findings ingest` first")
        if n > 1 and not probe(intents_dir(run) / f"propose-r{n:03d}.json"):
            raise Fail(f"revision {n} is published but `findings propose` has not run for it")
        frozen = run.rev_dir(n) / "bundle" / "frozen"
        stale = []
        for item in rev["manifest"]["items"]:
            if item["type"] == "evidence" and item["validity"].get("type") == "observation":
                record = load(frozen / "evidence" / f"{item['id']}.json")
                stale += [f"{item['id']}: {p}" for p in check_evidence(record, frozen / "evidence", run.repo, at=now())]
        if stale:
            raise Fail(f"observation evidence no longer valid for a new round: {stale}; recollect and republish")
        mandate, extra = (mandate_for(st, n, rev) if st and args.kind != "triage" else []), []
        if st and args.kind == "gate" and st["bad"]:
            raise Fail(f"size decision {st['bad'][0][0]} is malformed: {st['bad'][0][1]}")
        if st and args.kind == "gate" and st["basis"] is None:
            raise Fail(f"revision {n} is not gate-eligible under the size policy: {st['need']}")
        if st and n > 1 and cut_warned(cut_of(pol, n), st["sizes"][n], st["sizes"][n - 1]):
            extra += ["", f"This revision answers findings and is "
                      f"{(st['sizes'][n - 1] - st['sizes'][n]) / st['sizes'][n - 1] * 100:.2f}% smaller than revision "
                      f"{n - 1}: check that every cut is explained by the finding it answers or by its disposition."]
        for entry in mandate:
            extra += meaning_block(pol, n, entry)
        runner = runner_path()
        call_dir = run.call_dir(args.call, args.attempt)
        model = config["gate_model"] if args.kind == "gate" and config["gate_model"] else config["reviewer_model"]
        feedback = feedback_text(run, n, rev, args.kind, args.call, args.attempt, extra).encode("utf-8")
        expect = expected_coverage(run, args.kind)
        reserve = call_dir.parent / f".reserve-{uuid.uuid4().hex}"
        frozen_snap = next(i for i in rev["manifest"]["items"] if i["type"] == "snapshot")
        unreserved = f"could not prepare call {args.call} attempt {args.attempt} ({{}}); nothing was reserved and " \
            "Codex did not run: run the command again once the path it names can be read and written"
        private = run.isolated / f"r-{uuid.uuid4().hex[:16]}"
        artifacts, copy, made = run.state / "calls" / f"{call_dir.name}-{private.name}", private / "repo", {}
        nonce = uuid.uuid4().hex
        scope = scope_of(run.id, str(artifacts))
        dispatch = {"schema": "planloop-dispatch/1", "run_id": run.id, "revision": n, "revision_sha256": head[1],
                    "bundle_sha256": rev["bundle_sha256"], "plan_sha256": rev["plan_sha256"], "call": args.call,
                    "attempt": args.attempt, "kind": args.kind, "effort": args.effort,
                    "model": model, "snapshot": str(copy),
                    "snapshot_tree_sha256": frozen_snap["tree_sha256"], "feedback_sha256": sha(feedback),
                    "artifacts_root": str(artifacts), "scope": scope, "view": seen, "live_repo": str(run.repo),
                    "expected_coverage": expect, "dispatched_at": iso(now())}
        if mandate:
            dispatch["meaning_check"] = mandate
        try:
            (reserve / "input").mkdir(parents=True)
            (reserve / "input" / "feedback.md").write_bytes(feedback)
            run.isolated.mkdir(parents=True, exist_ok=True)
            run.isolated.chmod(0o300)
            with contextlib.suppress(PermissionError):
                os.listdir(run.isolated)
                raise Unverifiable(f"{run.isolated} can still be listed after chmod 0300 (a filesystem that ignores "
                                   "permissions, such as drvfs without metadata); put PLANLOOP_ISOLATED on ext4")
            write_new(reserve / "input" / "dispatch.json", canon(dispatch))
            made = {private: "the private snapshot copy", artifacts: "the artifact directory"}
            mark(private, reserve.name, 0o700)
            artifacts.parent.mkdir(parents=True, exist_ok=True)
            mark(artifacts, reserve.name)
            shutil.copytree(frozen_snap["path"], copy, symlinks=True)
            if tree_hash(copy) != frozen_snap["tree_sha256"]:
                raise Fail("the frozen snapshot changed since publication; republish")
            (reserve / "running.json").write_bytes(canon({**identity(), "nonce": nonce, "scope": scope,
                                                          "view": seen}))
            crash_point("before_reserve")
            if probe(call_dir):
                raise Conflict(f"{call_dir} appeared concurrently")
            args.interrupted = f"if {call_dir} exists now, do not dispatch call {args.call} attempt {args.attempt} " \
                f"again: run `receipt --run {run.id} --call {args.call} --attempt {args.attempt}`, which records it " \
                "or prints its receipt; otherwise run the command again"
            rename(reserve, call_dir, then=f"if {call_dir} exists now, {unrun(run, args.call, args.attempt)}; "
                   "otherwise run the command again")
            lock.done = f"call {args.call} attempt {args.attempt} is reserved and Codex has not run; " \
                f"{unrun(run, args.call, args.attempt)}"
        except BaseException as failed:
            left = []
            for path, what in made.items():
                try:
                    unmark(path, reserve.name)
                except OSError as exc:
                    left.append(f"{what} {path} ({exc})")
            if left:
                try:
                    published = not on_disk(reserve)
                except OSError:
                    published = None
                kept = (f"its record {reserve} is kept so that the next dispatch removes it" if published is False
                        else f"call {args.call} attempt {args.attempt} is reserved in {call_dir}, so `receipt --run "
                        f"{run.id} --call {args.call} --attempt {args.attempt}` removes what is left of its private "
                        "snapshot copy (an artifact directory left under its own name holds only its .planloop-reserve "
                        "marker: remove it by hand)" if published else
                        f"its record {reserve} (or {call_dir}, if the reservation was renamed there) is kept so that "
                        "the next dispatch (or that call's `receipt`) removes it")
                sys.stdout.flush()
                print(f"NOTE  could not remove {' or '.join(left)}; no review used it, and {kept}", file=sys.stderr)
            else:
                shutil.rmtree(reserve, ignore_errors=True)
            if isinstance(failed, OSError):
                raise Unverifiable(unreserved.format(failed) if not left else (
                    f"could not prepare call {args.call} attempt {args.attempt} ({failed}); no call was reserved and "
                    f"Codex did not run, but {kept}: run the command again once the path it names can be read and "
                    "written")) from failed
            raise
    argv = runner + ["review", "--host", "claude", "--repo", str(copy), "--plan", ".planloop-bundle/plan.md",
                     "--effort", args.effort, "--timeout", "1800", "--artifacts", str(artifacts), "--feedback",
                     str(call_dir / "input" / "feedback.md")]
    if model:
        argv += ["--model", model]
    ran = f"the review runner ran for call {args.call} attempt {args.attempt}"
    stopped, late, done, handlers, proc, killed, failed, unit = [], [], [], {}, None, None, None, Path(scope).name
    kills, opened, refused, abandoned = [], False, None, False
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, FORWARDED)

    def forward(signum, frame):
        if done and refused is None:
            late.append(signum)
            if len(late) > 1:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            return
        stopped.append((signum, time.monotonic()))
        if len(stopped) > 1:
            kills.append(kill_scope(scope))
        else:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.SIGINT)

    def child():
        for sig in FORWARDED:
            signal.signal(sig, signal.SIG_DFL)
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)

    def notes():
        sys.stdout.flush()
        if stopped and not opened:
            print(f"NOTE  this dispatch was interrupted by {signal.Signals(stopped[0][0]).name} before it let the "
                  "review runner start, so the runner never started and Codex did not run", file=sys.stderr)
        elif stopped:
            print(f"NOTE  this dispatch was interrupted by {signal.Signals(stopped[0][0]).name}: it asked the review "
                  "runner to stop with SIGINT (the signal on which the runner stops Codex)", file=sys.stderr)
        if killed and None not in kills:
            print(f"NOTE  this dispatch could not kill the review's scope {unit} (writing its cgroup.kill, which "
                  f"kills every process in it, failed: {kills[-1]})", file=sys.stderr)
        elif killed:
            print(f"NOTE  this dispatch killed the review's scope {unit} (cgroup.kill, which kills every process in "
                  "it), " + ("after the review runner had exited" if proc.returncode not in (None, -signal.SIGKILL)
                             else "the review runner included unless something else had killed it"), file=sys.stderr)
        for signum in late:
            print(f"NOTE  this dispatch received {signal.Signals(signum).name} after the review runner had stopped, "
                  "and held it until it had finished", file=sys.stderr)
    try:
        try:
            try:
                proc, go = start_scoped(argv, scope, child)
            except (OSError, subprocess.SubprocessError) as exc:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
                sys.stdout.flush()
                print(f"NOTE  the review runner could not be started in its scope {unit} ({exc}); Codex did not run",
                      file=sys.stderr)
                code, out, ran = None, "", None
            else:
                handlers = {sig: signal.signal(sig, forward) for sig in FORWARDED}
                try:
                    admit = Lock(run.dir)
                    admit.timeout *= ADMIT_WAIT
                    admit.abandon = lambda: bool(signal.sigpending() & set(FORWARDED))
                    with admit as lock:
                        lock.done = "running.json was checked under the run lock"
                        mine = load(call_dir / "running.json") if probe(call_dir / "running.json") else None
                        if not isinstance(mine, dict) or mine.get("nonce") != nonce or probe(call_dir / "receipt.json"):
                            raise Conflict(f"{call_dir / 'running.json'} no longer names this dispatch, or the "
                                           "attempt's receipt.json is written: something else took the attempt")
                        if not signal.sigpending() & set(FORWARDED):
                            os.write(go, b"1")
                            opened = True
                            lock.done = (f"the review runner was started for call {args.call} attempt "
                                         f"{args.attempt} and is stopped again, since the run lock it was started "
                                         "under was not released; " + unrun(run, args.call, args.attempt, "its "
                                                                            "call.json is missing, so it is recorded "
                                                                            "invalid"))
                except Abandoned:
                    abandoned = True
                except (OSError, Fail, Unverifiable, Conflict) as exc:
                    if opened:
                        raise
                    refused, said = exc, (f"call {args.call} attempt {args.attempt} was reserved, but its review "
                                          "runner was not started and Codex did not run")
                    after = (f"do not dispatch call {args.call} attempt {args.attempt} again (where that says to run "
                             f"the command again, it means `receipt`): run `receipt --run {run.id} --call {args.call} "
                             f"--attempt {args.attempt}` once that is resolved, which records it or prints its receipt")
                    if isinstance(exc, Unreadable):
                        raise Unreadable(exc.what, exc.error, f"{exc.then}; {said}: {after}") from exc
                    kind = Conflict if isinstance(exc, Conflict) else Fail if isinstance(exc, Fail) else Unverifiable
                    raise kind(f"{said} ({exc}): {after}") from exc
                finally:
                    os.close(go)
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
                out, timed_out, killed, unkilled = await_runner(proc, scope, stopped)
                kills.append(unkilled)
                done.append(True)
                if not opened:
                    code, out, ran = None, "", None
                elif timed_out:
                    code, out, ran = None, "", ran + " and timed out"
                else:
                    code, out = proc.returncode, out.decode("utf-8", errors="replace")
                    ran += f" (exit {code})"
        except BaseException as exc:
            if proc is None or not isinstance(exc, Exception):
                raise
            stop_scope(proc, scope)
            done.append(True)
            failed, ran = exc, (f"dispatch stopped on an unexpected error ({type(exc).__name__}: {exc}) while {ran}"
                                if refused is None else f"the review runner of call {args.call} attempt "
                                f"{args.attempt} was never let start, so Codex did not run ({refused})")
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            if proc is not None:
                for pipe in (proc.stdout, proc.stderr):
                    pipe.close()
        left = scope_left(scope) if proc is not None else None
        if failed is not None and left is None:
            if isinstance(failed, (Fail, Unverifiable, Conflict)):
                raise failed
            raise Unverifiable("dispatch stopped on an unexpected error while the review runner ran "
                               f"({type(failed).__name__}: {failed}); it stopped every process in the review's scope "
                               f"{unit}, and call.json was not written: do not dispatch call {args.call} attempt "
                               f"{args.attempt} again; "
                               + unrun(run, args.call, args.attempt, "its call.json is missing, so it is recorded "
                                       "invalid")) from failed
        if failed is None:
            record_call(run, args.call, args.attempt, artifacts, code, out, ran)
        if left is not None:
            wrote, then = ("nothing was recorded and call.json was not written", unrun(
                run, args.call, args.attempt, "its call.json is missing, so it is recorded invalid; it records "
                "nothing while a process runs in that scope")) if failed else (
                "call.json is written and nothing else was recorded", f"run `receipt --run {run.id} --call {args.call} "
                f"--attempt {args.attempt}`, which records the attempt")
            raise Conflict(f"{ran or 'the review runner was never let start (Codex did not run)'}, but its systemd "
                           f"scope {unit} was killed and {left}; {wrote}: do not dispatch call "
                           f"{args.call} attempt {args.attempt} again; {scope_exit(scope, then)}")
        if abandoned:
            raise Fail(f"call {args.call} attempt {args.attempt} was reserved, but this dispatch was interrupted while "
                       "its admission waited for the run lock, so its review runner was not started and Codex did not "
                       "run; its call.json is written and its receipt is not: do not dispatch call "
                       f"{args.call} attempt {args.attempt} again: " + unrun(run, args.call, args.attempt))
        try:
            return finish_receipt(run, args.call, args.attempt)
        except Unreadable as exc:
            if exc.then not in (Unreadable.NOTHING, Unreadable.SPECIAL):
                raise
            raise Unreadable(exc.what, exc.error, f"{ran or 'the review runner could not be started (Codex did not run)'}"
                             f"; its call.json is written but its receipt is not: do not dispatch call {args.call} "
                             f"attempt {args.attempt} again; once it "
                             f"{'can be read' if exc.then == Unreadable.NOTHING else 'is removed'}, record it with "
                             f"`receipt --run {run.id} --call {args.call} --attempt {args.attempt}`") from exc.error
        except (Conflict, Unverifiable) as exc:
            if not getattr(exc, "lock", False):
                raise
            raise type(exc)(f"{ran or 'the review runner could not be started (Codex did not run)'}; its call.json is "
                            f"written but its receipt is not ({exc}): do not dispatch call {args.call} attempt "
                            f"{args.attempt} again (where that says to run the command again, it means `receipt`): "
                            f"record it with `receipt --run {run.id} --call {args.call} --attempt {args.attempt}`") \
                from exc
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if proc is not None:
            notes()


def record_call(run: Run, call: int, attempt: int, artifacts: Path, code, out: str, ran) -> None:
    call_dir = run.call_dir(call, attempt)
    try:
        located = [p for p in listing(artifacts, "claudex-*") if probe(p / "result.json", "is_file")]
    except Unreadable as exc:
        name = f"{artifacts}/<the claudex-* directory in it holding a result.json file>"
        raise Unreadable(exc.what, exc.error, f"{ran}, but call.json was not written, so its result is not "
                         f"recorded; do not dispatch call {call} attempt {attempt} again: once it can be "
                         f"read, record it with `receipt --run {run.id} --call {call} --attempt {attempt} "
                         f"--artifacts {name}`, or without `--artifacts` if no directory there holds a result.json "
                         "file (it is then recorded invalid)" if ran else f"Codex did not run; once it can be read, "
                         f"{unrun(run, call, attempt)}") from exc.error
    record = {"schema": "planloop-call/1", "runner_exit": code,
              "artifacts": str(located[0]) if len(located) == 1 else None, "runner_stdout_sha256": sha(out.encode())}
    try:
        write_new(call_dir / "call.json", canon(record))
    except OSError as exc:
        try:
            (call_dir / "call.json").unlink(missing_ok=True)
            advice = unrun(run, call, attempt, "its call.json is missing (never written, or removed "
                           "after the failed write), so it is recorded invalid")
        except OSError:
            advice = unrun(run, call, attempt, f"it is recorded invalid unless {call_dir / 'call.json'} "
                           "reads in full, and nothing is recorded while it cannot be read at all",
                           " if it is invalid, or carry on from it if it counted")
        raise Unverifiable(f"could not write {call_dir / 'call.json'} ({exc}), so the review runner's result is "
                           f"not recorded; {advice}") from exc
    crash_point("after_runner")


def unrun(run: Run, call: int, attempt: int, why: str = "Codex did not run, so it is recorded invalid",
          tail: str = "") -> str:
    then = f"dispatch call {call} attempt {attempt + 1}" if attempt < MAX_ATTEMPTS else \
        f"dispatch call {call + 1} attempt 1"
    return (f"record it with `receipt --run {run.id} --call {call} --attempt {attempt}` ({why}), then {then}{tail} "
            "(after `state --set active` if that receipt blocks the run)")


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
    if probe(run.call_dir(call, attempt)):
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
    if any(r.get("revision") != n for r in prior):
        raise Fail("the plan changed since the first attempt: a changed plan is a new call")


def rollout_for(session: str):
    root = Path(os.environ.get("PLANLOOP_CODEX_SESSIONS", "~/.codex/sessions")).expanduser()
    found = sorted(Path(d) / name for d, _, names in walk(root)
                   for name in fnmatch.filter(names, f"rollout-*-{session}.jsonl"))
    if len(found) != 1:
        return None, f"found {len(found)} Codex rollout files for session {session}"
    return found[0], None


def accepted_versions() -> set:
    if probe(VERSIONS_FILE) and not probe(VERSIONS_FILE, "is_file"):
        raise NotFile(VERSIONS_FILE, f"{VERSIONS_FILE}: not a file (repair it by hand; reading it again cannot help)")
    try:
        lines = read_file(VERSIONS_FILE, text=True).splitlines()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
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
    version = (cli_version.split() or [""])[-1] if cli_version else ""
    if check_version and version not in accepted_versions():
        raise Unverifiable(f"Codex CLI {cli_version!r} has not been validated against {ROLLOUT_PARSER}; run "
                           "`planloop.py rollout-check` on one real review from it before trusting it")
    records = []
    for number, line in enumerate(read_file(path, text=True).splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            canon(row)
        except (ValueError, RecursionError) as exc:
            raise Unverifiable(f"rollout line {number} is not JSON text") from exc
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
        if not isinstance(c, dict) or not isinstance(c.get("model"), str) or not isinstance(c.get("effort"), str) \
                or c["effort"] not in EFFORTS \
                or not isinstance(c.get("sandbox_policy"), dict):
            raise Unverifiable("turn_context lacks model, effort or sandbox_policy")
        if any(v is not None and not isinstance(v, str) for v in (c["sandbox_policy"].get("type"),
                                                                    c.get("approval_policy"))):
            raise Unverifiable("turn_context sandbox_policy type or approval_policy is not a string")
        mode = c.get("collaboration_mode") or {}
        mode = (mode.get("settings") or {}) if isinstance(mode, dict) else None
        if not isinstance(mode, dict):
            raise Unverifiable("turn_context collaboration_mode has an unfamiliar shape")
        if mode.get("reasoning_effort") not in (None, c["effort"]):
            raise Fail("turn_context effort and collaboration_mode effort disagree")
        settings.add((c["model"], c["effort"], c["sandbox_policy"].get("type"), c.get("approval_policy")))
    if len(settings) != 1:
        raise Fail(f"turn_context settings change within the session: {sorted(settings, key=repr)}")
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
    for line in read_file(rollout_path, text=True).splitlines():
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


def dispatch_record(run: Run, call: int, attempt: int) -> dict:
    dispatch = load(run.call_dir(call, attempt) / "input" / "dispatch.json", "dispatch.json")
    if isinstance(dispatch, dict):
        dispatch.setdefault("meaning_check", None)
        dispatch.setdefault("scope", None)
        dispatch.setdefault("view", None)
    dispatch = shape(dispatch,
                     {"schema": {"planloop-dispatch/1"}, "run_id": "str", "revision": "int", "revision_sha256": "hex",
                      "bundle_sha256": "hex", "plan_sha256": "hex", "call": "int", "attempt": "int",
                      "kind": set(KINDS), "effort": set(EFFORTS), "model": "str?", "snapshot": "path",
                      "snapshot_tree_sha256": "hex", "feedback_sha256": "hex", "artifacts_root": "path",
                      "scope": "path?", "view": "any", "live_repo": "path", "expected_coverage": "list",
                      "dispatched_at": "str", "meaning_check": "any"}, "dispatch.json")
    if (dispatch["run_id"], dispatch["call"], dispatch["attempt"]) != (run.id, call, attempt):
        raise Fail("dispatch.json belongs to another call")
    mandate = dispatch["meaning_check"]
    if mandate is not None and (not isinstance(mandate, list) or not mandate or any(
            not isinstance(e, dict) or not isinstance(e.get("revision"), int) or not isinstance(e.get("units"), list)
            or any(not isinstance(u, str) for u in e["units"]) for e in mandate)):
        raise Fail("dispatch.json meaning_check is not a list of meaning obligations")
    if any(not isinstance(r, str) for r in dispatch["expected_coverage"]):
        raise Fail("dispatch.json expected_coverage is not a list of finding ids")
    return dispatch


def verify_call(run: Run, call: int, attempt: int, artifacts_override: str | None = None,
                recorded=None, revalidation=None) -> dict:
    call_dir, dispatch = run.call_dir(call, attempt), dispatch_record(run, call, attempt)
    mandate = dispatch["meaning_check"]
    feedback = present(call_dir / "input" / "feedback.md", "feedback.md")
    reasons, infra = [], []
    record = {"schema": "planloop-receipt/1", "run_id": run.id, "call": call, "attempt": attempt,
              "kind": dispatch["kind"], "revision": dispatch["revision"], "revision_sha256": dispatch["revision_sha256"],
              "bundle_sha256": dispatch["bundle_sha256"], "plan_sha256": dispatch["plan_sha256"],
              "requested": {"model": dispatch["model"], "effort": dispatch["effort"]}, "effective": None,
              "session_id": None, "fresh": False, "verdict": None, "findings": [], "coverage": [],
              "live_reads": [], "revalidation": [], "artifacts": {}, "dispatched_at": dispatch["dispatched_at"]}
    if mandate:
        record["meaning_check"] = [{"revision": e["revision"], "previous_revision": e.get("previous_revision"),
                                    "verdicts": {}} for e in mandate]
    if sha(feedback) != dispatch["feedback_sha256"]:
        reasons.append("feedback.md changed after dispatch")
    artifacts = artifacts_override
    if artifacts is None and probe(call_dir / "call.json"):
        try:
            if not probe(call_dir / "call.json", "is_file"):
                raise Fail("not a file")
            artifacts = load(call_dir / "call.json").get("artifacts")
            if artifacts is not None and not text_path(artifacts):
                raise Fail("its artifacts is not a path")
        except (Fail, AttributeError) as exc:
            infra.append(f"call.json does not read ({exc}), so the runner's result is not recorded for this call and "
                         "the attempt is invalid")
            return finalize(record, reasons, infra)
    elif artifacts is None and any(probe(p / "result.json") for p in listing(Path(dispatch["artifacts_root"]),
                                                                              "claudex-*")):
        infra.append("call.json is missing (never written, or removed after a failed write: the dispatching process "
                     "failed or stopped before it recorded the runner's result), so the runner's artifacts are not "
                     "bound to this call and the attempt is invalid")
        return finalize(record, reasons, infra)
    if not artifacts:
        infra.append("runner left no artifact directory (failed before launch, timed out or crashed)")
        return finalize(record, reasons, infra)
    adir = Path(artifacts)
    if adir.parent != Path(dispatch["artifacts_root"]):
        reasons.append("artifact directory is not the one reserved for this call")
    try:
        if probe(adir) and not probe(adir, "is_dir"):
            raise Fail(f"runner artifact directory {adir} is not a directory")
        if probe(adir / "result.json") and not probe(adir / "result.json", "is_file"):
            raise Fail("runner result.json: not a file")
        result = load(adir / "result.json", "runner result.json")
        try:
            canon(result)
        except UnicodeEncodeError as exc:
            raise Fail("runner result.json holds an unpaired surrogate escape (\\ud800 to \\udfff alone), which is "
                       "not text, so no receipt could record it") from exc
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
    if not isinstance(result.get("cli_version", ""), (str, type(None))):
        reasons.append("result.json cli_version is not a string or null")
    if reasons:
        return finalize(record, reasons, infra)
    files = {}
    for name in ("result.json", "command.json", "prompt.txt", "reply.txt", "stdout.txt", "stderr.txt", "schema.json"):
        path = adir / name
        if not probe(path):
            infra.append(f"runner artifact {name} missing")
        elif not probe(path, "is_file"):
            infra.append(f"runner artifact {name} is not a file")
        else:
            files[name] = sha_file(path)
    record["artifacts"] = {"dir": str(adir), "files": files}
    try:
        if not infra:
            stdout, prompt = (read_file(adir / name, f"runner artifact {name}", text=True)
                              for name in ("stdout.txt", "prompt.txt"))
    except Fail as exc:
        infra.append(str(exc))
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
    for number, line in enumerate(stdout.splitlines(), 1):
        if line.strip():
            try:
                event = loads(line, f"stdout event {number}")
                canon(event)
                events.append(event)
            except Fail as exc:
                reasons.append(str(exc))
            except UnicodeEncodeError:
                infra.append(f"stdout event {number} holds an unpaired surrogate escape (\\ud800 to \\udfff alone), "
                             "which is not text, so no receipt could record it")
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
    if not probe(run.rev_dir(dispatch["revision"]) / "plan.md", "is_file"):
        raise Fail(f"revision {dispatch['revision']} plan.md: missing or not a file")
    plan_text = read_file(run.rev_dir(dispatch["revision"]) / "plan.md", text=True)
    marker = f"sha256={dispatch['bundle_sha256']}"
    if f"PLAN SHA256: {dispatch['plan_sha256']}\n" not in prompt or f"<plan>\n{plan_text}\n</plan>\n" not in prompt:
        reasons.append("prompt.txt does not carry this revision's plan")
    if not prompt.endswith("HOST DISPOSITIONS / FIX REQUEST:\n" + feedback.decode("utf-8", "replace")) \
            or marker not in prompt:
        reasons.append("prompt.txt does not end with this call's feedback and bundle marker")
    keep = adir / "rollout.jsonl"
    if probe(keep) and not probe(keep, "is_file"):
        infra.append("runner artifact rollout.jsonl (the kept copy of Codex's session record) is not a file")
        return finalize(record, reasons, infra)
    try:
        rollout_path, missing = rollout_for(session)
    except Unreadable:
        if not probe(keep):
            raise
        missing = "unreadable"
    if not missing and not probe(rollout_path, "is_file"):
        missing = f"Codex's session record {rollout_path} is not a file"
    if missing and probe(keep):
        rollout_path, missing = keep, None
    if missing:
        infra.append(f"effective settings unverifiable: {missing}")
        return finalize(record, reasons, infra)
    manifest = bundle_manifest(run, dispatch["revision"], dispatch["bundle_sha256"])
    frozen = Path(next(i for i in manifest["items"] if i["type"] == "snapshot")["path"]) / "AGENTS.md"
    context = {"cwd": str(snap),
               "agents_md": read_file(frozen, text=True) if probe(frozen, "is_file") else None}
    try:
        rollout = parse_rollout(rollout_path, session, prompt, result.get("cli_version", ""), context=context)
    except (Unreadable, NotFile):
        raise
    except Unverifiable as exc:
        infra.append(f"effective settings unverifiable: {exc}")
        return finalize(record, reasons, infra)
    except Fail as exc:
        reasons.append(str(exc))
        return finalize(record, reasons, infra)
    if not probe(keep):
        try:
            write_atomic(keep, read_file(rollout_path, "Codex's session record"))
        except OSError as exc:
            raise Unverifiable(f"could not keep a copy of Codex's session record {rollout_path} as {keep} ({exc}); "
                               f"nothing was recorded for call {call} attempt {attempt}: run `receipt --run {run.id} "
                               f"--call {call} --attempt {attempt}` once it can be written") from exc
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
    earlier = {r.get("session_id") for c, a, p, r in receipts(run) if r and (c, a) != (call, attempt)
               and isinstance(r.get("session_id"), str)}
    fresh = (rollout["prompt_in_first_turn"] and rollout["user_turns"] == 1 and not rollout["lineage_fields"]
             and session not in earlier and result.get("previous") is None and "resume" not in argv[2:3])
    record["fresh"] = fresh
    if not fresh:
        reasons.append("context is not provably fresh (resume, earlier user turns, lineage fields or reused session)")
    record["live_reads"] = live_reads(events, rollout_path, dispatch, run)
    if record["live_reads"]:
        reasons.append(f"reviewer reached outside its private snapshot (live checkout, planloop state, Codex "
                       f"home, or a relative path climbing above the snapshot root): {record['live_reads'][:3]}")
    changed = "frozen snapshot changed during the review"
    kept = recorded.get("reasons") if isinstance(recorded, dict) and not probe(snap.parent) else None
    if changed in kept if isinstance(kept, list) else tree_hash(snap) != dispatch["snapshot_tree_sha256"]:
        reasons.append(changed)
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
        raised = {f["id"] for f in response.get("findings") if isinstance(f, dict) and isinstance(f.get("id"), str)} \
            if isinstance(response.get("findings"), list) else set()
        missing = [r for r in dispatch["expected_coverage"] if r not in seen and r not in raised]
        if missing:
            reasons.append(f"reviewer did not report on findings {missing} (fix-proposed: resolved/unresolved; "
                           "withdrawn, at the gate: withdrawal confirmed, or re-raise)")
        clash = [r for r in seen if r in raised and seen[r] != "unresolved"]
        if clash:
            reasons.append(f"findings {clash} are both re-raised and reported {', '.join(seen[r] for r in clash)}")
        if mandate:
            reasons += meaning_problems(mandate, response, record["meaning_check"])
    record["verdict"] = response.get("verdict") if isinstance(response, dict) else None
    record["findings"] = response.get("findings", []) if isinstance(response, dict) else []
    record["coverage"] = response.get("coverage", []) if isinstance(response, dict) else []
    record["usage"] = result.get("usage")
    record["cli_version"] = result.get("cli_version")
    try:
        record["revalidation"], failure = revalidation or (
            revalidate(run, dispatch["revision"], dispatch["bundle_sha256"]), None)
    except Unreadable:
        raise
    except Unverifiable as exc:
        failure = str(exc)
    if failure is not None:
        infra.append(f"{REVALIDATION[1]}{failure}")
    if record["revalidation"]:
        reasons.append(f"{REVALIDATION[0]}{record['revalidation'][:5]}")
    return finalize(record, reasons, infra)


REVALIDATION = ("relevant inputs changed during the review: ", "live inputs could not be revalidated: ")


def revalidation_of(record) -> tuple | None:
    changes, reasons = record.get("revalidation"), record.get("reasons")
    if not all(isinstance(v, list) and all(isinstance(e, str) for e in v) for v in (changes, reasons)):
        return None
    failures = [r[len(REVALIDATION[1]):] for r in reasons if r.startswith(REVALIDATION[1])]
    return changes, failures[0] if failures else None


def finalize(record: dict, reasons: list, infra: list) -> dict:
    record["reasons"] = reasons + infra
    record["infrastructure"] = bool(infra) and not reasons
    if reasons or infra:
        record["status"] = "invalid"
    else:
        record["status"] = "triage" if record["kind"] == "triage" else "counted"
    return record


def bundle_manifest(run: Run, n: int, bundle_sha: str) -> dict:
    what = f"revision {n} bundle manifest"
    data = present(run.rev_dir(n) / "bundle" / "manifest.json", what)
    if sha(data) != bundle_sha:
        raise Fail(f"{what} does not match the bundle_sha256 it was published and dispatched with")
    return parse(data, what)


def revalidate(run: Run, n: int, bundle_sha: str) -> list:
    manifest = bundle_manifest(run, n, bundle_sha)
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
    call_dir = run.call_dir(call, attempt)
    running = call_dir / "running.json"
    command = f"receipt --run {run.id} --call {call} --attempt {attempt}"
    with Lock(run.dir) as lock:
        owner = held = None
        if probe(running):
            try:
                owner, held = load(running, "running.json"), True
            except Fail:
                if probe(running):
                    raise
            if held and (not isinstance(owner, dict) or probe(running, "is_symlink")):
                raise Fail("running.json: not a JSON object in a regular file (repair it by hand; reading it again "
                           "cannot help)")
        rerun = f"run `{command}{'' if artifacts is None else ' --artifacts ' + artifacts}` again"
        cannot = f"call {call} attempt {attempt} cannot be recorded yet: "
        recorded = probe(call_dir / "receipt.json")
        far = owner_far(owner) if held else None
        if held and not recorded and (owner.get("pid") != os.getpid() or far) and owner_alive(owner):
            here = owner.get("host") == socket.gethostname()
            raise Conflict(f"call {call} attempt {attempt} is still being reviewed by {owner_named(owner)}; "
                           "wait for it" + ((f" (it took the call on this host and is alive), or stop it (`kill "
                                             f"{owner['pid']}`, which also stops the review runner it started, "
                                             f"killing every process in the review's scope if it is not empty "
                                             f"{STOP_GRACE} seconds later), then {rerun}" if owner_proven(owner) else
                                             (f"; {far}, so whether it is alive cannot be checked here: run "
                                              f"`{command}` where the call was dispatched (the container, sandbox or "
                                              "session of that PID namespace), or check there that "
                                              f"{owner_named(owner)} is not a planloop dispatch {far_check(owner)}, "
                                              "then" if far else
                                              f"; if {owner_named(owner)} on this host is not a planloop dispatch,")
                                             + f" remove {running} by hand and {rerun}: that gives up only "
                                             "the wait for the dispatching process (a dispatch that has not started "
                                             "its review runner by then never starts it), and the call is still not "
                                             "recorded while a process runs in the scope of its review") if here
                           else elsewhere(owner, "a planloop dispatch", running) + f" and {rerun}"))
        stands = "its receipt.json is written and stands, and is printed once nothing runs" \
            if recorded else "nothing was recorded"
        dispatched = dispatch_record(run, call, attempt)
        scope, seen, mine = dispatched["scope"], dispatched["view"], view()
        unit = Path(scope).name if scope else None
        by_hand = (f"check by hand that nothing runs in that scope (`systemd-cgls --user-unit {unit}` lists no "
                   f"process, or says the unit is not found), then remove {call_dir} (what it records of the "
                   f"attempt is discarded) and dispatch call {call} attempt {attempt} again")
        if scope is None and seen is None:
            if held:
                raise Conflict(f"{cannot}its dispatch.json records no systemd scope (a planloop older than the scope "
                               "dispatched it), so whether a process still runs for it cannot be checked here; "
                               f"{stands}: check by hand that the review runner and the Codex it started are gone "
                               f"(`ps -eo pid,lstart,args`), and only then remove {running} and {rerun}")
        else:
            named = scope_of(run.id, dispatched["artifacts_root"])
            if scope is not None and (seen is None or scope != named and os.path.dirname(scope) == os.path.dirname(
                    named) and re.match(r"^planloop-.*\.scope$", unit)):
                raise Conflict(f"{cannot}its dispatch.json records the systemd scope {unit} "
                               + ("without how its dispatch saw cgroups" if seen is None else "under a name this "
                                  "planloop does not give the scope of this run and artifacts_root")
                               + ": an unreleased planloop build (rounds 21 and 22 of quartz-rs-72m, which never "
                               "left its scratch clones) wrote that record, or it was edited, and this planloop "
                               f"cannot check that scope; {stands}: {by_hand}")
            try:
                shape(seen, VIEW, "dispatch.json.view")
                if scope != named:
                    raise Fail("dispatch.json.scope: not the scope of this run and artifacts_root for this user")
            except Fail as exc:
                raise Conflict(f"{cannot}{exc}, so whether a process still runs in its review's scope cannot be "
                               f"checked; {stands}: dispatch.json was edited, or another user runs this command: "
                               f"restore it as dispatch wrote it, or {rerun} as the user who dispatched it") from exc
            far = [k for k in VIEW if seen[k] != mine[k]]
            rebooted = "boot_id" in far and mine["boot_id"] and not {"host", "machine_id"} & set(far)
            if far and not (rebooted and mine["machine_id"]):
                raise Conflict(f"{cannot}{unit} is the systemd scope of its review, and this command does not see "
                               "cgroups as its dispatch did ("
                               + "; ".join(f"{k}: dispatch.json records {seen[k]!r}, here {mine[k]!r}" for k in far)
                               + ("; machine_id: none is recorded and none reads here, so another boot of this "
                                  "host cannot be told from another host" if rebooted else "")
                               + f"), so a scope that is absent here may still hold a process there; {stands}: run "
                               f"`{command}` on the host and in the session (not a container, another distribution or "
                               "another cgroup namespace) that dispatched it; if there is none any more (the host "
                               f"was renamed, its machine id changed or cannot be read), {by_hand}")
            left = None if far else scope_left(scope)
            if left is not None:
                raise Conflict(f"{cannot}{unit} is the systemd scope of its review, and {left}; {stands}: "
                               f"{scope_exit(scope, rerun)}")
        path = call_dir / "receipt.json"
        have = probe(path)
        old = load(path) if have else None
        bind = artifacts is not None and not have and not probe(call_dir / "call.json")
        if bind:
            adir, root = Path(artifacts), Path(dispatched["artifacts_root"])
            found = [p for p in listing(root, "claudex-*") if probe(p / "result.json", "is_file")]
            if adir.parent != root or found != [adir]:
                raise Fail(f"--artifacts {artifacts} is not the one runner directory dispatch would have recorded "
                           f"(the only claudex-* directory directly in {root} holding a result.json file; there: "
                           f"{', '.join(p.name for p in found) or 'none'}); nothing was recorded: name that directory, "
                           f"or run `{command}` without --artifacts, which records the attempt invalid")
        command += "" if artifacts is None or bind else f" --artifacts {artifacts}"
        record = verify_call(run, call, attempt, artifacts, recorded=old)
        if bind:
            try:
                write_new(call_dir / "call.json", canon({"schema": "planloop-call/1", "runner_exit": None,
                                                         "artifacts": str(adir), "runner_stdout_sha256": None}))
            except OSError as exc:
                left = ", but a partial call.json remains: remove it by hand first" \
                    if os.path.lexists(call_dir / "call.json") else ""
                raise Unverifiable(f"could not write {call_dir / 'call.json'} ({exc}), so {adir} is not bound to "
                                   f"call {call} attempt {attempt} and nothing was recorded{left}; run "
                                   f"`{command} --artifacts {artifacts}` again once it can be written") from exc
        moved = None
        if have:
            stored = {k: v for k, v in old.items() if k != "created_at"} if isinstance(old, dict) else None
            if stored != record:
                was = revalidation_of(stored) if stored is not None else None
                if was is None or canon(stored) != canon(verify_call(run, call, attempt, artifacts, recorded=old,
                                                                     revalidation=was)):
                    raise Conflict(f"{path} exists and differs from a fresh verification in more than the live-input "
                                   "revalidation; it was left unchanged and is not printed: compare it with the call's "
                                   "runner artifacts and Codex records before relying on it")
                moved = [("; ".join(changes + ([] if failure is None else [REVALIDATION[1] + failure]))
                          or f"no declared input {verb} from the frozen bundle")
                         for (changes, failure), verb in ((revalidation_of(record), "differs"), (was, "differed"))]
                record = stored
        else:
            record["created_at"] = iso(now())
            try:
                write_new(path, canon(record))
            except OSError as exc:
                left = f", but a partial {path.name} remains: remove it by hand first" if os.path.lexists(path) else ""
                raise Unverifiable(f"could not write {path} ({exc}), so call {call} attempt {attempt} is not "
                                   f"recorded{left}; do not dispatch that attempt again: run `{command}` again once "
                                   "it can be written") from exc
            record.pop("created_at")
        try:
            left = prune_copies(run, f"`{command}`")
            bead = run.run_bead()
            if record["status"] == "invalid" and invalid_streak(run, meta_of(bead)) >= MAX_ATTEMPTS:
                run.beads.update(bead, {"planloop_state": "blocked",
                                        "planloop_reason": f"text: {MAX_ATTEMPTS} review attempts in a row failed; "
                                                           f"last: {record['reasons'][0][:200]}"})
        except Unreadable as exc:
            raise Unreadable(exc.what, exc.error, f"call {call} attempt {attempt} is recorded {record['status']} in "
                             f"{path} and stands, but this command stopped before printing it and before checking "
                             "whether that blocks the run; do not dispatch that attempt again: once it can be read, "
                             f"run `{command}` again, which prints it and makes that check") from exc.error
        except (Fail, Unverifiable, *MALFORMED) as exc:
            raise (Unverifiable if isinstance(exc, Unverifiable) else Fail)(
                       (f"{exc}" if isinstance(exc, (Fail, Unverifiable)) else
                        f"a record it read is malformed ({type(exc).__name__}: {exc})")
                       + f"; call {call} attempt {attempt} is recorded {record['status']} in {path} and stands, but "
                       "this command stopped before printing it and before checking whether that blocks the run; do "
                       f"not dispatch that attempt again: once that is repaired, run `{command}` again, which prints "
                       "it and makes that check") from exc
        for reason in record["reasons"]:
            print(f"FAIL  {reason}")
        print(f"call {call} attempt {attempt}: {record['status']}, verdict {record['verdict']}, effort "
              f"{record['requested']['effort']}->{(record['effective'] or {}).get('effort')}, fresh {record['fresh']}")
        if moved is not None:
            sys.stdout.flush()
            print(f"NOTE  this is the receipt as recorded; the live inputs revalidate differently now ({moved[0]}) "
                  f"than the receipt records ({moved[1]}); the recorded receipt stands and receipt.json was not "
                  "rewritten", file=sys.stderr)
        for note in left:
            sys.stdout.flush()
            print(f"NOTE  {note}", file=sys.stderr)
        lock.done = f"the review is recorded (call {call} attempt {attempt}: {record['status']}, see the output " \
            f"above), carry on from it (a counted review goes to `findings ingest`); `{command}` prints it again"
        with contextlib.suppress(OSError):
            running.unlink()
    return 0 if record["status"] in ("counted", "triage") else 1


def prune_copies(run: Run, rerun: str) -> list:
    rows, left = [row for row in receipts(run) if row[3] is not None], []
    kept = max(((c, a) for c, a, _, r in rows if r.get("kind") == "gate" and r["status"] == "counted"), default=None)
    for c, a, path, r in rows:
        if (c, a) == kept:
            continue
        try:
            record = load(path / "input" / "dispatch.json")
            if not isinstance(record, dict) or not text_path(record.get("snapshot")):
                continue
            private = Path(record["snapshot"]).parent
            if private.parent != run.isolated:
                continue
            art = record.get("artifacts_root")
            made = [private] + ([Path(art)] if text_path(art) and Path(art).parent == run.state / "calls" else [])
            leftovers = [marking(p) for p in made if probe(marking(p))]
            if not probe(private):
                private = None
        except Unreadable as exc:
            left.append(f"{exc.why}, so the private snapshot copy or artifact directory of call {c} attempt {a} was "
                        "not checked or removed; the receipt is recorded and stands and no review needs that copy: "
                        "once it can be read, "
                        f"running {rerun} again removes the copy")
            continue
        for doomed in leftovers:
            try:
                remove_tree(doomed)
            except OSError as exc:
                left.append(f"could not remove {doomed} ({exc}), left by the dispatch of call {c} attempt {a} that "
                            "stopped before its review runner started; the receipt is recorded and stands and no "
                            f"review uses it: running {rerun} again removes it")
        if private is None:
            continue
        doomed = private.with_name(f".pruned-{private.name}")
        try:
            os.rename(private, doomed)
            remove_tree(doomed)
        except OSError as exc:
            left.append(f"could not remove the private snapshot copy {doomed if os.path.lexists(doomed) else private} "
                        f"({exc}); the receipt is recorded and stands and no review needs that copy: remove it by hand "
                        "(`chmod -R u+w` first) once no planloop process runs")
    return left


def cmd_receipt(args) -> int:
    run = Run(args.run)
    run.config()
    return finish_receipt(run, args.call, args.attempt, args.artifacts)


def intents_dir(run: Run) -> Path:
    return run.dir / "intents"


def save_intent(run: Run, name: str, intent: dict) -> Path:
    path = intents_dir(run) / f"{name}.json"
    try:
        write_atomic(path, canon(intent))
    except OSError as exc:
        raise Unverifiable(f"could not write intent {name} ({exc}); no Beads change was made from it: if {path} "
                           f"exists now, the next locking command (`publish --run {run.id} --recover`) applies it, "
                           "otherwise run the command again once it can be written") from exc
    return path


def load_intent(path: Path) -> dict:
    intent = load(path, str(path))
    try:
        shape(intent, {"schema": {"planloop-intent/1"}, "name": "str", "state": {"planned", "applied", "verified"},
                       "ops": "list"}, "intent")
        for i, op in enumerate(intent["ops"]):
            shape(op, {"key": "str", "meta": "dict"}, f"intent.ops[{i}]", exact=False)
            create = op.get("create")
            if op.get("status") not in (None, "open", "closed") or not isinstance(op.get("reason", ""), str) or \
                    create is not None and (not isinstance(create, dict) or not isinstance(create.get("title"), str)
                                            or not isinstance(create.get("meta"), dict)):
                raise Fail(f"intent.ops[{i}]: status, reason or create is malformed")
    except Fail as exc:
        raise Fail(f"intent {path.name} is not a planloop intent ({exc}); nothing was applied from it: restore or "
                   "repair it by hand, then run the command again") from exc
    return intent


def apply_intent(run: Run, path: Path) -> None:
    intent = load_intent(path)
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
    unfinished = f"its Beads changes are made and {path.name} stays unfinished: once {path.parent} can be written, " \
        f"`publish --run {run.id} --recover` replays it to completion"
    try:
        write_atomic(path, canon(intent))
    except OSError as exc:
        raise Unverifiable(f"could not record intent {path.name} as applied ({exc}); {unfinished}") from exc
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
    try:
        write_atomic(path, canon(intent))
    except OSError as exc:
        raise Unverifiable(f"could not record intent {path.name} as verified ({exc}); {unfinished}") from exc


def recover_intents(run: Run) -> None:
    for path in listing(intents_dir(run), "*.json"):
        intent = load_intent(path)
        if intent["state"] != "verified":
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
    if probe(existing):
        return existing
    receipt = load_receipt(run.call_dir(call, attempt) / "receipt.json", call, attempt)
    if receipt["status"] != "counted":
        raise Fail(f"call {call} attempt {attempt} is {receipt['status']}; only counted reviews change findings")
    for c, a, path, r in receipts(run):
        done = probe(intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json")
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
            update |= {"planloop_state": "reopened", "planloop_reopens": int(meta.get("planloop_reopens") or 0) + 1,
                       "planloop_resolution": ""}
            run_updates["planloop_min_effort"] = "high"
            ops.append({"key": finding_key(run, fid), "meta": update, "status": "open"})
            continue
        if state == "fix_proposed":
            if receipt["revision"] < int(meta.get("planloop_last_fix_revision") or 0):
                ops.append({"key": finding_key(run, fid), "meta": update})
                continue
            count = int(meta.get("planloop_unresolved_after_fix") or 0) + 1
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
                and call > int(meta.get("planloop_raised_call") or 0):
            ops.append({"key": finding_key(run, fid), "meta": {"planloop_state": "verified", "planloop_resolution": ref},
                        "status": "closed", "reason": f"verified by planloop {ref}"})
            redesign.discard(fid)
        elif verdict == "unresolved" and state == "fix_proposed" and current:
            count = int(meta.get("planloop_unresolved_after_fix") or 0) + 1
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
    if probe(intents_dir(run) / f"{name}.json"):
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
        if meta.get("planloop_state") not in ("open", "reopened") \
                or int(meta.get("planloop_last_fix_revision") or 0) >= n:
            continue
        if answer == "REJECT":
            ops.append({"key": finding_key(run, fid), "meta": {"planloop_rejected_revision": n}})
            continue
        update = {"planloop_state": "fix_proposed", "planloop_last_fix_revision": n,
                  "planloop_fix_proposals": int(meta.get("planloop_fix_proposals") or 0) + 1}
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
    if probe(intents_dir(run) / f"{name}.json"):
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
    for path in listing(intents_dir(run), "*.json"):
        if load_intent(path)["state"] != "verified":
            problems.append(f"intent {path.name} is unfinished; re-run any findings command to replay it")
    try:
        findings = run.findings()
        run_meta = meta_of(run.run_bead())
    except (Unverifiable, Conflict) as exc:
        return problems + [f"Beads unreadable or inconsistent: {exc}"]
    for c, a, p, r in receipts(run):
        if r and r["status"] == "counted" and not probe(intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json"):
            problems.append(f"counted review call {c} attempt {a} has not been ingested")
    for fid, bead in findings.items():
        meta = meta_of(bead)
        state = meta.get("planloop_state")
        closed = bead.get("status") == "closed"
        if (state in OPEN_STATES) == closed:
            problems.append(f"{fid}: state {state} but bead status {bead.get('status')}")
        ref = meta.get("planloop_resolution", "")
        if state in ("verified", "withdrawn"):
            rpath = run.dir / ref
            try:
                r = load_receipt(rpath)
            except Fail as exc:
                problems.append(f"{fid}: resolution {ref!r} is not a receipt ({exc})")
                continue
            want = f"finding {fid}: resolved" if state == "verified" else f"finding {fid}: withdrawn: "
            lines = [c.strip() for c in r["coverage"]] if r["status"] == "counted" else []
            shown = want in lines if state == "verified" else any(c.startswith(want) and COVERAGE.match(c) for c in lines)
            if r["status"] != "counted" or not shown or fid in [f["id"] for f in r["findings"]]:
                problems.append(f"{fid}: receipt {ref} does not show a counted '{want}' for it")
            if state == "verified" and r["call"] <= int(meta.get("planloop_raised_call") or 0):
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
        save(run.dir / "run.json", canon(config), "the model change was not recorded (any interrupted publication or "
             "unfinished Beads intent the lock replayed first stays completed)")
        print(f"run {run.id}: Codex reviews on {args.model!r}, the final gate on {args.gate_model!r}, from the next "
              "dispatch")
    return 0


def approval_holds(run: Run) -> bool:
    pointer = run.dir / "APPROVAL"
    if not probe(pointer):
        return False
    try:
        p = shape(load(pointer, "APPROVAL"), {"schema": {"planloop-approval-pointer/1"}, "record": "str",
                                              "sha256": "hex"}, "APPROVAL")
        record = load(run.dir / "approvals" / p["record"], "approval record")
        report = Report()
        with contextlib.redirect_stdout(io.StringIO()):
            facts = readiness(run, report, at_publication=False)
        return not report.failures and facts == {k: v for k, v in record.items() if k not in ("approved_at", "schema")}
    except Unreadable:
        raise
    except (Fail, Unverifiable, Conflict):
        return False


def cmd_ledger(args) -> int:
    run = Run(args.run)
    run.config()
    head = run.head()
    pol, st = policy_now(run)
    lines = ["<!-- GENERATED by .claude/skills/planloop/scripts/planloop.py ledger. Not authoritative and not",
             "     to be edited: finding status lives in Beads, review facts in reviews/*/receipt.json. -->",
             f"# planloop ledger: {run.id}", "",
             f"HEAD: revision {head[0] if head else '-'}; run state {meta_of(run.run_bead()).get('planloop_state')}", "",
             "| call | attempt | kind | revision | status | effort req -> eff | fresh | verdict | reasons |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c, a, p, r in receipts(run, deep=True):
        if r is None:
            lines.append(f"| {c} | {a} | ? | ? | no receipt | | | | |")
            continue
        lines.append(f"| {c} | {a} | {r['kind']} | {r['revision']} | {r['status']} | {r['requested']['effort']} -> "
                     f"{(r['effective'] or {}).get('effort')} | {r['fresh']} | {r['verdict']} | "
                     f"{'; '.join(r['reasons'])[:160]} |")
    lines += ["", "| revision | bytes | change vs previous | shrink-only | judged by |", "|---|---|---|---|---|"]
    for m in range(1, pol["head"] + 1):
        b, before = len(pol["plans"][m]), len(pol["plans"].get(m - 1, b""))
        change = f"{b - before:+,} ({(b - before) / before * 100:+.2f}%)" if m > 1 else "-"
        shrink, judged = "-", "-"
        if st and m >= pol["first"]:
            cut, j = cut_of(pol, m), st["judged"].get(m)
            shrink = ("from text: " if cut.get("from_text") else "") + ("yes" if cut["shrink_only"] else "no")
            judged = f"call {j['call']} on revision {j['on']}" if j else ("not yet" if cut["shrink_only"] else "-")
        lines.append(f"| {m} | {b:,} | {change} | {shrink} | {judged} |")
    lines += ["", findings_table(run), ""]
    save(run.dir / "ledger.md", "\n".join(lines).encode("utf-8"),
         "the ledger was not written, and nothing else was changed")
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
    try:
        pol, st = policy_now(run)
        walked(pol, n, rev)
    except Unbound as exc:
        report.check(False, f"[mechanical] every stored meaning receipt is bound to revisions 1 to {n}", str(exc))
        return None
    except Unreadable:
        raise
    except Unverifiable as exc:
        report.check(False, f"[mechanical] revisions 1 to {n} verify as a chain from HEAD", str(exc))
        return None
    if st:
        report.check(True, f"[mechanical] revisions 1 to {n} verify as a chain from HEAD")
        for line in st["notes"]:
            print(line)
        for name, why in st["bad"]:
            report.check(False, f"[mechanical] size decision {name} well formed", why)
        done = "; ".join(f"revision {s}: call {j['call']} on revision {j['on']}, {j['preserved']} units preserved, "
                         f"{j['changed']} changed and raised as findings"
                         for s, j in sorted(st["judged"].items()) if s in st["shrinks"])
        report.check(not st["unjudged"], "[judgement, recorded] every shrink-only revision since the size policy "
                     f"applied has a counted reviewer's meaning judgement ({done or 'no shrink-only revision'}); "
                     "planloop records that the judgement was made and bound to the frozen inputs, never that it is "
                     "right", f"not judged: revision(s) {st['unjudged']}")
        report.check(st["basis"] is not None, f"[mechanical] revision {n} is gate-eligible under the size policy"
                     + (f" ({st['basis']})" if st["basis"] else ""), st["need"] or "")
    all_receipts = receipts(run)
    last = all_receipts[-1] if all_receipts else None
    gate_ok = bool(last and last[3] and last[3].get("kind") == "gate" and last[3].get("revision") == n)
    report.check(gate_ok, "[mechanical] the latest review call is a final gate on the published revision")
    if not gate_ok:
        return None
    c, a, _, stored = last
    fresh = verify_call(run, c, a, recorded=stored if stored["status"] != "counted" else None)
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
    gate_lines = {c.strip() for c in fresh["coverage"]} if fresh["status"] == "counted" else set()
    unconfirmed = sorted(f for f, b in run.findings().items() if meta_of(b).get("planloop_state") == "withdrawn"
                         and f"finding {f}: withdrawal confirmed" not in gate_lines)
    report.check(not unconfirmed, "[mechanical] the final gate confirmed every withdrawn finding against its "
                 "original failure scenario", ", ".join(unconfirmed))
    changes = revalidate(run, n, rev["bundle_sha256"])
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
    ingested = probe(intents_dir(run) / f"ingest-call-{c:03d}-a{a}.json")
    report.check(ingested or not fresh["findings"], "[mechanical] the gate's own findings are ingested")
    run_meta = meta_of(run.run_bead())
    report.check(run_meta.get("planloop_state") in ("active", "approved"), "[mechanical] run is not blocked or "
                 "awaiting a decision", f"{run_meta.get('planloop_state')}: {run_meta.get('planloop_reason')}")
    handback = load(run.rev_dir(n) / "handback.json")
    accepted = {}
    for path in listing(run.dir / "decisions", "D*.json"):
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
            "risk_acceptances": sorted(set(accepted.values())), "observations": observations,
            **(st["facts"] if st else {})}


def cmd_rollout_check(args) -> int:
    adir = Path(args.artifacts).resolve()
    result = shape(load(adir / "result.json", "runner result.json"),
                   {"status": {"completed"}, "provider": {"codex"}, "session_id": "str", "cli_version": "str",
                    "requested_effort": set(EFFORTS)}, "result.json", exact=False)
    prompt = present(adir / "prompt.txt", "runner prompt.txt", text=True)
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
        text = read_file(VERSIONS_FILE, text=True) if probe(VERSIONS_FILE) else ""
        line = f"{version} {now().date()} rollout-check of session {result['session_id']} ({adir})\n"
        save(VERSIONS_FILE, (text + line).encode("utf-8"),
             f"Codex {version} was not accepted, and nothing else was changed")
        print(f"accepted Codex {version} for {ROLLOUT_PARSER}")
    else:
        print(f"Codex {version} matches {ROLLOUT_PARSER}; re-run with --accept to record it")
    return 0


def cmd_gate(args) -> int:
    run = Run(args.run)
    run.config()
    report = Report()
    if not args.publish:
        with contextlib.suppress(Unverifiable):
            print_policy(run)
        facts = readiness(run, report, at_publication=False)
        pointer = run.dir / "APPROVAL"
        if facts and probe(pointer):
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
    with Lock(run.dir) as lock:
        prepare(run)
        with contextlib.suppress(Unverifiable):
            print_policy(run)
        facts = readiness(run, report, at_publication=True)
        if report.failures or facts is None:
            print(f"NOT APPROVED: {len(report.failures)} check(s) failed")
            lock.done = "the gate found the plan NOT APPROVED (see the output above)"
            return 1
        record = {"schema": "planloop-approval/1", **facts, "approved_at": iso(now())}
        data = canon(record)
        name = f"approval-r{facts['revision']:03d}-{sha(data)[:12]}.json"
        try:
            write_new(run.dir / "approvals" / name, data)
        except OSError as exc:
            left = f"a partial record {name} remains unreferenced" if os.path.lexists(run.dir / "approvals" / name) \
                else "no approval record was written"
            raise Unverifiable(f"could not write {run.dir / 'approvals' / name} ({exc}); this approval was not "
                               f"published: {left}, APPROVAL is unchanged and Beads records no approval candidate for it; once "
                               f"{run.dir / 'approvals'} can be written, run `gate --run {run.id} --publish` "
                               "again") from exc
        crash_point("approval_pending")
        args.interrupted = f"the approval record {name} is written and unreferenced, and APPROVAL is unchanged: run " \
            f"`gate --run {run.id} --publish` again"
        bead = run.run_bead()
        run.beads.update(bead, {"planloop_approval_candidate": sha(data)})
        crash_point("beads_candidate")
        again = Report()
        try:
            facts_again = readiness(run, again, at_publication=True)
        except Unreadable as exc:
            raise Unreadable(exc.what, exc.error, f"this approval was not published: the pending record {name} "
                             f"stays unreferenced and APPROVAL is unchanged; once it can be read, run `gate --run "
                             f"{run.id} --publish` again") from exc.error
        if facts_again != facts or again.failures:
            print("NOT APPROVED: inputs changed while publishing; the pending record stays unreferenced")
            lock.done = "the gate found the plan NOT APPROVED (see the output above)"
            return 1
        try:
            write_atomic(run.dir / "APPROVAL", canon({"schema": "planloop-approval-pointer/1", "record": name,
                                                      "sha256": sha(data)}))
        except OSError as exc:
            raise Unverifiable(f"could not write {run.dir / 'APPROVAL'} ({exc}); this approval was not published: "
                               f"the pending record {name} stays unreferenced and APPROVAL is unchanged; once "
                               f"{run.dir} can be written, run `gate --run {run.id} --publish` again") from exc
        crash_point("approval_pointer")
        args.interrupted = f"APPROVAL names {name}, and Beads may not record it yet: run `gate --run {run.id} " \
            "--publish` again, which publishes the approval afresh"
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
        try:
            return handlers[args.command](args)
        except BaseException:
            if os.environ.get("PLANLOOP_DEBUG") == "1":
                with contextlib.suppress(OSError):
                    sys.stdout.flush()
                traceback.print_exc()
            raise
    except (Fail, Unverifiable, Conflict) as exc:
        sys.stdout.flush()
        print(f"{'FAIL' if isinstance(exc, NotFile) else type(exc).__name__.upper()}  {exc}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        with contextlib.suppress(OSError):
            sys.stdout.flush()
        cause = f"{exc.filename} can be read and written" if exc.filename else "its cause is cleared"
        print(f"UNVERIFIABLE  {exc}; what this command had written stands: "
              + getattr(args, "interrupted", f"run it again once {cause}, it re-checks what is on disk"),
              file=sys.stderr)
        return Unverifiable.code
    except KeyboardInterrupt:
        with contextlib.suppress(OSError):
            sys.stdout.flush()
        print("INTERRUPTED  stopped by SIGINT before the command finished; what it had written stands: "
              + getattr(args, "interrupted", "run it again, it re-checks what is on disk"), file=sys.stderr)
        return 130
    except MALFORMED as exc:
        with contextlib.suppress(OSError):
            sys.stdout.flush()
        command = f"{args.command} {args.action}" if args.command == "findings" else args.command
        print(f"FAIL  {command}: a record it read is malformed ({type(exc).__name__}: {exc}); it stopped there, and "
              "what it had written before stands: " + getattr(args, "interrupted", "repair or restore that record, "
                                                              "then run the command again, it re-checks what is on "
                                                              "disk")
              + ("" if os.environ.get("PLANLOOP_DEBUG") == "1" else " (PLANLOOP_DEBUG=1 prints where it stopped)"),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
