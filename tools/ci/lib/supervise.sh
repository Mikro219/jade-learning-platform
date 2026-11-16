# Supervision of long child commands for a bash script (sourced; used by
# tools/ci/migration-compat.sh, tested by tests/unit/supervise.test.ts).
#
#   source tools/ci/lib/supervise.sh
#   supervise_init <name> <cleanup function>
#   run <command> [args...]      # each long command
#
# run() starts the command in a session and process group of its own (`setsid -w ... &`) and
# waits for it with `wait`. Bash runs a trap while `wait` waits, but not while a foreground child
# runs, so a SIGINT or SIGTERM to the script is handled at once. The trap ignores further INT and
# TERM, prints "<name>: stopped by SIG<sig>" and exits 130 or 143; the EXIT trap then calls the
# cleanup function once, with the exit status. The cleanup function calls signal_child TERM (ask
# the running command to stop) and stop_child (TERM, then KILL after 3 s, to the command's pid
# and to its whole group, so its grandchildren go too).
#
# A signal that arrives between the fork and `child=$!` is held and acted on as soon as the child
# is known (N4). supervise_after_fork, when the caller defines it, runs inside that window: a test
# hook.
#
# A SIGKILL of the script itself (no INT or TERM before it) cannot be handled: running children
# are orphaned. A hosted CI runner discards its VM after the job; locally the next run of
# migration-compat.sh warns about what was left.
#
# The script must not run under job control or interactively: there `&` makes each child a group
# leader, setsid then forks, and the group would not be the one run() records.
case $- in
*m* | *i*)
	echo "supervise: refusing to run under job control or interactively (shell flags $-)" >&2
	exit 2
	;;
esac
if ! command -v setsid >/dev/null 2>&1; then
	echo "supervise: setsid is not on PATH (util-linux); it is needed to stop child commands" >&2
	exit 2
fi

child=""
_supervise_name=supervise
_supervise_cleanup=""
_supervise_starting=0
_supervise_pending=""
_supervise_done=0

# Send `$1` (TERM, KILL) to the running child's pid and to its whole process group.
signal_child() {
	[ -n "$child" ] || return 0
	kill "-$1" "$child" 2>/dev/null || true
	kill "-$1" -- "-$child" 2>/dev/null || true
}

# TERM the running child and its group, then KILL whatever of the group is left after 3 s.
stop_child() {
	[ -n "$child" ] || return 0
	signal_child TERM
	local _
	for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
		kill -0 -- "-$child" 2>/dev/null || kill -0 "$child" 2>/dev/null || break
		sleep 0.2
	done
	signal_child KILL
	child=""
}

_supervise_signal() {
	if [ "$_supervise_starting" = 1 ]; then
		# Between the fork and child=$!: act once the child is known.
		_supervise_pending=$1
		return 0
	fi
	trap '' INT TERM
	echo "$_supervise_name: stopped by SIG$1" >&2
	if [ "$1" = INT ]; then exit 130; fi
	exit 143
}

_supervise_exit() {
	local status=$?
	trap '' INT TERM
	if [ "$_supervise_done" = 0 ]; then
		_supervise_done=1
		set +e
		if [ -n "$_supervise_cleanup" ]; then "$_supervise_cleanup" "$status"; fi
		stop_child
	fi
	exit "$status"
}

# supervise_init <name> <cleanup function>: install the traps.
supervise_init() {
	_supervise_name=$1
	_supervise_cleanup=$2
	trap _supervise_exit EXIT
	trap '_supervise_signal INT' INT
	trap '_supervise_signal TERM' TERM
}

# Run a command in a process group of its own and wait for it; returns its exit status.
run() {
	local status=0
	_supervise_starting=1
	setsid -w "$@" &
	if declare -F supervise_after_fork >/dev/null; then supervise_after_fork; fi
	child=$!
	_supervise_starting=0
	if [ -n "$_supervise_pending" ]; then _supervise_signal "$_supervise_pending"; fi
	wait "$child" || status=$?
	child=""
	return "$status"
}
