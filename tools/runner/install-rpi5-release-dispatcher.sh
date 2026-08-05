#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'

for user in github-release-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in awk bash chmod cmp curl docker flock git grep gzip id install mktemp pgrep python3 readlink rm runuser sha256sum stat sudo systemctl tar tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

SOURCE_WORKTREE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
SOURCE_OWNER='andris'
SOURCE_HOME='/home/andris'
PRIMARY_GIT_DIR='/home/andris/hermes-deals/.git'
EXPECTED_SOURCE='/home/andris/hermes-deals-worktrees/release-control'

run_owner_git() {
  runuser -u "$SOURCE_OWNER" -- env \
    HOME="$SOURCE_HOME" \
    PATH='/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin' \
    git -C "$SOURCE_WORKTREE" "$@"
}

[[ "$SOURCE_WORKTREE" == "$EXPECTED_SOURCE" ]] \
  || fail 'installer source must be the isolated release-control worktree'
[[ "$(stat -c '%U:%G' "$SOURCE_WORKTREE")" == 'andris:andris' ]] \
  || fail 'release source worktree ownership is invalid'
[[ "$(run_owner_git rev-parse --is-inside-work-tree)" == true ]] \
  || fail 'installer source is not a Git worktree'
WORKTREE_GIT_DIR="$(readlink -f -- "$(run_owner_git rev-parse --path-format=absolute --git-dir)")"
[[ -f "$WORKTREE_GIT_DIR/index" ]] || fail 'release source index is missing'
[[ "$(stat -c '%U:%G' "$WORKTREE_GIT_DIR/index")" == 'andris:andris' ]] \
  || fail 'release source index ownership is invalid'
[[ -z "$(run_owner_git branch --show-current)" ]] \
  || fail 'release source worktree must remain detached'
[[ "$(run_owner_git rev-parse HEAD)" == "$(run_owner_git rev-parse refs/remotes/origin/main)" ]] \
  || fail 'release source HEAD is not exact origin/main'
[[ -z "$(run_owner_git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail 'installer source worktree is not clean'
COMMON_GIT_DIR="$(readlink -f -- "$(run_owner_git rev-parse --path-format=absolute --git-common-dir)")"
[[ "$COMMON_GIT_DIR" == "$PRIMARY_GIT_DIR" ]] \
  || fail 'release source is not linked to the Hermes Deals primary Git directory'
case "$(run_owner_git remote get-url origin)" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'installer source origin is invalid' ;;
esac

RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service'
DISPATCHER='/usr/local/sbin/hermes-deals-release-dispatch'
REGISTER='/usr/local/sbin/hermes-deals-release-register'
BRIDGE='/usr/local/sbin/hermes-deals-release-bridge'
AUTO_REGISTER='/usr/local/sbin/hermes-deals-release-auto-register'
MAIN_REGISTER='/usr/local/sbin/hermes-deals-release-main-register'
MAIN_DEPLOY='/usr/local/sbin/hermes-deals-release-main-deploy'
SUDOERS='/etc/sudoers.d/hermes-deals-release-runner'
REGISTRY_DIR='/etc/hermes-deals-releases.d'
RELEASE_ARCHIVE_DIR='/opt/backups/hermes-deals/releases'
RELEASE_LIBEXEC_DIR='/usr/local/libexec/hermes-deals-releases'
STAGING_ROOT='/home/andris/hermes-deals-release-evidence'

SOURCE_DISPATCHER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-dispatch"
SOURCE_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-register"
SOURCE_BRIDGE="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-bridge"
SOURCE_AUTO_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-auto-register"
SOURCE_MAIN_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-main-register"
SOURCE_MAIN_DEPLOY="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-main-deploy"

for source in \
  "$SOURCE_DISPATCHER" \
  "$SOURCE_REGISTER" \
  "$SOURCE_BRIDGE" \
  "$SOURCE_AUTO_REGISTER" \
  "$SOURCE_MAIN_REGISTER" \
  "$SOURCE_MAIN_DEPLOY"; do
  [[ -f "$source" && ! -L "$source" ]] \
    || fail "release source is missing or unsafe: $source"
done
for tracked in \
  tools/runner/release/hermes-deals-release-dispatch \
  tools/runner/release/hermes-deals-release-register \
  tools/runner/release/hermes-deals-release-bridge \
  tools/runner/release/hermes-deals-release-auto-register \
  tools/runner/release/hermes-deals-release-main-register \
  tools/runner/release/hermes-deals-release-main-deploy; do
  run_owner_git ls-files --error-unmatch "$tracked" >/dev/null \
    || fail "release source is not tracked: $tracked"
done

/bin/bash -n "$SOURCE_DISPATCHER"
/bin/bash -n "$SOURCE_REGISTER"
/bin/bash -n "$SOURCE_AUTO_REGISTER"
/bin/bash -n "$SOURCE_MAIN_REGISTER"
/bin/bash -n "$SOURCE_MAIN_DEPLOY"
python3 - "$SOURCE_BRIDGE" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-release-installer.XXXXXX)"
cleanup() {
  rm -rf -- "$TMPDIR_INSTALL"
}
trap cleanup EXIT

cat >"$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-release-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-dispatch
SUDOERS
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null

install -d -o root -g root -m 0750 \
  "$REGISTRY_DIR" \
  "$RELEASE_ARCHIVE_DIR" \
  "$RELEASE_LIBEXEC_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0755 "$SOURCE_DISPATCHER" "$DISPATCHER"
install -o root -g root -m 0755 "$SOURCE_REGISTER" "$REGISTER"
install -o root -g root -m 0755 "$SOURCE_BRIDGE" "$BRIDGE"
install -o root -g root -m 0755 "$SOURCE_AUTO_REGISTER" "$AUTO_REGISTER"
install -o root -g root -m 0755 "$SOURCE_MAIN_REGISTER" "$MAIN_REGISTER"
install -o root -g root -m 0755 "$SOURCE_MAIN_DEPLOY" "$MAIN_DEPLOY"
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

systemctl is-active --quiet "$RUNNER_SERVICE" \
  || fail "GitHub Actions release runner service is not active: $RUNNER_SERVICE"
if id -nG github-release-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail 'github-release-runner must not belong to docker group'
fi
sudo -l -U github-release-runner | grep -Fq '/usr/local/sbin/hermes-deals-release-dispatch' \
  || fail 'release dispatcher sudo rule was not installed'
for root_only in \
  /usr/local/sbin/hermes-deals-release-register \
  /usr/local/sbin/hermes-deals-release-auto-register \
  /usr/local/sbin/hermes-deals-release-main-register \
  /usr/local/sbin/hermes-deals-release-main-deploy; do
  if sudo -l -U github-release-runner | grep -Fq "$root_only"; then
    fail "root-only release tool leaked into runner sudo rules: $root_only"
  fi
done
[[ "$(stat -c '%U:%G' "$WORKTREE_GIT_DIR/index")" == 'andris:andris' ]] \
  || fail 'release source index ownership changed during installation'

printf 'INSTALL_RESULT=PASS\n'
printf 'SOURCE_WORKTREE=%s\n' "$SOURCE_WORKTREE"
printf 'SOURCE_SHA=%s\n' "$(run_owner_git rev-parse HEAD)"
printf 'RUNNER_SERVICE=%s\n' "$RUNNER_SERVICE"
printf 'DISPATCHER_SHA256=%s\n' "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
printf 'REGISTER_SHA256=%s\n' "$(sha256sum "$REGISTER" | awk '{print $1}')"
printf 'BRIDGE_SHA256=%s\n' "$(sha256sum "$BRIDGE" | awk '{print $1}')"
printf 'AUTO_REGISTER_SHA256=%s\n' "$(sha256sum "$AUTO_REGISTER" | awk '{print $1}')"
printf 'MAIN_REGISTER_SHA256=%s\n' "$(sha256sum "$MAIN_REGISTER" | awk '{print $1}')"
printf 'MAIN_DEPLOY_SHA256=%s\n' "$(sha256sum "$MAIN_DEPLOY" | awk '{print $1}')"
printf 'SUDOERS_VALID=true\n'
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'DATABASE_WRITES_AUTHORIZED=false\n'
