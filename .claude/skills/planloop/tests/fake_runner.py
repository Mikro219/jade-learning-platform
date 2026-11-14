#!/usr/bin/env python3
"""
Fake claudex-loop runner for planloop tests (quartz-rs-lur). Accepts the
`review` arguments planloop's dispatch passes and writes the artifact set the
real runner.py 2.1.0 writes (result.json, command.json, prompt.txt with the
runner's exact layout, reply.txt, stdout.txt events, stderr.txt,
schema.json), plus a Codex rollout built from the real-shape fixture
fixtures/codex-0.156.1-rollout-shape.json. The review response comes from the
file named by FAKE_REVIEW; FAKE_MODE (comma-separated) injects faults:
  rollout_effort=<e>  rollout records another effort than requested
  resume              invocation resumes an earlier session
  wrong_bundle        prompt carries another bundle hash
  wrong_thread        event stream names another session
  malformed_reply     reply.txt is not JSON
  dup_key_result      result.json has a duplicate key
  no_session          result.json lacks session_id
  no_rollout          no rollout file is written
  rollout_version=<v> result.json reports another CLI version
  second_user_turn    rollout holds an earlier user turn
  context_turn=<v>    a separate pre-prompt context turn (AGENTS.md wrapper + environment_context), as
                      codex-cli 0.156.1 sends since 2026-10-24: agents (the snapshot's own AGENTS.md),
                      tampered (AGENTS.md text differs), extra (an additional item), elsewhere (another cwd)
  live_read           a tool call reads the live checkout (FAKE_LIVE_REPO)
  output_mentions_live  command output and reasoning mention the live path (not a read)
  sibling_read        a command climbs out of the private snapshot with ..
  relative_parent     an ordinary `cd src && cat ../docs/...` inside the snapshot
  codex_home          a command lists ~/.codex
  relative_state_read  a relative path climbs out to planloop's state directory
  state_read          a command reads planloop's state directory by absolute path
  failed              runner status failed
  touch=<path>        append to <path> in the live checkout during review
  add=<path>          create <path> in the live checkout during review
  delete=<path>       delete <path> from the live checkout during review
  bead_text=<id>      change bead <id>'s description during review
  bead_notes=<id>     change bead <id>'s notes during review
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-0.156.1-rollout-shape.json"
INSTRUCTIONS = "You are the independent reviewer. (fake runner instructions)\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode")
    for a in ("--host", "--repo", "--plan", "--effort", "--timeout", "--artifacts", "--feedback", "--model"):
        p.add_argument(a)
    args = p.parse_args()
    modes = dict((m.split("=", 1) + [""])[:2] for m in os.environ.get("FAKE_MODE", "").split(",") if m)
    repo = Path(args.repo).resolve()
    plan = (repo / args.plan).resolve()
    run_dir = Path(tempfile.mkdtemp(prefix="claudex-", dir=args.artifacts))
    body = plan.read_bytes()
    plan_sha = hashlib.sha256(body).hexdigest()
    session = str(uuid.uuid4())
    feedback = Path(args.feedback).read_text(encoding="utf-8")
    if "wrong_bundle" in modes:
        feedback = feedback.replace("sha256=", "sha256=0" , 1)
    prompt = INSTRUCTIONS + f"\nPLAN PATH: {plan}\nPLAN SHA256: {plan_sha}\n"
    prompt += "<plan>\n" + body.decode("utf-8-sig") + "\n</plan>\n"
    prompt += "\nHOST DISPOSITIONS / FIX REQUEST:\n" + feedback
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    exe = "/fake/codex"
    argv = [exe, "exec"] + (["resume", str(uuid.uuid4())] if "resume" in modes else [])
    argv += ["-s", "read-only", "-c", 'approval_policy="never"', "--json", "-o", str(run_dir / "reply.txt"),
             "--skip-git-repo-check", "--output-schema", str(run_dir / "schema.json")]
    if args.model:
        argv += ["-m", args.model]
    argv += ["-c", f'model_reasoning_effort="{args.effort}"', "-"]
    (run_dir / "command.json").write_text(json.dumps(argv, indent=2))
    (run_dir / "schema.json").write_text("{}")
    (run_dir / "stderr.txt").write_text("")
    response = json.loads(Path(os.environ["FAKE_REVIEW"]).read_text())
    (run_dir / "reply.txt").write_text("{not json" if "malformed_reply" in modes else json.dumps(response))
    live = os.environ.get("FAKE_LIVE_REPO", "")
    command = f"cat {live}/src/a.rs" if "live_read" in modes else "cat src/a.rs"
    if "sibling_read" in modes:
        command = "ls ../.. && cat ../../*/repo/.planloop-bundle/plan.md"
    if "relative_parent" in modes:
        command = "cd src && sed -n 1,80p ../docs/req.md && ls .."
    if "codex_home" in modes:
        command = "ls ~/.codex/sessions"
    if "relative_state_read" in modes:
        command = "cat ../../../planloop/qz-abc.pl1/calls/call-001-a1/reply.txt"
    if "state_read" in modes:
        command = f"cat {os.environ['PLANLOOP_STATE']}/qz-abc.pl1/calls/call-001-a1/claudex-x/reply.txt"
    output = f"plans/x.md:3: see {live}/backend\n" if "output_mentions_live" in modes else ""
    events = [{"type": "thread.started", "thread_id": str(uuid.uuid4()) if "wrong_thread" in modes else session},
              {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "item_0", "type": "command_execution", "command": command,
                                                  "aggregated_output": output, "exit_code": 0, "status": "completed"}},
              {"type": "item.completed", "item": {"id": "item_1", "type": "reasoning",
                                                  "text": f"thinking about {live}" if output else "thinking"}},
              {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}]
    (run_dir / "stdout.txt").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    for key, value in modes.items():
        target = Path(live) / value if value else None
        if key == "touch":
            with open(target, "a") as f:
                f.write("changed during review\n")
        elif key == "add":
            target.write_text("new file\n")
        elif key == "delete":
            target.unlink()
        elif key in ("bead_text", "bead_notes"):
            db = json.loads(Path(os.environ["FAKE_BD_DB"]).read_text())
            db["issues"][value]["description" if key == "bead_text" else "notes"] += " (edited)"
            Path(os.environ["FAKE_BD_DB"]).write_text(json.dumps(db))
    if "no_rollout" not in modes:
        write_rollout(session, repo, prompt, modes.get("rollout_effort") or args.effort, args.model, modes, live)
    record = {"status": "failed" if "failed" in modes else "completed", "mode": "review", "provider": "codex",
              "roles": {}, "repo": str(repo), "plan": str(plan), "plan_sha256": plan_sha,
              "requested_model": args.model, "requested_effort": args.effort, "base": None, "snapshot": None,
              "previous": "/old/result.json" if "resume" in modes else None, "started_at": 0,
              "artifacts": str(run_dir), "cli_version": "codex-cli " + modes.get("rollout_version", "0.156.1"),
              "executable": [exe], "exit_code": 0, "response": response, "usage": {"input_tokens": 10},
              "observed_models": [], "elapsed_seconds": 1.0}
    if "no_session" not in modes:
        record["session_id"] = session
    if "failed" in modes:
        record["error"] = "codex exited 1"
    text = json.dumps(record, indent=2)
    if "dup_key_result" in modes:
        text = text.replace('"mode": "review",', '"mode": "review", "mode": "review",', 1)
    (run_dir / "result.json").write_text(text)
    print(json.dumps({"provider": "codex", "artifacts": str(run_dir)}))
    return 0 if record["status"] == "completed" else 1


def write_rollout(session, repo, prompt, effort, model, modes, live):
    shape = json.loads(FIXTURE.read_text())["records"]
    rows = []
    for record in shape:
        row = json.loads(json.dumps(record))
        p = row["payload"]
        if row["type"] == "session_meta":
            p.update(id=session, session_id=session, cwd=str(repo), runtime_workspace_roots=[str(repo)])
        elif row["type"] == "turn_context":
            p.update(cwd=str(repo), workspace_roots=[str(repo)], effort=effort, model=model or "gpt-6-astra")
            p["collaboration_mode"]["settings"].update(reasoning_effort=effort, model=model or "gpt-6-astra")
        elif row["type"] == "response_item" and p.get("type") == "message":
            p["content"][1]["text"] = prompt
            if "second_user_turn" in modes:
                earlier = json.loads(json.dumps(row))
                earlier["payload"]["content"][1]["text"] = "an earlier conversation"
                rows.append(earlier)
            if "context_turn" in modes:
                variant = modes["context_turn"]
                cwd = "/elsewhere" if variant == "elsewhere" else str(repo)
                agents = (repo / "AGENTS.md").read_text() + ("tampered\n" if variant == "tampered" else "")
                env = (f"<environment_context>\n  <cwd>{cwd}</cwd>\n  <shell>bash</shell>\n"
                       "</environment_context>")
                items = [f"# AGENTS.md instructions for {cwd}\n\n<INSTRUCTIONS>\n{agents}\n</INSTRUCTIONS>", env]
                if variant == "extra":
                    items.append("an earlier conversation")
                context = json.loads(json.dumps(row))
                context["payload"]["content"] = [{"type": "input_text", "text": t} for t in items]
                rows.append(context)
        elif row["type"] == "response_item" and p.get("type") == "custom_tool_call":
            p["input"] = f"cat {live}/src/a.rs" if "live_read" in modes else "cat src/a.rs"
        rows.append(row)
    root = Path(os.environ["PLANLOOP_CODEX_SESSIONS"]) / "2026" / "10" / "22"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"rollout-2026-10-22T00-00-00-{session}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


if __name__ == "__main__":
    sys.exit(main())
