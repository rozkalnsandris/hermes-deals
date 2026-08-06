#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run installer with sudo'

SOURCE_WORKTREE='/home/andris/hermes-deals-worktrees/release-control'
SOURCE_REL='tools/runner/release/hermes-deals-deploy-main'
SOURCE="$SOURCE_WORKTREE/$SOURCE_REL"
DEST='/usr/local/sbin/hermes-deals-deploy-main'
SUDOERS='/etc/sudoers.d/hermes-deals-github-deploy'
RUNNER='github-release-runner'
OWNER='andris'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service'

id "$RUNNER" >/dev/null 2>&1 || fail 'release runner user is missing'
id "$OWNER" >/dev/null 2>&1 || fail 'owner user is missing'
[[ "$(pwd -P)" == "$SOURCE_WORKTREE" ]] || fail 'installer must run from release-control worktree'
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail 'deploy helper source is missing or unsafe'
runuser -u "$OWNER" -- env HOME=/home/andris PATH=/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin \
  git -C "$SOURCE_WORKTREE" ls-files --error-unmatch "$SOURCE_REL" >/dev/null \
  || fail 'deploy helper source is not tracked'
HEAD_SHA="$(runuser -u "$OWNER" -- env HOME=/home/andris PATH=/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin git -C "$SOURCE_WORKTREE" rev-parse HEAD)"
REMOTE_SHA="$(runuser -u "$OWNER" -- env HOME=/home/andris PATH=/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin git -C "$SOURCE_WORKTREE" rev-parse refs/remotes/origin/main)"
[[ "$HEAD_SHA" == "$REMOTE_SHA" ]] || fail 'release-control is not exact origin/main'
[[ -z "$(runuser -u "$OWNER" -- env HOME=/home/andris PATH=/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin git -C "$SOURCE_WORKTREE" status --porcelain=v1 --untracked-files=all)" ]] \
  || fail 'release-control worktree is not clean'

bash -n "$SOURCE"
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub release runner service is not active'
if id -nG "$RUNNER" | tr ' ' '\n' | grep -Fxq docker; then
  fail 'release runner must not belong to docker group'
fi

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-github-deploy.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT

cat >"$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-deploy-main env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-deploy-main *
SUDOERS
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null
install -o root -g root -m 0755 "$SOURCE" "$DEST"
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null
sudo -n -l -U "$RUNNER" -- "$DEST" "$HEAD_SHA" \
  "/home/github-release-runner/actions-runner/_work/_temp/hermes-deals-main-deploy-1-1" \
  >/dev/null 2>&1 || fail 'narrow deploy sudo rule is not visible to runner'

printf 'GITHUB_DEPLOY_INSTALL_RESULT=PASS\n'
printf 'SOURCE_SHA=%s\n' "$HEAD_SHA"
printf 'HELPER_SHA256=%s\n' "$(sha256sum "$DEST" | awk '{print $1}')"
printf 'RUNNER_SERVICE=%s\n' "$RUNNER_SERVICE"
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'DATABASE_WRITES_AUTHORIZED=false\n'
printf 'PRODUCTION_CHANGED=false\n'
