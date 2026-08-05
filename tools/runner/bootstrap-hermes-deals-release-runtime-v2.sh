#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "bootstrap v2 must run as root"
[[ $# -eq 1 ]] || fail "usage: bootstrap-hermes-deals-release-runtime-v2.sh <exact-current-main-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "expected SHA must be exact lowercase 40-character hex"
[[ -n "${HERMES_GITHUB_TOKEN:-}" ]] || fail "HERMES_GITHUB_TOKEN must be passed through sudo environment"

PRIMARY='/home/andris/hermes-deals'
RUNNER_META='/home/github-release-runner/actions-runner/.runner'
RUNNER_NAME='rpi5-hermes-deals-release'
REPOSITORY_URL='https://github.com/rozkalnsandris/hermes-deals'
TMPDIR_REPAIR="$(mktemp -d /tmp/hermes-deals-release-bootstrap-v2.XXXXXX)"
V1="$TMPDIR_REPAIR/bootstrap-v1.sh"
NORMALIZER="$TMPDIR_REPAIR/normalize-runner-metadata.py"

cleanup() {
  rm -rf -- "$TMPDIR_REPAIR"
}
trap cleanup EXIT

for command in bash chmod git mktemp python3 rm runuser; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ -d "$PRIMARY" && ! -L "$PRIMARY" ]] || fail "primary repository is missing or unsafe"

runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 \
  git -C "$PRIMARY" fetch --prune origin main
ACTUAL_SHA="$(runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 \
  git -C "$PRIMARY" rev-parse refs/remotes/origin/main)"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "origin/main does not equal the authorized bootstrap SHA"

runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 \
  git -C "$PRIMARY" show \
  "$EXPECTED_SHA:tools/runner/bootstrap-hermes-deals-release-runtime.sh" > "$V1"
runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 \
  git -C "$PRIMARY" show \
  "$EXPECTED_SHA:tools/runner/normalize-actions-runner-metadata.py" > "$NORMALIZER"
chmod 0700 "$V1" "$NORMALIZER"

run_v1() {
  env HERMES_GITHUB_TOKEN="$HERMES_GITHUB_TOKEN" bash "$V1" "$EXPECTED_SHA"
}

set +e
run_v1
first_rc=$?
set -e
if (( first_rc == 0 )); then
  exit 0
fi

[[ -f "$RUNNER_META" && ! -L "$RUNNER_META" ]] || {
  echo "Original bootstrap failed before safe runner metadata existed; no retry performed." >&2
  exit "$first_rc"
}

set +e
python3 "$NORMALIZER" "$RUNNER_META" "$RUNNER_NAME" "$REPOSITORY_URL"
repair_rc=$?
set -e
if (( repair_rc != 0 )); then
  echo "Original bootstrap failed and no valid BOM-only repair was available; no retry performed." >&2
  exit "$first_rc"
fi

echo "Retrying the exact bootstrap once after validated BOM-only metadata normalization."
run_v1
