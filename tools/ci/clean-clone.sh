#!/usr/bin/env bash
# Proves the README's setup steps from a clean clone of HEAD (plan H8, phase exit criterion AC1).
# Refuses to run while the working tree has any change, so it only ever tests the commit it names.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

if [ -n "$(git status --porcelain)" ]; then
	echo "clean-clone: refusing to run: the working tree has uncommitted changes:" >&2
	git status --porcelain >&2
	exit 1
fi

sha=$(git rev-parse HEAD)
echo "clean-clone: HEAD $sha"

work=$(mktemp -d "${TMPDIR:-/tmp}/jade-clean-XXXXXXXX")
clone="$work/repo"
COMPOSE_PROJECT_NAME="jade-clean-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
export COMPOSE_PROJECT_NAME
dev_pid=""

cleanup() {
	status=$?
	if [ -n "$dev_pid" ] && kill -0 "$dev_pid" 2>/dev/null; then
		kill "$dev_pid" 2>/dev/null || true
		wait "$dev_pid" 2>/dev/null || true
	fi
	if [ -d "$clone" ]; then
		(cd "$clone" && docker compose -p "$COMPOSE_PROJECT_NAME" down -v --remove-orphans >/dev/null 2>&1) ||
			echo "clean-clone: warning: could not remove Compose project $COMPOSE_PROJECT_NAME" >&2
	fi
	rm -rf "$work"
	echo "clean-clone: exit $status for $sha"
	exit "$status"
}
trap cleanup EXIT

git clone --quiet --no-local --no-checkout "$repo_root" "$clone"
cd "$clone"
git checkout --quiet --detach "$sha"

# The setup block: the fenced commands between the README's setup markers, run exactly as written.
setup=$(sed -n '/<!-- setup:begin -->/,/<!-- setup:end -->/p' README.md |
	sed -n '/^```/,/^```/p' | sed '/^```/d')
if [ -z "$setup" ]; then
	echo "clean-clone: README.md has no setup block between the setup markers" >&2
	exit 1
fi
echo "clean-clone: setup block:"
printf '%s\n' "$setup" | sed 's/^/  | /'
bash -euo pipefail -c "$setup"

pnpm test
pnpm e2e

# pnpm dev on a port from freePort(), so no other server on the machine can answer in its place.
# A start that fails because the port was taken in between is retried, at most three times.
for attempt in 1 2 3; do
	port=$(pnpm --silent exec node tools/free-port.ts)
	log="$work/dev-$attempt.log"
	pnpm dev --port "$port" --strictPort >"$log" 2>&1 &
	dev_pid=$!
	for _ in $(seq 1 120); do
		if ! kill -0 "$dev_pid" 2>/dev/null; then break; fi
		code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/" || true)
		if [ "$code" = "200" ]; then
			echo "clean-clone: pnpm dev answered 200 on port $port"
			kill "$dev_pid" 2>/dev/null || true
			wait "$dev_pid" 2>/dev/null || true
			dev_pid=""
			exit 0
		fi
		sleep 0.5
	done
	kill "$dev_pid" 2>/dev/null || true
	wait "$dev_pid" 2>/dev/null || true
	dev_pid=""
	if grep -q -i 'already in use' "$log"; then
		echo "clean-clone: port $port was taken; retrying ($attempt of 3)" >&2
		continue
	fi
	echo "clean-clone: pnpm dev did not answer 200 on port $port:" >&2
	cat "$log" >&2
	exit 1
done
echo "clean-clone: pnpm dev could not get a free port in three attempts" >&2
exit 1
