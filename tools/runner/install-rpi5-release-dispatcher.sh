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
for command in awk bash chmod curl docker flock git grep gzip id install mktemp pgrep python3 readlink rm sha256sum stat sudo systemctl tar tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
[[ "$REPO" == '/home/andris/hermes-deals' ]] || fail "installer source must be /home/andris/hermes-deals"
[[ -d "$REPO/.git" ]] || fail "installer source is not a Git checkout"
[[ "$(git -C "$REPO" branch --show-current)" == main ]] || fail "installer source branch must be main"
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail "installer source worktree is not clean"
case "$(git -C "$REPO" remote get-url origin)" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "installer source origin is invalid" ;;
esac

RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service'
DISPATCHER='/usr/local/sbin/hermes-deals-release-dispatch'
REGISTER='/usr/local/sbin/hermes-deals-release-register'
SUDOERS='/etc/sudoers.d/hermes-deals-release-runner'
REGISTRY_DIR='/etc/hermes-deals-releases.d'
RELEASE_ARCHIVE_DIR='/opt/backups/hermes-deals/releases'
STAGING_ROOT='/home/andris/hermes-deals-release-evidence'
SOURCE_DISPATCHER="$REPO/tools/runner/release/hermes-deals-release-dispatch"
SOURCE_REGISTER="$REPO/tools/runner/release/hermes-deals-release-register"

for source in "$SOURCE_DISPATCHER" "$SOURCE_REGISTER"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "release source is missing or unsafe: $source"
done
git -C "$REPO" ls-files --error-unmatch tools/runner/release/hermes-deals-release-dispatch >/dev/null || fail "release dispatcher source is not tracked"
git -C "$REPO" ls-files --error-unmatch tools/runner/release/hermes-deals-release-register >/dev/null || fail "release register source is not tracked"
/bin/bash -n "$SOURCE_DISPATCHER"
/bin/bash -n "$SOURCE_REGISTER"

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-release-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT
cat > "$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-release-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-dispatch
SUDOERS
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null

install -d -o root -g root -m 0750 "$REGISTRY_DIR" "$RELEASE_ARCHIVE_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0755 "$SOURCE_DISPATCHER" "$DISPATCHER"
install -o root -g root -m 0755 "$SOURCE_REGISTER" "$REGISTER"
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

printf 'INSTALL_RESULT=PASS\nRUNNER_SERVICE=%s\nDISPATCHER_SHA256=%s\nREGISTER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nDATABASE_WRITES_AUTHORIZED=false\n' \
  "$RUNNER_SERVICE" \
  "$(sha256sum "$DISPATCHER" | awk '{print $1}')" \
  "$(sha256sum "$REGISTER" | awk '{print $1}')"
