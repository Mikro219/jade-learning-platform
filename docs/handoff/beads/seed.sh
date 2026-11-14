#!/usr/bin/env bash
# Seed the JADE build plan into beads. Run from the repo root after `bd init`.
# Safe to re-run: it refuses to seed twice.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN="$HERE/plan.json"
MAP="$HERE/id-map.json"
EXPECTED="$HERE/expected.json"

command -v bd >/dev/null || { echo "bd is not installed. See prompts/01-beads-setup.md step 2." >&2; exit 1; }
[ -f "$PLAN" ] || { echo "Missing $PLAN" >&2; exit 1; }

if [ -f "$MAP" ]; then
  echo "Already seeded ($MAP exists). Delete it only if you also wiped the beads database." >&2
  exit 1
fi

echo "== Dry run"
DRY="$(bd create --graph "$PLAN" --dry-run)"
printf '%s\n' "$DRY" | sed -n '1p'

echo "== Creating issues"
TMP="$(mktemp)"
bd create --graph "$PLAN" --json > "$TMP"
mv "$TMP" "$MAP"

echo "== Verifying"
python3 - "$MAP" "$EXPECTED" "$PLAN" <<'PY'
import json, subprocess, sys
ids = json.load(open(sys.argv[1]))["ids"]
exp = json.load(open(sys.argv[2]))
plan = json.load(open(sys.argv[3]))
want = exp["phases"] + exp["tasks"]
assert len(ids) == want == len(plan["nodes"]), f"created {len(ids)} issues, expected {want}"
ready = json.loads(subprocess.check_output(
    ["bd", "ready", "--exclude-type", "epic", "--limit", "0", "--json"]))
got = sorted(i["id"] for i in ready)
exp_ready = sorted(ids[k] for k in exp["initially_ready_tasks"])
assert got == exp_ready, f"ready set differs:\n got {got}\n exp {exp_ready}"
print(f"OK: {exp['phases']} epics, {exp['tasks']} tasks, {exp['edges']} dependencies.")
print("Ready now (plan key -> bead id):")
for k in exp["initially_ready_tasks"]:
    print(f"  {k:20s} {ids[k]}")
PY

bd dep cycles
echo "== Done. Plan-key to bead-id map: $MAP (commit it)."
