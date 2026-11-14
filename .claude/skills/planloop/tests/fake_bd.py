#!/usr/bin/env python3
"""
Fake `bd` for planloop tests (quartz-rs-lur). Implements the subset planloop
uses, with bd 1.2.2's observed behaviour: `show` of a missing id exits 1 with
{"error": "no issues found matching the provided IDs"}; `create --parent`
allocates <parent>.<n>; --metadata JSON keeps strings while --set-metadata
coerces digits to integers and true/false to booleans, as bd 1.2.2 does. State lives in the JSON
file named by FAKE_BD_DB. Fault injection through FAKE_BD_FAULTS, a JSON list
consumed one entry per matching call:
  {"op": "create", "mode": "lost_reply"}   write lands, exit 1, no output
  {"op": "create", "mode": "race"}         another writer creates the same
                                           logical key first, then ours lands
  {"op": "create", "mode": "steal"}        another writer's record lands, ours
                                           does not
  {"op": "update", "mode": "dropped"}      exit 0, nothing written
  {"op": "update", "mode": "lost_reply"}   write lands, exit 1
  {"op": "show", "mode": "commit"}         `git commit -am` in the cwd first
  {"op": "list", "mode": "fail"}           exit 1 without output
  {"op": "list", "mode": "pause:<path>"}   touch <path>.waiting, wait until <path> exists, then list
"""
import json
import os
import sys
import time
import uuid


def db_load():
    with open(os.environ["FAKE_BD_DB"]) as f:
        return json.load(f)


def db_save(db):
    with open(os.environ["FAKE_BD_DB"], "w") as f:
        json.dump(db, f)


def fault(db, op):
    faults = db.setdefault("faults", [])
    for i, item in enumerate(faults):
        if item["op"] == op:
            faults.pop(i)
            return item["mode"]
    return None


def pause(db, mode):
    path = mode[len("pause:"):]
    db_save(db)
    open(path + ".waiting", "w").close()
    while not os.path.exists(path):
        time.sleep(0.05)
    return db_load()


def opt(args, name, default=None):
    if name in args:
        return args[args.index(name) + 1]
    return default


def opts(args, name):
    return [args[i + 1] for i, a in enumerate(args) if a == name]


def new_child(db, parent, title, kind, meta):
    db["counters"][parent] = db["counters"].get(parent, 0) + 1
    bead_id = f"{parent}.{db['counters'][parent]}"
    db["issues"][bead_id] = {"id": bead_id, "title": title, "issue_type": kind, "status": "open",
                             "parent": parent, "metadata": meta, "description": "", "notes": "",
                             "acceptance_criteria": "", "design": ""}
    return bead_id


def main():
    args = sys.argv[1:]
    db = db_load()
    if "FAKE_BD_FAULTS" in os.environ and not db.get("faults_loaded"):
        db["faults"] = json.loads(os.environ["FAKE_BD_FAULTS"])
        db["faults_loaded"] = True
    cmd = args[0]
    if cmd == "show":
        if fault(db, "show") == "commit":
            import subprocess
            db_save(db)
            subprocess.run(["git", "commit", "-qam", "concurrent commit"], check=True, capture_output=True)
        issue = db["issues"].get(args[1])
        if issue is None:
            print(json.dumps({"error": "no issues found matching the provided IDs", "schema_version": 1}))
            db_save(db)
            return 1
        print(json.dumps([issue]))
    elif cmd == "list":
        mode = fault(db, "list") or ""
        if mode.startswith("pause:"):
            db = pause(db, mode)
        if mode == "fail":
            db_save(db)
            print("fake bd: transient failure", file=sys.stderr)
            return 1
        out = list(db["issues"].values())
        parent = opt(args, "--parent")
        if parent:
            out = [i for i in out if i.get("parent") == parent]
        for field in opts(args, "--metadata-field"):
            k, v = field.split("=", 1)
            out = [i for i in out if i["metadata"].get(k) == v]
        print(json.dumps(out))
    elif cmd == "create":
        parent, title, kind = opt(args, "--parent"), opt(args, "--title"), opt(args, "--type", "task")
        meta = json.loads(opt(args, "--metadata", "{}"))
        mode = fault(db, "create")
        if mode in ("race", "steal"):
            other = dict(meta, planloop_write=uuid.uuid4().hex)
            new_child(db, parent, title, kind, other)
            if mode == "steal":
                db_save(db)
                return 1
        bead_id = new_child(db, parent, title, kind, meta)
        db_save(db)
        if mode == "lost_reply":
            return 1
        print(bead_id)
        return 0
    elif cmd == "update":
        issue = db["issues"].get(args[1])
        if issue is None:
            return 1
        mode = fault(db, "update")
        if mode != "dropped":
            for item in opts(args, "--set-metadata"):
                k, v = item.split("=", 1)
                issue["metadata"][k] = int(v) if v.isdigit() else {"true": True, "false": False}.get(v, v)
            if "--status" in args:
                issue["status"] = opt(args, "--status")
            for field in ("--notes", "--description", "--title"):
                if field in args:
                    issue[field[2:]] = opt(args, field)
        db_save(db)
        return 1 if mode == "lost_reply" else 0
    elif cmd == "close":
        issue = db["issues"].get(args[1])
        if issue is None:
            return 1
        issue["status"] = "closed"
        issue["close_reason"] = opt(args, "--reason", "")
    else:
        print(f"fake bd: unsupported {cmd}", file=sys.stderr)
        return 2
    db_save(db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
