#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"

for user in github-release-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in awk bash chmod cmp curl docker flock git grep gzip id install mktemp pgrep python3 readlink rm sha256sum stat sudo systemctl tar tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

SOURCE_WORKTREE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PRIMARY_GIT_DIR='/home/andris/hermes-deals/.git'
EXPECTED_SOURCE='/home/andris/hermes-deals-worktrees/release-control'
[[ "$SOURCE_WORKTREE" == "$EXPECTED_SOURCE" ]] || fail "installer source must be the isolated release-control worktree"
[[ "$(stat -c '%U:%G' "$SOURCE_WORKTREE")" == 'andris:andris' ]] || fail "release source worktree ownership is invalid"
[[ "$(git -C "$SOURCE_WORKTREE" rev-parse --is-inside-work-tree)" == true ]] || fail "installer source is not a Git worktree"
[[ -z "$(git -C "$SOURCE_WORKTREE" branch --show-current)" ]] || fail "release source worktree must remain detached"
[[ "$(git -C "$SOURCE_WORKTREE" rev-parse HEAD)" == "$(git -C "$SOURCE_WORKTREE" rev-parse refs/remotes/origin/main)" ]] || fail "release source HEAD is not exact origin/main"
[[ -z "$(git -C "$SOURCE_WORKTREE" status --porcelain=v1 --untracked-files=all)" ]] || fail "installer source worktree is not clean"
COMMON_GIT_DIR="$(readlink -f -- "$(git -C "$SOURCE_WORKTREE" rev-parse --path-format=absolute --git-common-dir)")"
[[ "$COMMON_GIT_DIR" == "$PRIMARY_GIT_DIR" ]] || fail "release source is not linked to the Hermes Deals primary Git directory"
case "$(git -C "$SOURCE_WORKTREE" remote get-url origin)" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "installer source origin is invalid" ;;
esac

RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service'
DISPATCHER='/usr/local/sbin/hermes-deals-release-dispatch'
REGISTER='/usr/local/sbin/hermes-deals-release-register'
BRIDGE='/usr/local/sbin/hermes-deals-release-bridge'
AUTO_REGISTER='/usr/local/sbin/hermes-deals-release-auto-register'
SUDOERS='/etc/sudoers.d/hermes-deals-release-runner'
REGISTRY_DIR='/etc/hermes-deals-releases.d'
RELEASE_ARCHIVE_DIR='/opt/backups/hermes-deals/releases'
RELEASE_LIBEXEC_DIR='/usr/local/libexec/hermes-deals-releases'
STAGING_ROOT='/home/andris/hermes-deals-release-evidence'
SOURCE_DISPATCHER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-dispatch"
SOURCE_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-register"
SOURCE_BRIDGE="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-bridge"
SOURCE_AUTO_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-auto-register"

for source in "$SOURCE_DISPATCHER" "$SOURCE_REGISTER" "$SOURCE_BRIDGE" "$SOURCE_AUTO_REGISTER"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "release source is missing or unsafe: $source"
done
for tracked in \
  tools/runner/release/hermes-deals-release-dispatch \
  tools/runner/release/hermes-deals-release-register \
  tools/runner/release/hermes-deals-release-bridge \
  tools/runner/release/hermes-deals-release-auto-register; do
  git -C "$SOURCE_WORKTREE" ls-files --error-unmatch "$tracked" >/dev/null \
    || fail "release source is not tracked: $tracked"
done
/bin/bash -n "$SOURCE_DISPATCHER"
/bin/bash -n "$SOURCE_REGISTER"
/bin/bash -n "$SOURCE_AUTO_REGISTER"
python3 - "$SOURCE_BRIDGE" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-release-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT
cat > "$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-release-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-dispatch
SUDOERS
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null

install -d -o root -g root -m 0750 "$REGISTRY_DIR" "$RELEASE_ARCHIVE_DIR" "$RELEASE_LIBEXEC_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0755 "$SOURCE_DISPATCHER" "$DISPATCHER"
install -o root -g root -m 0755 "$SOURCE_REGISTER" "$REGISTER"
install -o root -g root -m 0755 "$SOURCE_BRIDGE" "$BRIDGE"
install -o root -g root -m 0755 "$SOURCE_AUTO_REGISTER" "$AUTO_REGISTER"
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions release runner service is not active: $RUNNER_SERVICE"
if id -nG github-release-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail "github-release-runner must not belong to docker group"
fi
sudo -l -U github-release-runner | grep -Fq '/usr/local/sbin/hermes-deals-release-dispatch' || fail "release dispatcher sudo rule was not installed"
if sudo -l -U github-release-runner | grep -Fq '/usr/local/sbin/hermes-deals-release-register'; then
  fail "root-only release register tool leaked into runner sudo rules"
fi
if sudo -l -U github-release-runner | grep -Fq '/usr/local/sbin/hermes-deals-release-auto-register'; then
  fail "root-only release auto-register tool leaked into runner sudo rules"
fi

printf 'INSTALL_RESULT=PASS\nSOURCE_WORKTREE=%s\nSOURCE_SHA=%s\nRUNNER_SERVICE=%s\nDISPATCHER_SHA256=%s\nREGISTER_SHA256=%s\nBRIDGE_SHA256=%s\nAUTO_REGISTER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nDATABASE_WRITES_AUTHORIZED=false\n' \
  "$SOURCE_WORKTREE" \
  "$(git -C "$SOURCE_WORKTREE" rev-parse HEAD)" \
  "$RUNNER_SERVICE" \
  "$(sha256sum "$DISPATCHER" | awk '{print $1}')" \
  "$(sha256sum "$REGISTER" | awk '{print $1}')" \
  "$(sha256sum "$BRIDGE" | awk '{print $1}')" \
  "$(sha256sum "$AUTO_REGISTER" | awk '{print $1}')"
