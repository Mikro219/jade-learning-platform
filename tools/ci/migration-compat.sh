#!/usr/bin/env bash
# `pnpm ci:compat` (plan X4, INV5, OB53): does the previous app still work on the new schema?
#
#   pnpm ci:compat                 the base of tools/ci/base-ref.ts (JADE_CI_BASE in CI; locally the
#                                  merge base of HEAD and main, else HEAD~1)
#   pnpm ci:compat --base <ref>    that commit as the base
#   pnpm ci:compat --self-test     the harness itself, on the situation of Phase 2's first migration
#
# With no base, or a base without migrations/manifest.json, or a head whose manifest lists no file
# beyond the base's, there is nothing to compare: it says which and exits 0. Otherwise the base
# commit is checked out in a temporary git worktree, installed and built, and, on the cluster that
# this checkout's `.env` names (the development database, or the CI job's service container):
#   (1) the head's runner (this checkout's code, on the head's migrations/) migrates a fresh
#       database `jade_compat_<run id>_<n>` and a fresh template `jade_compat_tmpl_<run id>_<n>`;
#       the run stops red unless both ledgers then equal the head's manifest.json, name for name
#       and hash for hash, so the base's tests cannot be running on the base's schema;
#   (2) the base build (`node build`) starts on the fresh database and must answer /readyz 200: its
#       database is ahead of it (A3);
#   (3) the base's `integration` project runs with JADE_TEST_TEMPLATE naming the template (U7): its
#       global setup runs the base's migrate() on it, which must apply nothing, and its files clone
#       from it. Afterwards the template's ledger must still equal the head's manifest.
# tools/ci/compat.ts does the database and app half and exits with the code of the step that
# failed (COMPAT_EXIT there). Both databases and the worktrees are removed at the end, whatever
# happened, also on SIGINT or SIGTERM: every long child runs through run() of
# tools/ci/lib/supervise.sh, in a process group of its own, which a signal stops (TERM, then KILL)
# while the databases are dropped. A SIGKILL of this script with no INT or TERM before it cannot be
# handled and orphans the running children: a hosted runner discards its VM after the job, and
# locally the next run warns about the directories and databases left behind.
#
# The self-test (plan 12.1): the base is HEAD; the head is a temporary worktree of HEAD with the
# fixture migration of tests/infra/fixtures/migrations/ added to migrations/ and to its manifest,
# and that run must exit 0. A second run uses a breaking fixture instead, which revokes jade_app's
# SELECT on schema_migrations (the base app's readiness query and its baseline test both need it),
# and that run must be caught in step (2), /readyz 503 with `migrations` not ok, or in step (3),
# test files failing once the base's harness has started; any other failure fails the self-test.
#
# Output is fixed phrases, commits, database names, migration names and HTTP statuses: never a URL
# or a password.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

usage() {
	echo "usage: ci:compat [--base <ref> | --self-test]" >&2
	exit 2
}

mode=compat
base_args=()
case "${1-}" in
'') ;;
--base)
	[ -n "${2-}" ] && [ -z "${3-}" ] || usage
	base_args=(--base "$2")
	;;
--self-test)
	[ -z "${2-}" ] || usage
	mode=self-test
	;;
*) usage ;;
esac

# The pinned Node (INV9): pnpm puts it first on PATH for its scripts.
want="v$(cat .nvmrc)"
if [ "$(node --version)" != "$want" ]; then
	echo "ci:compat: node on PATH is $(node --version), not the pinned $want; run it as pnpm ci:compat" >&2
	exit 1
fi
if [ ! -f .env ]; then
	echo "ci:compat: no .env in this checkout; run pnpm env:init (and pnpm db:up) first" >&2
	exit 1
fi

# In CI the runner's Node from .nvmrc runs everything, so pnpm downloads no runtime (plan 6.1).
install_flags=(--frozen-lockfile)
# CI counts as set unless it is empty, "false" or "0" (as tools/ci/base-ref.ts reads it).
ci=${CI-}
case "${ci,,}" in
'' | false | 0) ;;
*) install_flags+=(--no-runtime) ;;
esac

# Earlier runs' leftovers are reported, never removed: they may belong to a run still going.
for dir in "${TMPDIR:-/tmp}"/jade-compat-*; do
	if [ -e "$dir" ]; then
		echo "ci:compat: warning: a directory of an earlier run remains (not removed): $dir" >&2
	fi
done

# shellcheck source=tools/ci/lib/supervise.sh
source tools/ci/lib/supervise.sh

# Set before the traps are installed (R4): cleanup reads them, and `work` is created only after
# supervise_init, so a signal can never leave a temporary directory behind.
work=""
worktrees=()
databases=()
in_step3=0

# compat.ts subcommands that read files only; every one that connects to the database goes
# through run() (`db`), so a signal is not held up by a connection attempt. The drop in cleanup
# runs in the foreground but in a session of its own (`setsid -w`): bash ignores INT and TERM
# during cleanup, but Node resets inherited signal dispositions at start-up, so without a session
# of its own a second Ctrl-C from the terminal would kill the drop (R1).
compat() { node tools/ci/compat.ts "$@"; }
db() { run node tools/ci/compat.ts "$@"; }
drop_databases() { setsid -w node tools/ci/compat.ts drop "$@"; }

# The EXIT handler of tools/ci/lib/supervise.sh calls this once, with INT and TERM ignored.
cleanup() {
	local status=$1
	# The running child is asked to stop first; the databases are dropped while it does (DROP
	# DATABASE ... WITH (FORCE) ends its sessions), then once more after it is gone, in case a
	# CREATE DATABASE in flight committed after the first drop. All fits a 10-second grace.
	signal_child TERM
	if [ "${#databases[@]}" -gt 0 ]; then
		drop_databases ${databases[@]+"${databases[@]}"}
	fi
	stop_child
	if [ "${#databases[@]}" -gt 0 ]; then
		drop_databases ${databases[@]+"${databases[@]}"}
	fi
	if [ "$in_step3" = 1 ]; then
		echo "ci:compat: note: interrupted in step 3, the base harness's own jade_t_* clone databases" \
			"may remain; the README's CI section shows how to list and drop them" >&2
	fi
	for tree in ${worktrees[@]+"${worktrees[@]}"}; do
		if ! git worktree remove --force --force "$tree" >/dev/null 2>&1; then
			rm -rf "$tree"
			echo "ci:compat: warning: could not remove the worktree $tree; its directory is gone," \
				"and \`git worktree prune\` clears its registration" >&2
		fi
	done
	if [ -n "$work" ]; then rm -rf "$work"; fi
	echo "ci:compat: exit $status"
}
supervise_init ci:compat cleanup
work=$(mktemp -d "${TMPDIR:-/tmp}/jade-compat-XXXXXXXX")
run_id=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')

elapsed() { printf '%ds' $(($(date +%s) - $1)); }

# Whether commit `$1` has migrations/manifest.json. It is called in `if !`, where set -e does not
# apply, so a git error ends the run explicitly instead of reading as "no manifest".
has_manifest() {
	local listed
	listed=$(git ls-tree --name-only "$1" -- migrations/manifest.json) || {
		echo "ci:compat: git ls-tree failed on $1" >&2
		exit 1
	}
	[ -n "$listed" ]
}

# Check out `$1` in a new worktree at `$2`, recorded before it is created.
add_worktree() {
	worktrees+=("$2")
	git worktree add --quiet --detach "$2" "$1"
}

# Check out, install and build the base `$1` at $work/base; it gets this checkout's `.env`, which
# names the same cluster.
prepare_base() {
	local t
	t=$(date +%s)
	add_worktree "$1" "$work/base"
	cp .env "$work/base/.env"
	run env -C "$work/base" pnpm install "${install_flags[@]}" >"$work/base-install.log" 2>&1 || {
		cat "$work/base-install.log" >&2
		echo "ci:compat: the base's pnpm install failed" >&2
		return 1
	}
	run env -C "$work/base" APP_VERSION=compat-base pnpm build >"$work/base-build.log" 2>&1 || {
		cat "$work/base-build.log" >&2
		echo "ci:compat: the base's build failed" >&2
		return 1
	}
	echo "ci:compat: base $1 checked out, installed and built ($(elapsed "$t"))"
}

# Steps (1) to (3) on the head's migrations at `$1/migrations` and the base at $work/base; the
# return status is compat.ts's code of the step that failed (COMPAT_EXIT).
run_compat() {
	local dir="$1/migrations" n="$2" fresh template t status=0
	fresh="jade_compat_${run_id}_${n}"
	template="jade_compat_tmpl_${run_id}_${n}"
	databases+=("$fresh" "$template")
	t=$(date +%s)
	db prepare "$dir" "$fresh" "$template" || return $?
	echo "ci:compat: step 1 done ($(elapsed "$t"))"
	t=$(date +%s)
	db readyz "$work/base" "$fresh" || return $?
	echo "ci:compat: step 2 done ($(elapsed "$t"))"
	t=$(date +%s)
	in_step3=1
	rm -f "$work/step3.json"
	run env -C "$work/base" JADE_TEST_TEMPLATE="$template" pnpm exec vitest run --project integration \
		--reporter=default --reporter=json --outputFile.json="$work/step3.json" || status=$?
	in_step3=0
	db step3 "$work/step3.json" "$status" || return $?
	db ledger "$dir" "$template" || return $?
	echo "ci:compat: step 3 done ($(elapsed "$t"))"
}

if [ "$mode" = compat ]; then
	base=$(node tools/ci/base-ref.ts ${base_args[@]+"${base_args[@]}"})
	if [ "$base" = "no base" ]; then
		echo "ci:compat: no base: nothing was deployed before, so there is nothing to compare; passed"
		exit 0
	fi
	if ! has_manifest "$base"; then
		echo "ci:compat: the base $base has no migrations (no migrations/manifest.json); passed"
		exit 0
	fi
	base_count=$(compat count-at "$base")
	head_count=$(compat count-dir migrations)
	if [ "$head_count" -le "$base_count" ]; then
		echo "ci:compat: the head's manifest lists no migration beyond the base's ($head_count, base $base); nothing to test; passed"
		exit 0
	fi
	echo "ci:compat: the head adds $((head_count - base_count)) migration(s) to the base $base"
	db leftovers
	prepare_base "$base"
	status=0
	run_compat "$repo_root" 1 || status=$?
	if [ "$status" -ne 0 ]; then
		echo "ci:compat: FAILED (code $status): the base's code does not work on the head's schema" >&2
		exit 1
	fi
	echo "ci:compat: passed: the base's code works on the head's schema"
	exit 0
fi

# --self-test
head=$(git rev-parse HEAD)
echo "ci:compat: self-test: the base is HEAD ($head)"
if ! has_manifest "$head"; then
	echo "ci:compat: self-test: HEAD has no migrations/manifest.json" >&2
	exit 1
fi
db leftovers
prepare_base "$head"
count=$(compat count-at "$head")
next=$(printf '%04d' "$count")

# A head that adds `$2` as migration `$next`_`$1`.sql to a worktree of HEAD at `$3`.
make_head() {
	add_worktree "$head" "$3"
	printf '%s\n' "$2" >"$3/migrations/${next}_$1.sql"
	compat manifest "$3/migrations"
}

harmless=$(cat tests/infra/fixtures/migrations/0001_infra_fixture.sql)
breaking='-- The self-test of pnpm ci:compat only (plan 12.1): a migration that breaks the previous app.
REVOKE SELECT ON schema_migrations FROM jade_app;'

make_head infra_fixture "$harmless" "$work/head-harmless"
status=0
run_compat "$work/head-harmless" 1 || status=$?
if [ "$status" -ne 0 ]; then
	echo "ci:compat: self-test FAILED: the harmless fixture was refused (code $status)" >&2
	exit 1
fi
echo "ci:compat: self-test: the harmless fixture passed"

make_head revoke_ledger_select "$breaking" "$work/head-breaking"
status=0
run_compat "$work/head-breaking" 2 || status=$?
case "$status" in
12 | 13)
	echo "ci:compat: self-test: the breaking fixture was caught in step $((status - 10)), as it must be"
	;;
0)
	echo "ci:compat: self-test FAILED: the breaking fixture passed" >&2
	exit 1
	;;
*)
	echo "ci:compat: self-test FAILED: the breaking fixture failed with code $status, which is not a compatibility failure of step 2 or 3" >&2
	exit 1
	;;
esac
echo "ci:compat: self-test passed"
