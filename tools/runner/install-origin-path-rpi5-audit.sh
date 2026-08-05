#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

AUDIT_NAME='origin-path-audit'
DISPATCH_TARGET='/usr/local/sbin/hermes-deals-origin-path-audit-dispatch'
PROBE_TARGET='/usr/local/libexec/hermes-deals-audits/origin-path-probe.py'
CONF='/etc/hermes-deals-audits.d/origin-path-audit.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-origin-path-audit'
PRIMARY_REPO='/home/andris/hermes-deals'

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "installer must run as root"

if [[ ${1:-} == '--remove' ]]; then
  [[ $# -eq 1 ]] || fail "usage: $0 --remove"
  rm -f -- "$SUDOERS" "$CONF" "$DISPATCH_TARGET" "$PROBE_TARGET"
  printf 'REMOVED=%s\n' "$AUDIT_NAME"
  exit 0
fi

[[ $# -eq 2 ]] || fail "usage: $0 <detached-source-root> <commit-sha>"
SOURCE_ROOT="$(readlink -f -- "$1")"
COMMIT_SHA="$2"
[[ "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA must be 40 lowercase hex characters"
[[ -d "$SOURCE_ROOT/.git" || -f "$SOURCE_ROOT/.git" ]] || fail "source root is not a Git worktree"
[[ "$SOURCE_ROOT" != "$PRIMARY_REPO" ]] || fail "primary production worktree is forbidden"
[[ "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" == "$COMMIT_SHA" ]] || fail "source HEAD does not match requested commit"
[[ -z "$(git -C "$SOURCE_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "source worktree is not clean"
[[ "$(git -C "$SOURCE_ROOT" symbolic-ref -q HEAD || true)" == '' ]] || fail "source worktree must be detached"
git -C "$SOURCE_ROOT" merge-base --is-ancestor "$COMMIT_SHA" origin/main || fail "commit is not reachable from origin/main"

PROBE_SOURCE="$SOURCE_ROOT/tools/hermes_deals_origin_probe.py"
DISPATCH_SOURCE="$SOURCE_ROOT/tools/runner/origin-path-rpi5-audit-dispatcher.sh"
WORKFLOW_SOURCE="$SOURCE_ROOT/.github/workflows/origin-path-rpi5-audit.yml"
DOC_SOURCE="$SOURCE_ROOT/docs/operations/origin-path-rpi5-audit.md"
for path in "$PROBE_SOURCE" "$DISPATCH_SOURCE" "$WORKFLOW_SOURCE" "$DOC_SOURCE"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "required source file is missing or unsafe: $path"
done

python3 -m py_compile "$PROBE_SOURCE"
bash -n "$DISPATCH_SOURCE"

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits
install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d
install -o root -g root -m 0755 "$DISPATCH_SOURCE" "$DISPATCH_TARGET"
install -o root -g root -m 0755 "$PROBE_SOURCE" "$PROBE_TARGET"

probe_sha256="$(sha256sum "$PROBE_TARGET" | awk '{print $1}')"
dispatcher_sha256="$(sha256sum "$DISPATCH_TARGET" | awk '{print $1}')"
workflow_sha256="$(sha256sum "$WORKFLOW_SOURCE" | awk '{print $1}')"

tmp_conf="$(mktemp)"
tmp_sudoers="$(mktemp)"
cleanup() { rm -f -- "$tmp_conf" "$tmp_sudoers"; }
trap cleanup EXIT

cat > "$tmp_conf" <<EOF
audit_name='$AUDIT_NAME'
commit_sha='$COMMIT_SHA'
probe_path='$PROBE_TARGET'
probe_sha256='$probe_sha256'
dispatcher_sha256='$dispatcher_sha256'
workflow_sha256='$workflow_sha256'
public_base_url='https://deals.rozkalns.net'
origin_base_url='http://192.168.0.180:9128'
origin_host='deals.rozkalns.net'
timeout_seconds='5'
EOF
install -o root -g root -m 0600 "$tmp_conf" "$CONF"

cat > "$tmp_sudoers" <<EOF
github-runner ALL=(root) NOPASSWD: $DISPATCH_TARGET
EOF
visudo -cf "$tmp_sudoers" >/dev/null
install -o root -g root -m 0440 "$tmp_sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

printf 'INSTALLED=%s\nCOMMIT_SHA=%s\nPROBE_SHA256=%s\nDISPATCHER_SHA256=%s\nWORKFLOW_SHA256=%s\n' \
  "$AUDIT_NAME" "$COMMIT_SHA" "$probe_sha256" "$dispatcher_sha256" "$workflow_sha256"
printf 'PRODUCTION_DEPLOYMENT=false\nPRODUCTION_DATABASE_WRITE=false\nWORKFLOW_EXECUTED=false\n'
