#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ $# -eq 1 ]] || fail 'usage: sudo bash tools/runner/install-aldi-registration-refresh-bridge.sh <merged-main-sha>'

EXPECTED_SHA="$1"
REPO='/home/andris/hermes-deals'
SOURCE_REL='tools/runner/hermes-deals-aldi-registration-refresh-dispatch'
SOURCE="$REPO/$SOURCE_REL"
DISPATCHER='/usr/local/sbin/hermes-deals-aldi-registration-refresh-dispatch'
CONFIG='/etc/hermes-deals-audits.d/aldi-registration-refresh.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-aldi-registration-refresh'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'commit SHA is invalid'
for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in bash git id install mktemp readlink runuser sha256sum stat visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail 'github-runner must not be a member of the docker group'
fi

git_as_andris() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
    /usr/bin/git "$@"
}

[[ -d "$REPO" && ! -L "$REPO" ]] || fail 'primary checkout path is missing or unsafe'
[[ "$(readlink -f -- "$REPO")" == "$REPO" ]] || fail 'primary checkout path drift'
[[ "$(stat -c '%U:%G' "$REPO")" == 'andris:andris' ]] || fail 'primary checkout owner drift'
[[ -d "$REPO/.git" && ! -L "$REPO/.git" ]] || fail 'primary checkout .git is missing or unsafe'
[[ "$(git_as_andris -C "$REPO" rev-parse --is-inside-work-tree)" == 'true' ]] || fail 'primary checkout is not a Git worktree'
[[ "$(git_as_andris -C "$REPO" rev-parse --is-shallow-repository)" == 'false' ]] || fail 'shallow checkout is unsupported'
[[ "$(git_as_andris -C "$REPO" branch --show-current)" == 'main' ]] || fail 'primary checkout branch must be main'
[[ "$(git_as_andris -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail 'primary checkout HEAD mismatch'
[[ -z "$(git_as_andris -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'primary checkout is not clean'
case "$(git_as_andris -C "$REPO" remote get-url origin)" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'primary checkout origin is not canonical Hermes Deals' ;;
esac

git_as_andris -C "$REPO" ls-files --error-unmatch "$SOURCE_REL" >/dev/null || fail 'dispatcher source is not tracked'
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail 'dispatcher source is missing or unsafe'
/usr/bin/bash -n "$SOURCE" || fail 'dispatcher source syntax check failed'
DISPATCHER_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
[[ "$DISPATCHER_SHA" =~ ^[0-9a-f]{64}$ ]] || fail 'dispatcher source SHA-256 is invalid'

TMP="$(mktemp -d /tmp/hermes-deals-aldi-registration-refresh-install.XXXXXX)"
KEEP_TMP=true
cleanup() {
  if [[ "$KEEP_TMP" == false ]]; then
    rm -rf -- "$TMP"
  else
    printf 'INSTALL_STAGING_PRESERVED=%s\n' "$TMP" >&2
  fi
}
trap cleanup EXIT

cat > "$TMP/config" <<EOF_CONFIG
bridge_contract_version='hermes-deals-aldi-registration-refresh-v1'
registered_bridge_sha='$EXPECTED_SHA'
repo_path='$REPO'
dispatcher_path='$DISPATCHER'
dispatcher_sha256='$DISPATCHER_SHA'
EOF_CONFIG

cat > "$TMP/sudoers" <<'EOF_SUDOERS'
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-aldi-registration-refresh-dispatch *
EOF_SUDOERS
chmod 0600 "$TMP/config" "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null || fail 'registration-refresh sudoers validation failed'

# Persistent bootstrap registration begins here. This installer never refreshes ALDI registrations itself.
install -d -o root -g root -m 0755 "$(dirname "$CONFIG")"
install -o root -g root -m 0755 "$SOURCE" "$DISPATCHER"
install -o root -g root -m 0644 "$TMP/config" "$CONFIG"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null || fail 'installed registration-refresh sudoers validation failed'
[[ "$(sha256sum "$DISPATCHER" | awk '{print $1}')" == "$DISPATCHER_SHA" ]] || fail 'installed dispatcher hash mismatch'
[[ "$(stat -c '%U:%G %a' "$DISPATCHER")" == 'root:root 755' ]] || fail 'installed dispatcher metadata mismatch'
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 644' ]] || fail 'installed config metadata mismatch'
[[ "$(stat -c '%U:%G %a' "$SUDOERS")" == 'root:root 440' ]] || fail 'installed sudoers metadata mismatch'
[[ "$(git_as_andris -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail 'source checkout changed during bridge registration'
[[ -z "$(git_as_andris -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'source checkout became dirty during bridge registration'

KEEP_TMP=false
printf 'INSTALL_RESULT=PASS\n'
printf 'REGISTERED_BRIDGE_SHA=%s\n' "$EXPECTED_SHA"
printf 'DISPATCHER_SHA256=%s\n' "$DISPATCHER_SHA"
printf 'SUDOERS_VALID=true\n'
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'ALDI_REGISTRATION_REFRESH_EXECUTED=false\n'
printf 'NETWORK_SOURCE_READ=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'REVIEW_PUBLICATION_WRITE=false\n'
printf 'SCHEDULER_SYSTEMD_CHANGE=false\n'
printf 'PRODUCTION_CANARY=false\n'
printf 'PRODUCTION_DEPLOY=false\n'
