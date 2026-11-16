#!/usr/bin/env bash
# `pnpm ci:local` (plan X1): the CI stages, in order, on this machine, with a timing per stage.
# The workflow (.github/workflows/ci.yml) runs the same pnpm scripts, one job each, in parallel:
#   ci:check     lint, type check, db:check against the base (tools/ci/base-ref.ts), pnpm test
#   ci:e2e       Playwright on Chromium and WebKit
#   test:infra   the image (built once, through pnpm ci:image) and the production stack
#   ci:compat    the base's app and integration tests on the head's schema (tools/ci/migration-compat.sh)
# Every stage runs even when an earlier one failed, as the parallel jobs would; the exit status is
# non-zero when any stage failed. It needs what the stages need: `.env` (`pnpm env:init`), the
# development database (`pnpm db:up`) and Docker. Locally the base is the merge base of HEAD and
# main (X1a); JADE_CI_BASE, when set, names it instead.
set -uo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

stages=(ci:check ci:e2e test:infra ci:compat)
results=()
failed=0
started=$(date +%s)

fmt() { printf '%d:%02d' $(($1 / 60)) $(($1 % 60)); }

summary() {
	echo "ci:local: stage       status   time"
	for line in ${results[@]+"${results[@]}"}; do echo "ci:local: $line"; done
	echo "ci:local: total $(fmt $(($(date +%s) - started)))"
}

# Ctrl-C or a TERM stops the whole run, not only the current stage. Each stage runs in a session
# and process group of its own (`setsid -w ... &`) and is waited for, so the trap runs at once
# (bash defers traps while a foreground child runs), and the terminal's Ctrl-C reaches this script
# only. The trap sends TERM to the stage's whole group (pnpm and the script it runs, such as
# tools/ci/migration-compat.sh, whose own handlers clean up), waits up to 15 s for the group to go,
# KILLs what is left, and exits. As in tools/ci/lib/supervise.sh, `&` must not make the stage a
# group leader, so this script refuses job control.
case $- in
*m* | *i*)
	echo "ci:local: refusing to run under job control or interactively (shell flags $-)" >&2
	exit 2
	;;
esac
stage_pid=""
stop() {
	trap '' INT TERM
	if [ -n "$stage_pid" ]; then
		kill -TERM -- "-$stage_pid" 2>/dev/null || kill -TERM "$stage_pid" 2>/dev/null
		local _
		for _ in $(seq 1 75); do
			kill -0 -- "-$stage_pid" 2>/dev/null || break
			sleep 0.2
		done
		kill -KILL -- "-$stage_pid" 2>/dev/null
		wait "$stage_pid" 2>/dev/null
	fi
	summary
	echo "ci:local: $2" >&2
	exit "$1"
}
trap 'stop 130 interrupted' INT
trap 'stop 143 terminated' TERM

for stage in "${stages[@]}"; do
	echo "ci:local: == $stage"
	t=$(date +%s)
	setsid -w pnpm "$stage" &
	stage_pid=$!
	wait "$stage_pid"
	status=$?
	stage_pid=""
	took=$(($(date +%s) - t))
	results+=("$(printf '%-11s exit %-3d %s' "$stage" "$status" "$(fmt "$took")")")
	if [ "$status" -ne 0 ]; then failed=1; fi
	# A stage stopped by SIGINT or SIGTERM: stop here, as the signal asked.
	if [ "$status" -eq 130 ] || [ "$status" -eq 143 ]; then
		summary
		echo "ci:local: $stage was interrupted (exit $status); later stages not run" >&2
		exit "$status"
	fi
done

summary
exit "$failed"
