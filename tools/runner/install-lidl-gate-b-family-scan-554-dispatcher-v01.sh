#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo as root'
[[ $# -eq 1 ]] || fail 'usage: sudo bash tools/runner/install-lidl-gate-b-family-scan-554-dispatcher-v01.sh <merged-main-sha>'

EXPECTED_SHA="$1"
SOURCE_REPO='/home/andris/hermes-deals'
DISPATCHER_REL='tools/runner/lidl-gate-b-family-scan-554-dispatcher-v01.sh'
EXPECTED_DISPATCHER_BLOB='c09a1fc40c6ff4953b0b63c6a2f58170747a7160'
PREDECESSOR_DISPATCHER_BLOB='720983e83f45391a35629cb49ffc8d12ac71cb03'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-gate-b-family-scan-554'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-gate-b-family-scan-554'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'merged main SHA is invalid'
for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in bash cmp git grep id install mktemp readlink runuser stat sudo tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail 'github-runner must not belong to the Docker group'
fi

SUDO_VERSION_OUTPUT="$(sudo -V)"
SUDO_VERSION_LINE="${SUDO_VERSION_OUTPUT%%$'\n'*}"
if [[ ! "$SUDO_VERSION_LINE" =~ ^Sudo\ version\ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
  fail 'unable to parse host Sudo version'
fi
SUDO_MAJOR="${BASH_REMATCH[1]}"
SUDO_MINOR="${BASH_REMATCH[2]}"
SUDO_PATCH="${BASH_REMATCH[3]}"
if (( SUDO_MAJOR < 1 || (SUDO_MAJOR == 1 && SUDO_MINOR < 9) || (SUDO_MAJOR == 1 && SUDO_MINOR == 9 && SUDO_PATCH < 10) )); then
  fail 'host Sudo is older than 1.9.10; regex command arguments are unavailable'
fi

[[ -d "$SOURCE_REPO/.git" && ! -L "$SOURCE_REPO/.git" ]] || fail 'primary repository is missing or unsafe'
[[ "$(readlink -f -- "$SOURCE_REPO")" == "$SOURCE_REPO" ]] || fail 'primary repository path drift'

git_source() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$SOURCE_REPO" "$@"
}

[[ "$(git_source rev-parse --is-inside-work-tree 2>/dev/null)" == true ]] || fail 'primary source path is not a Git worktree'
git_source cat-file -e "$EXPECTED_SHA^{commit}" 2>/dev/null || fail 'merged main SHA is unavailable locally'
git_source show-ref --verify --quiet refs/remotes/origin/main || fail 'origin/main is unavailable locally'
git_source merge-base --is-ancestor "$EXPECTED_SHA" refs/remotes/origin/main || fail 'merged main SHA is not reachable from origin/main'

DISPATCHER_BLOB="$(git_source rev-parse "$EXPECTED_SHA:$DISPATCHER_REL")"
[[ "$DISPATCHER_BLOB" == "$EXPECTED_DISPATCHER_BLOB" ]] || fail 'registered dispatcher Git blob mismatch'

TMP="$(mktemp -d /tmp/hermes-deals-lidl-gate-b-scan-554-installer.XXXXXX)"
cleanup() {
  rm -rf -- "$TMP"
}
trap cleanup EXIT

git_source show "$EXPECTED_SHA:$DISPATCHER_REL" > "$TMP/dispatcher"
[[ "$(git_source hash-object --stdin < "$TMP/dispatcher")" == "$EXPECTED_DISPATCHER_BLOB" ]] || fail 'materialized dispatcher byte identity mismatch'
/usr/bin/bash -n "$TMP/dispatcher"
chmod 0755 "$TMP/dispatcher"

TAG_A='NOPASS'
TAG_B='WD'
printf 'Cmnd_Alias HERMES_DEALS_LIDL_GATE_B_SCAN_554 = %s ^[1-9][0-9]* [1-9][0-9]*$\ngithub-runner ALL=(root) %s%s: HERMES_DEALS_LIDL_GATE_B_SCAN_554\n' \
  "$DISPATCHER" "$TAG_A" "$TAG_B" > "$TMP/sudoers"
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null \
  || fail 'host sudoers parser lacks required regex support or generated policy is invalid'

# Accept exactly one known predecessor state produced by the immediately prior
# installer. This permits a safe one-time narrowing from shell wildcards to the
# exact positive-integer regex. Any unrelated or edited sudoers state still
# fails closed.
printf 'Cmnd_Alias HERMES_DEALS_LIDL_GATE_B_SCAN_554 = %s [1-9][0-9]* [1-9][0-9]*\ngithub-runner ALL=(root) %s%s: HERMES_DEALS_LIDL_GATE_B_SCAN_554\n' \
  "$DISPATCHER" "$TAG_A" "$TAG_B" > "$TMP/sudoers.predecessor"
chmod 0440 "$TMP/sudoers.predecessor"
visudo -cf "$TMP/sudoers.predecessor" >/dev/null

DISPATCHER_IDENTICAL=false
DISPATCHER_PREDECESSOR=false
if [[ -e "$DISPATCHER" || -L "$DISPATCHER" ]]; then
  [[ -f "$DISPATCHER" && ! -L "$DISPATCHER" ]] || fail 'existing dispatcher is not a regular non-symlink file'
  [[ "$(stat -c '%U:%G %a' "$DISPATCHER")" == 'root:root 755' ]] || fail 'existing dispatcher metadata mismatch'
  EXISTING_DISPATCHER_BLOB="$(git_source hash-object "$DISPATCHER")"
  if [[ "$EXISTING_DISPATCHER_BLOB" == "$EXPECTED_DISPATCHER_BLOB" ]]; then
    DISPATCHER_IDENTICAL=true
  elif [[ "$EXISTING_DISPATCHER_BLOB" == "$PREDECESSOR_DISPATCHER_BLOB" ]]; then
    DISPATCHER_PREDECESSOR=true
  else
    fail 'existing dispatcher content differs from registered blob and known predecessor'
  fi
fi

SUDOERS_IDENTICAL=false
SUDOERS_PREDECESSOR=false
if [[ -e "$SUDOERS" || -L "$SUDOERS" ]]; then
  [[ -f "$SUDOERS" && ! -L "$SUDOERS" ]] || fail 'existing sudoers entry is not a regular non-symlink file'
  [[ "$(stat -c '%U:%G %a' "$SUDOERS")" == 'root:root 440' ]] || fail 'existing sudoers metadata mismatch'
  visudo -cf "$SUDOERS" >/dev/null
  if cmp -s "$TMP/sudoers" "$SUDOERS"; then
    SUDOERS_IDENTICAL=true
  elif cmp -s "$TMP/sudoers.predecessor" "$SUDOERS"; then
    SUDOERS_PREDECESSOR=true
  else
    fail 'existing sudoers content differs from registered command boundary and known predecessor'
  fi
fi

if [[ "$DISPATCHER_IDENTICAL" == true && "$SUDOERS_IDENTICAL" == true ]]; then
  printf 'INSTALL_RESULT=NO_OP_IDENTICAL\n'
else
  if [[ "$DISPATCHER_IDENTICAL" != true ]]; then
    install -o root -g root -m 0755 "$TMP/dispatcher" "$DISPATCHER"
  fi
  if [[ "$SUDOERS_IDENTICAL" != true ]]; then
    install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
  fi
  printf 'INSTALL_RESULT=PASS\n'
fi

[[ -f "$DISPATCHER" && ! -L "$DISPATCHER" ]] || fail 'installed dispatcher is unsafe'
[[ "$(stat -c '%U:%G %a' "$DISPATCHER")" == 'root:root 755' ]] || fail 'installed dispatcher metadata mismatch'
[[ "$(git_source hash-object "$DISPATCHER")" == "$EXPECTED_DISPATCHER_BLOB" ]] || fail 'installed dispatcher content drift'
[[ -f "$SUDOERS" && ! -L "$SUDOERS" ]] || fail 'installed sudoers entry is unsafe'
[[ "$(stat -c '%U:%G %a' "$SUDOERS")" == 'root:root 440' ]] || fail 'installed sudoers metadata mismatch'
visudo -cf "$SUDOERS" >/dev/null
cmp -s "$TMP/sudoers" "$SUDOERS" || fail 'installed sudoers content drift'

# Query sudo's policy engine for the exact intended invocation. This follows the
# repository's established command-targeted authorization proof and does not
# execute the dispatcher.
sudo -n -l -U github-runner -- "$DISPATCHER" 1 1 >/dev/null 2>&1 \
  || fail 'github-runner fixed dispatcher sudo permission is unavailable'

sudo_policy_must_deny() {
  if sudo -n -l -U github-runner -- "$DISPATCHER" "$@" >/dev/null 2>&1; then
    fail 'github-runner sudo policy unexpectedly accepts malformed dispatcher arguments'
  fi
}
sudo_policy_must_deny 0 1
sudo_policy_must_deny 1 0
sudo_policy_must_deny x 1
sudo_policy_must_deny 1 x
sudo_policy_must_deny 1
sudo_policy_must_deny 1 1 extra

printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'DISPATCHER_BLOB=%s\n' "$EXPECTED_DISPATCHER_BLOB"
printf 'PREDECESSOR_DISPATCHER_BLOB=%s\n' "$PREDECESSOR_DISPATCHER_BLOB"
printf 'DISPATCHER_PATH=%s\n' "$DISPATCHER"
printf 'SUDOERS_PATH=%s\n' "$SUDOERS"
printf 'SUDO_VERSION=%s\n' "$SUDO_VERSION_LINE"
printf 'SUDOERS_REGEX_BOUND=true\n'
printf 'DISPATCHER_UPGRADED_FROM_PREDECESSOR=%s\n' "$DISPATCHER_PREDECESSOR"
printf 'SUDOERS_UPGRADED_FROM_PREDECESSOR=%s\n' "$SUDOERS_PREDECESSOR"
printf 'RUNNER_DOCKER_GROUP=false\n'
printf 'LIVE_SCAN_PERFORMED=false\n'
printf 'CORPUS_WRITE=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'REVIEW_WRITE=false\n'
printf 'PRODUCTION_PUBLISH=false\n'
printf 'PRODUCTION_DEPLOY=false\n'
printf 'SYSTEMD_CHANGE=false\n'
printf 'LIDL_GATE_B_SCAN_554_REGISTRATION=PASS\n'
