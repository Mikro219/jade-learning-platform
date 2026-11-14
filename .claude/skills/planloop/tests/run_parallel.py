#!/usr/bin/env python3
"""
The runner behind the planloop test suite (stdlib only). test_planloop.py's
own entry point calls main() here, so the suite has one command:
  python3 .claude/skills/planloop/tests/test_planloop.py [names...] [-j N] [--times FILE] [--timeout S]
                                                         [--allow-skips] [--serial]
Names are unittest names (tests.test_planloop, tests.test_planloop.Gate, ...;
the whole suite when none is given), loaded the way
`python3 -m unittest tests.test_planloop` loads them.

By default every test runs in its own Python process and session with its own
temporary directory (and its own directory under PLANLOOP_TEST_TMP when that is
set), at most -j at a time (one per CPU), longest first when --times names the
JSON of seconds per test that a green run rewrites, and the run reports like
unittest: one line per test, the output of every test that did not pass,
`Ran N tests in Xs`, then `OK` or `FAILED (...)`. --serial runs the same
selection in this process with unittest's own runner (verbosity 2) instead,
for debugging or a host without room for parallel systemd scopes; -j, --times
and --timeout do not apply to it.

Either way the run fails (exit 1) on a failure, an error, an unexpected
success, a skip (unless --allow-skips: this host skips nothing, so a skip means
the host lost something the tests need), or anything a test leaves in its
temporary directories; in parallel it also fails on a test process that ends
without a usable result (killed, crashed, or stopped after --timeout seconds).
Selecting no test exits 5, and an unknown option exits 2. In parallel, tests
that assert on state the whole host shares run one at a time after the others:
those that reach, through the helpers of their module, code naming a marker in
ALONE. Units named planloop-* that appeared during the run and are still
listed after it are a warning, not a failure, because another run on this
host may own them.

SIGINT, SIGTERM and SIGHUP stop the run, as does any error in the runner:
each test process gets one SIGTERM, which the test module turns into
KeyboardInterrupt so its fixture sweep runs, then its process group is killed
if it has not ended in GRACE seconds; an interrupted run exits 130.
"""
import argparse
import contextlib
import inspect
import itertools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALONE = ("list-units",)
COUNTS = ("failures", "errors", "skipped", "expectedFailures", "unexpectedSuccesses")
SHOWN = {"expectedFailures": "expected failures", "unexpectedSuccesses": "unexpected successes"}
WORDS = (("errors", "ERROR"), ("failures", "FAIL"), ("unexpectedSuccesses", "unexpected success"),
         ("skipped", "skipped"), ("expectedFailures", "expected failure"))
STOP = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
GRACE = 30


def load(names):
    sys.path[0] = str(ROOT)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(names)
    if loader.errors:
        sys.exit("\n".join(loader.errors))
    return suite


def flat(suite):
    for test in suite:
        yield from flat(test) if isinstance(test, unittest.TestSuite) else (test,)


def shared(tests):
    source = {}
    for name in {type(t).__module__ for t in tests}:
        for thing in vars(sys.modules[name]).values():
            for key, value in ({thing.__name__: thing} if inspect.isfunction(thing) else
                               vars(thing) if inspect.isclass(thing) else {}).items():
                if inspect.isfunction(value) and value.__module__ == name:
                    with contextlib.suppress(OSError, TypeError):
                        source[key] = source.get(key, "") + inspect.getsource(value)
    marked = {key for key, text in source.items() if any(a in text for a in ALONE)}
    while marked:
        calls = re.compile(r"\b(?:%s)\(" % "|".join(map(re.escape, marked)))
        more = {key for key, text in source.items() if key not in marked and calls.search(text)}
        if not more:
            break
        marked |= more
    return [t.id() for t in tests if t._testMethodName in marked]


def units():
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        listed = subprocess.run(["systemctl", "--user", "list-units", "planloop-*", "--all", "--no-legend", "--plain"],
                                capture_output=True, text=True, timeout=30)
        if listed.returncode == 0:
            return {line.split()[0] for line in listed.stdout.splitlines() if line.split()}
    return None


def one(test_id, out):
    signal.pthread_sigmask(signal.SIG_UNBLOCK, STOP)
    result = unittest.TextTestRunner(verbosity=2).run(load([test_id]))
    record = {key: len(getattr(result, key)) for key in COUNTS} | {"ran": result.testsRun}
    Path(out).write_text(json.dumps(record))
    sys.exit(not result.wasSuccessful())


def start(test_id, n, spots):
    env = dict(os.environ)
    for key, base in spots.items():
        (base / str(n)).mkdir()
        env[key] = str(base / str(n))
    log, out = open(spots["TMPDIR"] / f"{n}.log", "wb+"), spots["TMPDIR"] / f"{n}.json"
    proc = subprocess.Popen([sys.executable, __file__, "--one", test_id, str(out)], cwd=ROOT, env=env,
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return proc, test_id, log, out, time.monotonic()


def stop(jobs):
    for job in jobs:
        job[0].send_signal(signal.SIGTERM)
    end = time.monotonic() + GRACE
    for job in jobs:
        try:
            job[0].wait(max(end - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                os.killpg(job[0].pid, signal.SIGKILL)
            job[0].wait()


def finish(job, why, tally, allow_skips):
    proc, test_id, log, out, began = job
    try:
        if why:
            raise ValueError(why)
        record = json.loads(out.read_text())
        counts = {key: int(record[key]) for key in COUNTS}
        passed = not (counts["failures"] or counts["errors"] or counts["unexpectedSuccesses"])
        if record["ran"] != 1 and not (record["ran"] == 0 and any(counts.values())):
            raise ValueError(f"it ran {record['ran']} tests, not the one it was given")
        if passed != (proc.returncode == 0):
            raise ValueError(f"its result says the test {'passed' if passed else 'did not pass'}")
        said = ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        counts = dict.fromkeys(COUNTS, 0) | {"errors": 1}
        said = f"\nno usable result from the test process, which exited {proc.returncode}: {exc}\n"
    for key in COUNTS:
        tally["totals"][key] += counts[key]
    status = next((word for key, word in WORDS if counts[key]), "ok")
    name = test_id.rsplit(".", 1)[1]
    print(f"{name} ({test_id}) ... {status}", flush=True)
    tally["times"][test_id] = round(time.monotonic() - began, 1)
    if status in ("ERROR", "FAIL", "unexpected success") or status == "skipped" and not allow_skips:
        log.seek(0)
        tally["failed"].append(f"{'=' * 70}\n{status}: {name} ({test_id})\n{'-' * 70}\n"
                               f"{log.read().decode('utf-8', 'replace')}{said}")
    log.close()


def run(ids, args, spots, tally, running, jobs):
    queue = list(ids)
    while queue or running:
        while queue and len(running) < jobs:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOP)
            try:
                running.append(start(queue.pop(0), next(tally["count"]), spots))
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        for job in list(running):
            late = time.monotonic() - job[4] > args.timeout
            if late:
                stop([job])
            if job[0].poll() is not None:
                running.remove(job)
                finish(job, f"it had not ended after {args.timeout:g} seconds and was stopped" if late else None,
                       tally, args.allow_skips)
        time.sleep(0.02)


def serial(tests, spots):
    for key, base in spots.items():
        (base / "1").mkdir()
        os.environ[key] = str(base / "1")
    tempfile.tempdir = None
    return unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))


def tidy(spots):
    left = []
    for base in spots.values():
        here = sorted(str(p) for p in base.glob("*/*"))
        left += here
        if not here:
            shutil.rmtree(base, ignore_errors=True)
    if left:
        print(f"tests left files behind: {' '.join(left)}", file=sys.stderr)
    return left


def main():
    parser = argparse.ArgumentParser(prog="test_planloop.py", description="run the planloop tests, one process "
                                     "per test in parallel unless --serial")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--times", type=Path, help="JSON of seconds per test id: read to start the longest first, "
                        "rewritten after a green run")
    parser.add_argument("--timeout", type=float, default=900, help="seconds one test may take (default 900)")
    parser.add_argument("--allow-skips", action="store_true", help="do not fail the run on a skipped test")
    parser.add_argument("--serial", action="store_true", help="run in this process with unittest's own runner")
    parser.add_argument("--one", nargs=2, help=argparse.SUPPRESS)
    parser.add_argument("names", nargs="*", default=["tests.test_planloop"])
    args = parser.parse_args()
    if args.one:
        one(*args.one)
    sys.stdout.reconfigure(errors="replace")
    tests = list({t.id(): t for t in flat(load(args.names))}.values())
    if not tests:
        print(f"{'-' * 70}\nRan 0 tests in 0.000s\n\nNO TESTS RAN")
        sys.exit(5)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.default_int_handler)
    known = {}
    with contextlib.suppress(OSError, ValueError, AttributeError):
        known = {k: v for k, v in json.loads(args.times.read_text()).items() if isinstance(v, (int, float))}
    alone = shared(tests)
    ids = sorted((t.id() for t in tests if t.id() not in alone), key=lambda i: -known.get(i, 1e9))
    tally = {"totals": dict.fromkeys(COUNTS, 0), "failed": [], "times": {}, "count": itertools.count(1)}
    running, before, began = [], units(), time.monotonic()
    spots = {"TMPDIR": Path(tempfile.mkdtemp(prefix="planloop-par-"))}
    if os.environ.get("PLANLOOP_TEST_TMP"):
        spots["PLANLOOP_TEST_TMP"] = Path(tempfile.mkdtemp(prefix="planloop-par-", dir=os.environ["PLANLOOP_TEST_TMP"]))
    try:
        if args.serial:
            result = serial(tests, spots)
            totals = {key: len(getattr(result, key)) for key in COUNTS}
            bad = not result.wasSuccessful() or result.testsRun != len(tests)
        else:
            run(ids, args, spots, tally, running, max(args.jobs, 1))
            run(alone, args, spots, tally, running, 1)
            totals, times = tally["totals"], tally["times"]
            took, plural = time.monotonic() - began, "" if len(times) == 1 else "s"
            print("\n" + "\n".join(tally["failed"]) + f"{'-' * 70}\nRan {len(times)} test{plural} in {took:.3f}s\n")
            bad = bool(tally["failed"]) or len(times) != len(tests)
    except BaseException as exc:
        stop(running)
        tidy(spots)
        if not isinstance(exc, KeyboardInterrupt):
            raise
        print(f"\ninterrupted: {len(tally['times'])} of {len(tests)} tests reported", file=sys.stderr)
        sys.exit(130)
    refused = bool(totals["skipped"]) and not args.allow_skips
    if refused:
        print("a skipped test fails the run: pass --allow-skips to accept skips", file=sys.stderr)
    bad = bool(tidy(spots)) or bad or refused
    for _ in range(50):
        after = units()
        if before is None or after is None or not after - before:
            break
        time.sleep(0.1)
    if before is None or after is None:
        print("warning: systemctl --user could not list planloop-* units, so leftover units were not checked",
              file=sys.stderr)
    elif after - before:
        print("warning: units that appeared during the run are still listed (another run on this host may own "
              f"them): {' '.join(sorted(after - before))}", file=sys.stderr)
    if args.times and tally["times"] and not bad:
        args.times.write_text(json.dumps(known | tally["times"], indent=0, sort_keys=True))
    shown = ", ".join(f"{SHOWN.get(key, key)}={totals[key]}" for key in COUNTS if totals[key])
    if not args.serial or bad and result.wasSuccessful():
        print(("FAILED" if bad else "OK") + (f" ({shown})" if shown else ""))
    sys.exit(bad)


if __name__ == "__main__":
    main()
