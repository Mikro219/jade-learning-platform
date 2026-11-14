#!/usr/bin/env python3
"""
Fake Claude Code reviewer for planloop's claude backend tests (2026-11-14). It
writes what a background Plan agent leaves behind, agent-<id>.jsonl and
agent-<id>.meta.json, built from the real record shapes in
fixtures/claude-code-2.1.325-subagent-shape.json (first user turn, the
SubagentHandback system reminder, attachments, API requests with
params.output_config.effort, assistant turns carrying model, requestedModel,
effort and perTurnEffort, tool results, the handback and its acknowledgement).
The tests pass the prompt planloop's dispatch wrote, the private copy, the
review response and the faults to inject.
"""
import copy as copying
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "claude-code-2.1.325-subagent-shape.json"


def fill(value, subs: dict):
    if isinstance(value, dict):
        return {k: fill(v, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, subs) for v in value]
    if isinstance(value, str) and value in subs:
        return subs[value]
    return value


def default_tools(copy: str) -> list:
    return [("Read", {"file_path": f"{copy}/.planloop-bundle/plan.md"}),
            ("Read", {"file_path": f"{copy}/.planloop-call/feedback.md"}),
            ("Bash", {"command": f"cd {copy} && command grep -rn checksum docs src | head -20",
                      "description": "Search the snapshot for the checksum rule"}),
            ("Grep", {"pattern": "checksum", "path": f"{copy}/docs"}),
            ("Glob", {"pattern": "**/*.rs", "path": copy})]


def write(directory: Path, name: str, prompt: str, message, copy: str, cwd: str, tools=None, model="claude-opus-5-5",
          alias="opus", effort="high", agent_type="Plan", finished=True, later_user=False, drop_effort=False,
          delivered=True, final="handback") -> Path:
    shape = json.loads(FIXTURE.read_text())
    records = shape["records"]
    first, reminder, attachments = records[0], records[1], records[2:6]
    request, assistant, hook, result, handback, ack = (records[6], records[7], records[8], records[9], records[14],
                                                       records[15])
    subs = {"<<ID2>>": name, "<<MODEL>>": model, "<<CWD>>": cwd}
    rows = []

    def turn(block, n):
        row = fill(copying.deepcopy(request), subs)
        row["params"]["output_config"]["effort"] = effort
        rows.append(row)
        row = fill(copying.deepcopy(assistant), subs)
        row["message"]["content"] = [block]
        row["message"]["stop_reason"] = "tool_use" if block["type"] == "tool_use" else "end_turn"
        row["effort"] = row["perTurnEffort"] = effort
        if drop_effort:
            row.pop("effort")
            row.pop("perTurnEffort")
        row["requestedModel"] = model
        rows.append(row)

    row = fill(copying.deepcopy(first), subs)
    row["message"]["content"] = prompt
    rows.append(row)
    row = fill(copying.deepcopy(reminder), subs)
    row["message"]["content"] = "<system-reminder>\nYour final report is delivered through SubagentHandback.\n" \
        "</system-reminder>"
    rows.append(row)
    rows += [fill(copying.deepcopy(a), subs) for a in attachments]
    for n, (tool, value) in enumerate(tools if tools is not None else default_tools(copy)):
        tid = f"toolu_{name}_{n}"
        turn({"type": "tool_use", "id": tid, "name": tool, "input": value, "caller": {"type": "direct"}}, n)
        rows.append(fill(copying.deepcopy(hook), subs))
        row = fill(copying.deepcopy(result), subs)
        row["message"]["content"] = [{"tool_use_id": tid, "type": "tool_result", "content": "ok", "is_error": False}]
        rows.append(row)
    if later_user:
        row = fill(copying.deepcopy(first), subs)
        row["parentUuid"] = "earlier"
        row["message"]["content"] = "One more thing: also check the importer."
        rows.append(row)
    text = message if isinstance(message, str) else json.dumps(message)
    if final == "handback":
        tid = f"toolu_{name}_handback"
        turn({"type": "tool_use", "id": tid, "name": "SubagentHandback", "input": {"message": text},
              "caller": {"type": "direct"}}, -1)
        row = fill(copying.deepcopy(ack), subs)
        row["message"]["content"] = [{"tool_use_id": tid, "type": "tool_result", "content": [
            {"type": "text", "text": '{"success":true,"message":"Report delivered to your caller."}' if delivered
             else '{"success":false}'}]}]
        rows.append(row)
    else:
        turn({"type": "text", "text": text}, -1)
    path = Path(directory) / f"agent-{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = fill(copying.deepcopy(shape["meta"]), {"<<MODEL_ALIAS>>": alias, "<<AGENT_TYPE>>": agent_type,
                                                  "<<EFFORT>>": effort})
    if finished:
        meta["finished"] = True
    else:
        meta.pop("finished", None)
    (Path(directory) / f"agent-{name}.meta.json").write_text(json.dumps(meta))
    return path
