#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail 'installer must run as root'

SOURCE_WORKTREE='/home/andris/hermes-deals-worktrees/release-control'
SOURCE_REL='tools/runner/release/hermes-deals-release-runtime-sync'
SOURCE="$SOURCE_WORKTREE/$SOURCE_REL"
DEST='/usr/local/sbin/hermes-deals-release-runtime-sync'
SUDOERS='/etc/sudoers.d/hermes-deals-operator'
OWNER='andris'

[[ "$(pwd -P)" == "$SOURCE_WORKTREE" ]] \
  || fail 'installer source must be the isolated release-control worktree'
[[ -z "$(runuser -u "$OWNER" -- git -C "$SOURCE_WORKTREE" status --porcelain=v1 --untracked-files=all)" ]] \
  || fail 'release-control worktree is not clean'
HEAD_SHA="$(runuser -u "$OWNER" -- git -C "$SOURCE_WORKTREE" rev-parse HEAD)"
REMOTE_SHA="$(runuser -u "$OWNER" -- git -C "$SOURCE_WORKTREE" rev-parse refs/remotes/origin/main)"
[[ "$HEAD_SHA" == "$REMOTE_SHA" ]] || fail 'release-control HEAD is not exact origin/main'
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail 'runtime-sync source is missing or unsafe'
runuser -u "$OWNER" -- git -C "$SOURCE_WORKTREE" ls-files --error-unmatch "$SOURCE_REL" >/dev/null \
  || fail 'runtime-sync source is not tracked'
/bin/bash -n "$SOURCE"

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-operator-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT

cat >"$TMPDIR_INSTALL/sudoers" <<'EOF'
Defaults!/usr/local/sbin/hermes-deals-release-runtime-sync env_reset
Defaults!/usr/local/sbin/hermes-deals-release-runtime-sync secure_path=/home/andris/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
andris ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-runtime-sync *
EOF
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null

install -o root -g root -m 0755 "$SOURCE" "$DEST"
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null
sudo -l -U "$OWNER" | grep -Fq '/usr/local/sbin/hermes-deals-release-runtime-sync' \
  || fail 'narrow runtime-sync sudo rule is not visible to andris'

printf 'OPERATOR_RUNTIME_INSTALL_RESULT=PASS\n'
printf 'SOURCE_SHA=%s\n' "$HEAD_SHA"
printf 'RUNTIME_SYNC_SHA256=%s\n' "$(sha256sum "$DEST" | awk '{print $1}')"
printf 'SUDOERS_VALID=true\n'
printf 'DATABASE_WRITES_AUTHORIZED=false\n'
printf 'PRODUCTION_CHANGED=false\n'
