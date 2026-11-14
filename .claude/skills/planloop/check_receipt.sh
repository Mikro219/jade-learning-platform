#!/usr/bin/env bash
# planloop approval check (quartz-rs-lur; kept under its old name because
# CLAUDE.md and older plans cite it). It no longer reads a host-written
# RECEIPT line: it runs `scripts/planloop.py gate`, which re-derives the
# final-gate receipt from the runner's artifacts and Codex's own session
# record and checks every readiness condition listed in SKILL.md.
#
# Usage:
#   .claude/skills/planloop/check_receipt.sh --run <bead>.pl<N> [--publish]
# Exit 0 = the plan is approved (with --publish: approval published now);
# 1 = a check failed (printed); 2 = unverifiable input; 3 = conflict.
set -uo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/scripts/planloop.py" gate "$@"
